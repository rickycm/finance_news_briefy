import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration"""

    # Summary generation
    enable_summary: bool

    # Reader API
    reader_api_endpoint: str
    reader_api_key: str

    # LLM
    llm_api_key: str
    llm_model: str
    llm_api_base: str

    # Paths
    data_dir: Path
    summaries_dir: Path
    audio_dir: Path
    temp_dir: Path

    # Scheduler
    fetch_interval_minutes: int

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables"""
        return cls(
            enable_summary=os.getenv("ENABLE_SUMMARY", "0") == "1",
            reader_api_endpoint=os.getenv("READER_API_ENDPOINT", "https://api.shuyanai.com/v1/reader"),
            reader_api_key=os.getenv("READER_API_KEY", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            llm_api_base=os.getenv("LLM_API_BASE", ""),
            data_dir=Path("data"),
            summaries_dir=Path("data/summaries"),
            audio_dir=Path("data/audio"),
            temp_dir=Path("temp"),
            fetch_interval_minutes=int(os.getenv("FETCH_INTERVAL_MINUTES", "30")),
        )


# Global config instance
cfg = Config.from_env()
