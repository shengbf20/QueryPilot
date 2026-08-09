# Extra 金标目录（阶段三续二）

官方金标 `data/Q&A.xlsx`（7 题）**只读、不改**。本目录存放自建 Extra 评测集。

## 目标文件（Step 2 落盘）

| 文件 | 题量 | 说明 |
|------|------|------|
| `Q&A_easy.xlsx` | 10 | E01–E10（✅ Step 2b） |
| `Q&A_medium.xlsx` | 14 | M01–M14（✅ Step 2c） |
| `Q&A_hard.xlsx` | 12 | H01–H12（✅ Step 2d–2e） |
| `Q&A_all.xlsx` | 36 | 三档合并（✅ Step 2f；顺序 E→M→H） |

## 表头约定

`序号` | `问题` | `SQL` | `难度` | `theme`

- `难度`：`简单` / `中等` / `困难`（或 easy/medium/hard）
- `theme`：加载进 `EvalCase.extras["theme"]`
- `序号`：使用 `E01`… / `M01`… / `H01`… 前缀

## 辅助文件

| 文件 | 用途 |
|------|------|
| `entities.md` | Step 2a 探数结果（写金标常量冻结表） |
| `_explore_step2a.py` | 探数复现脚本（`PYTHONPATH=. python data/extra/_explore_step2a.py`） |
| `_explore_report.txt` | 探数原始输出 |
| `_analyze_extra_a_fails.py` | Step 4：对照 Extra-A 失败题 pred/gold（需已有 `extra_all_A_report.json`） |
| `README.md` | 本说明 |

规划详见 `logs/03-阶段三续二-Extra金标扩充与泛化评测.md`。
