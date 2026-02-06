import logging
from datetime import datetime

import fetcher  # noqa: F401 - Register all fetchers
from config import cfg
from fetcher.registry import FetcherRegistry
from storage.aggregator import DailyAggregator
from storage.cache import CacheStorage

logger = logging.getLogger(__name__)


async def fetch_all_sources():
    """Fetch all data sources"""
    source_ids = FetcherRegistry.list_source_ids()
    logger.info(f"Fetching {len(source_ids)} sources...")

    storage = CacheStorage()
    success_count = 0
    total_items = 0

    for source_id in source_ids:
        try:
            fetcher_instance = FetcherRegistry.get(source_id)
            items = await fetcher_instance.fetch()
            storage.save(source_id, items)
            total_items += len(items)
            success_count += 1
        except Exception as e:
            logger.error(f"❌ {source_id}: {e}")

    logger.info(f"Fetch completed: {success_count}/{len(source_ids)} succeeded, {total_items} items total")
    return success_count > 0


def aggregate_today():
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"Aggregating data for {today}...")

    try:
        aggregator = DailyAggregator()
        aggregator.generate(today)
        logger.info(f"✅ Aggregation completed for {today}")
        return True
    except Exception as e:
        logger.error(f"❌ Aggregation failed for {today}: {e}")
        return False


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
        aggregate_today()

        if cfg.enable_summary:
            await generate_summary()
    else:
        logger.warning("Fetch failed, skipping aggregation")

    logger.info("Scheduled task completed")
