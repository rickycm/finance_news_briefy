import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from config import cfg
from logger.logging import setup_logger
from scheduler import scheduled_task
from web.render import render_page

setup_logger()
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting scheduler...")
    scheduler.add_job(
        scheduled_task,
        "interval",
        minutes=cfg.fetch_interval_minutes,
        id="fetch_and_aggregate",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started: fetch and aggregate every {cfg.fetch_interval_minutes} minutes")

    logger.info("Running initial fetch and aggregate...")
    asyncio.create_task(scheduled_task())

    yield

    logger.info("Stopping scheduler...")
    scheduler.shutdown()


app = FastAPI(title="Briefy - AI 驱动的每日简报", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(date: str | None = Query(None, description="日期，格式：YYYY-MM-DD")):
    """首页，展示指定日期的热搜数据"""
    try:
        html_content = render_page(date)
        return HTMLResponse(content=html_content)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/summary/{date}")
async def get_summary(date: str):
    """获取指定日期的摘要数据"""
    summary_file = cfg.summaries_dir / f"{date}.json"
    if not summary_file.exists():
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的摘要数据")

    try:
        with open(summary_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取摘要数据失败: {str(e)}")


@app.get("/api/audio/{date}")
async def get_audio(date: str):
    """获取指定日期的音频"""
    audio_file = cfg.audio_dir / f"{date}.mp3"

    if not audio_file.exists():
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的音频文件")

    return FileResponse(
        path=str(audio_file),
        media_type="audio/mpeg",
        filename=f"{date}.mp3",
    )


def main():
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
