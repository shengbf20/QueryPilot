# QueryPilot：双路径——快取数 + 强 Agent

> 记录范围：在**不改**现有 `ask()` 编排的前提下，并列增加强 Agent 工具循环；问数页 / 默认 CLI 仍走快路径，对话页 / `--mode agent` 走新路径。  
> 状态：✅ v1 已落地（预算化工具循环 + 会话记忆 + 入口分发）  
> 对照：`logs/07` 建议把 Agentic 挂在 `ask()` 失败/复杂分支上；本路径按产品要求改为**两条并行编排**。

---

## 原则

- `querypilot.agent.pipeline.ask()` 签名与步骤不变；默认 `eval` 仍只调 `ask()`。
- 强 Agent **复用函数、不复用编排**：剪枝 / `generate_sql` / L1 / L2 / `execute` / 探针 / `intent_guard` 当工具。
- 恶意指令在两条入口都过同一套 `check_malicious_intent`（Agent 不经过 `ask()`）。

## 入口

| 表面 | 快路径 | 强 Agent |
|------|--------|----------|
| CLI | `querypilot ask "..."` | `querypilot ask --mode agent [--session id] "..."` |
| API | `POST /api/ask` 默认 `mode=fast` | `mode=agent` + 可选 `session_id` |
| UI | 问数页 | 对话页（`postAsk(..., { mode: "agent", sessionId })`） |

返回仍是 `PipelineResult`；轨迹在 `extras.agent_trace`，对话页「详情」里显示工具链。

## 运行时（`querypilot/agentic/`）

`run` → 意图围栏 → `SessionMemory` → 每轮一个 JSON 工具（上限 6）→ `ask_user` / `finish` / 预算耗尽。

对话线程是**追加式** `messages[]`：system 与已发出的轮次不重写，只在末尾追加 assistant / 工具观察；剩余轮次写在最新一条观察里，便于前缀缓存。会话跨 `run()` 续接同一条线程。

工具：`search_schema` / `run_sql` / `ask_user` / `finish`。  
`run_sql` 对模型像执行一条命令：提交 SQL，成功回结果，失败回原因。L1/L2 在工具内部消化，不写进提示词。

## 与 07 五条判据（v1）

- A/B：模型选工具，硬预算  
- C：`run_sql` 失败后可改 SQL 再跑  
- D：进程内 `session_id` 记忆  
- E：执行反馈（结果或失败说明）喂回，无独立 reflect 模块  

07 的 P0（改 `ask()` 内反思 / 多候选 / 探针回流）**未做**，以免动快路径。

## 评测

`querypilot eval --mode agent` 走 `agentic.run`，每条金标独立 `session_id=eval-{case.id}`，仍用 Execution Match。默认 `--mode fast` 不变。

```
querypilot eval --mode agent --path "data/Q&A.xlsx" --workers 4 --output logs/eval_reports/eval_agent_gold.json
querypilot eval --mode agent --path "data/extra/Q&A_all.xlsx" --workers 4 --output logs/eval_reports/extra36_agent.json
querypilot eval --mode agent --path "data/extra2/Q&A_all.xlsx" --workers 4 --output logs/eval_reports/extra2_agent.json
querypilot eval --mode agent --path "data/extra3/Q&A_all.xlsx" --output logs/eval_reports/extra3_agent.json
```

下表为 **v1 当时** 数字。口径对齐、续聊剪枝、L1 整库目录与之后的满分复测见 `logs/11-口径对齐与双路径收口.md`。

| 集 | 快路径 `ask()` | 强 Agent | Agent 失败题（v1） |
|---|---|---|---|
| 官方 7 | 7/7 | **7/7** | — |
| Extra36 | 36/36 | **32/36（88.9%）** | H01 H02 H03 H06（全 Hard） |
| Extra2 | 40/40 | **35/40（87.5%）** | FH01 FH02 FH06 FH09 FH12（全 Hard） |
| Extra3 | 24/24（拒绝+警告） | **24/24** | — |

Easy/Medium 两套 Extra 当时已满分；缺口集中在 Hard。Agent 墙钟 p50 约 1.5–1.7s。

## 后置

- 意图指纹、自动 Few-Shot 回流仍按 07
- 续：`logs/11`
