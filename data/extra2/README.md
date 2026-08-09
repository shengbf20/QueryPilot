# Extra2 清新泛化评测集（阶段四续二）

官方 `data/Q&A.xlsx` 与 Extra36 `data/extra/` **只读、不改**。本目录为独立 held-out（约 40 题）。

## 目标文件

| 文件 | 题量 | 说明 |
|------|------|------|
| `Q&A_easy.xlsx` | 12 | FE01–FE12 |
| `Q&A_medium.xlsx` | 16 | FM01–FM16 |
| `Q&A_hard.xlsx` | 12 | FH01–FH12 |
| `Q&A_all.xlsx` | 40 | 合并顺序 FE→FM→FH |

## 表头

`序号` | `问题` | `SQL` | `难度` | `theme`

- id 前缀：`FE` / `FM` / `FH`（避免与 Extra36 的 E/M/H 合并撞车）
- 难度：`简单` / `中等` / `困难`

## 辅助文件

| 文件 | 用途 |
|------|------|
| `dedupe_checklist.md` | S1 去重占用集 + 本批问句 |
| `entities.md` | S2 实体与阈值冻结 |
| `_explore.py` / `_explore_report.txt` | 探数 |
| `_probe_thresholds.py` | 中难阈值探数 |
| `_build_extra2.py` | 造题校验① + 写 xlsx |

规划见 `logs/04-阶段四续二-Extra2清新泛化评测集.md`。

## 重建与评测

```powershell
$env:PYTHONPATH="."
python data/extra2/_explore.py
python data/extra2/_build_extra2.py
python -m pytest tests/test_extra2_isolation.py -q

# Extra2-A / B（关短路）+ 官方默认回归
python scripts/baseline_eval.py --path "data/extra2/Q&A_all.xlsx" --no-exact-few-shot --max-few-shots 3 --stem logs/eval_reports/extra2_A_fs3 --no-llm-diagnose
python scripts/baseline_eval.py --path "data/extra2/Q&A_all.xlsx" --no-exact-few-shot --max-few-shots 0 --stem logs/eval_reports/extra2_B_fs0 --no-llm-diagnose
python scripts/baseline_eval.py --stem logs/eval_reports/official_p4x2_default --no-llm-diagnose
```

本轮（2026-08-09）结果摘要：Extra2-A **35/40**，Extra2-B **33/40**，官方默认 **7/7**。
