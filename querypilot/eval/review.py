"""File-level HITL review routing + Few-Shot reflux (phase-3 step 5)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from querypilot.config import get_settings
from querypilot.eval.models import (
    BUCKET_AUTO_PASS,
    BUCKET_BAD_CASE,
    BUCKET_NEEDS_REVIEW,
    CaseEvalResult,
    Diagnosis,
    EvalReport,
    ReviewQueue,
    ReviewTicket,
)

# README-aligned bands for unmatched cases (attribution confidence).
CONF_REVIEW_MIN = 0.60
CONF_HIGH = 0.85


def default_review_dir() -> Path:
    return get_settings().root_dir / "logs" / "review"


def default_few_shots_path() -> Path:
    return get_settings().metadata_dir / "few_shots" / "examples.yaml"


def route_case(
    result: CaseEvalResult,
    diagnosis: Diagnosis | None = None,
    *,
    review_min: float = CONF_REVIEW_MIN,
) -> str:
    """Return bucket: auto_pass | needs_review | bad_case."""
    if result.matched:
        return BUCKET_AUTO_PASS
    conf = 0.0 if diagnosis is None else float(diagnosis.confidence)
    if conf >= review_min:
        return BUCKET_NEEDS_REVIEW
    return BUCKET_BAD_CASE


def build_review_queue(
    report: EvalReport,
    diagnoses: Sequence[Diagnosis] | None = None,
    *,
    review_min: float = CONF_REVIEW_MIN,
) -> ReviewQueue:
    """Build a review queue from eval results and optional diagnoses."""
    diag_map: dict[str, Diagnosis] = {}
    for d in diagnoses or []:
        diag_map[d.case_id] = d

    tickets: list[ReviewTicket] = []
    auto_pass_ids: list[str] = []
    needs_review_ids: list[str] = []
    bad_case_ids: list[str] = []

    for item in report.results:
        diag = diag_map.get(item.case_id)
        bucket = route_case(item, diag, review_min=review_min)
        ticket = ReviewTicket(
            case_id=item.case_id,
            bucket=bucket,
            question=item.question,
            gold_sql=item.gold_sql,
            pred_sql=item.pred_sql,
            matched=item.matched,
            score=item.score,
            confidence=0.0 if diag is None else diag.confidence,
            error=item.error or item.match_reason,
            error_types=list(diag.error_types) if diag else [],
            diagnosis_summary=diag.summary if diag else "",
        )
        tickets.append(ticket)
        if bucket == BUCKET_AUTO_PASS:
            auto_pass_ids.append(item.case_id)
        elif bucket == BUCKET_NEEDS_REVIEW:
            needs_review_ids.append(item.case_id)
        else:
            bad_case_ids.append(item.case_id)

    return ReviewQueue(
        tickets=tickets,
        auto_pass_ids=auto_pass_ids,
        needs_review_ids=needs_review_ids,
        bad_case_ids=bad_case_ids,
    )


def save_review_queue(
    queue: ReviewQueue,
    path: Path | str | None = None,
) -> Path:
    """Persist review queue JSON under logs/review/ by default."""
    if path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = default_review_dir() / f"queue_{stamp}.json"
    else:
        out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = queue.to_dict()
    payload["saved_at"] = datetime.now(timezone.utc).isoformat()
    payload["thresholds"] = {
        "review_min": CONF_REVIEW_MIN,
        "high": CONF_HIGH,
        "note": "matched→auto_pass; unmatched conf>=review_min→needs_review; else bad_case",
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_review_queue(path: Path | str) -> ReviewQueue:
    """Load a previously saved review queue."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tickets = [ReviewTicket(**t) for t in data.get("tickets") or []]
    return ReviewQueue(
        tickets=tickets,
        auto_pass_ids=list(data.get("auto_pass_ids") or []),
        needs_review_ids=list(data.get("needs_review_ids") or []),
        bad_case_ids=list(data.get("bad_case_ids") or []),
    )


def _norm_question(question: str) -> str:
    return " ".join(question.strip().split())


def _load_few_shot_doc(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"examples": []}
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        return {"examples": []}
    examples = raw.get("examples")
    if not isinstance(examples, list):
        raw["examples"] = []
    return raw


