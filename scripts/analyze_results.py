"""分析消融实验结果，统计各配置的正确率。

Usage:
    python scripts/analyze_results.py
    python scripts/analyze_results.py --input logs/eval_reports/ablation_full_run_v2.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# 设置标准输出编码为UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def analyze_results(input_file: str):
    """分析消融实验结果"""
    data = json.loads(Path(input_file).read_text(encoding='utf-8'))
    results = data.get('results', [])

    # 统计每个配置的结果
    config_stats = defaultdict(lambda: {'total': 0, 'passed': 0, 'failed': 0, 'failed_cases': []})

    for r in results:
        config = r.get('config')
        case_id = r.get('case_id')
        matched = r.get('matched', False)

        config_stats[config]['total'] += 1
        if matched:
            config_stats[config]['passed'] += 1
        else:
            config_stats[config]['failed'] += 1
            config_stats[config]['failed_cases'].append(case_id)

    # 打印结果
    print("=" * 70)
    print("消融实验结果统计")
    print("=" * 70)
    print(f"{'配置':<18} {'准确率':>10} {'通过/总数':>12} {'失败案例':<30}")
    print("-" * 70)

    for config in sorted(config_stats.keys()):
        stats = config_stats[config]
        acc = stats['passed'] / stats['total'] * 100 if stats['total'] > 0 else 0
        failed_str = ', '.join(stats['failed_cases']) if stats['failed_cases'] else '无'
        print(f"{config:<18} {acc:>9.1f}% {stats['passed']:>4}/{stats['total']:<4}  {failed_str}")

    print("-" * 70)

    # 找出至少有一个配置失败的案例
    all_failed_cases = set()
    for stats in config_stats.values():
        all_failed_cases.update(stats['failed_cases'])

    print(f"\n至少有一个配置失败的案例数：{len(all_failed_cases)}")
    if all_failed_cases:
        print(f"案例ID：{sorted(all_failed_cases)}")

    # 分析各配置的差异
    print("\n" + "=" * 70)
    print("各配置对比分析")
    print("=" * 70)

    full_stats = config_stats.get('full', {})
    full_passed = set(r.get('case_id') for r in results if r.get('config') == 'full' and r.get('matched'))

    for config in sorted(config_stats.keys()):
        if config == 'full':
            continue

        config_passed = set(r.get('case_id') for r in results if r.get('config') == config and r.get('matched'))

        regressions = full_passed - config_passed  # full通过但此配置失败
        improvements = config_passed - full_passed  # full失败但此配置通过

        if regressions or improvements:
            print(f"\n{config} vs full:")
            if regressions:
                print(f"  回退（full通过但此配置失败）：{sorted(regressions)}")
            if improvements:
                print(f"  提升（full失败但此配置通过）：{sorted(improvements)}")


def main():
    parser = argparse.ArgumentParser(description="分析消融实验结果")
    parser.add_argument(
        "--input",
        type=str,
        default="logs/eval_reports/ablation_full_run_v2.json",
        help="输入的JSON结果文件路径"
    )
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误：文件不存在 {args.input}")
        return

    analyze_results(args.input)


if __name__ == "__main__":
    main()
