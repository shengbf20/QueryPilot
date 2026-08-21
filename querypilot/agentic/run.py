"""Strong-agent entry: intent fence → session memory → tool loop → PipelineResult."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

import duckdb
from openai import OpenAI

from querypilot.agent.models import PipelineResult, StageTiming
from querypilot.agentic.loop import continue_messages, run_loop, seed_messages
from querypilot.agentic.tools import AgentWorkspace, build_opening
from querypilot.agentic.memory import SessionMemory, get_memory
from querypilot.agentic.protocol import MAX_LLM_TURNS
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.safety.intent_guard import check_malicious_intent, format_safety_message


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _as_history(history: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in history or []:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": content})
    return out


def run(
    question: str,
    *,
    session_id: str | None = None,
    history: Sequence[Mapping[str, Any]] | None = None,
    metadata: MetadataBundle | None = None,
    client: OpenAI | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    max_rows: int = 1000,
    include_values: bool = True,
    memory: SessionMemory | None = None,
    max_turns: int = MAX_LLM_TURNS,
) -> PipelineResult:
    """One strong-agent turn. Does not call ``ask()``."""
    t_all = time.perf_counter()
    timing = StageTiming()
    q = (question or "").strip()
    if not q:
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=question,
            degraded=True,
            message="问题不能为空",
            stage="agent",
            timing=timing,
            extras={"mode": "agent"},
        )

    intent = check_malicious_intent(q)
    if intent:
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=q,
            degraded=True,
            message=format_safety_message(intent),
            stage="safety",
            timing=timing,
            extras={"mode": "agent", "safety_reason": intent},
        )

    mem = memory or get_memory()
    sid = (session_id or "").strip() or uuid4().hex
    state = mem.get(sid)
    incoming = _as_history(history)
    if not incoming:
        incoming = list(state.turns)
    if not incoming or incoming[-1] != {"role": "user", "content": q}:
        state.turns.append({"role": "user", "content": q})

    ws = AgentWorkspace(
        question=q,
        history=incoming,
        metadata=metadata,
        client=client,
        con=con,
        max_rows=max_rows,
        include_values=include_values,
        constraints=list(state.constraints),
        sql=state.last_sql,
        rationale=state.last_rationale,
        tables=list(state.last_tables),
    )

    if state.messages:
        thread = continue_messages(state.messages, q)
    else:
        thread = seed_messages(q, history=incoming, opening=build_opening(ws))

    try:
        control = run_loop(ws, client=client, max_turns=max_turns, messages=thread)
    except Exception as exc:  # noqa: BLE001
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=q,
            degraded=True,
            message=f"强 Agent 失败: {exc}",
            stage="agent",
            timing=timing,
            extras={"mode": "agent", "session_id": sid},
        )

    if control.get("messages"):
        state.messages = list(control["messages"])

    thought = " ".join(control.get("thoughts") or []).strip()
    extras: dict[str, Any] = {
        "mode": "agent",
        "session_id": sid,
        "agent_trace": control.get("trace") or [],
    }
    timing.total_ms = _elapsed_ms(t_all)

    if control["kind"] == "clarify":
        msg = str(control.get("message") or "")
        state.turns.append({"role": "assistant", "content": msg})
        return PipelineResult(
            ok=True,
            question=q,
            sql="",
            rationale=thought,
            tables=ws.tables,
            message=msg,
            stage="clarify",
            pruned=ws.pruned,
            timing=timing,
            extras={**extras, "needs_clarify": True, "clarify": msg},
        )

    state.last_sql = ws.sql
    state.last_tables = list(ws.tables)
    state.last_probe = ws.probe_message
    state.last_rationale = ws.rationale
    if q and q not in state.constraints and len(state.constraints) < 8:
        state.constraints.append(q)

    if ws.ran:
        state.turns.append({"role": "assistant", "content": ws.sql or "ok"})
        message = "ok"
        if ws.probe_message:
            message = ws.probe_message
            if ws.probe_suggestions:
                message = message + " " + " / ".join(ws.probe_suggestions)
        return PipelineResult(
            ok=True,
            question=q,
            sql=ws.sql,
            rationale=thought or ws.rationale,
            tables=ws.tables,
            columns=ws.columns,
            rows=ws.rows,
            row_count=ws.row_count,
            message=message,
            probe_message=ws.probe_message,
            probe_suggestions=ws.probe_suggestions,
            corrected=ws.corrected,
            stage="done",
            pruned=ws.pruned,
            timing=timing,
            extras=extras,
        )

    note = str(control.get("message") or "") or "未能完成取数"
    state.turns.append({"role": "assistant", "content": note})
    return PipelineResult(
        ok=False,
        question=q,
        sql=ws.sql,
        rationale=thought or ws.rationale,
        tables=ws.tables,
        degraded=True,
        message=note,
        stage="agent",
        pruned=ws.pruned,
        timing=timing,
        extras=extras,
    )
