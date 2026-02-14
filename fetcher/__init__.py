from .baidu import BaiduFetcher
from .cailian import CailianFetcher
from .ifeng import IfengFetcher
from .jin10 import Jin10Fetcher
from .toutiao import ToutiaoFetcher
from .wallstreetcn import WallstreetcnFetcher
from .rss import RSSFetcher, RSSSource
from .registry import FetcherRegistry
import yaml
import logging

logger = logging.getLogger(__name__)

# Register standard fetchers
FetcherRegistry.register(BaiduFetcher())
FetcherRegistry.register(ToutiaoFetcher())
FetcherRegistry.register(IfengFetcher())
FetcherRegistry.register(CailianFetcher())
FetcherRegistry.register(WallstreetcnFetcher())
FetcherRegistry.register(Jin10Fetcher())

# Register RSS fetchers dynamically
try:
    with open("config/rss_sources.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        if data and "sources" in data:
            for s in data["sources"]:
                try:
                    # Construct RSSSource from config dict
                    # Handle potential missing keys with defaults
                    source_conf = RSSSource(
                        id=s["id"],
                        name=s["name"],
                        url=s["url"],
                        enabled=s.get("enabled", True),
                        language=s.get("language", "zh"),
                        translate=s.get("translate", False)
                    )
                    
                    if source_conf.enabled:
                        fetcher = RSSFetcher(source_conf)
                        FetcherRegistry.register(fetcher)
                        logger.info(f"Registered RSS source: {source_conf.name} ({source_conf.id})")
                except Exception as e:
                    logger.error(f"Failed to register RSS source {s.get('name', 'unknown')}: {e}")
                    
except Exception as e:
    logger.error(f"Failed to load RSS config: {e}")

__all__ = [
    "BaiduFetcher",
    "ToutiaoFetcher",
    "IfengFetcher",
    "CailianFetcher",
    "WallstreetcnFetcher",
    "Jin10Fetcher",
    "FetcherRegistry",
]
