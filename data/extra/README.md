# Extra 金标目录（阶段三续二）

官方金标 `data/Q&A.xlsx`（7 题）**只读、不改**。本目录存放自建 Extra 评测集。

## 目标文件（Step 2 落盘）

| 文件 | 题量 | 说明 |
|------|------|------|
| `Q&A_easy.xlsx` | 10 | E01–E10 |
| `Q&A_medium.xlsx` | 14 | M01–M14 |
| `Q&A_hard.xlsx` | 12 | H01–H12 |
| `Q&A_all.xlsx` | 36 | 三档合并，便于基线 |

## 表头约定

`序号` | `问题` | `SQL` | `难度` | `theme`

- `难度`：`简单` / `中等` / `困难`（或 easy/medium/hard）
- `theme`：加载进 `EvalCase.extras["theme"]`
- `序号`：使用 `E01`… / `M01`… / `H01`… 前缀

## 辅助文件

| 文件 | 用途 |
|------|------|
| `entities.md` | Step 2a 探数：状态码/职业码/产品名/阈值 |
| `README.md` | 本说明 |

规划详见 `logs/03-阶段三续二-Extra金标扩充与泛化评测.md`。
