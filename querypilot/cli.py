"""QueryPilot CLI entry point."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="querypilot",
        description="QueryPilot — Agentic NL2SQL for customer marketing analytics",
    )
    parser.add_argument("--version", action="version", version="QueryPilot 0.1.0")
    parser.parse_args()
    print("QueryPilot scaffold is ready. Implement pipeline modules next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
