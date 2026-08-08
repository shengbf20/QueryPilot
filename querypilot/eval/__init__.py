"""Execution Match evaluation and Eval-Agent."""

from querypilot.eval.dataset import cases_from_records, default_qa_path, load_qa_cases
from querypilot.eval.eval_agent import (
    ERROR_TYPES,
    classify_heuristic,
    diagnose_case,
    diagnose_failures,
    render_diagnosis_markdown,
    save_diagnoses,
)
from querypilot.eval.execution_match import compare_results, execution_match
from querypilot.eval.models import (
    CaseEvalResult,
    Diagnosis,
    EvalCase,
    EvalReport,
    MatchResult,
    TimingInfo,
)
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
    "Diagnosis",
    "ERROR_TYPES",
    "EvalCase",
    "EvalReport",
    "MatchResult",
    "TimingInfo",
    "cases_from_records",
    "classify_heuristic",
    "compare_results",
    "default_qa_path",
    "default_report_dir",
    "diagnose_case",
    "diagnose_failures",
    "execution_match",
    "load_eval_report",
    "load_qa_cases",
    "percentile",
    "render_diagnosis_markdown",
    "run_case",
    "run_eval",
    "save_diagnoses",
    "save_eval_report",
    "summarize",
]
