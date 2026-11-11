# QueryPilot

证券客户营销场景下的 AI Native NL2SQL / 取数原型：业务人员用中文提问，系统生成只读 SQL，在本地 DuckDB 脱敏库上返回结果表。用来替代「固化报表不够灵活、自助 BI 门槛高、需求回流研发」的路径。

三句话：

1. YAML 元数据（表/列语义、Metric Tree、Join-Graph、Value Descriptor、Few-Shot）把业务口径从模型猜测里抽出来。
2. 默认快路径是 Schema 剪枝 + 单次 LLM 生成 + 确定性 SQL 修复 + L1 AST / L2 EXPLAIN 围栏 + 执行。
3. 并列一条强 Agent 工具循环；评测用 Execution Match，而不是比对 SQL 字符串。

过程记录与复测命令见 [`logs/Summary.md`](logs/Summary.md) 与 `logs/` 下各篇实验文档。

---

## 已实现能力

系统交付的是一套可运行、可评测、可运营的工程闭环，而不是单个 Prompt 或 API。三大业务模块如下。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      AI Native 智能数据洞察系统原型                      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     ▼                               ▼                               ▼
┌─────────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
│  1. 高性能取数 Agent    │ │  2. AI 友好元数据知识库 │ │ 3. 自动化评测与复核平台 │
│  (Pipeline + Agentic)   │ │   (Metadata Engine)     │ │   (Eval & Human-in-Loop)│
├─────────────────────────┤ ├─────────────────────────┤ ├─────────────────────────┤
│ • 动态 Schema 剪枝      │ │ • 指标树 (Metric Tree)  │ │ • Execution Match 引擎  │
│ • 单次 LLM SQL 生成     │ │ • Join-Graph 拓扑图谱   │ │ • Eval-Agent 归因分析   │
│ • 双层确定性安全围栏    │ │ • Value Descriptor      │ │ • CLI 复核与案例回流    │
│ • 并列强 Agent 工具循环 │ │ • 新表自助接入          │ │ • Extra 泛化 / 安全集   │
└─────────────────────────┘ └─────────────────────────┘ └─────────────────────────┘
```

**取数 Agent。** 默认问数走 Python 原生剪枝 + 单次 LLM SQL 生成 + 双层确定性安全围栏的快路径（`ask()`），避免多轮 Tool 循环的时延。并列一条强 Agent 工具循环（`querypilot.agentic.run`），复用同一套剪枝 / 围栏 / 执行函数，**不折进** `ask()`。问数页 / `querypilot ask` 走快路径；对话页 / `querypilot ask --mode agent` 走强 Agent。

**元数据知识库。** 表定义、指标树、Join-Graph、枚举字典、Few-Shot 与剪枝领域知识都在 YAML 里维护。Agent 只经 `load_metadata()`（热路径可用 `get_metadata()`），不直接读文件。新表接入走 `table_ops` 与网页 `/onboarding`，不必改热路径代码。

**评测与复核。** 以 Execution Match（EX）比对 Agent SQL 与金标 SQL 的执行结果集。Extra3 看意图围栏（拒绝 + 安全警告算对）。EX 失败时可跑 Eval-Agent 归因；HITL 是 CLI 分流 + 文件队列（`querypilot review`），确认后的样例回流到 Few-Shot YAML。没有独立的复核 Web UI。

外围支撑：HTTP API + Chat UI、可带走的 [`QueryPilot-demo/`](QueryPilot-demo/)、进程内查询/元数据缓存（可选 Redis）、冷/热压测脚本。

---

## 系统架构

端到端入口：快路径为 `querypilot.agent.pipeline.ask()`（CLI `querypilot ask` / HTTP `POST /api/ask`，默认 `mode=fast`）。**一次调用对应一次** `PipelineResult`；澄清后的追问是下一次调用，经 `history` 衔接。对话页与 `querypilot ask --mode agent` 走并列的强 Agent，返回同一套 `PipelineResult`。

### 输入 → 输出契约

| 方向 | 内容 |
| ---- | ---- |
| **Input** | 中文自然语言问题 `question`；可选 `history`（`[{role, content}]`，澄清/多轮）；以及 `max_rows`、`max_few_shots`、`use_cache`、`use_parallel` 等 |
| **Output（成功）** | `ok=True`：通常含 `sql`、`rationale`、剪枝命中的 `tables`、`columns` + `rows`、各阶段 `timing`；若结果为空/异常可能附带 `probe_message`（不阻断成功）。`stage=clarify` 时 `sql` 为空，`message` 为追问 |
| **Output（失败）** | `ok=False`、`degraded=True`：停在失败阶段 `stage`（`safety` / `prune` / `generate` / `l1` / `l2` / `execute`），`message` 说明原因；已生成的 `sql` / `rationale` 尽量保留供排查 |

### 快路径（`ask()`）

```
[用户自然语言 question]
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ 0. 加载元数据（MetadataBundle，进程内缓存）                    │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 0b. 意图围栏  check_malicious_intent（问句 + 拼接后的 history）│
│     命中 → stage=safety，不剪枝、不调 LLM                      │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Schema 剪枝  prune_schema / get_pruned_schema             │
│    问句扩展 → 关键词/别名打分命中表/列/指标 → 领域 cue 补种子表 │
│    → Join-Graph 补全多表路径 → 输出剪枝 Schema 文本供 Prompt   │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. SQL 生成  generate_sql                                     │
│    ├─（可选）Few-Shot 问句完全匹配 → 直接返回已知 SQL，不调 LLM │
│    └─ 否则：组装 Prompt → DeepSeek 单次 JSON 输出            │
│       { sql, rationale, uses_cte, clarify? }               │
│       clarify 非空且 sql 为空 → stage=clarify，ok=True，停   │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2b. 确定性 SQL 归一化（无 LLM）                               │
│     fix_period_pnl_sql（区间盈亏口径）+ fix_org_topn_sql（网点 Top-N）│
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. L1 静态围栏  guard_sql（sqlglot AST）                      │
│     拦截写操作 / 非授权表；列名模糊修正；失败 → 降级返回       │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. L2 动态围栏  validate_with_l2                              │
│     DuckDB EXPLAIN 预检                                       │
│     ├─ 通过 → 进入执行                                        │
│     └─ 失败 → 1-Shot LLM 纠错（附带 EXPLAIN 报错 + Schema）   │
│              → 纠错 SQL 再过 L1 → 再 EXPLAIN（最多 1 次纠错）  │
│              → 仍失败 → 降级返回（无 ReAct 循环）              │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 4b. 再次应用 2b 确定性归一化（L2 纠错后）                    │
└─────────────────────────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 执行  execute（DuckDB 只读，受 max_rows 限制）              │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. 结果探针  probe_result（空结果 / 计数为 0 / 异常量级）     │
│     生成交互提示与放宽建议；ok 仍为 True，message 可能 enriched  │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. 写入 Query Cache（成功且非降级路径）→ 返回 PipelineResult   │
└─────────────────────────────────────────────────────────────┘
```

要点：L1 失败直接终止，不进入 L2。L2 纠错不回到剪枝，只在 L2 内部完成「EXPLAIN 失败 → 一次 LLM 纠错 → L1 → 再 EXPLAIN」。主路径 LLM 上限为 **生成 1 次 + 纠错 1 次**（Few-Shot 短路与 Cache 命中时可为 0 次）。探针不阻止返回数据；缓存只写入围栏通过的成功路径。有 `history` 时不走问句缓存 / 精确 Few-Shot 短路。

**实现锚点**：`querypilot/agent/pipeline.py`（编排）、`sql_generator.py`（生成）、`safety/intent_guard.py`（意图围栏）、`safety/l1_ast.py` + `l2_explain.py`（围栏）、`safety/result_probe.py`（探针）、`cache/query_cache.py`（问句级缓存）。

### 快捷分支

| 分支 | 触发条件 | 行为 |
| ---- | -------- | ---- |
| **Query Cache 命中** | 相同问句 + 参数组合的缓存存在；**无** `history` | 跳过剪枝/生成/围栏；直接回放已验 SQL；若缓存含结果行则毫秒级返回，否则重执行 + 探针 |
| **Few-Shot 精确短路** | `allow_exact_few_shot=True`、无 `history`，且 HITL 回流样例问句完全一致 | 在步骤 2 内直接返回样例 SQL，不调用 LLM（评测泛化时可 `--no-exact-few-shot` 关闭） |
| **规则并行（可选）** | CLI/API 传入 `use_parallel=True` 且问法命中多指标规则 | `parallel.try_parallel_pipeline` 拆成多条 SQL 并行执行后在 `pty_id` 上合并；成功则提前返回，失败则回退上述主流程 |

默认缓存是进程内；设置 `REDIS_URL` 时查询缓存可走 Redis，未配置则回落内存。

### 强 Agent 工具循环（`agentic.run`）

与快路径**并列**，不改 `ask()` 编排。原则：复用函数（剪枝 / `generate_sql` / L1 / L2 / `execute` / 探针 / 意图围栏），不复用编排。两条入口都过同一套 `check_malicious_intent`。

| 表面 | 快路径 | 强 Agent |
| ---- | ------ | -------- |
| CLI | `querypilot ask "..."` | `querypilot ask --mode agent [--session id] "..."` |
| API | `POST /api/ask` 默认 `mode=fast` | `mode=agent` + 可选 `session_id` |
| UI | 问数页 | 对话页（`mode=agent` + `sessionId`） |
| 评测 | `eval --mode fast`（默认，只调 `ask()`） | `eval --mode agent`（每题独立 `session_id=eval-{id}`） |

```
[用户自然语言 question]
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ 意图围栏  check_malicious_intent（与快路径同一套）            │
│     命中 → stage=safety，不进工具循环                         │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ SessionMemory（session_id 续接追加式 messages[]）            │
│     首轮带剪枝 Schema + Few-Shot；续聊换题重新剪枝            │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 预算化工具循环（每轮一个 JSON 工具，上限 6）                  │
│     search_schema / run_sql / ask_user / finish             │
│     run_sql：提交 SQL，成功回结果、失败回原因；L1/L2 在工具内 │
│     消化，不写进提示词；失败可改 SQL 再跑                     │
│     ask_user / finish / 预算耗尽 → 结束                      │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 返回 PipelineResult；轨迹在 extras.agent_trace               │
└─────────────────────────────────────────────────────────────┘
```

**实现锚点**：`querypilot/agentic/run.py`（入口）、`loop.py`（循环）、`tools.py`（工具包装）、`memory.py`（会话）。细节见 `logs/10`、`logs/11`。

---

## 关键设计

**为何双路径，而不是全程 ReAct。** 多轮 Tool 拉元数据耗时长，复杂题还要多轮交互。快路径主路径最多「生成 1 次 + L2 纠错 1 次」，步骤固定、temperature=0，评测可复现；写操作与表白名单在 Python AST / EXPLAIN / 只读连接里硬拦，不靠模型自觉。强 Agent 留给对话页：失败可改 SQL 再跑，可 `ask_user`。两路径复用剪枝、围栏、`execute` 和口径规则，只是编排不同。

**口径在 YAML，不靠模型猜。** Schema 剪枝是关键词/别名打分 + 领域 cue + Join-Graph 路径补全，不是向量检索。Few-Shot 存在 `metadata/few_shots/`，没有单独的向量库。跨表默认只按 `pty_id` / `org_id` Join，**不要默认加** `data_dt`（维表与事实表日期集合不对齐）。公共维表 `dim_public` 必须同时匹配 `code` 与 `code_type_id`。期间盈亏统一为 `aset_pft = end − (bgn_nm + bgn_fc) + out − in`（见 `logs/11`）。

**安全分层。** 恶意 / 越狱问句在剪枝前被意图围栏拒绝（`stage=safety`）。L1 拦写操作与越权表，并做列名模糊修正；L2 用 `EXPLAIN` 抓库级错误，最多 1 次 LLM 纠错。需求不清时生成步可停在 `stage=clarify`（空 SQL），由 CLI / 对话带 `history` 再调一次。

**评测看结果集。** 字符串比对 SQL 几乎无意义。官方金标与 Few-Shot 问句相同，**保留**精确短路才反映「原题可秒过」。Extra / Extra2 是改写题，必须 `--no-exact-few-shot`，否则会虚高。Extra3 看意图围栏，与 Few-Shot 无关。

---

## 实验结果

数字来自 [`logs/11`](logs/11-口径对齐与双路径收口.md)（官方 DeepSeek API，`deepseek-chat`，2026-08-21）。官方金标保留精确 Few-Shot；Extra / Extra2 关短路、`fs=3`；Extra3 拒绝 + 警告算对。这是当前 benchmark，**不是**生产 100%；214 含官方集短路轨。

| 集 | fast | agent |
| --- | --- | --- |
| 官方 7 | 7/7 | 7/7 |
| Extra36 | 36/36 | 36/36 |
| Extra2 | 40/40 | 40/40 |
| Extra3 | 24/24 | 24/24 |

合计 **214/214**。报告：`logs/eval_reports/{gold,extra36,extra2,extra3}_{fast,agent}.json`。

单题 `total_ms` 分位数（不是 4 进程批跑墙钟）。冷路径几乎全在 `generate_ms`。

| 集 | 模式 | p50 | p95 | mean |
| --- | --- | ---: | ---: | ---: |
| 官方 7 | fast | 2.7 s | 3.1 s | 1.8 s |
| 官方 7 | agent | 5.0 s | 6.1 s | 3.3 s |
| Extra36 | fast | 2.3 s | 4.2 s | 2.5 s |
| Extra36 | agent | 3.2 s | 12.3 s | 4.3 s |
| Extra2 | fast | 2.2 s | 3.0 s | 2.3 s |
| Extra2 | agent | 3.5 s | 6.9 s | 4.2 s |
| Extra3 | fast | <1 ms | 8 ms | 1 ms |
| Extra3 | agent | <1 ms | 13 ms | 2 ms |

Extra3 在意图围栏拦截，不调 LLM。组件消融见 [`logs/09`](logs/09-阶段九-消融实验与改进总结.md)；多模型双路径对照见 [`logs/13`](logs/13-多模型双路径评测对照.md)。

---

## 快速开始

环境：Python 3.10+，Windows / PowerShell（命令逐行执行，不要用 `&&` 串联）。乱码时先执行 `$env:PYTHONIOENCODING="utf-8"`。

```powershell
# 1. 配置密钥（切勿提交 .env）
Copy-Item .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 安装并导入脱敏 CSV → DuckDB
pip install -e .
python scripts/import_data.py
```

导入会重建 `db/competition.duckdb`。`data/` 是官方 CSV，只读；新表 CSV 放 `data_sim/`，步骤见 [`ONBOARDING.md`](ONBOARDING.md)。

### 问数

```powershell
# 快路径（需 .env 中 DEEPSEEK_API_KEY，以及已导入的 db/competition.duckdb）
querypilot ask "有多少年龄大于30岁的女性客户？"

