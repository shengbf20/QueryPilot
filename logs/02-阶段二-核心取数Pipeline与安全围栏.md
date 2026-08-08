# QueryPilot 阶段二：核心取数 Pipeline 与多层安全围栏

> 记录范围：Schema 剪枝、单次 LLM SQL 生成、L1/L2 安全围栏、结果探针与端到端编排。  
> 记录时间：2026-08-07 规划落档；2026-08-08 收口修订  
> 状态：✅ 阶段二主线完成（步骤 1–7）  
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

## 二、文件框架（落地后）

```
querypilot/
├── agent/
│   ├── pipeline.py           # ask() 主编排
│   ├── prompt.py             # SYSTEM_PROMPT + build_prompt
│   ├── sql_generator.py      # LLM → 结构化 SQL
│   └── models.py             # PromptBundle / SqlGenerationResult / PipelineResult
│
├── safety/
│   ├── l1_ast.py             # sqlglot 静态校验与列名修正
│   ├── l2_explain.py         # EXPLAIN + 1-Shot 纠错
│   ├── result_probe.py       # 空结果 / 异常量级探针
│   └── models.py             # L1/L2 GuardResult 等
│
├── metadata_engine/
│   └── schema_pruner.py      # 剪枝（阶段二补齐）
│
├── llm/chat.py               # chat / generate / generate_json
├── db/connection.py          # execute / explain（默认只读）
└── cli.py                    # querypilot ask
```

配套：`metadata/few_shots/examples.yaml`；`tests/test_{db,llm_chat,schema_pruner,sql_generator,safety_l1,safety_l2,pipeline,cli}.py`；`scripts/demo_{schema_pruner,sql_generator,pipeline}.py`。

**未做（可选/后续）**：`few_shot_retriever.py`（向量检索 Few-Shot）；demo 问句与 `Q&A.xlsx` 金标对齐（属阶段三）。

---

## 三、预计完成步骤（原计划）

1. **执行底座**：`db/connection.py` + `llm/chat.py`
2. **Schema Pruner**：基于 `load_metadata()` 做检索与拓扑扩展
3. **Prompt + SQL 生成器**：剪枝上下文 + 规则 + Few-Shot → JSON/SQL
4. **L1 围栏**：只读、表白名单、列校验/模糊修正
5. **L2 + 纠错环**：EXPLAIN → 1-Shot 重生 → 再校验；二次失败降级
6. **Pipeline 串联 + 结果探针**：端到端 `ask()`
7. **CLI / Demo + 测试**：冒烟问句与围栏单测

---

## 四、进度记录

| 步骤 | 状态 | 一句话 |
|------|------|--------|
| 1 执行底座 | ✅ | DuckDB 执行/EXPLAIN + DeepSeek 统一调用 |
| 2 Schema Pruner | ✅ | 关键词剪枝 + Join-Graph 补全 |
| 3 Prompt / SQL 生成 | ✅ | 单次 LLM 结构化 JSON→SQL |
| 4 L1 AST | ✅ | 只读/白名单/列修正；含 SELECT 别名修复 |
| 5 L2 + 1-Shot | ✅ | EXPLAIN 失败仅纠错 1 次后降级 |
| 6 Pipeline + 探针 | ✅ | `ask()` 全链路 + 结果探针 |
| 7 CLI / Demo / 测试 | ✅ | CLI、demo、阶段二相关 **116** 测通过 |

---

### 步骤 1：执行底座

**解决什么问题 / 交付成果**

- 问题：Pipeline 与 L2 需要稳定的「跑 SQL / 试跑 EXPLAIN」能力，以及统一的 LLM 调用与 JSON 解析，避免各模块各自接 API。
- 交付：只读 DuckDB 连接与 `execute`/`explain`；DeepSeek `chat` / `generate` / `generate_json`（含 fence 解析）。

**涉及文件**

- `querypilot/db/connection.py`
- `querypilot/llm/chat.py`、`querypilot/llm/client.py`
- `tests/test_db.py`、`tests/test_llm_chat.py`

**修改重点与明细**

- 连接默认 `read_only=True`；提供 `QueryResult` / `ExplainResult`、`connection()` 上下文。
- `execute` 支持 `max_rows`；`explain` 规范化 SQL、兼容已带 `EXPLAIN` 前缀、空 SQL 报错。
- `generate_json` 使用 `response_format=json_object`，`parse_json_content` 容忍 markdown fence、拒绝非 object。
- 测试：内存库 execute/explain；项目库冒烟；JSON 解析单测 + 真实 DeepSeek（无 Key 则 skip）。

---

### 步骤 2：Schema Pruner

**解决什么问题 / 交付成果**

