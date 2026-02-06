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


async def generate_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    summary_file = cfg.summaries_dir / f"{today}.json"

    if summary_file.exists():
        logger.debug(f"Summary for {today} already exists, skipping")
        return

    try:
        from summary.generator import generate_daily_summary

        await generate_daily_summary(today, top_n=cfg.summary_top_n)
    except Exception as e:
        logger.error(f"Summary generation error: {e}")


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
