"""AI 客户端模块 - 使用 LiteLLM 统一接口"""

import asyncio
import logging
import re
from typing import List

from litellm import acompletion

from config import cfg

logger = logging.getLogger(__name__)

# 内容截取长度（避免超过 8K tokens 限制）
# GLM-4-Flash 免费版：上下文超过 8K tokens 时，并发限制为标准速率的 1%
# 中文文本：约 1.5-2 字符 = 1 token
# Prompt 本身约 500-1000 tokens，所以内容限制在约 12000 字符（约 6000-7000 tokens）
MAX_CONTENT_LENGTH = 12000

# 重试配置
MAX_RETRIES = 3
INITIAL_DELAY = 1.0  # 初始延迟（秒）
MAX_DELAY = 60.0  # 最大延迟（秒）
BACKOFF_MULTIPLIER = 2.0  # 指数退避倍率

# 摘要生成 Prompt 模板
SUMMARY_PROMPT_TEMPLATE = """你是一个专业的新闻摘要助手。请根据以下内容生成简洁、准确的摘要。

**原始内容：**

{content}

**要求：**

1. 字数：250-300字

2. 结构清晰，分段呈现（2-3个自然段）

3. 保留关键信息、数据、人物、时间等要素

4. 使用客观、中立的语气

5. 避免主观评价和情绪化表达

6. 如果是争议话题，呈现多方观点

7. 保持逻辑连贯，易于理解

**输出格式：**

直接输出摘要内容，不需要标题或其他说明。"""


async def generate_summaries(news_list: List[dict]) -> List[dict]:
    """
    为每条新闻生成摘要（逐条处理，带重试）

    Args:
        news_list: 新闻列表，每个元素包含 title, url, markdown_content 等字段

    Returns:
        带摘要的新闻列表，每个元素添加了 summary 字段
    """
    if not cfg.llm_api_key:
        logger.error("LLM_API_KEY not set")
        return news_list

    results = []

    # 逐条处理
    for i, news in enumerate(news_list, 1):
        logger.info(
            f"处理 {i}/{len(news_list)}: {news.get('title', 'Unknown')[:50]}..."
        )

        prompt = _build_prompt(news)

        try:
            summary = await _invoke_llm_with_retry(prompt)
            news_copy = news.copy()
            news_copy["summary"] = summary
        except Exception as e:
            logger.error(f"LLM 调用失败（第 {i} 条，已重试 {MAX_RETRIES} 次）: {e}")
            news_copy = news.copy()
            news_copy["summary"] = ""

        results.append(news_copy)

        # 添加请求间隔，避免触发速率限制（每条之间等待 5 秒）
        if i < len(news_list):
            await asyncio.sleep(5.0)

    return results


async def generate_summaries_with_progress(
    news_list: List[dict], date: str, total: int
) -> List[dict]:
    """
    为每条新闻生成摘要（带进度更新）

    Args:
        news_list: 新闻列表
        date: 日期字符串（用于更新进度）
        total: 总数量（用于计算进度）

    Returns:
        带摘要的新闻列表
    """
    if not cfg.llm_api_key:
        logger.error("LLM_API_KEY not set")
        return news_list

    results = []

    for i, news in enumerate(news_list, 1):
        logger.info(f"处理 {i}/{len(news_list)}: {news.get('title', 'Unknown')[:50]}...")

        prompt = _build_prompt(news)

        try:
            summary = await _invoke_llm_with_retry(prompt)
            news_copy = news.copy()
            news_copy["summary"] = summary
        except Exception as e:
            logger.error(f"LLM 调用失败（第 {i} 条，已重试 {MAX_RETRIES} 次）: {e}")
            news_copy = news.copy()
            news_copy["summary"] = ""

        results.append(news_copy)

        # 更新进度
        from summary.generator import _write_progress

        _write_progress(date, i, total)

        # 添加请求间隔，避免触发速率限制（每条之间等待 5 秒）
        if i < len(news_list):
            await asyncio.sleep(5.0)

    return results


def _build_prompt(news: dict) -> str:
    """构建 LLM 提示词"""
    if news.get("markdown_content"):
        content = news["markdown_content"][:MAX_CONTENT_LENGTH]
        if len(news["markdown_content"]) > MAX_CONTENT_LENGTH:
            content += "..."
    else:
        content = f"标题：{news['title']}\n\n（无法获取正文内容，请根据标题生成摘要）"

    return SUMMARY_PROMPT_TEMPLATE.format(content=content)


def _is_rate_limit_error(error: Exception) -> bool:
    """检测是否是速率限制错误"""
    error_str = str(error).lower()
    rate_limit_keywords = [
        "rate limit",
        "rateLimit",
        "rate_limit",
        "限流",
        "速率限制",
        "too many requests",
        "429",
    ]
    return any(keyword in error_str for keyword in rate_limit_keywords)


async def _invoke_llm_with_retry(prompt: str) -> str:
    """
    调用 LLM 生成摘要（带重试机制）

    Args:
        prompt: 提示词

    Returns:
        摘要文本
    """
    delay = INITIAL_DELAY

    for attempt in range(MAX_RETRIES):
        try:
            return await _invoke_llm(prompt)
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)

            if attempt == MAX_RETRIES - 1:
                # 最后一次尝试，直接抛出异常
                logger.error(f"LLM 调用失败（已重试 {MAX_RETRIES} 次）: {e}")
                raise

            if is_rate_limit:
                logger.warning(
                    f"触发速率限制，{delay:.1f}秒后重试（{attempt + 1}/{MAX_RETRIES}）"
                )
            else:
                logger.warning(
                    f"LLM 调用失败，{delay:.1f}秒后重试（{attempt + 1}/{MAX_RETRIES}）: {e}"
                )

            await asyncio.sleep(delay)
            delay = min(delay * BACKOFF_MULTIPLIER, MAX_DELAY)


async def _invoke_llm(prompt: str) -> str:
    """
    调用 LLM 生成摘要

    Args:
        prompt: 提示词

    Returns:
        摘要文本
    """
    try:
        response = await acompletion(
            model=cfg.llm_model,
            messages=[{"role": "user", "content": prompt}],
            api_key=cfg.llm_api_key,
            api_base=cfg.llm_api_base if cfg.llm_api_base else None,
            temperature=0.7,
            max_tokens=2000,  # 增加 token 限制，确保能返回完整摘要
        )

        content = response.choices[0].message.content
        logger.debug(f"AI 返回内容（前500字符）: {content[:500]}")

        summary = _extract_summary(content)

        # 验证摘要质量
        if summary and len(summary) < 200:
            logger.warning(
                f"摘要太短（{len(summary)}字，要求250-300字）: {summary[:100]}..."
            )

        return summary

    except Exception as e:
        logger.error(f"AI API 调用失败: {e}")
        raise


def _extract_summary(response: str) -> str:
    """从 LLM 响应中提取摘要"""
    content = response.strip()

    if not content:
        return ""

    # 移除可能的标记前缀（如"摘要："等）
    content = re.sub(r"^摘要[：:]\s*", "", content).strip()

    return content
