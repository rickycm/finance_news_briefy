import logging
from datetime import datetime
import asyncio

import fetcher  # noqa: F401 - Register all fetchers
from config import cfg
from fetcher.registry import FetcherRegistry
from storage.aggregator import DailyAggregator
from storage.cache import CacheStorage

logger = logging.getLogger(__name__)


async def fetch_all_sources():
    """Fetch all data sources sequentially and update aggregator immediately"""
    source_ids = FetcherRegistry.list_source_ids()
    logger.info(f"Fetching {len(source_ids)} sources...")

    # Initialize aggregator early
    aggregator = DailyAggregator()

    success_count = 0
    total_items = 0

    for source_id in source_ids:
        try:
            # Use registry to get fetcher instance
            # Note: FetcherRegistry.get creates a NEW instance each time?
            # Or reuses? If it reuses, we need to check if it's stateful.
            # Assuming stateless or new instance.
            fetcher_instance = FetcherRegistry.get(source_id)
            if not fetcher_instance:
                logger.warning(f"Fetcher not found for source_id: {source_id}")
                continue

            logger.info(f"Fetching source: {source_id}")
            
            # Add simple timeout protection (300s per source to allow linear translation)
            # Increased from 180s to 300s to allow more time for slow API translations
            items = await asyncio.wait_for(fetcher_instance.fetch(), timeout=300)
            
            if items:
                # Save to cache storage (JSON files in temp dir)
                storage = CacheStorage()
                storage.save(source_id, items)
                
                count = len(items)
                total_items += count
                success_count += 1
                logger.info(f"✅ {source_id}: Fetched {count} items")
                
                # Immediate aggregation update (incremental)
                # This ensures the page shows data as it comes in
                try:
                    today = datetime.now().strftime("%Y-%m-%d")
                    aggregator.generate(today)
                except Exception as agg_err:
                    logger.warning(f"Incremental aggregation failed: {agg_err}")
            else:
                logger.info(f"ℹ️ {source_id}: No items fetched (or empty)")
                
        except asyncio.TimeoutError:
             logger.error(f"❌ {source_id}: Timeout fetching (300s)")
        except Exception as e:
            logger.error(f"❌ {source_id}: {e}")

    logger.info(f"Fetch completed: {success_count}/{len(source_ids)} sources succeeded, {total_items} items total")
    return success_count > 0


async def generate_summary(date: str | None = None):
    """
    生成指定日期的摘要

    Args:
        date: 日期字符串，格式：YYYY-MM-DD，默认今天
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    summary_file = cfg.summaries_dir / f"{target_date}.json"
    markdown_file = cfg.data_dir / f"{target_date}.md"

    # 检查 markdown 文件是否存在
    if not markdown_file.exists():
        logger.warning(f"Markdown 文件不存在: {markdown_file}")
        return {"success": False, "error": "数据文件不存在"}

    # 直接生成，不检查是否已存在（因为刷新时会先删除）
    try:
        from summary.generator import generate_daily_summary

        await generate_daily_summary(target_date, top_n=cfg.summary_top_n)
        return {"success": True}
    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        return {"success": False, "error": str(e)}


async def scheduled_task():
    logger.info("Scheduled task started")

    fetch_success = await fetch_all_sources()

    if fetch_success:
        # Final aggregation (redundant but safe)
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            aggregator = DailyAggregator()
            aggregator.generate(today)
        except Exception as e:
            logger.error(f"Final aggregation failed: {e}")

        if cfg.enable_summary:
            await generate_summary()
    else:
        logger.warning("Fetch failed, skipping final steps")

    logger.info("Scheduled task completed")
