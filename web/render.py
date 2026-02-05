from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "trending.html"
OUTPUT_PATH = BASE_DIR / "trending.html"

sys.path.insert(0, str(BASE_DIR))
from config import cfg

DATE_FILE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
ITEM_LINE_PATTERN = re.compile(r"^(\d+)\.\s+\[(.+?)\]\((.+?)\)(?:\s+\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\])?")

SOURCE_PRESENTATION: Dict[str, Dict[str, str]] = {
    "财联社": {"icon": "💰", "color_class": "red"},
    "华尔街见闻": {"icon": "💹", "color_class": "green"},
    "金十数据": {"icon": "📊", "color_class": "cyan"},
    "百度热搜": {"icon": "🔍", "color_class": "blue"},
    "今日头条": {"icon": "📅", "color_class": "orange"},
    "凤凰网": {"icon": "💎", "color_class": "purple"},
}


def get_available_dates() -> List[str]:
    dates: List[str] = []
    for md_file in DATA_DIR.glob("*.md"):
        if DATE_FILE_PATTERN.fullmatch(md_file.stem):
            dates.append(md_file.stem)
    return sorted(dates, reverse=True)


def parse_markdown(date_str: str) -> Dict[str, object]:
    md_path = DATA_DIR / f"{date_str}.md"
    if not md_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{md_path}")

    sources: List[Dict[str, object]] = []
    current: Dict[str, object] | None = None
    title_line: str | None = None

    with md_path.open(encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("# "):
                title_line = line.lstrip("# ").strip()
                continue
            if line.startswith("## "):
                source_name = line[3:].strip()
                meta = SOURCE_PRESENTATION.get(
                    source_name,
                    {"icon": "💎", "color_class": "green"},
                )
                current = {"name": source_name, "meta": meta, "items": []}
                sources.append(current)
                continue
            match = ITEM_LINE_PATTERN.match(line)
            if match and current:
                rank = int(match.group(1))
                title = match.group(2).strip()
                link = match.group(3).strip()
                publish_time = match.group(4)
                current["items"].append({"rank": rank, "title": title, "link": link, "date": date_str, "publish_time": publish_time})

    return {
        "title": title_line or f"{date_str} 热门资讯",
        "sources": sources,
    }


def render_page(selected_date: str | None = None) -> str:
    available_dates = get_available_dates()
    if not available_dates:
        raise RuntimeError("data 目录中未找到任何日期文件")

    date_to_use = selected_date or available_dates[0]

    # 如果日期不存在，返回空数据
    if date_to_use not in available_dates:
        sources: Sequence[Dict[str, object]] = []
    else:
        parsed = parse_markdown(date_to_use)
        sources = parsed["sources"]  # type: ignore[assignment]

    total_items = sum(len(s["items"]) for s in sources)  # type: ignore[index]

    # 准备数据对象
    data = {
        "selected_date": date_to_use,
        "selected_date_display": date_to_use,
        "sources": sources,
        "source_count": len(sources),
        "item_count": total_items,
        "build_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fetch_interval_minutes": cfg.fetch_interval_minutes,
    }

    # 读取模板并替换占位符
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    html_content = template_text.replace("__DATA_PLACEHOLDER__", json_data)

    return html_content


def main() -> None:
    parser = argparse.ArgumentParser(description="渲染 trending.html 静态页面")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)，默认使用最新日期")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="输出 HTML 文件路径（默认写入项目根目录的 trending.html）",
    )
    args = parser.parse_args()

    html_content = render_page(args.date)
    args.output.write_text(html_content, encoding="utf-8")
    print(f"已生成 {args.output} （日期：{args.date or '最新'})")


if __name__ == "__main__":
    main()