- 问题：全量元数据进 Prompt 过长且易干扰；多表查询需自动补中间表，且遵守「不默认 data_dt Join」「dim_public 不默认进 seed」。
- 交付：`SchemaPruner.prune()` → `PrunedSchema`（seed/tables/join_plan/notes + `format_for_prompt`）。

**涉及文件**

- `querypilot/metadata_engine/schema_pruner.py`
- `querypilot/metadata_engine/bundle.py`（`prune_schema` 快捷入口）
- `tests/test_schema_pruner.py`
- `scripts/demo_schema_pruner.py`

**修改重点与明细**

- 表/字段别名与描述加权检索；营销用语扩展（如「女性」→性别、「买过」→交易）。
- 事实表 +「客户」线索时补 `ads_cust_info_d`；`dim_public` 默认不进 seed（枚举走 Value Descriptor）。
- Join-Graph `expand_tables` 补全中间表；Prompt 输出含业务约定与建议 Join（Join 子句不含默认 `data_dt`）。
- 测试：各主题命中、客户中枢、Join 键约定、空问句/fallback、bundle 入口。

---

### 步骤 3：Prompt + SQL 生成器

**解决什么问题 / 交付成果**

- 问题：多轮 Tool 循环耗时长；需单次 LLM 在剪枝 Schema + 硬规则下生成可解析 SQL。
- 交付：`build_prompt` + `generate_sql` / `parse_sql_payload`；Few-Shot YAML；结构化 JSON（sql / rationale / uses_cte）。

**涉及文件**

- `querypilot/agent/prompt.py`、`sql_generator.py`、`models.py`
- `metadata/few_shots/examples.yaml`
- `tests/test_sql_generator.py`
- `scripts/demo_sql_generator.py`

**修改重点与明细**

- `SYSTEM_PROMPT` 硬编码：只读、仅用给定表列、跨表默认 `pty_id`/`org_id`、禁止默认 `data_dt` Join、`dim_public` 双键、复杂逻辑强制 CTE、JSON 输出。
- `build_prompt` 组装：用户问题 + 剪枝 Schema/约定/建议 Join + Few-Shot + JSON 示例。
- `generate_sql`：剪枝（可注入）→ Prompt → `generate_json` → `parse_sql_payload`（含 SQL fence、WITH 检测）。
- Few-Shot 3 条（含女性码 `5000003`、资产 CTE+pty_id Join）。
- 测试：Prompt/解析/假 client；live 生成 + EXPLAIN；硬约定与 Join 静态检查。

---

### 步骤 4：L1 AST 围栏

**解决什么问题 / 交付成果**

- 问题：LLM 可能生成写操作、越权表、拼错列名；需在进库前确定性拦截/轻量修正。
- 交付：`guard_sql()` → `L1GuardResult`（ok / violations / fixes / 改写后 SQL）。

**涉及文件**

- `querypilot/safety/l1_ast.py`、`models.py`
- `querypilot/safety/__init__.py`
- `querypilot/agent/__init__.py`（`ask` 惰性导入，避免与 safety 循环依赖）
- `tests/test_safety_l1.py`

**修改重点与明细**

- sqlglot（DuckDB）：拦截写操作/多语句；表白名单（支持 pruned `allowed_tables`）；CTE 名不当物理表。
- 列名 `difflib` 模糊修正（可关闭）；无近邻则 `unknown_column` 阻断。
- **收口修复**：识别 `SELECT ... AS` 投影别名，允许 `ORDER BY cust_cnt` 等合法引用（避免营业部计数类误杀）。
- 测试：危险语句、ATTACH/子查询越权、错表列、别名 ORDER BY 回归、live `generate_sql`→L1。

---

### 步骤 5：L2 EXPLAIN + 1-Shot 纠错

**解决什么问题 / 交付成果**

- 问题：静态通过仍可能有绑定/函数等 DB 级错误；需预执行校验，且禁止多轮死循环。
- 交付：`validate_with_l2()` — EXPLAIN 失败则 **仅 1 次** LLM 纠错 → 再 L1 → 再 EXPLAIN；仍失败则 `degraded=True`。

**涉及文件**

- `querypilot/safety/l2_explain.py`
- `querypilot/safety/models.py`（`L2GuardResult`）
- `tests/test_safety_l2.py`

**修改重点与明细**

- `run_explain` / `build_correction_prompt` / `correct_sql_once`；`CORRECTION_SYSTEM` 强调「只修正一次」。
- 纠错后必须再过 L1；L1 拒绝时退回 `original_sql`；LLM 异常亦降级。
- 测试：直通、关纠错降级、假 client 成功/仍失败/L1 拒/抛异常、`attempts`/`calls` 上限、live 好/坏 SQL。

---

### 步骤 6：Pipeline 串联 + 结果探针

**解决什么问题 / 交付成果**

