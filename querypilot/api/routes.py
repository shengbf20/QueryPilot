"""HTTP routes: /health, /api/ask, /api/export."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from querypilot.api.schemas import AskRequest, ExportRequest, HealthResponse
from querypilot.api.serialize import pipeline_result_to_api_dict

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


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


@router.post("/api/export")
def api_export(body: ExportRequest) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(body.columns)
    for row in body.rows:
        writer.writerow(row)
    data = buf.getvalue().encode("utf-8-sig")
    name = body.filename.strip() or "querypilot_export.csv"
    if not name.lower().endswith(".csv"):
        name += ".csv"
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
