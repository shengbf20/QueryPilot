"""Call POST /api/ask with UTF-8 and print a short summary (Windows-friendly).

Usage:
  python scripts/api_ask_demo.py
  python scripts/api_ask_demo.py --question "总资产超过100万的客户有多少人？"
  python scripts/api_ask_demo.py --base-url http://127.0.0.1:8000 --save logs/api_ask_last.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo client for QueryPilot /api/ask")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--question",
        default="有多少年龄大于30岁的女性客户？",
        help="Natural-language question",
    )
    parser.add_argument(
        "--save",
        default=None,
        help="Optional path to write full UTF-8 JSON response",
    )
    args = parser.parse_args(argv)

    url = args.base_url.rstrip("/") + "/api/ask"
    body = json.dumps({"question": args.question}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.URLError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        print("hint: start API with  querypilot serve --host 127.0.0.1 --port 8000", file=sys.stderr)
        return 1

    data = json.loads(raw.decode("utf-8"))
    if args.save:
        path = Path(args.save)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        print(f"saved: {path}")

    # ASCII-safe summary for consoles that mangle Chinese (e.g. some PS hosts).
    print(f"content-type: {ctype}")
    print(f"ok: {data.get('ok')}")
    print(f"question: {data.get('question')}")
    print(f"stage: {data.get('stage')}")
    print(f"tables: {data.get('tables')}")
    print(f"columns: {data.get('columns')}")
    print(f"rows: {data.get('rows')}")
    print(f"row_count: {data.get('row_count')}")
    timing = data.get("timing") or {}
    print(
        "timing: "
        f"total_ms={timing.get('total_ms')} cache_hit={timing.get('cache_hit')}"
    )
    sql = data.get("sql") or ""
    print("sql:")
    print(sql)
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