- 问题：各模块需串成单一入口；执行成功但结果为空/异常时需给业务可理解的交互提示。
- 交付：`ask(question)` → `PipelineResult`；`probe_result` 空结果/零计数/极端量级建议。

**涉及文件**

- `querypilot/agent/pipeline.py`、`models.py`（`PipelineResult`）
- `querypilot/safety/result_probe.py`
- `tests/test_pipeline.py`

**修改重点与明细**

- 链路：prune → generate → L1 → L2(+1-Shot) → execute → probe；失败带 `stage` / `degraded` / `message`。
- 探针按问句解析年龄/性别/资产门槛，生成「是否放宽…」类建议；执行成功但探针触发时仍可 `ok=True`（带 `probe_*`）。
- 测试：探针单测；假 client 成功 / generate 失败 / L1 拦 / L2 纠错成功与降级 / 不可能年龄探针；live `ask`。

---

### 步骤 7：CLI / Demo + 测试收口

**解决什么问题 / 交付成果**

- 问题：需要可命令行演示与批量冒烟，便于答辩与本地验收（非金标评测）。
- 交付：`querypilot ask`；`demo_pipeline.py`；CLI/格式化单测；阶段二测试集可一键跑通。

**涉及文件**

- `querypilot/cli.py`
- `scripts/demo_pipeline.py`
- `tests/test_cli.py`
- `README.md`（阶段二快速试用）

**修改重点与明细**

- CLI：`ask` 子命令、`--max-rows` / `--max-few-shots`；`format_pipeline_result` 打印 status/stage/sql/表/行/探针/降级；失败 exit 1。
- Demo：5 条营销样例（含 1 条故意空结果探针）；**非** `Q&A.xlsx` 金标，仅验证链路可用性。
- 测试：解析默认值、失败/截断格式、mock 传参、live CLI 冒烟。
- 回归（2026-08-08）：阶段二相关测试 **116 passed**  
  `test_db` + `test_llm_chat` + `test_schema_pruner` + `test_sql_generator` + `test_safety_l1` + `test_safety_l2` + `test_pipeline` + `test_cli`。

---

## 五、阶段二完成度与可选收尾

**主线结论：已基本完成。** README 阶段二 Step 5–8 + Pipeline/CLI 均已落地并可演示。

| 可选收尾（非阻断） | 说明 |
|--------------------|------|
| Few-Shot 向量检索 | 规划中的 `few_shot_retriever.py` 未做；现为 YAML 全量截断加载 |
| Demo ↔ 金标对齐 | 样例问句为冒烟集；标准答案 EX Match 属阶段三 |
| 延迟压测统计 | 体验性指标可补简单计时日志，非本阶段必交付 |
| 指标树 `metrics/` | 仍为预留，复杂派生口径后续扩展 |

**阶段二收口用法**

```powershell
querypilot ask "有多少年龄大于30岁的女性客户？"
python scripts/demo_pipeline.py
pytest tests/test_cli.py tests/test_pipeline.py tests/test_safety_l1.py tests/test_safety_l2.py tests/test_sql_generator.py tests/test_schema_pruner.py tests/test_db.py tests/test_llm_chat.py -q
```

---

## 六、主要交付成果与主模块用法（agent / safety）

> 目录名为 `querypilot/agent/`（单数），不是 `agents/`。剪枝引擎在 `metadata_engine/`，由 agent 调用。

### 6.1 本阶段主要交付成果

