"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    use_cache: bool | None = None
    max_rows: int = Field(default=1000, ge=1, le=100_000)
    use_parallel: bool = False


class ExportRequest(BaseModel):
    columns: list[str]
    rows: list[list[Any]] = Field(default_factory=list)
    filename: str = "querypilot_export.csv"


class HealthResponse(BaseModel):
    status: str = "ok"
