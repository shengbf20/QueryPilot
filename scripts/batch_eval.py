"""Run the 8 evals in logs/11. Optional args become DEEPSEEK_MODEL.

  python scripts/batch_eval.py
  python scripts/batch_eval.py deepseek-chat deepseek-reasoner --workers 4
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JOBS = [
    ("gold_fast", ["--mode", "fast", "--path", "data/Q&A.xlsx"]),
    ("gold_agent", ["--mode", "agent", "--path", "data/Q&A.xlsx"]),
    ("extra36_fast", [
        "--mode", "fast", "--path", "data/extra/Q&A_all.xlsx",
        "--no-exact-few-shot", "--max-few-shots", "3",
    ]),
    ("extra36_agent", [
        "--mode", "agent", "--path", "data/extra/Q&A_all.xlsx",
        "--no-exact-few-shot", "--max-few-shots", "3",
    ]),
    ("extra2_fast", [
        "--mode", "fast", "--path", "data/extra2/Q&A_all.xlsx",
        "--no-exact-few-shot", "--max-few-shots", "3",
    ]),
    ("extra2_agent", [
        "--mode", "agent", "--path", "data/extra2/Q&A_all.xlsx",
        "--no-exact-few-shot", "--max-few-shots", "3",
    ]),
    ("extra3_fast", ["--mode", "fast", "--path", "data/extra3/Q&A_all.xlsx"]),
    ("extra3_agent", ["--mode", "agent", "--path", "data/extra3/Q&A_all.xlsx"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch logs/11 evals")
    parser.add_argument("models", nargs="*", help="DEEPSEEK_MODEL values; omit to use .env")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "logs" / "eval_reports" / "batch",
    )
    args = parser.parse_args()

    code = 0
    for model in args.models or [""]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if model:
            env["DEEPSEEK_MODEL"] = model
        tag = model or "default"
        outdir = args.output_root / tag
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"======== {tag} ========", flush=True)
        for name, flags in JOBS:
            out = outdir / f"{name}.json"
            cmd = [
                sys.executable, "-m", "querypilot.cli", "eval",
                *flags, "--workers", str(max(1, args.workers)),
                "--output", str(out),
            ]
            print(f"-------- {tag} {name} --------", flush=True)
            if subprocess.run(cmd, cwd=ROOT, env=env).returncode:
                code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