# 或：python -m querypilot.cli ask "总资产超过100万的客户有多少人？"

# 强 Agent（对话页同一条路径；不走 ask()）
querypilot ask --mode agent "帮我看看客户情况"

# 批量 Demo（5 条样例问句，快路径）
python scripts/demo_pipeline.py
```

同问二次：第二次应 `cache_hit=yes`（热路径毫秒～亚秒）。冷/热压测：

```powershell
python scripts/bench_pipeline.py --limit 3 --warm --output logs/perf_reports/bench_warm.json
python scripts/phase4_perf_closeout.py --live
```

### HTTP API + Chat UI

```powershell
# 终端 1：先启动 API
querypilot serve --host 127.0.0.1 --port 8000

# 终端 2：再启动 Chat UI（默认 http://127.0.0.1:5173，代理 /api → 8000）
# 问数页走 ask()；对话页走 --mode agent
cd frontend
npm install
npm run dev
```

新表接入问卷：服务已启动时打开 http://127.0.0.1:8000/onboarding 。Swagger：http://127.0.0.1:8000/docs 。前端操作见 [`frontend/README.md`](frontend/README.md)。

### 局域网使用

页面和接口由同一个进程提供。其他电脑不用安装本项目；数据库和模型密钥留在运行服务的这台机器上。

```powershell
cd frontend
npm install
npm run build

