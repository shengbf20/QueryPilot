"""HTTP routes: /health, /api/ask, /api/export."""

from __future__ import annotations

import csv
import io
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from querypilot.api.llm_settings import apply_llm_settings, current_llm_settings
from querypilot.api.schemas import AskRequest, ExportRequest, HealthResponse, LlmSettingsUpdate
from querypilot.api.serialize import pipeline_result_to_api_dict

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/api/settings")
def api_settings_get() -> JSONResponse:
    return JSONResponse(
        content=current_llm_settings(),
        media_type="application/json; charset=utf-8",
    )


@router.put("/api/settings")
def api_settings_put(body: LlmSettingsUpdate) -> JSONResponse:
    payload = apply_llm_settings(
        api_key=body.api_key,
        base_url=body.base_url,
        model=body.model,
    )
    return JSONResponse(
        content=payload,
        media_type="application/json; charset=utf-8",
    )


@router.post("/api/ask")
def api_ask(body: AskRequest) -> JSONResponse:
    from querypilot.agent import ask

    history = [{"role": t.role, "content": t.content} for t in body.history]
    if body.mode == "agent":
        from querypilot.agentic import run as agentic_run

        result = agentic_run(
            body.question.strip(),
            session_id=body.session_id or None,
            history=history or None,
            max_rows=body.max_rows,
        )
    else:
        result = ask(
            body.question.strip(),
            max_rows=body.max_rows,
            use_cache=body.use_cache,
            use_parallel=body.use_parallel,
            history=history or None,
        )
    payload = pipeline_result_to_api_dict(result, max_rows=body.max_rows)
    # Explicit charset helps Windows clients / proxies display Chinese correctly.
    return JSONResponse(
        content=payload,
        media_type="application/json; charset=utf-8",
    )


def _export_filename(raw: str, ext: str) -> str:
    name = (raw or "").strip() or f"querypilot_export.{ext}"
    lower = name.lower()
    if lower.endswith(".csv") or lower.endswith(".xlsx"):
        name = name.rsplit(".", 1)[0]
    return f"{name}.{ext}"


def _content_disposition(filename: str, ext: str) -> str:
    fallback = f"querypilot_export.{ext}"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _xlsx_bytes(columns: list[str], rows: list[list[Any]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "结果"
    ws.append(list(columns))
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.post("/api/export")
def api_export(body: ExportRequest) -> Response:
    fmt = body.format
    name = _export_filename(body.filename, fmt)
    if fmt == "xlsx":
        data = _xlsx_bytes(body.columns, body.rows)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(body.columns)
        for row in body.rows:
            writer.writerow(row)
        data = buf.getvalue().encode("utf-8-sig")
        media = "text/csv; charset=utf-8"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": _content_disposition(name, fmt)},
    )
