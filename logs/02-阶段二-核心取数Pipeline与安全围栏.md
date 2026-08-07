# QueryPilot 阶段二：核心取数 Pipeline 与多层安全围栏

> 记录范围：Schema 剪枝、单次 LLM SQL 生成、L1/L2 安全围栏、结果探针与端到端编排。  
> 记录时间：2026-08-07（规划落档）  
> 状态：🚧 进行中（步骤 1 已完成）  
> 前置依赖：阶段一已完成（`load_metadata()` / Join-Graph / 编码字典）

---

## 一、阶段目标

打通可运行的 NL2SQL 闭环：**自然语言 → Schema 剪枝 → 单次 LLM 生成 SQL → 双层确定性围栏 → 执行 / 1-Shot 纠错 → 结果探针**。

| 交付物 | 对应 | 验收要点 |
|--------|------|----------|
| Schema Pruner | 工作流步骤 1 | 命中相关表列 + Join-Graph 补全；输出精简 Schema |
| SQL 生成器 | Step 5 | Prompt 组装；复杂查询强制 CTE；结构化 JSON 输出 |
| L1 AST 围栏 | Step 6 | sqlglot 拦写操作/越权表；列名幻觉模糊修正 |
| L2 EXPLAIN + 1-Shot | Step 7 | 预执行校验；失败纠错仅 1 次；再失败优雅降级 |
| 结果探针 | Step 8 | 空结果 / 明显异常时给出交互提示 |
| Pipeline 入口 | — | `ask(question)` / CLI 可端到端跑通 |

**本阶段不做**：Execution Match 评测（阶段三）、Chat UI（阶段五）、缓存与并行优化（阶段四）。

**须遵守约定**：跨表默认只按 `pty_id`/`org_id` Join（不加默认 `data_dt`）；`dim_public` 须同时匹配 `code` + `code_type_id`；Agent 只依赖 `load_metadata()`。

---

## 二、文件框架

主目录：`querypilot/agent/` + `querypilot/safety/`。

```
querypilot/
├── agent/
│   ├── pipeline.py           # 主编排
│   ├── prompt.py             # Prompt 组装
│   ├── sql_generator.py      # LLM → 结构化 SQL
│   ├── models.py             # Request / Result 类型
│   └── few_shot_retriever.py #（可选）Few-Shot 检索
│
├── safety/
│   ├── l1_ast.py             # sqlglot 静态校验与列名修正
│   ├── l2_explain.py         # EXPLAIN 试跑
│   ├── result_probe.py       # 空结果 / 异常量级探针
│   └── models.py             # GuardResult 等
│
├── metadata_engine/
│   └── schema_pruner.py      # 剪枝（阶段二补齐）
│
├── llm/chat.py               #（建议）统一 generate / JSON
└── db/connection.py          # DuckDB：execute / explain
```

配套：`tests/test_schema_pruner.py`、`test_safety_*.py`、`test_pipeline_smoke.py`；`scripts/demo_pipeline.py`；完善 `cli.py`。

---

## 三、预计完成步骤

1. **执行底座**：`db/connection.py` + `llm/chat.py`
2. **Schema Pruner**：基于 `load_metadata()` 做检索与拓扑扩展
3. **Prompt + SQL 生成器**：剪枝上下文 + 规则 + Few-Shot → JSON/SQL
4. **L1 围栏**：只读、表白名单、列校验/模糊修正
5. **L2 + 纠错环**：EXPLAIN → 1-Shot 重生 → 再校验；二次失败降级
6. **Pipeline 串联 + 结果探针**：端到端 `ask()`
7. **CLI / Demo + 测试**：冒烟问句与围栏单测

---

## 四、进度记录

| 步骤 | 状态 | 备注 |
|------|------|------|
| 1 执行底座 | ✅ | `db`：`get_connection` / `execute` / `explain`；`llm`：`chat` / `generate` / `generate_json`；16 个单测通过 |
| 2 Schema Pruner | ⏳ | |
| 3 Prompt / SQL 生成 | ⏳ | |
| 4 L1 AST | ⏳ | |
| 5 L2 + 1-Shot | ⏳ | |
| 6 Pipeline + 探针 | ⏳ | |
| 7 CLI / Demo / 测试 | ⏳ | |

### 步骤 1 明细（2026-08-07）

- `querypilot/db/connection.py`：扩展连接默认只读；新增 `QueryResult` / `ExplainResult`、`connection()` 上下文、`execute()`、`explain()`（供 L2 围栏）
- `querypilot/llm/chat.py`：统一 `chat` / `generate` / `generate_json`；支持 JSON fence 解析与 `json_object` 响应格式
- 测试：`tests/test_db.py`、`tests/test_llm_chat.py`
  - LLM：本地 JSON 解析单测 + **真实 DeepSeek** `chat` / `generate` / `generate_json`（无 Key 则 skip）

