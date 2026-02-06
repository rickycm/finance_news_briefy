"""Content fetcher module - Fetch article content using HTTP (Playwright unavailable)"""

import asyncio
import logging
import random
import re
from typing import Optional

import httpx

from config import cfg

logger = logging.getLogger(__name__)

# 浏览器 User-Agent 列表
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def clean_html_content(html: str) -> str:
    """从 HTML 中提取纯文本内容"""
    if not html:
        return ""

    # 移除脚本和样式
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<noscript[^>]*>.*?</noscript>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    # 移除非内容元素
    html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<aside[^>]*>.*?</aside>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # 移除标签
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html)

    # 解码 HTML 实体
    html = html.replace("&nbsp;", " ")
    html = html.replace("&amp;", "&")
    html = html.replace("&lt;", "<")
    html = html.replace("&gt;", ">")
    html = html.replace("&quot;", '"')
    html = html.replace("&#39;", "'")

    return html.strip()


async def fetch_content_via_http(url: str, max_retries: int = 2) -> Optional[str]:
    """通过 HTTP 请求获取文章内容（带反爬处理和重试）"""
    last_error = None

    for attempt in range(max_retries):
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)

            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}"
                logger.warning(f"HTTP 尝试 {attempt + 1}/{max_retries}: {last_error} (URL: {url})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                continue

            text_content = clean_html_content(response.text)

            if text_content and len(text_content) > 100:
                max_length = 10000
                if len(text_content) > max_length:
                    text_content = text_content[:max_length] + "\n\n[内容已截断]"
                logger.debug(f"HTTP 成功提取 {len(text_content)} 字符 (URL: {url})")
                return text_content
            else:
                last_error = "内容过短或为空"
                logger.warning(f"HTTP 尝试 {attempt + 1}/{max_retries}: {last_error} (URL: {url})")

        except Exception as e:
            last_error = str(e)
            logger.warning(f"HTTP 错误: {last_error} (URL: {url})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))

    logger.warning(f"HTTP 最终失败: {last_error} (URL: {url})")
    return None


async def fetch_content_via_playwright(url: str, max_retries: int = 2) -> Optional[str]:
    """通过 Playwright 获取文章内容（支持 JavaScript 渲染）"""
    last_error = None

    for attempt in range(max_retries):
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-sync",
                        "--disable-translate",
                        "--metrics-recording-only",
                        "--mute-audio",
                        "--no-first-run",
                        "--safebrowsing-disable-auto-update",
                        "--disable-web-security",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                    java_script_enabled=True,
                )
                page = await context.new_page()

                # 设置更短的超时
                page.set_default_timeout(15000)  # 15 seconds
                page.set_default_navigation_timeout(15000)

                response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                if response is None or response.status >= 400:
                    last_error = f"HTTP {response.status if response else 'No response'}"
                    await browser.close()
                    continue

                # 等待内容加载（给更多时间）
                try:
                    await page.wait_for_selector(
                        "article, main, .article-content, .content, .post-content, #article-body, .article-body, body",
                        timeout=15000,
                    )
                except asyncio.TimeoutError:
                    # 即使没找到元素也尝试获取内容
                    pass

                await asyncio.sleep(1)

                html_content = await page.content()
                await browser.close()

                text_content = clean_html_content(html_content)

                if text_content and len(text_content) > 100:
                    max_length = 10000
                    if len(text_content) > max_length:
                        text_content = text_content[:max_length] + "\n\n[内容已截断]"
                    logger.debug(f"Playwright 成功提取 {len(text_content)} 字符 (URL: {url})")
                    return text_content
                else:
                    last_error = "内容过短或为空"

        except Exception as e:
            error_msg = str(e)
            # 检查是否是浏览器关闭错误
            if any(x in error_msg for x in ["Target page, context or browser has been closed", "Browser crashed", "Executable doesn't exist", "BrowserType.launch"]):
                # 浏览器问题，降级到 HTTP
                raise RuntimeError(f"Playwright 浏览器异常: {error_msg[:100]}")
            last_error = error_msg
            logger.debug(f"Playwright 尝试 {attempt + 1}/{max_retries}: {error_msg[:80]} (URL: {url})")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)

    if last_error:
        logger.warning(f"Playwright 最终失败: {last_error[:100]} (URL: {url})")
    else:
        logger.warning(f"Playwright 最终失败 (URL: {url})")
    return None


async def fetch_content_via_reader_api(url: str) -> Optional[str]:
    """通过 Reader API 获取文章内容"""
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

        if data.get("code") != 0:
            logger.warning(f"Reader API 返回错误: {data.get('message')} (URL: {url})")
            return None

        markdown_content = data.get("data", {}).get("markdown")
        if markdown_content:
            return markdown_content
        logger.warning(f"Reader API 无内容 (URL: {url})")
        return None

    except Exception as e:
        logger.warning(f"Reader API 调用失败 {url}: {e}")
        return None


async def fetch_contents_batch(news_list: list) -> list:
    """
    批量获取新闻内容（并发控制）

    Args:
        news_list: 新闻列表，每个元素包含 title, url, source_name, rank 等字段

    Returns:
        带内容的新闻列表，每个元素添加了 markdown_content 字段
    """
    semaphore = asyncio.Semaphore(5)

    async def fetch_with_limit(news_item: dict) -> dict:
        async with semaphore:
            url = news_item.get("url")
            if not url:
                news_item["markdown_content"] = None
                return news_item

            logger.debug(f"获取内容: {news_item.get('title', '')[:50]}...")
            markdown_content = await fetch_content(url)
            news_item["markdown_content"] = markdown_content
            return news_item

    # 并发获取所有内容
    tasks = [fetch_with_limit(news_item.copy()) for news_item in news_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常结果
    processed_results = []
    for item in results:
        if isinstance(item, Exception):
            logger.warning(f"获取内容失败: {item}")
            processed_results.append({"markdown_content": None})
        else:
            processed_results.append(item)

    # 统计成功数量
    success_count = sum(1 for item in processed_results if item.get("markdown_content"))
    logger.info(f"成功获取 {success_count}/{len(processed_results)} 篇文章内容")

    return list(processed_results)


async def fetch_content(url: str) -> Optional[str]:
    """
    获取文章内容

    策略：
    1. playwright - 使用 Playwright（支持 JavaScript 渲染）
    2. http - 简单 HTTP 请求（轻量级）
    3. reader_api - Reader API（需要配置）
    """
    fetcher = cfg.content_fetcher

    if fetcher == "reader_api":
        return await fetch_content_via_reader_api(url)
    elif fetcher == "http":
        return await fetch_content_via_http(url)
    else:
        # playwright (default) - try playwright, fall back to http on error or no content
        try:
            result = await fetch_content_via_playwright(url)
            if result is not None and len(result) > 100:
                return result
            # Playwright didn't get useful content, fall back to HTTP
            logger.debug(f"Playwright 未获取到足够内容，降级到 HTTP 方式 (URL: {url})")
            return await fetch_content_via_http(url)
        except Exception as e:
            if "Executable doesn't exist" in str(e) or "BrowserType.launch" in str(e):
                logger.warning("Playwright 浏览器未安装，降级到 HTTP 方式")
            else:
                logger.warning(f"Playwright 错误: {type(e).__name__}，降级到 HTTP 方式")
            return await fetch_content_via_http(url)