querypilot serve --host 0.0.0.0 --port 8000
```

本机打开 http://127.0.0.1:8000/ 。同一局域网的其他电脑打开 `http://<本机IPv4>:8000/` 。本机 IPv4 在 PowerShell 里用 `ipconfig` 查看。Windows 首次弹出防火墙提示时，允许 Python 访问专用网络。

问数、对话、表格和新表登记都在这个地址上。改过前端后要重新 `npm run build`，再启动服务。开发时若要热更新，仍用上一节的两个终端；页面命令换成 `npm run dev -- --host` 后，其他电脑使用终端打印的 Network 地址，接口继续只监听本机。

访问密钥写在项目根目录的 `access_keys.txt`，一行一个，`#` 开头的行会被忽略。也可以用环境变量 `QUERYPPILOT_ACCESS_KEYS`，多个密钥用逗号分隔。至少有一个密钥时，打开页面要先输入密钥；文件和环境变量都留空则不校验。这个密钥只用来进入页面，和设置里的模型密钥无关。

可单独带走的演示包：进入 `QueryPilot-demo/`，双击 `启动演示.bat`，浏览器打开 http://127.0.0.1:8787/（说明见 [`logs/14`](logs/14-独立演示包.md)）。

### 评测

默认 `--mode fast` 只调 `ask()`；`--mode agent` 走 `agentic.run`，每题独立会话，不经过 `ask()`。全量复测命令与参数见 `logs/11` §3。

