"""Ablation study: test necessity of fix_sql / L1 / L2 fence.

Usage:
    python scripts/ablation.py                        # default 7 gold cases
    python scripts/ablation.py --limit 76             # official + extra
    python scripts/ablation.py --paths data/extra/Q&A_all.xlsx data/extra2/Q&A_all.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from querypilot.eval.dataset import load_qa_cases, load_qa_cases_many
from querypilot.eval.models import EvalCase


@dataclass
class AblationConfig:
    name: str
    description: str
    fix_sql: bool = True
    l1_enabled: bool = True
    l2_enabled: bool = True


CONFIGS = [
    AblationConfig("full", "完整管线（fix_sql + L1 + L2）"),
    AblationConfig("no_fix_sql", "去掉确定性SQL归一化", fix_sql=False),
    AblationConfig("no_l1", "去掉L1静态围栏", l1_enabled=False),
    AblationConfig("no_l2", "去掉L2动态围栏", l2_enabled=False),
    AblationConfig("minimal", "只保留LLM生成 + 执行", fix_sql=False, l1_enabled=False, l2_enabled=False),
]


def run_single_case(
    case: EvalCase,
    *,
    config: AblationConfig,
) -> dict:
    """Run one case with the given ablation config, return result dict."""
    from querypilot.agent.pipeline import ask
    from querypilot.db import execute as db_execute

    result: dict = {
        "case_id": case.id,
        "question": case.question,
        "config": config.name,
    }

    # Ask
    t0 = time.perf_counter()
    try:
        pipe = ask(
            case.question,
            fix_sql=config.fix_sql,
            l1_enabled=config.l1_enabled,
            l2_enabled=config.l2_enabled,
            use_cache=False,
        )
        ask_ms = (time.perf_counter() - t0) * 1000
        result["ask_ok"] = pipe.ok
        result["pred_sql"] = pipe.sql or ""
        result["error"] = "" if pipe.ok else (pipe.message or "")
        result["stage"] = pipe.stage or ""
        result["ask_ms"] = round(ask_ms, 1)
        if pipe.timing:
            result["prune_ms"] = pipe.timing.prune_ms
            result["generate_ms"] = pipe.timing.generate_ms
            result["l1_ms"] = pipe.timing.l1_ms
            result["l2_ms"] = pipe.timing.l2_ms
    except Exception as exc:
        ask_ms = (time.perf_counter() - t0) * 1000
        result["ask_ok"] = False
        result["pred_sql"] = ""
        result["error"] = str(exc)
        result["stage"] = "exception"
        result["ask_ms"] = round(ask_ms, 1)

    # Gold SQL
    try:
        gold = db_execute(case.gold_sql, max_rows=1000)
        result["gold_ok"] = True
        result["gold_columns"] = gold.columns
        result["gold_rows"] = [list(r) for r in gold.rows]
    except Exception as exc:
        result["gold_ok"] = False
        result["error"] = f"{result.get('error','')}; gold failed: {exc}"

    # EX match
    matched = False
    if result.get("ask_ok") and result.get("gold_ok"):
        from querypilot.eval.execution_match import compare_results

        pred_rows = []
        if pipe.ok and pipe.rows:
            pred_rows = [tuple(r) for r in pipe.rows]
        pred_columns = list(pipe.columns) if pipe.ok and pipe.columns else []
        mr = compare_results(pred_columns, pred_rows, result["gold_columns"], result["gold_rows"])
        matched = mr.matched
        result["match_reason"] = mr.reason
    result["matched"] = matched

    return result


def run_ablation(
    cases: list[EvalCase],
    configs: list[AblationConfig],
) -> list[dict]:
    """Run all configs × all cases."""
    all_results = []
    total = len(configs) * len(cases)
    done = 0

    for config in configs:
        print(f"\n{'='*60}")
        print(f"Config: {config.name} — {config.description}")
        print(f"{'='*60}")

        matched = 0
        failed_cases = []
        ask_times = []

        for case in cases:
            done += 1
            result = run_single_case(case, config=config)
            all_results.append(result)

            status = "PASS" if result["matched"] else "FAIL"
            if result["matched"]:
                matched += 1
            else:
                failed_cases.append(result["case_id"])

            ask_times.append(result.get("ask_ms", 0))
            print(f"  [{done}/{total}] {status} #{result['case_id']} {result['question'][:30]}... "
                  f"({result.get('ask_ms',0):.0f}ms)")

        total_cases = len(cases)
        acc = matched / total_cases if total_cases else 0
        avg_ms = sum(ask_times) / len(ask_times) if ask_times else 0
        print(f"\n  → EX: {matched}/{total_cases} = {acc:.1%}  avg={avg_ms:.0f}ms")
        if failed_cases:
            print(f"  → Failed: {', '.join(failed_cases)}")

    return all_results


def print_comparison(all_results: list[dict], configs: list[AblationConfig], n_cases: int):
    """Print comparison table."""
    print(f"\n{'='*70}")
    print("消融实验对比结果")
    print(f"{'='*70}")
    print(f"{'配置':<18} {'EX准确率':>10} {'通过/总数':>10} {'平均耗时(ms)':>14}")
    print("-" * 70)

    for config in configs:
        config_results = [r for r in all_results if r["config"] == config.name]
        matched = sum(1 for r in config_results if r["matched"])
        total = len(config_results)
        acc = matched / total if total else 0
        avg_ms = sum(r.get("ask_ms", 0) for r in config_results) / total if total else 0
        print(f"{config.name:<18} {acc:>9.1%} {matched:>4}/{total:<4} {avg_ms:>12.0f}")

    print("-" * 70)

    # Show which cases differ
    full_results = {r["case_id"]: r["matched"] for r in all_results if r["config"] == "full"}
    for config in configs:
        if config.name == "full":
            continue
        config_results = {r["case_id"]: r["matched"] for r in all_results if r["config"] == config.name}
        regressions = [cid for cid, m in full_results.items() if m and not config_results.get(cid)]
        improvements = [cid for cid, m in full_results.items() if not m and config_results.get(cid)]
        if regressions or improvements:
            print(f"\n  {config.name} vs full:")
            if regressions:
                print(f"    回退（full通过但此配置失败）: {', '.join(regressions)}")
            if improvements:
                print(f"    提升（full失败但此配置通过）: {', '.join(improvements)}")


def main():
    parser = argparse.ArgumentParser(description="消融实验：测试 fix_sql / L1 / L2 的必要性")
    parser.add_argument("--limit", type=int, default=None, help="限制评测题数")
    parser.add_argument("--path", type=str, default=None, help="金标 xlsx 路径")
    parser.add_argument("--paths", type=str, nargs="*", default=None, help="额外 xlsx 路径")
    parser.add_argument("--output", type=str, default=None, help="结果输出 JSON 路径")
    parser.add_argument("--case-ids", type=str, nargs="*", default=None, help="只运行指定的案例ID（空格分隔）")
    parser.add_argument("--error-set", type=str, default=None, help="从之前的消融结果中加载错误案例集合")
    parser.add_argument("--config", type=str, default=None, help="只运行指定的配置（full/no_fix_sql/no_l1/no_l2/minimal）")
    args = parser.parse_args()

    # Load cases
    if args.paths:
        path_list = list(args.paths)
        if args.path:
            path_list = [args.path, *path_list]
        cases = load_qa_cases_many(path_list)
    else:
        cases = load_qa_cases(args.path)

    # Filter by case IDs or error set
    filter_ids = set()
    if args.case_ids:
        filter_ids = set(args.case_ids)
    elif args.error_set:
        error_data = json.loads(Path(args.error_set).read_text(encoding='utf-8'))
        for r in error_data.get('results', []):
            if not r.get('matched', True):
                filter_ids.add(r['case_id'])
        print(f"从 {args.error_set} 加载 {len(filter_ids)} 个错误案例")

    if filter_ids:
        cases = [c for c in cases if c.id in filter_ids]
        print(f"筛选后保留 {len(cases)} 道评测题")

    if args.limit:
        cases = cases[: args.limit]

    print(f"加载 {len(cases)} 道评测题")

    # Filter by config
    if args.config:
        config_names = [c.name for c in CONFIGS]
        if args.config not in config_names:
            print(f"错误：未知配置 '{args.config}'")
            print(f"可选配置：{', '.join(config_names)}")
            return
        selected_configs = [c for c in CONFIGS if c.name == args.config]
        print(f"只运行配置：{args.config}")
    else:
        selected_configs = CONFIGS

    all_results = run_ablation(cases, selected_configs)
    print_comparison(all_results, selected_configs, len(cases))

    # Save results
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = ROOT / "logs" / "eval_reports" / "ablation_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "cases": len(cases),
        "configs": [asdict(c) for c in CONFIGS],
        "results": all_results,
    }
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(f"\n详细结果已保存: {out_path}")


if __name__ == "__main__":
    main()
