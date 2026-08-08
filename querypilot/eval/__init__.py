"""Execution Match evaluation and Eval-Agent."""

from querypilot.eval.dataset import cases_from_records, default_qa_path, load_qa_cases
from querypilot.eval.execution_match import compare_results, execution_match
from querypilot.eval.models import CaseEvalResult, EvalCase, EvalReport, MatchResult, TimingInfo
from querypilot.eval.runner import (
    default_report_dir,
    load_eval_report,
    percentile,
    run_case,
    run_eval,
    save_eval_report,
    summarize,
)

__all__ = [
    "CaseEvalResult",
    "EvalCase",
    "EvalReport",
    "MatchResult",
    "TimingInfo",
    "cases_from_records",
    "compare_results",
    "default_qa_path",
    "default_report_dir",
    "execution_match",
    "load_eval_report",
    "load_qa_cases",
    "percentile",
    "run_case",
    "run_eval",
    "save_eval_report",
    "summarize",
]
