"""Phase-4 step-2 preflight: metadata baseline + fake-client bench smoke.

Does not call live LLM. Writes logs/perf_reports/step2_prep_fake.json.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import load_metadata


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)

    def create(self, **kwargs: Any) -> SimpleNamespace:
        content = (
            self._contents.pop(0)
            if self._contents
            else '{"sql":"SELECT 1","rationale":"","uses_cte":false}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class _FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(contents))


def _load_bench():
    bench_path = ROOT / "scripts" / "bench_pipeline.py"
    spec = importlib.util.spec_from_file_location("bench_pipeline", bench_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    load_ms: list[float] = []
    md = None
    for _ in range(3):
        t0 = time.perf_counter()
        md = load_metadata(load_db_codes=False)
        load_ms.append((time.perf_counter() - t0) * 1000.0)
    assert md is not None

    q = "有多少年龄大于30岁的女性客户？"
    t0 = time.perf_counter()
    p1 = md.prune_schema(q)
    p1_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    p2 = md.prune_schema(q)
    p2_ms = (time.perf_counter() - t0) * 1000.0

    print("=== step2 prep: metadata baseline (no cache yet) ===")
    print(f"load_metadata(load_db_codes=False) x3 ms: {[round(x, 2) for x in load_ms]}")
    print(f"tables={len(md.tables)}")
    print(f"prune same Q: first={p1_ms:.2f}ms second={p2_ms:.2f}ms tables={list(p1.tables)}")
    print(f"prune equal tables: {list(p1.tables) == list(p2.tables)}")

    bench = _load_bench()
    sql_json = (
        '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",'
        '"rationale":"count","uses_cte":false}'
    )
    client = _FakeClient([sql_json] * 4)
    report = bench.run_bench(
        [q],
        warm=True,
        rounds=1,
        max_few_shots=0,
        include_values=False,
        client=client,
        metadata=md,
    )
    out = ROOT / "logs" / "perf_reports" / "step2_prep_fake.json"
    saved = bench.save_bench_report(report, out)

    print()
    print("=== step2 prep: fake-client bench ===")
    print(bench.format_bench_report(report))
    print(f"saved: {saved}")

    stage_keys = set(report["stage_mean_ms"])
    required = {
        "prune_ms",
        "generate_ms",
        "l1_ms",
        "l2_ms",
        "execute_ms",
        "probe_ms",
        "total_ms",
    }
    assert required <= stage_keys, stage_keys
    assert all("cache_hit" in it["timing"] for it in report["items"])
    assert report["run_count"] == 2
    assert report["ok_count"] == 2

    # Contract snapshot for step-2 implementers (printed, not asserted as frozen forever)
    snapshot = {
        "ask_has_use_cache": False,
        "cache_package_exists": (ROOT / "querypilot" / "cache").is_dir(),
        "load_metadata_ms": [round(x, 3) for x in load_ms],
        "prune_ms": {"first": round(p1_ms, 3), "second": round(p2_ms, 3)},
        "bench_report": str(saved.relative_to(ROOT)).replace("\\", "/"),
    }
    snap_path = ROOT / "logs" / "perf_reports" / "step2_prep_snapshot.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"snapshot: {snap_path}")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
