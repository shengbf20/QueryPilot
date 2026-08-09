# Phase-4 performance closeout

- created_at: 2026-08-09T07:57:18.326172+00:00
- live_llm: True
- questions: 5 (Set-S=3, Set-C=2)

## Latency vs phase-3 baseline

| 指标            | 阶段三基线         | 阶段四冷路径(cache on) | 阶段四热路径(cache hit) | cache off cold |
| ------------- | ------------- | ---------------- | ----------------- | -------------- |
| p50 total_ms  | ≈3580         | 2564.8           | 34.1              | 3440.8         |
| p95 total_ms  | ≈4220 / ≈5021 | 3914.2           | 38.5              | 4438.5         |
| mean total_ms | ≈3873         | 1981.4           | 28.3              | 2491.6         |
| cache hit 率   | —             | 0.0%             | 100.0%            | 0%             |

## Parallel plan (mode B)

- question: 统计客户的资产和持仓市值
- domains: ['asset', 'hold']
- serial_ms: 96.4
- parallel_ms: 61.7
- speedup: 1.6x
- rows_match: True

## Notes

- Cold path still LLM-dominated when live_llm=true; warm path skips generate (cache_hit).
- Parallel path is opt-in rule metrics (ask --parallel); does not change default EX.
- phase3_baseline p50≈3.6s / p95≈5.0s (official 7-case eval, 2026-08-08).
