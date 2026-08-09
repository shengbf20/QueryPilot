"""Tests for QueryPilot CLI (phase-2 ask + phase-3 eval)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from querypilot.agent.models import PipelineResult
from querypilot.cli import (
    build_parser,
    format_diagnoses,
    format_eval_report,
    format_pipeline_result,
    main,
)
from querypilot.config import get_settings
from querypilot.eval.models import CaseEvalResult, Diagnosis, EvalReport, TimingInfo


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
    assert "timing_ms:" in text
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
    assert "eval" in captured.out
    assert "review" in captured.out


def test_build_parser_eval_defaults():
    parser = build_parser()
    args = parser.parse_args(["eval"])
    assert args.command == "eval"
    assert args.limit is None
    assert args.path is None
    assert args.paths is None
    assert args.max_rows is None
    assert args.max_few_shots == 3
    assert args.no_exact_few_shot is False
    assert args.output is None
    assert args.no_save is False
    assert args.diagnose is False
    assert args.diagnose_output is None
    assert args.no_llm_diagnose is False
    assert args.review is False
    assert args.review_output is None


def test_build_parser_eval_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "eval",
            "--limit",
            "5",
            "--path",
            "data/Q&A.xlsx",
            "--paths",
            "data/extra/Q&A_easy.xlsx",
            "--paths",
            "data/extra/Q&A_medium.xlsx",
            "--max-rows",
            "50",
            "--max-few-shots",
            "2",
            "--no-exact-few-shot",
            "--output",
            "out.json",
            "--no-save",
        ]
    )
    assert args.limit == 5
    assert args.path == "data/Q&A.xlsx"
    assert args.paths == [
        "data/extra/Q&A_easy.xlsx",
        "data/extra/Q&A_medium.xlsx",
    ]
    assert args.max_rows == 50
    assert args.max_few_shots == 2
    assert args.no_exact_few_shot is True
    assert args.output == "out.json"
    assert args.no_save is True


def test_format_eval_report_summary():
    report = EvalReport(
        total=2,
        matched_count=1,
        accuracy=0.5,
        failed_ids=["2"],
        p50_ms=100.0,
        p95_ms=200.0,
        results=[
            CaseEvalResult(
                case_id="1",
                question="q1",
                matched=True,
                score=1.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=100.0),
            ),
            CaseEvalResult(
                case_id="2",
                question="q2",
                matched=False,
                score=0.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
                error="row multiset mismatch",
                timing=TimingInfo(total_ms=200.0),
            ),
        ],
    )
    text = format_eval_report(report)
    assert "EX: 1/2 = 50.0%" in text
    assert "failed=['2']" in text
    assert "p50_ms=100.0" in text
    assert "[OK] id=1" in text
    assert "[FAIL] id=2" in text
    assert "row multiset mismatch" in text


def test_main_eval_uses_run_eval(capsys, tmp_path: Path):
    report = EvalReport(
        total=1,
        matched_count=1,
        accuracy=1.0,
        failed_ids=[],
        p50_ms=12.0,
        p95_ms=12.0,
        results=[
            CaseEvalResult(
                case_id="1",
                question="q",
                matched=True,
                score=1.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=12.0),
            )
        ],
    )
    out = tmp_path / "r.json"
    with patch("querypilot.eval.run_eval", return_value=report) as mocked:
        code = main(
            [
                "eval",
                "--limit",
                "2",
                "--path",
                "data/Q&A.xlsx",
                "--max-rows",
                "10",
                "--max-few-shots",
                "1",
                "--output",
                str(out),
            ]
        )
    assert code == 0
    mocked.assert_called_once_with(
        path="data/Q&A.xlsx",
        paths=None,
        limit=2,
        max_rows=10,
        max_few_shots=1,
        allow_exact_few_shot=True,
        max_workers=1,
    )
    printed = capsys.readouterr().out
    assert "EX: 1/1 = 100.0%" in printed
    assert "report saved:" in printed
    assert out.exists()


def test_main_eval_no_save(capsys, tmp_path: Path):
    report = EvalReport(total=0, matched_count=0, accuracy=0.0, results=[], failed_ids=[])
    with patch("querypilot.eval.run_eval", return_value=report):
        with patch("querypilot.eval.save_eval_report") as save_mock:
            code = main(["eval", "--no-save"])
    assert code == 0
    save_mock.assert_not_called()
    assert "report saved:" not in capsys.readouterr().out


def test_format_diagnoses():
    text = format_diagnoses(
        [
            Diagnosis(
                case_id="2",
                matched=False,
                error_types=["column_mismatch"],
                summary="列数不一致",
                markdown="## Case 2\n\n**Summary:** 列数不一致\n",
            )
        ]
    )
    assert "Case 2" in text
    assert "列数不一致" in text
    assert format_diagnoses([]) == "diagnoses: (none)"


def test_main_eval_diagnose_heuristic(capsys, tmp_path: Path):
    report = EvalReport(
        total=1,
        matched_count=0,
        accuracy=0.0,
        failed_ids=["2"],
        results=[
            CaseEvalResult(
                case_id="2",
                question="q",
                matched=False,
                score=0.0,
                error="column count mismatch: pred=3 gold=2",
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=10.0),
            )
        ],
    )
    diag_out = tmp_path / "diag.json"
    with patch("querypilot.eval.run_eval", return_value=report):
        with patch("querypilot.eval.save_eval_report", return_value=tmp_path / "r.json"):
            code = main(
                [
                    "eval",
                    "--diagnose",
                    "--no-llm-diagnose",
                    "--diagnose-output",
                    str(diag_out),
                ]
            )
    assert code == 0
    out = capsys.readouterr().out
    assert "EX:" in out
    assert "Case 2" in out or "column_mismatch" in out
    assert "diagnoses saved:" in out
    assert diag_out.exists()


def test_main_eval_diagnose_output_requires_flag():
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--diagnose-output", "d.json"])
    assert exc.value.code == 2


def test_main_eval_diagnose_no_save_skips_diag_persist(capsys):
    """P0: --diagnose --no-save prints attribution but must not write diag JSON."""
    report = EvalReport(
        total=1,
        matched_count=0,
        accuracy=0.0,
        failed_ids=["2"],
        results=[
            CaseEvalResult(
                case_id="2",
                question="q",
                matched=False,
                score=0.0,
                error="column count mismatch: pred=3 gold=2",
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=10.0),
            )
        ],
    )
    with patch("querypilot.eval.run_eval", return_value=report):
        with patch("querypilot.eval.save_eval_report") as save_report:
            with patch("querypilot.eval.save_diagnoses") as save_diag:
                with patch(
                    "querypilot.eval.diagnose_failures",
                    return_value=[
                        Diagnosis(
                            case_id="2",
                            matched=False,
                            error_types=["column_mismatch"],
                            summary="列数不一致",
                            markdown="## Case 2\n",
                        )
                    ],
                ) as diagnose_mock:
                    code = main(["eval", "--diagnose", "--no-llm-diagnose", "--no-save"])
    assert code == 0
    diagnose_mock.assert_called_once()
    assert diagnose_mock.call_args.kwargs.get("use_llm") is False
    save_report.assert_not_called()
    save_diag.assert_not_called()
    out = capsys.readouterr().out
    assert "Case 2" in out
    assert "diagnoses saved:" not in out


def test_main_eval_diagnose_output_and_no_save_exclusive():
    """P1: --diagnose-output cannot combine with --no-save."""
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--diagnose", "--diagnose-output", "d.json", "--no-save"])
    assert exc.value.code == 2


def test_main_eval_review_builds_queue(capsys, tmp_path: Path):
    report = EvalReport(
        total=2,
        matched_count=1,
        accuracy=0.5,
        failed_ids=["2"],
        results=[
            CaseEvalResult(
                case_id="1",
                question="ok",
                matched=True,
                score=1.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=1.0),
            ),
            CaseEvalResult(
                case_id="2",
                question="bad",
                matched=False,
                score=0.0,
                error="column count mismatch: pred=3 gold=2",
                gold_sql="SELECT 1",
                pred_sql="SELECT 1,2,3",
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=2.0),
            ),
        ],
    )
    qout = tmp_path / "queue.json"
    with patch("querypilot.eval.run_eval", return_value=report):
        with patch("querypilot.eval.save_eval_report", return_value=tmp_path / "r.json"):
            with patch("querypilot.eval.save_diagnoses", return_value=tmp_path / "d.json"):
                code = main(
                    [
                        "eval",
                        "--review",
                        "--no-llm-diagnose",
                        "--review-output",
                        str(qout),
                    ]
                )
    assert code == 0
    out = capsys.readouterr().out
    assert "review:" in out
    assert "auto_pass=['1']" in out
    # heuristic conf 0.55 < 0.60 → bad_case (not needs_review)
    assert "bad_case=['2']" in out
    assert qout.exists()
    loaded = json.loads(qout.read_text(encoding="utf-8"))
    assert loaded["bad_case_ids"] == ["2"]


def test_main_eval_review_no_save_skips_queue_persist(capsys):
    """P0: --review --no-save prints queue but must not write queue JSON."""
    report = EvalReport(
        total=1,
        matched_count=0,
        accuracy=0.0,
        failed_ids=["2"],
        results=[
            CaseEvalResult(
                case_id="2",
                question="q",
                matched=False,
                score=0.0,
                error="column count mismatch: pred=3 gold=2",
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=1.0),
            )
        ],
    )
    with patch("querypilot.eval.run_eval", return_value=report):
        with patch("querypilot.eval.save_eval_report") as save_report:
            with patch("querypilot.eval.save_review_queue") as save_queue:
                with patch("querypilot.eval.save_diagnoses") as save_diag:
                    code = main(
                        ["eval", "--review", "--no-llm-diagnose", "--no-save"]
                    )
    assert code == 0
    save_report.assert_not_called()
    save_queue.assert_not_called()
    save_diag.assert_not_called()
    out = capsys.readouterr().out
    assert "review:" in out
    assert "review queue saved:" not in out


def test_main_eval_review_output_requires_flag():
    """P1: --review-output requires --review."""
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--review-output", "q.json"])
    assert exc.value.code == 2


def test_main_eval_review_output_and_no_save_exclusive():
    """P1: --review-output cannot combine with --no-save."""
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--review", "--review-output", "q.json", "--no-save"])
    assert exc.value.code == 2


def test_main_review_reflux(tmp_path: Path, capsys):
    few = tmp_path / "examples.yaml"
    few.write_text("examples: []\n", encoding="utf-8")
    code = main(
        [
            "review",
            "reflux",
            "--question",
            "测试问句",
            "--sql",
            "SELECT 1",
            "--rationale",
            "unit",
            "--few-shots",
            str(few),
        ]
    )
    assert code == 0
    assert "written" in capsys.readouterr().out
    assert "测试问句" in few.read_text(encoding="utf-8")


def test_main_review_approve_and_missing_case(tmp_path: Path, capsys):
    """P1: review approve refluxes gold SQL; unknown case_id → exit 1."""
    from querypilot.eval import (
        Diagnosis,
        build_review_queue,
        save_review_queue,
    )

    few = tmp_path / "examples.yaml"
    few.write_text("examples: []\n", encoding="utf-8")
    queue_path = tmp_path / "queue.json"
    report = EvalReport(
        total=1,
        matched_count=0,
        accuracy=0.0,
        failed_ids=["2"],
        results=[
            CaseEvalResult(
                case_id="2",
                question="年龄段资产",
                matched=False,
                score=0.0,
                gold_sql="SELECT age, SUM(a) AS aset FROM t GROUP BY age",
                ask_ok=True,
                gold_ok=True,
                stage="done",
                timing=TimingInfo(total_ms=1.0),
            )
        ],
    )
    queue = build_review_queue(
        report,
        [Diagnosis(case_id="2", matched=False, confidence=0.8, summary="cols")],
    )
    save_review_queue(queue, queue_path)

    code = main(
        [
            "review",
            "approve",
            "--queue",
            str(queue_path),
            "--case-id",
            "2",
            "--few-shots",
            str(few),
            "--write-queue",
            str(queue_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "approved case=2" in out
    assert "written" in out
    assert "年龄段资产" in few.read_text(encoding="utf-8")
    reloaded = json.loads(queue_path.read_text(encoding="utf-8"))
    assert reloaded["tickets"][0]["status"] == "approved"

    code_miss = main(
        [
            "review",
            "approve",
            "--queue",
            str(queue_path),
            "--case-id",
            "missing",
            "--few-shots",
            str(few),
        ]
    )
    assert code_miss == 1
    assert "not found" in capsys.readouterr().out


def test_main_eval_default_save_calls_with_none(capsys):
    """P1: bare `eval` must persist via save_eval_report(report, None)."""
    report = EvalReport(total=0, matched_count=0, accuracy=0.0, results=[], failed_ids=[])
    with patch("querypilot.eval.run_eval", return_value=report):
        with patch(
            "querypilot.eval.save_eval_report",
            return_value="logs/eval_reports/eval_default.json",
        ) as save_mock:
            code = main(["eval"])
    assert code == 0
    save_mock.assert_called_once()
    saved_report, saved_path = save_mock.call_args.args
    assert saved_report is report
    assert saved_path is None
    assert "report saved:" in capsys.readouterr().out


def test_main_eval_output_and_no_save_are_exclusive():
    """P1: --output and --no-save must not be combined silently."""
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--output", "out.json", "--no-save"])
    assert exc.value.code == 2


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
    mocked.assert_called_once_with(
        "客户 数量",
        max_rows=5,
        max_few_shots=2,
        use_cache=None,
        cache_rows=None,
        use_parallel=False,
    )
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


def _cli_live_ready() -> bool:
    settings = get_settings()
    return (
        settings.db_path.exists()
        and bool(settings.deepseek_api_key)
        and not settings.deepseek_api_key.startswith("sk-your")
    )


@pytest.mark.skipif(not _cli_live_ready(), reason="DB or DEEPSEEK_API_KEY not ready")
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


@pytest.mark.skipif(
    not _cli_live_ready() or not (get_settings().data_dir / "Q&A.xlsx").exists(),
    reason="DB, DEEPSEEK_API_KEY, or Q&A.xlsx not ready",
)
def test_live_cli_eval_smoke(capsys, tmp_path: Path):
    """P1: CLI eval → real run_eval; shape only, not EX target."""
    out = tmp_path / "cli_eval_smoke.json"
    code = main(["eval", "--limit", "1", "--output", str(out)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "EX:" in printed
    assert "report saved:" in printed
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert '"total": 1' in text
    assert "accuracy" in text
    assert "p50_ms" in text
