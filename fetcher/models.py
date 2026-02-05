"""数据模型定义"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Trend:
    """Trending topics 热搜"""

    id: str
    """标识符"""

    title: str
    """标题"""

    url: str
    """链接地址"""

    description: Optional[str] = None
    """描述"""

    score: Optional[int] = None
    """热度分数"""

    timestamp: Optional[str] = None
    """时间戳，格式：YYYY-MM-DD HH:MM"""
