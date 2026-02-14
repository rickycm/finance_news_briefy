"""每日汇总文件生成"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from fetcher.models import Trend

logger = logging.getLogger(__name__)

# 得分计算权重
SCORE_COUNT_WEIGHT = 0.6
SCORE_RANK_WEIGHT = 0.4

# 分类显示顺序
CATEGORY_ORDER = ["news", "finance", "tech"]

# 每个源返回的最大条数
MAX_ITEMS_PER_SOURCE = 50

# 原始配置
SOURCES_CONFIG = {
    "cailian": {
        "name": "财联社",
        "order": 1,
    },
    "wallstreetcn": {
        "name": "华尔街见闻",
        "order": 2,
    },
    "jin10": {
        "name": "金十数据",
        "order": 3,
    },
    "ifeng": {
        "name": "凤凰网",
        "order": 4,
    },
    "toutiao": {
        "name": "今日头条",
        "order": 5,
    },
    "baidu": {
        "name": "百度热搜",
        "order": 6,
    },
}

# 动态加载 RSS 源配置
# 为了不破坏原有逻辑，我们将 RSS 源配置动态合并到 SOURCES_CONFIG
try:
    import yaml
    with open("config/rss_sources.yaml", "r", encoding="utf-8") as f:
        rss_data = yaml.safe_load(f)
        if rss_data and "sources" in rss_data:
            # RSS 源从 100 开始排序
            base_order = 100
            for idx, s in enumerate(rss_data["sources"]):
                SOURCES_CONFIG[s["id"]] = {
                    "name": s["name"],
                    "order": base_order + idx
                }
except Exception as e:
    logger.warning(f"Failed to load RSS sources for aggregator: {e}")


def aggregate_source_trends(items_list: List[List[Trend]]) -> List[Trend]:
    """
    聚合单源热搜数据
    items_list: 当天所有时间点的数据（每个元素是 Trend 对象列表）
    返回: 按综合得分排序的热搜列表
    """
    topic_stats: Dict[str, Dict] = {}

    for items in items_list:
        for rank, trend in enumerate(items, 1):
            topic_id = trend.id
            if topic_id not in topic_stats:
                topic_stats[topic_id] = {
                    "id": topic_id,
                    "title": trend.title,
                    "url": trend.url,
                    "description": trend.description,
                    "publish_time": trend.publish_time,
                    "count": 0,
                    "total_rank": 0,
                    "scores": [],
                }
            # Update description if newer one is longer/better? Just overwrite for now
            if trend.description:
                topic_stats[topic_id]["description"] = trend.description
                
            topic_stats[topic_id]["count"] += 1
            topic_stats[topic_id]["total_rank"] += rank
            if trend.score is not None:
                topic_stats[topic_id]["scores"].append(trend.score)

    result = []
    for topic_id, stats in topic_stats.items():
        # 优先使用原始 score，如果没有则计算
        if stats["scores"]:
            # 使用原始 score 的平均值
            final_score = int(sum(stats["scores"]) / len(stats["scores"]))
        else:
            # 计算综合得分：出现次数权重 + 排名权重
            avg_rank = stats["total_rank"] / stats["count"]
            calculated_score = stats["count"] * SCORE_COUNT_WEIGHT + (1 / avg_rank) * SCORE_RANK_WEIGHT
            final_score = int(round(calculated_score, 0))

        result.append(
            Trend(
                id=stats["id"],
                title=stats["title"],
                url=stats["url"],
                description=stats.get("description"),
                publish_time=stats.get("publish_time"),
                score=final_score,
            )
        )
    
    return sorted(result, key=lambda x: x.score or 0, reverse=True)[:MAX_ITEMS_PER_SOURCE]


class DailyAggregator:
    """每日热搜聚合器"""

    def __init__(self, temp_path: Path | None = None, output_path: Path | None = None):
        from config import cfg
        self.temp_path = temp_path or cfg.temp_dir
        self.output_path = output_path or cfg.data_dir

    def generate(self, date: str):
        """
        生成指定日期的汇总文件
        date: 日期字符串，格式：YYYY-MM-DD
        """
        date_str = date.replace("-", "")
        all_data: Dict[str, Dict] = {}

        for source_dir in self.temp_path.iterdir():
            if not source_dir.is_dir():
                continue

            source_id = source_dir.name
            items_list = []

            for json_file in source_dir.glob(f"{date_str}_*.json"):
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        items_dict = data.get("items", [])
                        timestamp = data.get("timestamp", "")
                        for item in items_dict:
                            item["timestamp"] = timestamp
                        items = [Trend(**item) for item in items_dict]
                        items_list.append(items)
                except Exception as e:
                    logger.warning(f"读取文件失败 {json_file}: {e}")
                    continue

            if items_list:
                ranked_items = aggregate_source_trends(items_list)
                all_data[source_id] = {
                    "items_list": items_list,
                    "ranked_items": ranked_items,
                }

        if not all_data:
            logger.warning(f"日期 {date} 没有数据")
            return

        markdown, all_sources_list = self._generate_markdown(date, all_data)

        output_file = self.output_path / f"{date}.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown)
            
        # Also save full data to JSON for rich frontend features (like RSS summary)
        try:
            from dataclasses import asdict
            json_output = self.output_path / f"{date}_full.json"
            # Convert Trend objects to dicts
            full_data_serializable = []
            for source_data in all_sources_list:
                 items_dicts = []
                 for item in source_data["ranked_items"]:
                     items_dicts.append(asdict(item))
                 
                 full_data_serializable.append({
                     "source_id": source_data["source_id"],
                     "name": source_data["name"],
                     "order": source_data["order"],
                     "items": items_dicts
                 })
            
            with open(json_output, "w", encoding="utf-8") as f:
                json.dump({"date": date, "sources": full_data_serializable}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save full JSON: {e}")

        total_sources = len(all_data)
        total_items = sum(len(data["ranked_items"]) for data in all_data.values())
        logger.info(f"✅ Generated: {output_file} ({total_sources} sources, {total_items} items)")

    def _generate_markdown(self, date: str, all_data: Dict[str, Dict]) -> Tuple[str, List[Dict]]:
        """生成 Markdown 内容，并返回排序后的数据源列表"""
        all_sources = []

        for source_id, data in all_data.items():
            config = SOURCES_CONFIG.get(source_id, {})
            name = config.get("name", source_id)

            all_sources.append(
                {
                    "source_id": source_id,
                    "name": name,
                    "ranked_items": data["ranked_items"],
                    "order": config.get("order", 999),
                }
            )

        # 按照全局 order 排序
        all_sources.sort(key=lambda x: x["order"])

        lines = [f"# {date} 热门新闻汇总\n"]

        for source_data in all_sources:
            lines.append(f"\n## {source_data['name']}\n")

            for i, item in enumerate(source_data["ranked_items"], 1):
                pt = item.publish_time if item.publish_time else ""
                pt_str = f" [{pt}]" if pt else ""
                lines.append(f"{i}. [{item.title}]({item.url}){pt_str}\n")
            lines.append("\n")

        return "".join(lines), all_sources
