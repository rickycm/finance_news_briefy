"""Reader API 调用模块 - 获取文章内容"""

import asyncio
import logging
import random
import time
from typing import List, Optional

import httpx

from config import cfg

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 5

# 浏览器 User-Agent 列表
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def get_random_headers() -> dict:
    """生成随机请求头"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


async def fetch_content_via_reader_api(url: str) -> Optional[str]:
    """
    通过 Reader API 获取文章内容

    Args:
        url: 文章 URL

    Returns:
        Markdown 格式的文章内容，失败返回 None
    """
    if not cfg.reader_api_key:
        logger.error("READER_API_KEY not set")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                cfg.reader_api_endpoint,
                headers={
                    "Authorization": f"Bearer {cfg.reader_api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url},
            )
        response.raise_for_status()
        data = response.json()

        # 检查返回码
        if data.get("code") != 0:
            logger.warning(f"Reader API 返回错误: {data.get('message')} (URL: {url})")
            return None

        # 提取 markdown 内容
        markdown_content = data.get("data", {}).get("markdown")
        if markdown_content:
            return markdown_content
        else:
            logger.warning(f"Reader API 返回数据中没有 markdown 字段 (URL: {url})")
            return None

    except httpx.TimeoutException:
        logger.warning(f"Reader API 调用超时: {url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(f"Reader API HTTP 错误 {e.response.status_code}: {url}")
        return None
    except Exception as e:
        logger.warning(f"Reader API 调用失败 {url}: {e}")
        return None


def fetch_content_via_newspaper3k(url: str, max_retries: int = 2) -> Optional[str]:
    """
    通过 Newspaper3k 获取文章内容（带重试和反爬处理）

    Args:
        url: 文章 URL
        max_retries: 最大重试次数

    Returns:
        清洗后的文章内容，失败返回 None
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            from newspaper import Article
            from newspaper.configuration import Configuration

            # 配置请求头
            config = Configuration()
            config.browser_user_agent = random.choice(USER_AGENTS)
            config.timeout = 15

            article = Article(url, language="zh", config=config)
            article.download()
            article.parse()

            if article.text and len(article.text) > 50:
                # 限制文本长度
                max_length = 10000
                text = article.text[:max_length]
                if len(article.text) > max_length:
                    text += "\n\n[内容已截断]"
                logger.debug(f"Newspaper3k 成功提取 {len(text)} 字符 (URL: {url})")
                return text
            else:
                last_error = "未能提取到足够文本"
                logger.warning(f"Newspaper3k 尝试 {attempt + 1}/{max_retries}: {last_error} (URL: {url})")

        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            if "418" in str(e) or "Client Error" in str(e):
                # 反爬错误，稍后重试
                wait_time = (attempt + 1) * 2
                logger.warning(f"Newspaper3k 反爬触发，等待 {wait_time}s 后重试 (URL: {url})")
                time.sleep(wait_time)
            else:
                logger.warning(f"Newspaper3k 错误 [{error_type}]: {last_error} (URL: {url})")

    logger.warning(f"Newspaper3k 最终失败: {last_error} (URL: {url})")
    return None


async def fetch_content_via_newspaper3k_async(url: str) -> Optional[str]:
    """
    异步调用 Newspaper3k（在线程池中执行）
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_content_via_newspaper3k, url)


async def fetch_content(url: str) -> Optional[str]:
    """
    从指定 URL 获取文章内容

    根据配置选择使用 Reader API 或 Newspaper3k

    Args:
        url: 文章 URL

    Returns:
        Markdown 格式的文章内容，失败返回 None
    """
    if cfg.content_fetcher == "reader_api":
        return await fetch_content_via_reader_api(url)
    else:
        # Newspaper3k 是同步的，在线程池中执行
        return await fetch_content_via_newspaper3k_async(url)


async def fetch_contents_batch(news_list: List[dict]) -> List[dict]:
    """
    批量获取新闻内容（并发控制）

    Args:
        news_list: 新闻列表，每个元素包含 title, url, source_name, rank 等字段

    Returns:
        带内容的新闻列表，每个元素添加了 markdown_content 字段
    """
    import asyncio

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def fetch_with_limit(news_item: dict) -> dict:
        async with semaphore:
            url = news_item["url"]
            logger.debug(f"获取内容: {news_item['title'][:50]}...")
            markdown_content = await fetch_content(url)
            news_item["markdown_content"] = markdown_content
            return news_item

    # 并发获取所有内容
    tasks = [fetch_with_limit(news_item.copy()) for news_item in news_list]
    results = await asyncio.gather(*tasks)

    # 统计成功数量
    success_count = sum(1 for item in results if item.get("markdown_content"))
    logger.info(f"成功获取 {success_count}/{len(results)} 篇文章内容")

    return list(results)
