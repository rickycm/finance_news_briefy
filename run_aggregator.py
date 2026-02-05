"""手动运行聚合器生成markdown"""
import asyncio
from storage.aggregator import DailyAggregator

aggregator = DailyAggregator()
aggregator.generate("2026-02-06")
print("✅ Markdown generated successfully")
