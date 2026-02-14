"""RSS Fetcher 模块，负责从配置的源抓取数据"""

import asyncio
import logging
import feedparser
import yaml
import re
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional
from litellm import acompletion

from config import cfg
from .base import BaseFetcher
from .models import Trend

logger = logging.getLogger(__name__)


@dataclass
class RSSSource:
    id: str
    name: str
    url: str
    enabled: bool = True
    language: str = "zh"
    translate: bool = False


class RSSFetcher(BaseFetcher):
    """
    单个 RSS 源的抓取器
    """

    def __init__(self, config: RSSSource):
        self.config = config
        # Default batch size, used as a cap
        self.max_batch_size = 5
        # Max characters per batch to send to LLM (approx safe limit)
        self.max_batch_chars = 4000

    @property
    def source_id(self) -> str:
        return self.config.id

    def _create_dynamic_batches(self, items: List[Trend]) -> List[List[Trend]]:
        """
        Create batches of items based on character count and max batch size.
        """
        batches = []
        current_batch = []
        current_chars = 0
        
        for item in items:
            # Calculate length for batching
            desc = (item.description or "")
            # Simple HTML tag removal for length estimation
            desc_clean = re.sub(r'<[^>]+>', '', desc)
            
            # If a single item is excessively long, we cap it for calculation
            # and later for transmission to avoid one item consuming too much context.
            # But we try to keep it as long as possible (e.g. 2000 chars)
            if len(desc_clean) > 2000:
                desc_clean = desc_clean[:2000]
            
            item_len = len(item.title) + len(desc_clean)
            
            # Check if adding this item would exceed limits
            if (current_batch and 
                (current_chars + item_len > self.max_batch_chars or len(current_batch) >= self.max_batch_size)):
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            
            current_batch.append(item)
            current_chars += item_len
            
        if current_batch:
            batches.append(current_batch)
            
        return batches

    async def fetch(self) -> List[Trend]:
        if not self.config.enabled:
            return []

        logger.info(f"Fetching RSS: {self.config.name} ({self.config.url})")
        try:
            feed = await asyncio.to_thread(feedparser.parse, self.config.url)
            
            all_items = []
            
            # 1. Parse all items first (up to 20)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                
                publish_time = None
                try:
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        publish_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        publish_time = datetime(*entry.updated_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                except:
                    pass

                # Clean up description (simple HTML tag stripping could be added here if needed)
                description = entry.get("summary", "") or entry.get("description", "")
                
                item = Trend(
                    id=link,
                    title=title,
                    url=link, 
                    publish_time=publish_time,
                    description=description,
                    score=0,
                )
                all_items.append(item)

            if not all_items:
                return []

            # 2. Sort by publish time (newest first) to prioritize translation
            all_items.sort(
                key=lambda x: x.publish_time if x.publish_time else "0000-00-00 00:00", 
                reverse=True
            )

            # 3. Process items (Translate if needed)
            if self.config.translate and self.config.language != "zh":
                # Translate top 10 items
                items_to_translate = all_items[:10]
                rest_items = all_items[10:]
                
                translated_items = []
                
                # Dynamic batching
                batches = self._create_dynamic_batches(items_to_translate)
                
                for i, batch in enumerate(batches):
                    logger.info(f"Translating batch {i+1}/{len(batches)} for {self.config.name} ({len(batch)} items)")
                    processed_batch = await self._translate_batch(batch)
                    translated_items.extend(processed_batch)
                    # Small delay between batches
                    await asyncio.sleep(1)
                
                return translated_items + rest_items
            else:
                return all_items[:10] # Return top 10 if no translation needed

        except Exception as e:
            logger.error(f"Error fetching {self.config.name}: {e}")
            return []

    async def _translate_batch(self, items: List[Trend]) -> List[Trend]:
        """
        Batch translate a list of items using LLM.
        Returns the list with updated titles and descriptions.
        """
        if not items:
            return []

        try:
            # Prepare input for LLM
            news_list = []
            for idx, item in enumerate(items):
                # Prepare content: remove HTML tags, limit length safely
                content_preview = item.description or ""
                content_preview = re.sub(r'<[^>]+>', '', content_preview)
                
                # Soft cap at 2000 chars per item to prevent prompt overflow
                if len(content_preview) > 2000:
                    content_preview = content_preview[:2000] + "..."
                
                news_list.append({
                    "id": idx,
                    "title": item.title,
                    "content": content_preview
                })
            
            prompt = f"""
You are a professional financial news editor.
Task: Translate news titles to Chinese and generate a concise Chinese summary of the content.

Input News Items:
{json.dumps(news_list, ensure_ascii=False, indent=2)}

Requirements:
1. "title_zh": Translate the "title" into Chinese.
2. "summary_zh": Summarize the "content" into a concise summary in Chinese (max 100 characters). The summary MUST be in Chinese.
3. Return a JSON Array with objects containing: "id", "title_zh", "summary_zh".
4. Strictly Output VALID JSON only. No markdown formatting.

Example Output:
[
  {{"id": 0, "title_zh": "...", "summary_zh": "..."}},
  {{"id": 1, "title_zh": "...", "summary_zh": "..."}}
]
"""
            
            response = await acompletion(
                model=cfg.llm_model,
                messages=[{"role": "user", "content": prompt}],
                api_base=cfg.llm_api_base,
                api_key=cfg.llm_api_key
            )
            
            content = response.choices[0].message.content.strip()
            
            # Clean up potential markdown code blocks
            if content.startswith("```"):
                content = re.sub(r"^```(json)?\n", "", content)
                content = re.sub(r"\n```$", "", content)
            
            try:
                results = json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"JSON decode failed for batch translation. Content: {content[:100]}...")
                return items # Return original on parse error

            # Map results back to items
            # Create a map for O(1) lookup
            result_map = {str(r.get("id")): r for r in results}
            
            for idx, item in enumerate(items):
                # Ensure idx matches the type in result_map keys
                res = result_map.get(str(idx))
                if res:
                    title_zh = res.get("title_zh")
                    summary_zh = res.get("summary_zh")
                    
                    if title_zh:
                        # Append original title for reference
                        item.title = f"{title_zh} ({item.title})"
                    if summary_zh:
                        # Overwrite description with translated summary
                        item.description = summary_zh
            
            return items

        except Exception as e:
            logger.warning(f"Batch translation failed: {e}")
            return items
