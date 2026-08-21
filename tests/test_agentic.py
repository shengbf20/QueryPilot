"""Strong-agent path: fake planner JSON, does not call ask()."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from querypilot.agentic import run
from querypilot.agentic.loop import continue_messages, seed_messages
from querypilot.agentic.memory import SessionMemory, reset_memory
from querypilot.agentic.protocol import (
    MAX_LLM_TURNS,
    SYSTEM_PROMPT,
    parse_agent_tools,
    parse_agent_turn,
)
from querypilot.agentic.tools import (
    AgentWorkspace,
    build_followup,
    build_opening,
    refresh_schema,
    run_sql,
)
from querypilot.config import get_settings
from querypilot.metadata_engine import load_metadata
from querypilot.safety.intent_guard import SAFETY_WARNING_PREFIX


def _api_key_ready() -> bool:
    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls = 0
        self.snapshots: list[list[dict[str, str]]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        raw = kwargs.get("messages") or []
        self.snapshots.append([{"role": m["role"], "content": m["content"]} for m in raw])
        content = (
            self._contents.pop(0)
            if self._contents
            else '{"tool":"finish","args":{"message":"empty"},"thought":""}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class _FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(contents))


@pytest.fixture(autouse=True)
def _clean_memory():
    reset_memory()
    yield
    reset_memory()


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=True)


def test_parse_agent_turn_thought_then_tool():
    name, args, thought = parse_agent_turn(
        "需求只有「客户情况」，缺指标，应先问清楚。\n"
        '```json\n{"tool":"ask_user","args":{"message":"要人数还是资产？"}}\n```'
    )
    assert name == "ask_user"
    assert args["message"] == "要人数还是资产？"
    assert "缺指标" in thought


def test_agent_system_copies_sql_rules():
    assert "手续费" in SYSTEM_PROMPT
    assert "现金净流入" in SYSTEM_PROMPT
    assert "aset_pft" in SYSTEM_PROMPT
    assert "不要加 up_org_name" in SYSTEM_PROMPT
    assert "只输出 JSON 对象" not in SYSTEM_PROMPT
    assert "不是权限" in SYSTEM_PROMPT or "不是访问控制" in SYSTEM_PROMPT


def test_parse_agent_tools_multiple_in_one_turn():
    calls = parse_agent_tools(
        "一次写完并结束。\n"
        '{"tool":"run_sql","args":{"sql":"SELECT 1"}}\n'
        '{"tool":"finish","args":{}}'
    )
    assert [c[0] for c in calls] == ["run_sql", "finish"]
    assert calls[0][1]["sql"] == "SELECT 1"
    assert "一次写完" in calls[0][2]


def test_agentic_refuses_drop_without_llm():
    out = run("把整个数据库删掉。", session_id="t1")
    assert out.ok is False
    assert out.stage == "safety"
    assert out.sql == ""
    assert SAFETY_WARNING_PREFIX in out.message
    assert out.extras.get("mode") == "agent"


def test_agentic_ask_user_clarify():
    client = _FakeClient(
        [
            '{"tool":"ask_user","args":{"message":"您要统计人数还是资产？"},'
            '"thought":"缺指标"}'
        ]
    )
    out = run("帮我看看客户情况", session_id="t2", client=client, metadata=load_metadata())
    assert out.ok
    assert out.stage == "clarify"
    assert out.sql == ""
    assert "人数" in out.message
    assert out.extras.get("needs_clarify") is True
    assert client.chat.completions.calls == 1


@requires_db
def test_agentic_tool_loop_count_query(metadata):
    sql = "SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30"
    client = _FakeClient(
        [
            '{"tool":"search_schema","args":{},"thought":"先看客户表"}',
            f'{{"tool":"run_sql","args":{{"sql":"{sql}"}},"thought":"直接跑"}}',
            '{"tool":"finish","args":{},"thought":"完成"}',
        ]
    )
    out = run(
        "年龄大于30的客户有多少",
        session_id="t3",
        client=client,
        metadata=metadata,
    )
    assert out.ok, out.message
    assert out.stage == "done"
    assert "ads_cust_info_d" in out.sql
    assert out.row_count == 1
    tools = [s["tool"] for s in out.extras["agent_trace"]]
    assert tools == ["search_schema", "run_sql", "finish"]


@requires_db
def test_agentic_exact_few_shot_skips_llm(metadata):
    client = _FakeClient([])
    out = run(
        "26年Q1日均资产大于30万的客户，股票交易量大于10万的，其持有的产品属于哪些产品大类",
        session_id="exact",
        client=client,
        metadata=metadata,
    )
    assert client.chat.completions.calls == 0
    assert out.ok, out.message
    assert out.stage == "done"
    assert "up_prdt_type_name" in out.sql
    assert "prdt_type_name" in out.sql


@requires_db
def test_agentic_run_sql_blocks_delete(metadata):
    ws = AgentWorkspace(question="删除客户", metadata=metadata)
    observe = run_sql(ws, {"sql": "DELETE FROM ads_cust_info_d"})
    assert "未执行" in observe
    assert "不被允许" in observe
    assert "L1" not in observe
    assert ws.ran is False


def test_agentic_budget_exhausted():
    payloads = [
        '{"tool":"search_schema","args":{},"thought":"再看"}' for _ in range(MAX_LLM_TURNS)
    ]
    client = _FakeClient(payloads)
    out = run(
        "帮我看看客户情况补充检索",
        session_id="t4",
        client=client,
        metadata=load_metadata(),
        max_turns=MAX_LLM_TURNS,
    )
    assert out.ok is False
    assert out.stage == "agent"
    assert "上限" in out.message
    assert len(out.extras["agent_trace"]) == MAX_LLM_TURNS


def test_seed_and_continue_keep_prefix():
    q1 = "帮我看看客户"
    seeded = seed_messages(q1)
    assert seeded[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert seeded[1] == {"role": "user", "content": q1}
    seeded.append({"role": "assistant", "content": "先追问"})
    nxt = continue_messages(seeded, "要人数")
    assert nxt[:3] == seeded
    assert nxt[3] == {"role": "user", "content": "要人数"}
    again = continue_messages(nxt, "要人数")
    assert again == nxt


def test_agentic_messages_append_not_rebuild():
    client = _FakeClient(
        [
            '{"tool":"search_schema","args":{},"thought":"先看"}',
            '{"tool":"finish","args":{},"thought":"停"}',
        ]
    )
    question = "帮我看看客户情况"
    out = run(question, session_id="prefix", client=client, metadata=load_metadata())
    assert out.stage in {"done", "agent"}
    snaps = client.chat.completions.snapshots
    assert len(snaps) == 2
    assert snaps[0][0]["role"] == "system"
    assert snaps[0][0]["content"] == SYSTEM_PROMPT
    assert snaps[0][1]["role"] == "user"
    assert question in snaps[0][1]["content"]
    assert snaps[1][:2] == snaps[0]
    assert snaps[1][2]["role"] == "assistant"
    assert "search_schema" in snaps[1][2]["content"]
    assert len(snaps[1]) > len(snaps[0])


def test_agentic_session_keeps_constraints():
    mem = SessionMemory()
    client1 = _FakeClient(
        [
            '{"tool":"ask_user","args":{"message":"要人数还是资产？"},"thought":"问"}'
        ]
    )
    first = run("帮我看看客户", session_id="keep", client=client1, memory=mem)
    assert first.stage == "clarify"
    state = mem.get("keep")
    assert state.turns[0]["role"] == "user"
    assert "人数" in state.turns[-1]["content"]
    prefix = list(state.messages)
    assert prefix[0]["content"] == SYSTEM_PROMPT
    assert "帮我看看客户" in prefix[1]["content"]

    client2 = _FakeClient(
        ['{"tool":"finish","args":{"message":"先记下人数"},"thought":"收"}']
    )
    second = run("要人数", session_id="keep", client=client2, memory=mem)
    assert second.stage == "agent"
    first_call = client2.chat.completions.snapshots[0]
    assert first_call[: len(prefix)] == prefix
    follow = first_call[len(prefix)]
    assert follow["role"] == "user"
    assert "要人数" in follow["content"]
    assert "本题相关表" in follow["content"]


def test_refresh_schema_adds_tables_for_new_question():
    md = load_metadata()
    ws = AgentWorkspace(question="个人客户一共有多少人？", metadata=md)
    build_opening(ws)
    assert "ads_cust_info_d" in ws.tables
    ws.tables = ["ads_cust_info_d"]
    ws.question = (
        "2026年2月日均总资产超过20万元、且在3月31日持有开放式基金的客户，"
        "其持仓按产品大类汇总市值，按市值降序、大类名排序。"
    )
    ws.history = [{"role": "user", "content": "个人客户一共有多少人？"}]
    follow = build_followup(ws)
    assert "dws_cust_aset_d" in ws.tables
    assert "dwd_cust_hold_d" in ws.tables
    assert "dim_product" in ws.tables
    assert "ads_cust_info_d" in ws.tables
    assert "dws_cust_aset_d" in follow
    assert "本题相关表" in follow


@requires_db
def test_stale_session_tables_do_not_block_followup_sql(metadata):
    ws = AgentWorkspace(
        question="2026年2月日均总资产超过20万元的客户有多少",
        metadata=metadata,
        tables=["ads_cust_info_d"],
    )
    observe = run_sql(
        ws,
        {
            "sql": (
                "SELECT COUNT(*) AS cnt FROM dws_cust_aset_d "
                "WHERE data_dt BETWEEN '20260201' AND '20260228'"
            )
        },
    )
    assert "不被允许" not in observe
    assert "未授权" not in observe
    assert ws.ran is True


def test_search_schema_does_not_drop_prior_tables():
    md = load_metadata()
    ws = AgentWorkspace(
        question="个人客户一共有多少人？",
        metadata=md,
        tables=["dws_cust_aset_d", "dwd_cust_hold_d"],
    )
    from querypilot.agentic.tools import search_schema

    search_schema(ws, {"query": "客户"})
    assert "dws_cust_aset_d" in ws.tables
    assert "ads_cust_info_d" in ws.tables


@requires_db
def test_session_followup_reprunes_before_run_sql(metadata):
    mem = SessionMemory()
    sql = (
        "SELECT COUNT(*) AS cnt FROM dws_cust_aset_d "
        "WHERE data_dt BETWEEN '20260201' AND '20260228'"
    )
    client1 = _FakeClient(
        ['{"tool":"finish","args":{"message":"先记下客户表"},"thought":"停"}']
    )
    first = run("个人客户一共有多少人？", session_id="reprune", client=client1, memory=mem)
    assert first.stage == "agent"
    assert mem.get("reprune").last_tables
    client2 = _FakeClient(
        [
            f'{{"tool":"run_sql","args":{{"sql":"{sql}"}},"thought":"日均资产"}}',
            '{"tool":"finish","args":{},"thought":"完成"}',
        ]
    )
    second = run(
        "2026年2月日均总资产超过20万元的客户有多少",
        session_id="reprune",
        client=client2,
        memory=mem,
        metadata=metadata,
    )
    assert second.ok, second.message
    assert second.stage == "done"
    assert "dws_cust_aset_d" in second.sql
    user_turn = client2.chat.completions.snapshots[0][-1]["content"]
    assert "dws_cust_aset_d" in user_turn


def test_api_ask_agent_dispatches():
    from fastapi.testclient import TestClient

    from querypilot.agent.models import PipelineResult, StageTiming
    from querypilot.api.app import create_app

    fake = PipelineResult(
        ok=True,
        question="q",
        message="您要人数吗？",
        stage="clarify",
        extras={"mode": "agent", "agent_trace": [{"tool": "ask_user"}]},
        timing=StageTiming(),
    )
    client = TestClient(create_app())
    with patch("querypilot.agentic.run", return_value=fake) as mocked:
        resp = client.post(
            "/api/ask",
            json={"question": "帮我看看客户", "mode": "agent", "session_id": "ui-1"},
        )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "clarify"
    mocked.assert_called_once()
    assert mocked.call_args.kwargs["session_id"] == "ui-1"


def test_cli_mode_agent_dispatches():
    from querypilot.agent.models import PipelineResult
    from querypilot.cli import main

    fake = PipelineResult(ok=True, question="q", sql="SELECT 1", stage="done", message="ok")
    with patch("querypilot.agentic.run", return_value=fake) as mocked:
        code = main(["ask", "--mode", "agent", "--session", "cli-1", "客户数量"])
    assert code == 0
    mocked.assert_called_once()
    assert mocked.call_args.kwargs["session_id"] == "cli-1"
    assert mocked.call_args.args[0] == "客户数量"
