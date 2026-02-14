"""手动运行聚合器生成markdown"""
import sys
from datetime import datetime
from storage.aggregator import DailyAggregator

if __name__ == "__main__":
    date = datetime.now().strftime("%Y-%m-%d")
    if len(sys.argv) > 1:
        date = sys.argv[1]
    
    print(f"Aggregating for date: {date}")
    aggregator = DailyAggregator()
    aggregator.generate(date)
    print("✅ Markdown generated successfully")
