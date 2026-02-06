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
    logger.info(
        f"Scheduler started: fetch and aggregate every {cfg.fetch_interval_minutes} minutes"
    )

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


@app.post("/api/regenerate-summary/{date}")
async def regenerate_summary(date: str):
    """
    重新生成指定日期的摘要数据
    
    会先删除旧的摘要文件，然后触发重新生成
    """
    import os
    from datetime import datetime
    from scheduler import generate_summary
    
    # 验证日期格式
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式无效，请使用 YYYY-MM-DD")
    
    summary_file = cfg.summaries_dir / f"{date}.json"
    audio_file = cfg.audio_dir / f"{date}.mp3"
    markdown_file = cfg.data_dir / f"{date}.md"
    
    # 检查 markdown 文件是否存在
    if not markdown_file.exists():
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的数据文件，请先抓取新闻")
    
    # 删除旧文件（如果存在）
    deleted_files = []
    if summary_file.exists():
        os.remove(summary_file)
        deleted_files.append("摘要")
    if audio_file.exists():
        os.remove(audio_file)
        deleted_files.append("音频")
    
    # 触发重新生成
    try:
        result = await generate_summary(date)
        if result["success"]:
            return {"success": True, "message": f"{', '.join(deleted_files) + '已删除并开始重新生成' if deleted_files else '开始生成摘要'}"}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "生成失败"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成摘要失败: {str(e)}")


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
    uvicorn.run(app, host="0.0.0.0", port=9000)


if __name__ == "__main__":
    main()
