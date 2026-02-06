"""Summary generation"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from config import cfg
from summary.client import generate_summaries, generate_summaries_with_progress
from summary.reader import fetch_contents_batch
from summary.selector import select_top_news

logger = logging.getLogger(__name__)


def _write_progress(date: str, current: int, total: int, status: str = "generating"):
    """Write progress to file for real-time updates"""
    progress_file = cfg.summaries_dir / f"{date}.progress.json"
    progress_data = {
        "date": date,
        "status": status,
        "current": current,
        "total": total,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, ensure_ascii=False)


def _clear_progress(date: str):
    """Clear progress file when generation is done"""
    progress_file = cfg.summaries_dir / f"{date}.progress.json"
    if progress_file.exists():
        progress_file.unlink()


async def generate_daily_summary(date: str, top_n: int = 10) -> Dict:
    """
    Generate daily news summary with real-time progress updates

    Args:
        date: Date string in format YYYY-MM-DD
        top_n: Number of news items to select

    Returns:
        Dict with success status and statistics
    """
    logger.info(f"Generating summary for {date}")
    start_time = time.time()

    temp_dir = cfg.temp_dir / "summaries" / date
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 选择热门新闻
    selected = select_top_news(date, top_n=top_n)
    if not selected:
        logger.warning("No news selected")
        _clear_progress(date)
        return {"success": False, "error": "No eligible news found"}
    logger.info(f"Selected {len(selected)} news items")

    # 获取文章内容
    news_with_content = await fetch_contents_batch(selected)
    success_count = sum(1 for item in news_with_content if item.get("markdown_content"))
    logger.info(f"Fetched {success_count}/{len(news_with_content)} article contents")

    for i, item in enumerate(news_with_content, 1):
        if item.get("markdown_content"):
            content_file = temp_dir / f"{i}.md"
            with open(content_file, "w", encoding="utf-8") as f:
                f.write(item["markdown_content"])
            item["content_file"] = f"{i}.md"
        else:
            item["content_file"] = None

    # 初始化进度
    total_to_generate = len(news_with_content)
    _write_progress(date, 0, total_to_generate)

    # 生成 AI 摘要（带进度更新）
    news_with_summaries = await generate_summaries_with_progress(
        news_with_content, date, total_to_generate
    )
    summaries_count = sum(1 for item in news_with_summaries if item.get("summary"))
    logger.info(f"Generated {summaries_count}/{len(news_with_summaries)} summaries")

    news_with_summaries.sort(key=lambda x: x.get("rank", 999))

    metadata = {
        "date": date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_news": len(news_with_summaries),
        "news": [
            {
                "title": item["title"],
                "url": item["url"],
                "source_name": item["source_name"],
                "rank": item["rank"],
                "summary": item.get("summary", ""),
                "content_file": item.get("content_file"),
            }
            for item in news_with_summaries
        ],
    }

    metadata_file = temp_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    total_content_length = sum(
        len(item.get("markdown_content", ""))
        for item in news_with_summaries
        if item.get("markdown_content")
    )

    final_data = {
        "date": date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_news": len(news_with_summaries),
        "stats": {
            "content_fetched": success_count,
            "summaries_generated": summaries_count,
            "total_content_length": total_content_length,
        },
        "news": [
            {
                "title": item["title"],
                "url": item["url"],
                "source_name": item["source_name"],
                "rank": item["rank"],
                "summary": item.get("summary", ""),
            }
            for item in news_with_summaries
        ],
    }

    output_file = cfg.summaries_dir / f"{date}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    logger.info(f"Summary saved: {output_file}")

    # 清除进度文件（已完成）
    _clear_progress(date)

    # 所有摘要完成后，生成 TTS 音频（同步等待完成）
    if cfg.enable_tts and summaries_count > 0:
        await generate_audio_sync(date, final_data)

    elapsed_time = time.time() - start_time
    logger.info(
        f"Summary generation completed: {len(news_with_summaries)} items, {summaries_count} summaries, elapsed: {elapsed_time:.2f}s"
    )

    return {
        "success": True,
        "date": date,
        "total_news": len(news_with_summaries),
        "content_fetched": success_count,
        "summaries_generated": summaries_count,
        "total_content_length": total_content_length,
        "output_file": str(output_file),
    }


async def generate_audio_sync(date: str, data: Dict):
    """
    同步生成 TTS 音频（等待所有摘要完成后执行）

    Args:
        date: 日期字符串
        data: 摘要数据
    """
    from summary.tts import generate_audio

    audio_file = cfg.audio_dir / f"{date}.mp3"
    text = format_text(data)

    logger.info(f"Starting TTS generation for {date} ({len(text)} chars)")

    try:
        await generate_audio(text, audio_file)
        logger.info(f"Audio generated successfully: {audio_file}")
    except Exception as e:
        logger.error(f"TTS generation failed for {date}: {e}")


def format_text(data: Dict) -> str:
    """
    Format summary data to plain text for TTS

    Args:
        data: Summary data dictionary

    Returns:
        Plain text string
    """
    lines = []

    for index, item in enumerate(data["news"], 1):
        source_name = item.get("source_name", "")
        title = item["title"]
        lines.append(f"{index}、【{source_name}新闻】{title}。\n\n")
        if item.get("summary"):
            lines.append(f" {item['summary']}\n\n")

    return "".join(lines)
