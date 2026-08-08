"""Phase-3 baseline closeout helpers (EX% / latency / gap to 90%)."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from querypilot.config import get_settings
from querypilot.eval.models import Diagnosis, EvalReport, ReviewQueue

TARGET_EX = 0.90


def default_baseline_stem() -> Path:
    """Default path stem: logs/eval_reports/phase3_baseline (no suffix)."""
    return get_settings().root_dir / "logs" / "eval_reports" / "phase3_baseline"


def build_baseline_summary(
    report: EvalReport,
    *,
    diagnoses: Sequence[Diagnosis] | None = None,
    queue: ReviewQueue | None = None,
    target_ex: float = TARGET_EX,
    label: str = "phase3_baseline",
) -> dict[str, Any]:
    """Build a JSON-serializable baseline summary from an eval report."""
    total = report.total
    matched = report.matched_count
    accuracy = report.accuracy
    gap = max(0.0, target_ex - accuracy)
    need_matched = math.ceil(target_ex * total - 1e-12) if total else 0
    need_more = max(0, min(total - matched, need_matched - matched))

    failed = []
    for item in report.results:
        if item.matched:
            continue
        failed.append(
            {
                "case_id": item.case_id,
                "question": item.question,
                "stage": item.stage,
                "ask_ok": item.ask_ok,
                "gold_ok": item.gold_ok,
                "error": item.error or item.match_reason,
                "total_ms": item.timing.total_ms,
            }
        )

    type_counts: dict[str, int] = {}
    for d in diagnoses or []:
        if d.matched:
            continue
        for t in d.error_types or ["unknown"]:
            type_counts[t] = type_counts.get(t, 0) + 1

    review_buckets = None
    if queue is not None:
        review_buckets = {
            "auto_pass": list(queue.auto_pass_ids),
            "needs_review": list(queue.needs_review_ids),
            "bad_case": list(queue.bad_case_ids),
            "review_share": (
                len(queue.needs_review_ids) / total if total else 0.0
            ),
            "bad_case_share": (len(queue.bad_case_ids) / total if total else 0.0),
        }

    return {
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_ex": target_ex,
        "total": total,
        "matched_count": matched,
        "accuracy": accuracy,
        "gap_to_target": gap,
        "additional_matches_needed": need_more,
        "failed_ids": list(report.failed_ids),
        "failed_cases": failed,
        "latency_ms": {
            "p50": report.p50_ms,
            "p95": report.p95_ms,
            "mean": report.mean_ms,
        },
        "by_difficulty": dict(report.by_difficulty),
        "error_type_counts": type_counts,
        "review_buckets": review_buckets,
        "notes": [
            "阶段三基线：评测平台可复跑；准确率未要求达到 >90%（阶段五验收）。",
            "提准：归因 + Few-Shot 回流 + 剪枝/Prompt；提速：阶段四缓存/并行。",
        ],
    }


def format_baseline_markdown(summary: dict[str, Any]) -> str:
    """Render baseline summary as Markdown for logs / handoff."""
    lat = summary.get("latency_ms") or {}
    lines = [
        f"# Baseline: {summary.get('label', 'baseline')}",
        "",
        f"- **created_at**: {summary.get('created_at', '-')}",
        f"- **EX**: {summary.get('matched_count', 0)}/{summary.get('total', 0)} "
        f"= {float(summary.get('accuracy') or 0):.1%}",
        f"- **target_ex**: {float(summary.get('target_ex') or TARGET_EX):.0%}",
        f"- **gap_to_target**: {float(summary.get('gap_to_target') or 0):.1%}",
        f"- **additional_matches_needed**: {summary.get('additional_matches_needed', 0)}",
        f"- **latency p50/p95/mean (ms)**: "
        f"{lat.get('p50')}, {lat.get('p95')}, {lat.get('mean')}",
        f"- **failed_ids**: {summary.get('failed_ids', [])}",
        "",
    ]
    type_counts = summary.get("error_type_counts") or {}
    if type_counts:
        lines.append("## Error type counts")
        lines.append("")
        for k, v in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    buckets = summary.get("review_buckets")
    if buckets:
        lines.append("## Review buckets")
        lines.append("")
        lines.append(f"- auto_pass: {buckets.get('auto_pass', [])}")
        lines.append(f"- needs_review: {buckets.get('needs_review', [])}")
        lines.append(f"- bad_case: {buckets.get('bad_case', [])}")
        lines.append(
            f"- review_share / bad_case_share: "
            f"{float(buckets.get('review_share') or 0):.1%} / "
            f"{float(buckets.get('bad_case_share') or 0):.1%}"
        )
        lines.append("")

    failed_cases = summary.get("failed_cases") or []
    if failed_cases:
        lines.append("## Failed cases")
        lines.append("")
        for item in failed_cases:
            q = str(item.get("question") or "").replace("\n", " ")
            if len(q) > 80:
                q = q[:77] + "..."
            lines.append(
                f"- **id={item.get('case_id')}** stage={item.get('stage')} "
                f"ask_ok={item.get('ask_ok')} gold_ok={item.get('gold_ok')} "
                f"total_ms={item.get('total_ms')}"
            )
            lines.append(f"  - Q: {q}")
            err = str(item.get("error") or "")[:160]
            if err:
                lines.append(f"  - error: {err}")
        lines.append("")

    notes = summary.get("notes") or []
    if notes:
        lines.append("## Notes")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_baseline(
    summary: dict[str, Any],
    *,
    stem: Path | str | None = None,
    report: EvalReport | None = None,
) -> tuple[Path, Path]:
    """
    Write ``{stem}.json`` summary and ``{stem}.md`` markdown.

    If ``report`` is provided, also write ``{stem}_report.json`` full EvalReport.
    Returns ``(json_path, md_path)``.
    """
    base = Path(stem) if stem is not None else default_baseline_stem()
    base.parent.mkdir(parents=True, exist_ok=True)
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(format_baseline_markdown(summary), encoding="utf-8")
    if report is not None:
        from querypilot.eval.runner import save_eval_report

        save_eval_report(report, Path(str(base) + "_report.json"))
    return json_path, md_path


def load_baseline(path: Path | str) -> dict[str, Any]:
    """Load a baseline summary JSON."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "TARGET_EX",
    "build_baseline_summary",
    "default_baseline_stem",
    "format_baseline_markdown",
    "load_baseline",
    "save_baseline",
]