def append_few_shot(
    question: str,
    sql: str,
    *,
    rationale: str = "",
    path: Path | str | None = None,
    skip_duplicate: bool = True,
) -> tuple[bool, Path]:
    """
    Append one example to few_shots YAML.

    Returns ``(written, path)``. If ``skip_duplicate`` and the same question
    already exists, returns ``(False, path)`` without rewriting.
    """
    q = question.strip()
    s = sql.strip()
    if not q or not s:
        raise ValueError("question and sql are required for few-shot reflux")

    out = Path(path) if path is not None else default_few_shots_path()
    doc = _load_few_shot_doc(out)
    examples: list[Any] = list(doc.get("examples") or [])
    norm_q = _norm_question(q)
    if skip_duplicate:
        for item in examples:
            if isinstance(item, Mapping) and _norm_question(str(item.get("question", ""))) == norm_q:
                return False, out

    entry: dict[str, str] = {"question": q, "sql": s if s.endswith("\n") else s + "\n"}
    if rationale.strip():
        entry["rationale"] = rationale.strip()
    examples.append(entry)
    doc["examples"] = examples
    out.parent.mkdir(parents=True, exist_ok=True)
    # Preserve a short header comment when rewriting.
    # Prefer block scalars for multiline SQL so examples.yaml stays readable.
    class _Dumper(yaml.SafeDumper):
        pass

    def _str_representer(dumper: yaml.SafeDumper, data: str):  # type: ignore[name-defined]
        style = "|" if "\n" in data else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

    _Dumper.add_representer(str, _str_representer)
    body = yaml.dump(doc, Dumper=_Dumper, allow_unicode=True, sort_keys=False)
    header = "# Few-shot CoT examples for NL2SQL (marketing analytics)\n\n"
    if out.exists():
        existing = out.read_text(encoding="utf-8")
        if existing.lstrip().startswith("#"):
            # keep first comment block lines starting with #
            lines = existing.splitlines()
            comment: list[str] = []
            for line in lines:
                if line.startswith("#") or not line.strip():
                    comment.append(line)
                else:
                    break
            if comment:
                header = "\n".join(comment).rstrip() + "\n\n"
    out.write_text(header + body, encoding="utf-8")
    return True, out


def approve_and_reflux(
    ticket: ReviewTicket,
    *,
    sql: str | None = None,
    rationale: str | None = None,
    few_shots_path: Path | str | None = None,
    skip_duplicate: bool = True,
) -> tuple[bool, Path, ReviewTicket]:
    """
    Human approval: append gold (or override) SQL to Few-Shot YAML.

    Marks ticket status=approved and refluxed=True when written (or already present).
    """
    chosen_sql = (sql if sql is not None else ticket.gold_sql).strip()
    if not chosen_sql:
        raise ValueError(f"ticket {ticket.case_id}: no SQL to reflux")
    reason = rationale if rationale is not None else (
        ticket.diagnosis_summary
        or f"HITL reflux from case {ticket.case_id}"
    )
    written, path = append_few_shot(
        ticket.question,
        chosen_sql,
        rationale=reason,
        path=few_shots_path,
        skip_duplicate=skip_duplicate,
    )
    ticket.status = "approved"
    ticket.refluxed = True
    return written, path, ticket


def reject_ticket(ticket: ReviewTicket) -> ReviewTicket:
    """Mark a ticket rejected (no Few-Shot write)."""
    ticket.status = "rejected"
    ticket.refluxed = False
    return ticket


def find_ticket(queue: ReviewQueue, case_id: str) -> ReviewTicket | None:
    for t in queue.tickets:
        if t.case_id == case_id:
            return t
    return None


def format_review_queue(queue: ReviewQueue) -> str:
    """CLI-friendly summary of a review queue."""
    lines = [
        f"review: auto_pass={queue.auto_pass_ids}  "
        f"needs_review={queue.needs_review_ids}  "
        f"bad_case={queue.bad_case_ids}"
    ]
    for t in queue.tickets:
        lines.append(
            f"  [{t.bucket}] id={t.case_id} matched={t.matched} "
            f"conf={t.confidence:.2f} status={t.status} "
            f"types={t.error_types or '-'}"
        )
        if t.error:
            lines.append(f"       error={t.error[:120]}")
    return "\n".join(lines)


__all__ = [
    "CONF_HIGH",
    "CONF_REVIEW_MIN",
    "append_few_shot",
    "approve_and_reflux",
    "build_review_queue",
    "default_few_shots_path",
    "default_review_dir",
    "find_ticket",
    "format_review_queue",
    "load_review_queue",
    "reject_ticket",
    "route_case",
    "save_review_queue",
]
