"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def _env_flag(name: str, *, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    metadata_dir: Path
    db_path: Path
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    cache_enabled: bool
    cache_backend: str
    redis_url: str
    cache_rows: bool
    query_cache_maxsize: int


def get_settings() -> Settings:
    # QUERYPPILOT_CACHE preferred; CACHE_ENABLED accepted as alias
    if os.getenv("QUERYPPILOT_CACHE") is not None:
        cache_enabled = _env_flag("QUERYPPILOT_CACHE", default=True)
    else:
        cache_enabled = _env_flag("CACHE_ENABLED", default=True)
    try:
        maxsize = int(os.getenv("QUERYPPILOT_QUERY_CACHE_MAXSIZE", "256"))
    except ValueError:
        maxsize = 256
    return Settings(
        root_dir=ROOT_DIR,
        data_dir=ROOT_DIR / "data",
        metadata_dir=ROOT_DIR / "metadata",
        db_path=ROOT_DIR / os.getenv("DUCKDB_PATH", "db/competition.duckdb"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        cache_enabled=cache_enabled,
        cache_backend=os.getenv("CACHE_BACKEND", "memory").strip().lower() or "memory",
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        cache_rows=_env_flag("QUERYPPILOT_CACHE_ROWS", default=False),
        query_cache_maxsize=max(1, maxsize),
    )
