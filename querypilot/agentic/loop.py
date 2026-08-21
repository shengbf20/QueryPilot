"""Budgeted tool loop: append-only messages so the prompt prefix stays stable."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from querypilot.agent.prompt import find_exact_few_shot, load_few_shots
from querypilot.agentic.protocol import MAX_LLM_TURNS, SYSTEM_PROMPT, parse_agent_tools
from querypilot.agentic.tools import AgentWorkspace, dispatch_tool, run_sql
from querypilot.llm.chat import chat


def seed_messages(
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    opening: str | None = None,
) -> list[dict[str, str]]:
    """Initial thread: stable system + prior turns + current user question."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        role = turn.get("role", "")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    first = (opening or question).strip()
    last = messages[-1] if messages else None
    if last is None or last.get("role") != "user" or last.get("content") != first:
        messages.append({"role": "user", "content": first})
    return messages


def continue_messages(
    existing: list[dict[str, str]],
    question: str,
) -> list[dict[str, str]]:
    """Keep the old prefix; only append a new user turn if needed."""
    messages = [dict(m) for m in existing]
    if not messages or messages[0].get("role") != "system":
        return seed_messages(question, history=existing)
    last = messages[-1]
    if last.get("role") != "user" or last.get("content") != question:
        messages.append({"role": "user", "content": question})
    return messages


def _finish(
    *,
    kind: str,
    message: str,
    thoughts: list[str],
    trace: list[dict[str, Any]],
    thread: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "message": message,
        "thoughts": thoughts,
        "trace": trace,
        "messages": thread,
    }


def _try_exact_few_shot(
    ws: AgentWorkspace,
    thread: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Reuse ask() exact few-shot short-circuit: run the reflux SQL, then finish."""
    if any(t.get("role") == "assistant" for t in (ws.history or [])):
        return None
    hit = find_exact_few_shot(ws.question, load_few_shots())
    if hit is None:
        return None
    observe = run_sql(ws, {"sql": hit.sql, "rationale": hit.rationale})
    if not ws.ran:
        return None
    thought = hit.rationale or "exact few-shot"
    thread.append(
        {
            "role": "assistant",
            "content": f"与参考示例问句一致，直接执行该 SQL。\n"
            f'{{"tool": "run_sql", "args": {{"sql": {hit.sql!r}}}}}\n'
            '{"tool": "finish", "args": {}}',
        }
    )
    thread.append({"role": "user", "content": f"[run_sql]\n{observe}"})
    return _finish(
        kind="finish",
        message="",
        thoughts=[thought],
        trace=[
            {"turn": 1, "tool": "run_sql", "thought": thought, "observe": observe[:800]},
            {"turn": 1, "tool": "finish", "thought": thought},
        ],
        thread=thread,
    )


def run_loop(
    ws: AgentWorkspace,
    *,
    client: OpenAI | None = None,
    max_turns: int = MAX_LLM_TURNS,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the planner loop. Returns a control dict (not PipelineResult)."""
    thread = messages or seed_messages(ws.question, history=ws.history)
    exact = _try_exact_few_shot(ws, thread)
    if exact is not None:
        return exact

    trace: list[dict[str, Any]] = []
    thoughts: list[str] = []
    active = client or ws.client

    for turn in range(1, max_turns + 1):
        result = chat(
            thread,
            temperature=0.0,
            max_tokens=2500,
            client=active,
        )
        raw = result.content
        thread.append({"role": "assistant", "content": raw})
        try:
            calls = parse_agent_tools(raw)
        except ValueError as exc:
            left = max_turns - turn
            thread.append(
                {
                    "role": "user",
                    "content": f"协议错误: {exc}。请先写判断，再给出一个或多个工具 JSON。还可再调用 {left} 次。",
                }
            )
            trace.append({"turn": turn, "tool": "invalid", "error": str(exc)})
            continue

        for name, args, thought in calls:
            if thought:
                thoughts.append(thought)
            step = {"turn": turn, "tool": name, "thought": thought}
            trace.append(step)

            if name == "ask_user":
                message = str(args.get("message") or args.get("question") or "").strip()
                if not message:
                    message = "请补充要统计的指标、时间或客群。"
                return _finish(
                    kind="clarify",
                    message=message,
                    thoughts=thoughts,
                    trace=trace,
                    thread=thread,
                )

            if name == "finish":
                return _finish(
                    kind="finish",
                    message=str(args.get("message") or "").strip(),
                    thoughts=thoughts,
                    trace=trace,
                    thread=thread,
                )

            observe = dispatch_tool(ws, name, args)
            step["observe"] = observe[:800]
            left = max_turns - turn
            check = ""
            if name == "run_sql" and ws.ran:
                cols = "、".join(ws.columns) or "(无列)"
                check = (
                    f"\n本次结果列：{cols}；共 {ws.row_count} 行。"
                    "请对照用户原题检查这张表是否严格满足要求："
                    "每一列是否都是题面要的、有没有多出题面没点名的维度、分组是否停在题面要的那一层、时间窗/分母是否一致。"
                    "题面列出的分档只是标签口径，不要为凑齐清单而补空行。"
                    "不满足则改 SQL 再 run_sql；只有全部满足才 finish。不要因为「执行成功」就结束。"
                )
            thread.append(
                {
                    "role": "user",
                    "content": f"[{name}]\n{observe}{check}\n\n还可再调用 {left} 次工具。",
                }
            )
            if name == "run_sql" and ws.ran:
                # 先让模型看见结果表，再决定 finish 或改写；同轮后续 finish 不生效
                break

    return _finish(
        kind="budget",
        message=f"已达工具轮次上限（{max_turns}）",
        thoughts=thoughts,
        trace=trace,
        thread=thread,
    )
