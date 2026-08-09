"""Reflux approved Extra candidates into metadata/few_shots/examples.yaml (Step 5)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.eval.dataset import load_qa_cases_many
from querypilot.eval.review import append_few_shot
from querypilot.agent.prompt import find_exact_few_shot, load_few_shots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=ROOT / "metadata/few_shots/candidates_extra.yaml",
    )
    parser.add_argument(
        "--examples",
        type=Path,
        default=ROOT / "metadata/few_shots/examples.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing examples.yaml",
    )
    args = parser.parse_args(argv)

    raw = yaml.safe_load(args.candidates.read_text(encoding="utf-8")) or {}
    candidates = list(raw.get("candidates") or [])
    approved = [c for c in candidates if str(c.get("status", "")).lower() == "approved"]
    if not approved:
        print("no approved candidates")
        return 1

    written_n = 0
    skipped_n = 0
    for item in approved:
        q = str(item["question"]).strip()
        sql = str(item["sql"]).strip()
        rationale = str(item.get("rationale") or "").strip()
        src = item.get("source_case_id", "?")
        if args.dry_run:
            print(f"[dry-run] would reflux {src}: {q[:40]}...")
            continue
        written, path = append_few_shot(
            q, sql, rationale=rationale, path=args.examples, skip_duplicate=True
        )
        if written:
            written_n += 1
            print(f"[write] {src} -> {path.name}")
        else:
            skipped_n += 1
            print(f"[skip-dup] {src}")

    if args.dry_run:
        return 0

    # Isolation: Extra eval questions must not exact-match any few-shot.
    eval_paths = [
        ROOT / "data/extra/Q&A_easy.xlsx",
        ROOT / "data/extra/Q&A_medium.xlsx",
        ROOT / "data/extra/Q&A_hard.xlsx",
    ]
    shots = load_few_shots(args.examples)
    polluted: list[str] = []
    for case in load_qa_cases_many(eval_paths):
        if find_exact_few_shot(case.question, shots) is not None:
            polluted.append(case.id)
    print(f"reflux done: written={written_n} skipped_dup={skipped_n} examples={len(shots)}")
    if polluted:
        print("POLLUTION: exact few-shot hits Extra eval ids:", polluted)
        return 2
    print("isolation ok: no Extra eval question exact-matches few-shots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