```powershell
# 官方金标（保留精确 Few-Shot 短路）
python -m querypilot.cli eval --mode fast  --path "data/Q&A.xlsx" --workers 4 --output "logs/eval_reports/gold_fast.json"
python -m querypilot.cli eval --mode agent --path "data/Q&A.xlsx" --workers 4 --output "logs/eval_reports/gold_agent.json"

# Extra36 / Extra2（关短路，fs=3）
python -m querypilot.cli eval --mode fast  --path "data/extra/Q&A_all.xlsx"  --no-exact-few-shot --max-few-shots 3 --workers 4 --output "logs/eval_reports/extra36_fast.json"
python -m querypilot.cli eval --mode agent --path "data/extra/Q&A_all.xlsx"  --no-exact-few-shot --max-few-shots 3 --workers 4 --output "logs/eval_reports/extra36_agent.json"
python -m querypilot.cli eval --mode fast  --path "data/extra2/Q&A_all.xlsx" --no-exact-few-shot --max-few-shots 3 --workers 4 --output "logs/eval_reports/extra2_fast.json"
python -m querypilot.cli eval --mode agent --path "data/extra2/Q&A_all.xlsx" --no-exact-few-shot --max-few-shots 3 --workers 4 --output "logs/eval_reports/extra2_agent.json"

# Extra3（安全拒答；不必关短路）
python -m querypilot.cli eval --mode fast  --path "data/extra3/Q&A_all.xlsx" --workers 4 --output "logs/eval_reports/extra3_fast.json"
python -m querypilot.cli eval --mode agent --path "data/extra3/Q&A_all.xlsx" --workers 4 --output "logs/eval_reports/extra3_agent.json"
```

