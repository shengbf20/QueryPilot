"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    metadata_dir: Path
    db_path: Path
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str


def get_settings() -> Settings:
    return Settings(
        root_dir=ROOT_DIR,
        data_dir=ROOT_DIR / "data",
        metadata_dir=ROOT_DIR / "metadata",
        db_path=ROOT_DIR / os.getenv("DUCKDB_PATH", "db/competition.duckdb"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    )
