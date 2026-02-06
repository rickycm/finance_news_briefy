"""新闻选择模块 - 从 markdown 文件中选出热门且不重复的新闻"""

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 相似度阈值（用于去重）
SIMILARITY_THRESHOLD = 0.85

# 默认摘要新闻来源（可在 .env 中通过 SUMMARY_SOURCES 配置）
DEFAULT_SOURCES = {"华尔街见闻", "财联社", "金十数据"}


def calculate_similarity(title1: str, title2: str) -> float:
    """计算两个标题的相似度"""
    return SequenceMatcher(None, title1.lower(), title2.lower()).ratio()


def extract_news_from_markdown(
    markdown_path: Path,
    selected_sources: Optional[set] = None,
) -> Dict[str, List[Dict]]:
    """
    从 Markdown 文件中提取指定源的新闻

    Args:
        markdown_path: Markdown 文件路径
        selected_sources: 要提取的源名称集合，默认使用配置中的值

    Returns:
        {source_name: [{"title": "...", "url": "...", "rank": 1}, ...]}
    """
    if selected_sources is None:
        from config import cfg
        selected_sources = cfg.summary_sources

    if not markdown_path.exists():
        logger.warning(f"Markdown 文件不存在: {markdown_path}")
        return {}

    with open(markdown_path, "r", encoding="utf-8") as f:
        content = f.read()

    result = {}
    current_source = None

    for line in content.split("\n"):
        line = line.strip()

        # 匹配源标题：## 源名称
        match = re.match(r"^##\s+(.+)$", line)
        if match:
            source_name = match.group(1)
            if source_name in selected_sources:
                current_source = source_name
                result[current_source] = []
            else:
                current_source = None
            continue

        # 匹配新闻条目：序号. [标题](URL) [发布时间]
        # 发布时间是可选的
        if current_source:
            match = re.match(r"^(\d+)\.\s+\[(.+?)\]\((.+?)\)(?:\s+\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\])?$", line)
            if match:
                rank = int(match.group(1))
                title = match.group(2)
                url = match.group(3)
                result[current_source].append(
                    {
                        "title": title,
                        "url": url,
                        "rank": rank,
                    }
                )

    return result


def select_top_news(
    date: str,
    markdown_path: Optional[Path] = None,
    top_n: int = 20,
    selected_sources: Optional[set] = None,
) -> List[Dict]:
    """
    从 markdown 文件中选出热门且不重复的前 N 条新闻

    Args:
        date: 日期字符串，格式：YYYY-MM-DD
        markdown_path: markdown 文件路径，默认 data/YYYY-MM-DD.md
        top_n: 返回的新闻数量
        selected_sources: 要选择的源名称集合

    Returns:
        选出的新闻列表，每个元素包含：
        - title: 标题
        - url: 链接
        - source_name: 源名称
        - rank: 在该源中的排名
        - weighted_score: 加权分数（暂时用排名，排名越小分数越高）
    """
    if selected_sources is None:
        from config import cfg
        selected_sources = cfg.summary_sources

    if markdown_path is None:
        from config import cfg

        markdown_path = cfg.data_dir / f"{date}.md"

    # 从 Markdown 文件提取新闻
    parsed_data = extract_news_from_markdown(markdown_path)

    if not parsed_data:
        logger.warning(f"未找到数据或文件不存在: {markdown_path}")
        return []

    # 收集所有候选新闻（带源信息）
    candidates = []

    for source_name, news_list in parsed_data.items():
        if source_name not in selected_sources:
            continue

        for news in news_list:
            # 加权分数：排名越小分数越高（用 1000 - rank 作为分数，保证排名靠前的分数高）
            weighted_score = 1000 - news["rank"]

            candidates.append(
                {
                    "title": news["title"],
                    "url": news["url"],
                    "source_name": source_name,
                    "rank": news["rank"],
                    "weighted_score": weighted_score,
                }
            )

    if not candidates:
        logger.warning("没有找到候选新闻")
        return []

    # 按加权分数排序
    candidates.sort(key=lambda x: x["weighted_score"], reverse=True)

    # 相似度去重
    selected = []
    selected_titles = []

    for candidate in candidates:
        title = candidate["title"]

        # 检查是否与已选新闻相似
        is_similar = False
        for selected_title in selected_titles:
            similarity = calculate_similarity(title, selected_title)
            if similarity >= SIMILARITY_THRESHOLD:
                is_similar = True
                logger.debug(
                    f"跳过相似新闻: {title} (与 {selected_title} 相似度 {similarity:.2f})"
                )
                break

        if not is_similar:
            selected.append(candidate)
            selected_titles.append(title)

            if len(selected) >= top_n:
                break

    logger.info(f"从 {len(candidates)} 条候选新闻中选出 {len(selected)} 条新闻")
    return selected