| 参数 | 含义 |
| ---- | ---- |
| `--mode fast` / `agent` | 默认 fast 走 `ask()`；agent 走 `agentic.run` |
| `--path` / `--paths` | 金标 xlsx；`--paths` 可重复，接在 `--path` 后合并 |
| `--no-exact-few-shot` | 关掉「问句原文命中 Few-Shot 则直接回流 SQL」 |
| `--max-few-shots N` | Prompt 里最多带 N 条相似样例（默认 3；`0` 为消融） |
| `--workers N` | 并行评题，各开自己的 DuckDB；只缩短墙钟 |
| `--output` | 报告 JSON；不加则写到 `logs/eval_reports/eval_*.json` |
| `--diagnose` / `--review` | 失败题归因；构建 HITL 复核队列（文件，不是 Web UI） |

---

## 仓库结构

```
source/
├── querypilot/                 # 主 Python 包
│   ├── config.py               # 统一配置（.env / 路径）
│   ├── cli.py                  # CLI：ask / eval / review / serve
│   ├── agent/                  # 快路径 Pipeline（ask()）
│   ├── agentic/                # 强 Agent 工具循环（不折进 ask()）
│   ├── metadata_engine/        # 元数据加载、Join-Graph、Schema 剪枝
│   ├── safety/                 # 意图围栏 + L1 AST + L2 EXPLAIN + 结果探针
│   ├── eval/                   # Execution Match + Extra3 安全拒绝 + Eval-Agent
│   ├── table_ops/              # 新表发现 / 问卷 / 注册 / 回归（不在热路径）
│   ├── cache/                  # 进程内元数据/剪枝/问句缓存；可选 Redis
│   ├── llm/                    # DeepSeek 客户端
│   ├── db/                     # DuckDB 只读连接
│   └── api/                    # HTTP API（ask + onboarding + settings）
│
├── metadata/                   # AI 友好元数据（YAML）
│   ├── tables/                 # 逐表定义
│   ├── metrics/metrics.yaml    # 指标树
│   ├── join_graph.yaml         # 表关联拓扑（含日期不对齐说明）
│   ├── value_descriptors.yaml  # 枚举值字典
│   ├── pruning.yaml            # 剪枝领域知识（触发词 / 同义词）
│   └── few_shots/examples.yaml # Few-Shot / HITL 回流样例
│
├── frontend/                   # Chat UI：问数页 + 对话模式
├── QueryPilot-demo/            # 可单独带走的演示包（双击 8787）
├── data/                       # 官方 CSV 与金标 / extra*（只读）
├── data_sim/                   # 模拟/新增表 CSV
├── db/                         # DuckDB 文件（gitignore）
├── scripts/                    # 导入、压测、demo、消融
├── tests/                      # 单元测试
├── logs/                       # 实验记录与评测/压测报告
├── ONBOARDING.md               # 新表接入操作手册
├── pyproject.toml
└── requirements.txt
```