| 类别 | 成果 |
|------|------|
| **取数链路** | 自然语言 → Schema 剪枝 → 单次 LLM 生成 SQL → L1/L2 围栏 → 执行 → 结果探针 |
| **统一入口** | Python：`ask(question)`；CLI：`querypilot ask "..."`；Demo：`scripts/demo_pipeline.py` |
| **agent/** | Prompt 组装、SQL 生成、Pipeline 编排与结果模型 |
| **safety/** | L1 AST 围栏、L2 EXPLAIN + 1-Shot 纠错、执行结果探针 |
| **配套底座** | `db/`（execute/explain）、`llm/`（chat/JSON）、`metadata_engine/schema_pruner.py`、`metadata/few_shots/` |
| **质量保障** | 阶段二相关自动化测试可一键回归（见上文 pytest 命令） |

数据流（两主模块协作）：

```
用户问题
   │
   ▼
┌─────────────────────────┐
│ agent/                  │  prune → prompt → generate_sql → ask 编排
│ (+ metadata_engine 剪枝) │
└───────────┬─────────────┘
            │ SQL
            ▼
┌─────────────────────────┐
│ safety/                 │  L1 guard → L2 explain/纠错 →（执行后）probe
└───────────┬─────────────┘
            │ 安全 SQL / 降级信息
            ▼
         DuckDB 执行 → PipelineResult
```

---

### 6.2 `querypilot/agent/` — 取数 Agent

**功能**：把业务问句变成「可执行 SQL + 表格结果」（或带说明的降级结果）。不负责危险语句拦截与 EXPLAIN（交给 safety）。

| 文件 | 职责 |
|------|------|
| `pipeline.py` | `ask()`：端到端编排 |
| `prompt.py` | System/User Prompt、Few-Shot 加载 |
| `sql_generator.py` | 调 LLM，解析 `{sql, rationale, uses_cte}` |
| `models.py` | `PromptBundle` / `SqlGenerationResult` / `PipelineResult` |

**常用 API**

- `ask(question, ...)` → `PipelineResult`（推荐入口）
- `generate_sql(question, ...)` → 只生成 SQL（不含围栏/执行）
- `build_prompt(...)` / `load_few_shots()` → Prompt 层工具

**使用示例**

```python
from querypilot.agent import ask, generate_sql
from querypilot.metadata_engine import load_metadata

md = load_metadata()

# 1) 完整 Pipeline（剪枝 + 生成 + 围栏 + 执行 + 探针）
r = ask("有多少年龄大于30岁的女性客户？", metadata=md)
print(r.ok, r.stage, r.tables)
print(r.sql)
print(r.columns, r.rows[:5])
if r.probe_suggestions:
    print("探针建议:", r.probe_suggestions)
if r.degraded:
    print("降级:", r.message)

# 2) 仅生成 SQL（调试 Prompt / 生成质量时用）
gen = generate_sql("总资产超过100万的客户有多少人？", metadata=md)
print(gen.rationale)
print(gen.sql)
```

CLI 等价用法：

```powershell
querypilot ask "买入交易额合计是多少？" --max-rows 20
```

---

### 6.3 `querypilot/safety/` — 多层安全围栏与探针

**功能**：在 SQL 进库前后做确定性校验与纠错，降低幻觉与写操作风险；执行后对空/异常结果给交互提示。

| 文件 | 职责 |
|------|------|
| `l1_ast.py` | sqlglot：只读拦截、表白名单、列名模糊修正 |
| `l2_explain.py` | DuckDB `EXPLAIN`；失败则 **仅 1 次** LLM 纠错后再验 |
| `result_probe.py` | 空结果 / 零计数 / 异常量级 → 建议放宽条件 |
| `models.py` | `L1GuardResult` / `L2GuardResult` / `GuardViolation` 等 |

**常用 API**

- `guard_sql(sql, metadata=..., allowed_tables=...)` → L1
- `validate_with_l2(sql, question=..., schema_context=..., ...)` → L2(+1-Shot)
- `probe_result(question, query_result)` → 探针
- `run_explain(sql)` → 单独 EXPLAIN

**使用示例**

```python
from querypilot.db import execute
from querypilot.metadata_engine import load_metadata
from querypilot.safety import guard_sql, validate_with_l2, probe_result

md = load_metadata(load_db_codes=False)
sql = "SELECT cust_agge FROM ads_cust_info_d"  # 故意拼错列名

# L1：模糊修正 cust_agge → cust_age；拦截 DELETE/越权表等
l1 = guard_sql(sql, metadata=md, allowed_tables={"ads_cust_info_d"})
print(l1.ok, l1.sql, l1.fixes)

# L2：EXPLAIN；失败则 1-Shot 纠错（需 LLM client / API Key）
l2 = validate_with_l2(
    l1.sql if l1.ok else sql,
    question="查看客户年龄",
    schema_context=md.format_table_schema("ads_cust_info_d", include_values=False),
    metadata=md,
    allowed_tables={"ads_cust_info_d"},
)
print(l2.ok, l2.corrected, l2.message)

if l2.ok:
    data = execute(l2.sql, max_rows=20)
    probe = probe_result("查看客户年龄", data)
    print(probe.triggered, probe.message, probe.suggestions)
```

危险语句会被 L1 直接拦截（无需进库）：

```python
from querypilot.safety import guard_sql

bad = guard_sql("DELETE FROM ads_cust_info_d", metadata=md)
assert not bad.ok
assert any(v.code == "dangerous_op" for v in bad.violations)
```

---

### 6.4 两模块怎么配合（最小心智模型）

| 步骤 | 谁做 | 入口 |
|------|------|------|
| 剪枝 + Prompt + 生成 SQL | **agent**（剪枝调 metadata_engine） | `generate_sql` / `ask` 前半段 |
| 静态安全 / 列名修复 | **safety L1** | `guard_sql` |
| 动态语法校验 + 一次纠错 | **safety L2** | `validate_with_l2` |
| 执行查询 | **db**（由 agent `ask` 调用） | `execute` |
| 空结果交互提示 | **safety probe** | `probe_result` |

日常使用优先走 **`ask()` / `querypilot ask`**；拆开调用 agent/safety API 主要用于单测、排错或二次集成。
