"""HTTP routes: /onboarding 问卷页面 + /api/onboarding/*（新表自助接入 UI 后端）。

流程（logs/08 §五 / ONBOARDING.md ⑤⑥ 的网页化）：
  GET  /onboarding/questionnaire?table=xxx   → Q1-Q7 + 机械默认答案
  POST /api/onboarding/register              → 答案落盘 + A6 同步 + A7/A8 回归报告
  GET  /onboarding                           → 表单页面（单文件 HTML，无构建）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from querypilot.table_ops.prompts import mechanical_questionnaire
from querypilot.table_ops.register import RegistrationAnswers, register_table, verify_registration

router = APIRouter()

_PAGE_PATH = Path(__file__).resolve().parent / "static" / "onboarding.html"


class RegisterRequest(BaseModel):
    """表单提交体（问卷答案）。"""

    table: str
    alias: str = ""
    description: str = ""
    domain: str = ""
    granularity: str = ""
    primary_key: list[str] | None = None
    column_descriptions: dict[str, str] = Field(default_factory=dict)
    column_aliases: dict[str, list[str]] = Field(default_factory=dict)
    join_edges: list[dict[str, Any]] = Field(default_factory=list)
    enum_meanings: dict[str, dict[str, str]] = Field(default_factory=dict)
    usage: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    cue_words: list[str] = Field(default_factory=list)
    smoke_questions: list[str] = Field(default_factory=list)
    metadata_dir: str | None = None  # 测试用：指向元数据副本；生产留空


@router.get("/onboarding")
def onboarding_page() -> FileResponse:
    return FileResponse(_PAGE_PATH, media_type="text/html; charset=utf-8")


@router.get("/api/onboarding/questionnaire")
def api_questionnaire(table: str) -> JSONResponse:
    """生成 Q1-Q7 问卷（A1/A2/A3/A4 机械候选 + 默认答案）。"""
    table = table.strip()
    if not table:
        return JSONResponse({"ok": False, "error": "table 不能为空"}, status_code=400)
    try:
        questionnaire = mechanical_questionnaire(table)
    except ValueError as exc:  # 表不在库里
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    return JSONResponse(
        {"ok": True, "questionnaire": questionnaire},
        media_type="application/json; charset=utf-8",
    )


@router.post("/api/onboarding/register")
def api_register(body: RegisterRequest) -> JSONResponse:
    """问卷答案 → A5 落盘 → A6 同步报告 → A7/A8 回归报告。"""
    if not body.alias.strip():
        return JSONResponse({"ok": False, "error": "表别名（Q1）不能为空"}, status_code=400)
    if not body.description.strip():
        return JSONResponse({"ok": False, "error": "表描述（Q1）不能为空"}, status_code=400)
    if not body.cue_words:
        return JSONResponse(
            {"ok": False, "error": "触发词（必填）不能为空：用户提到什么词必须选中这张表？"},
            status_code=400,
        )

    answers = RegistrationAnswers(
        table=body.table.strip(),
        alias=body.alias.strip(),
        description=body.description.strip(),
        domain=body.domain,
        granularity=body.granularity,
        primary_key=body.primary_key,
        column_descriptions={k: v for k, v in body.column_descriptions.items() if v.strip()},
        column_aliases=body.column_aliases,
        join_edges=body.join_edges,
        enum_meanings=body.enum_meanings,
        usage=body.usage,
        notes=body.notes,
        cue_words=[c.strip() for c in body.cue_words if c.strip()],
    )

    metadata_dir = Path(body.metadata_dir) if body.metadata_dir else None
    try:
        result = register_table(answers, metadata_dir=metadata_dir)
    except FileExistsError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    sync = verify_registration(body.table.strip(), metadata_dir=metadata_dir)

    from querypilot.table_ops.validate import run_onboarding_regression

    regression = run_onboarding_regression(
        body.table.strip(),
        smoke_questions=[q for q in body.smoke_questions if q.strip()],
        metadata_dir=metadata_dir,
    )

    return JSONResponse(
        {
            "ok": sync.ok and regression.ok,
            "table": result.table,
            "files_written": [str(p) for p in (result.table_yaml_path, result.join_graph_path, result.pruning_path)],
            "sync": {"ok": sync.ok, "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in sync.checks]},
            "regression": {
                "ok": regression.ok,
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in regression.checks],
            },
            "cue_inherited": bool(result.pruning_insert),
        },
        media_type="application/json; charset=utf-8",
    )
