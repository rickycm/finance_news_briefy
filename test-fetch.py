"""测试数据源获取功能"""

import asyncio
import logging

import fetcher  # noqa: F401 自动注册所有源
from fetcher.registry import FetcherRegistry
from logger.logging import setup_logger
from storage.cache import CacheStorage

setup_logger()
logger = logging.getLogger(__name__)


async def fetch_source(source_id: str):
    """获取单个源的数据"""
    fetcher_instance = FetcherRegistry.get(source_id)
    logger.info(f"开始获取 {source_id}...")

    try:
        items = await fetcher_instance.fetch()
        logger.info(f"获取到 {len(items)} 条数据")

        for i, item in enumerate(items[:5], 1):
            logger.info(f"  {i}. {item.title}")
            if item.description:
                logger.info(f"     {item.description[:50]}...")

        storage = CacheStorage()
        storage.save(source_id, items)
        logger.info(f"✅ {source_id} - 成功")
        return True
    except Exception as e:
        logger.error(f"❌ {source_id} - 失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """测试获取数据源"""
    source_ids = ["baidu", "toutiao", "ifeng", "cailian", "wallstreetcn", "jin10"]

    logger.info(f"测试源: {', '.join(source_ids)}")
    logger.info("=" * 50)

    for source_id in source_ids:
        await fetch_source(source_id)
        logger.info("-" * 50)


if __name__ == "__main__":
    asyncio.run(main())