| 目录 | 职责 |
| ---- | ---- |
| `metadata_engine/` | 元数据加载、Join-Graph、Schema 剪枝 |
| `agent/` | NL → SQL 快路径（`ask()`） |
| `agentic/` | 强 Agent 工具循环（`run()`） |
| `safety/` | 意图围栏 + sqlglot + EXPLAIN + 探针 |
| `eval/` | EX 评测 + Extra3 安全拒绝 + Eval-Agent + HITL 文件队列 |
| `table_ops/` | 新表自助接入（发现 → 问卷 → 落盘 → 回归） |
| `api/` + `frontend/` | HTTP 与 Chat UI，包装已有 `ask()` / `run()` |
| `QueryPilot-demo/` | 热路径 + DuckDB + 已构建 UI 的副本，不是第二条实现 |

---

## 更多文档

| 你想了解… | 建议文档 |
| --------- | -------- |
| 设计总览 | [`logs/Summary.md`](logs/Summary.md) |
| Pipeline 与围栏 | [`logs/02`](logs/02-阶段二-核心取数Pipeline与安全围栏.md) |
| EX / 归因 / 回流 | [`logs/03`](logs/03-阶段三-自动化评测与人机复核平台.md) |
| 缓存与延迟 | [`logs/04`](logs/04-阶段四-系统性能压测与极速响应优化.md) |
| API / 问数页 | [`logs/05`](logs/05-阶段五-原型系统交付与验证.md)；对话模式见 [`frontend/README.md`](frontend/README.md) |
| Extra3 安全评测 | [`data/extra3/README.md`](data/extra3/README.md) |
| 双路径强 Agent | [`logs/10`](logs/10-双路径强Agent与快取数并行.md) |
| 盈亏口径与全量分数 | [`logs/11`](logs/11-口径对齐与双路径收口.md) |
| 新表自助接入 | [`ONBOARDING.md`](ONBOARDING.md)、[`logs/12`](logs/12-元数据外部化与新表自助接入落地.md) |
| 消融 | [`logs/09`](logs/09-阶段九-消融实验与改进总结.md) |
| 多模型对照 | [`logs/13`](logs/13-多模型双路径评测对照.md) |
| 独立演示包 | [`logs/14`](logs/14-独立演示包.md) |
