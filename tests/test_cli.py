"""Tests for QueryPilot CLI (phase-2 step 7)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from querypilot.agent.models import PipelineResult
from querypilot.cli import build_parser, format_pipeline_result, main
from querypilot.config import get_settings


def test_build_parser_ask_defaults():
    parser = build_parser()
    args = parser.parse_args(["ask", "客户", "数量"])
    assert args.command == "ask"
    assert args.question == ["客户", "数量"]
    assert args.max_rows == 20
    assert args.max_few_shots == 3


def test_build_parser_version():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0


def test_format_pipeline_result_ok():
    result = PipelineResult(
        ok=True,
        question="客户数",
        sql="SELECT COUNT(*) AS cnt FROM ads_cust_info_d",
        tables=["ads_cust_info_d"],
        columns=["cnt"],
        rows=[(3,)],
        row_count=1,
        stage="done",
        message="ok",
    )
    text = format_pipeline_result(result)
    assert "status: ok" in text
    assert "ads_cust_info_d" in text
    assert "SELECT COUNT(*)" in text
    assert "cnt" in text
    assert "3" in text


def test_format_pipeline_result_failed_degraded():
    result = PipelineResult(
        ok=False,
        question="删除客户",
        sql="DELETE FROM ads_cust_info_d",
        degraded=True,
        message="L1 安全围栏拦截: Forbidden operation",
        stage="l1",
    )
    text = format_pipeline_result(result)
    assert "status: failed" in text
    assert "(degraded)" in text
    assert "stage: l1" in text
    assert "message: L1 安全围栏拦截" in text
    assert "DELETE FROM" in text


def test_format_pipeline_result_degraded_with_probe():
    result = PipelineResult(
        ok=True,
        question="200岁以上女性",
        sql="SELECT 1",
        stage="done",
        message="计数为 0",
        probe_message="计数为 0",
        probe_suggestions=["是否需要取消年龄限制？"],
        corrected=True,
    )
    text = format_pipeline_result(result)
    assert "(corrected)" in text
    assert "probe suggestions:" in text
    assert "年龄限制" in text


def test_format_pipeline_result_truncates_rows():
    rows = [(i,) for i in range(25)]
    result = PipelineResult(
        ok=True,
        question="列表",
        sql="SELECT id FROM t",
        columns=["id"],
        rows=rows,
        row_count=25,
        stage="done",
    )
    text = format_pipeline_result(result, max_print_rows=20)
    assert "rows: 25" in text
    assert "... (5 more rows not shown)" in text
    assert "\n19\n" in text + "\n"  # last printed row value (0..19)
    assert "\n24\n" not in text + "\n"


def test_main_no_command_prints_help(capsys):
    code = main([])
    assert code == 0
    captured = capsys.readouterr()
    assert "ask" in captured.out


def test_main_ask_uses_pipeline(capsys):
    fake = PipelineResult(
        ok=True,
        question="客户 数量",
        sql="SELECT 1 AS n",
        tables=["ads_cust_info_d"],
        columns=["n"],
        rows=[(1,)],
        row_count=1,
        stage="done",
    )
    with patch("querypilot.agent.ask", return_value=fake) as mocked:
        code = main(["ask", "客户", "数量", "--max-rows", "5", "--max-few-shots", "2"])
    assert code == 0
    mocked.assert_called_once_with("客户 数量", max_rows=5, max_few_shots=2)
    out = capsys.readouterr().out
    assert "SELECT 1 AS n" in out


def test_main_ask_failed_returns_1(capsys):
    fake = PipelineResult(
        ok=False,
        question="x",
        degraded=True,
        message="L1 blocked",
        stage="l1",
    )
    with patch("querypilot.agent.ask", return_value=fake):
        code = main(["ask", "x"])
    assert code == 1
    out = capsys.readouterr().out
    assert "L1 blocked" in out
    assert "status: failed" in out
    assert "(degraded)" in out


@pytest.mark.skipif(
    not get_settings().db_path.exists()
    or not get_settings().deepseek_api_key
    or get_settings().deepseek_api_key.startswith("sk-your"),
    reason="DB or DEEPSEEK_API_KEY not ready",
)
def test_live_cli_ask_smoke(capsys):
    code = main(
        ["ask", "有多少年龄大于30岁的女性客户？", "--max-rows", "5", "--max-few-shots", "2"]
    )
    out = capsys.readouterr().out
    assert "sql:" in out
    assert "status:" in out
    if code == 0:
        assert "status: ok" in out
        assert "ads_cust_info_d" in out or "SELECT" in out.upper()
    else:
        assert code == 1
        assert "status: failed" in out
        assert "message:" in out
