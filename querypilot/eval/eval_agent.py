"""Eval-Agent: attribute EX / pipeline failures (heuristic + optional LLM)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from querypilot.config import get_settings
from querypilot.eval.models import CaseEvalResult, Diagnosis, EvalReport

ERROR_TYPES: tuple[str, ...] = (
    "column_mismatch",
    "row_mismatch",
    "schema_hallucination",
    "join_error",
    "time_filter",
    "aggregation",
    "filter_predicate",
    "agent_failed",
    "gold_failed",
    "unknown",
)

_ERROR_TYPE_SET = set(ERROR_TYPES)

SYSTEM_PROMPT = """你是 NL2SQL 评测归因助手。根据用户问题、预测 SQL、金标 SQL 与评测错误信息，判断失败原因。
只输出 JSON 对象，字段：
- error_types: 字符串数组，元素必须取自给定枚举
- summary: 一句中文结论
- evidence: 字符串数组（简短证据）
- suggestions: 字符串数组（可执行的改法，面向 Prompt/Few-Shot/剪枝）
- confidence: 0 到 1 的小数
不要输出 markdown 代码块。"""


def classify_heuristic(result: CaseEvalResult) -> list[str]:
    """Rule-based error types from stage/error/SQL text (no LLM)."""
    if result.matched:
        return []

    types: list[str] = []
    err = (result.error or result.match_reason or "").lower()
    pred = (result.pred_sql or "").lower()
    gold = (result.gold_sql or "").lower()

    if not result.gold_ok or "gold execute failed" in err:
        types.append("gold_failed")
    if not result.ask_ok:
        types.append("agent_failed")

    if "column count mismatch" in err:
        types.append("column_mismatch")
    if (
        "row multiset mismatch" in err
        or "ordered row mismatch" in err
        or "row count" in err
    ):
        types.append("row_mismatch")
    if (
        "table not allowed" in err
        or "unknown column" in err
        or "unknown_column" in err
        or "forbidden" in err
    ):
        types.append("schema_hallucination")

    if "join" in err or "join condition" in err:
        types.append("join_error")
    elif (" join " in f" {pred} ") != (" join " in f" {gold} "):
        types.append("join_error")

    gold_compact = gold.replace(" ", "")
    if "max(data_dt)" in pred and "data_dt=" in gold_compact:
        types.append("time_filter")
    elif re.search(r"between\s+'?\d{8}", pred) and re.search(r"between\s+'?\d{8}", gold):
        if re.findall(r"\d{8}", pred) != re.findall(r"\d{8}", gold):
            types.append("time_filter")

    if ("group by" in pred) != ("group by" in gold) or ("count(" in pred) != (
        "count(" in gold
    ):
        types.append("aggregation")
    elif "sum(" in pred and "sum(" not in gold:
        types.append("aggregation")

    # de-dup preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for t in types:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered or ["unknown"]


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, conf))


def _normalize_types(raw: Any, fallback: Sequence[str]) -> list[str]:
    if not isinstance(raw, list):
        return list(fallback)
    out: list[str] = []
    for item in raw:
        name = str(item).strip().lower()
        if name in _ERROR_TYPE_SET and name not in out:
            out.append(name)
    return out or list(fallback)


def _as_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def render_diagnosis_markdown(diagnosis: Diagnosis) -> str:
    """Render a Diagnosis as Markdown (idempotent if markdown already set)."""
    lines = [
        f"## Case {diagnosis.case_id}",
        "",
        f"- **matched**: {diagnosis.matched}",
        f"- **source**: {diagnosis.source}",
        f"- **confidence**: {diagnosis.confidence:.2f}",
        f"- **error_types**: {', '.join(diagnosis.error_types) if diagnosis.error_types else '(none)'}",
        "",
        f"**Summary:** {diagnosis.summary or '-'}",
        "",
    ]
    if diagnosis.evidence:
        lines.append("**Evidence:**")
        for item in diagnosis.evidence:
            lines.append(f"- {item}")
        lines.append("")
    if diagnosis.suggestions:
        lines.append("**Suggestions:**")
        for item in diagnosis.suggestions:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _heuristic_summary(result: CaseEvalResult, types: Sequence[str]) -> str:
    if result.matched:
        return "EX matched; no attribution needed."
    primary = types[0] if types else "unknown"
    err = (result.error or result.match_reason or "").strip()
    if err:
        return f"Heuristic={primary}: {err[:160]}"
    return f"Heuristic attribution: {primary} (stage={result.stage or '-'})"


def _heuristic_suggestions(types: Sequence[str]) -> list[str]:
    tips: list[str] = []
    mapping = {
        "column_mismatch": "对齐金标投影列：不要多选客户数等额外指标，除非题目明确要求。",
        "row_mismatch": "检查过滤条件、分组键与去重逻辑是否与金标一致。",
        "schema_hallucination": "加强 Schema 剪枝/表白名单；Few-Shot 强调仅用给定表列。",
        "join_error": "检查 pty_id/org_id Join，避免默认 data_dt 对齐。",
        "time_filter": "核对题目时间窗与金标 data_dt / BETWEEN 口径。",
        "aggregation": "核对 COUNT/SUM 与 GROUP BY 是否与题意、金标一致。",
        "agent_failed": "查看 stage（generate/l1/l2）；优先修幻觉表列或 Prompt 硬规则。",
        "gold_failed": "检查金标 SQL 是否兼容 DuckDB；必要时改写方言后再评。",
    }
    for t in types:
        if t in mapping and mapping[t] not in tips:
            tips.append(mapping[t])
    return tips or ["对照 pred_sql 与 gold_sql 人工复核后写入 Bad Case。"]


def build_diagnose_prompt(
    result: CaseEvalResult,
    *,
    heuristic_types: Sequence[str],
) -> str:
    types_help = ", ".join(ERROR_TYPES)
    return (
        f"错误类型枚举: {types_help}\n"
        f"启发式初判: {list(heuristic_types)}\n\n"
        f"case_id: {result.case_id}\n"
        f"stage: {result.stage}\n"
        f"ask_ok: {result.ask_ok}\n"
        f"gold_ok: {result.gold_ok}\n"
        f"match_reason/error: {result.error or result.match_reason}\n"
        f"score: {result.score}\n\n"
        f"用户问题:\n{result.question}\n\n"
        f"预测 SQL:\n{result.pred_sql or '(empty)'}\n\n"
        f"金标 SQL:\n{result.gold_sql or '(empty)'}\n"
    )


def diagnose_case(
    result: CaseEvalResult,
    *,
    client: OpenAI | None = None,
    use_llm: bool = True,
) -> Diagnosis:
    """Attribute one case. Matched cases return an empty-type passed diagnosis."""
    if result.matched:
        diagnosis = Diagnosis(
            case_id=result.case_id,
            matched=True,
            error_types=[],
            summary="EX matched; no attribution needed.",
            evidence=[],
            suggestions=[],
            confidence=1.0,
            source="heuristic",
        )
        diagnosis.markdown = render_diagnosis_markdown(diagnosis)
        return diagnosis

    heuristic = classify_heuristic(result)
    diagnosis = Diagnosis(
        case_id=result.case_id,
        matched=False,
        error_types=list(heuristic),
        summary=_heuristic_summary(result, heuristic),
        evidence=[
            x
            for x in [
                f"stage={result.stage}" if result.stage else "",
                f"error={result.error}" if result.error else "",
                f"match_reason={result.match_reason}" if result.match_reason else "",
            ]
            if x
        ],
        suggestions=_heuristic_suggestions(heuristic),
        confidence=0.55 if heuristic != ["unknown"] else 0.35,
        source="heuristic",
        raw={"heuristic_types": list(heuristic)},
    )

    if not use_llm:
        diagnosis.markdown = render_diagnosis_markdown(diagnosis)
        return diagnosis

    try:
        from querypilot.llm.chat import generate_json

        payload = generate_json(
            build_diagnose_prompt(result, heuristic_types=heuristic),
            system=SYSTEM_PROMPT,
            client=client,
            temperature=0.0,
        )
        llm_types = _normalize_types(payload.get("error_types"), heuristic)
        # Prefer union: heuristic signals + llm, heuristic first
        merged: list[str] = []
        for t in list(heuristic) + llm_types:
            if t not in merged:
                merged.append(t)
        diagnosis.error_types = merged
        diagnosis.summary = str(payload.get("summary") or diagnosis.summary).strip()
        evidence = _as_str_list(payload.get("evidence"))
        if evidence:
            diagnosis.evidence = evidence
        suggestions = _as_str_list(payload.get("suggestions"))
        if suggestions:
            diagnosis.suggestions = suggestions
        diagnosis.confidence = _clamp_confidence(
            payload.get("confidence"),
            default=diagnosis.confidence,
        )
        diagnosis.source = "heuristic+llm"
        diagnosis.raw = {"heuristic_types": list(heuristic), "llm": payload}
    except Exception as exc:  # noqa: BLE001 — fall back to heuristic
        diagnosis.source = "heuristic"
        diagnosis.raw["llm_error"] = str(exc)

    diagnosis.markdown = render_diagnosis_markdown(diagnosis)
    return diagnosis


def diagnose_failures(
    report: EvalReport,
    *,
    client: OpenAI | None = None,
    use_llm: bool = True,
    include_matched: bool = False,
) -> list[Diagnosis]:
    """Diagnose failed cases in a report (optionally include matched)."""
    out: list[Diagnosis] = []
    for item in report.results:
        if item.matched and not include_matched:
            continue
        out.append(diagnose_case(item, client=client, use_llm=use_llm))
    return out


def save_diagnoses(
    diagnoses: Sequence[Diagnosis],
    path: Path | str | None = None,
) -> Path:
    """Write diagnoses JSON (+ embedded markdown) under logs/eval_reports/ by default."""
    if path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = get_settings().root_dir / "logs" / "eval_reports" / f"diag_{stamp}.json"
    else:
        out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(diagnoses),
        "diagnoses": [d.to_dict() for d in diagnoses],
        "markdown": "\n".join(d.markdown for d in diagnoses if d.markdown),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


__all__ = [
    "ERROR_TYPES",
    "SYSTEM_PROMPT",
    "build_diagnose_prompt",
    "classify_heuristic",
    "diagnose_case",
    "diagnose_failures",
    "render_diagnosis_markdown",
    "save_diagnoses",
]
