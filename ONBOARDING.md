# 新表接入操作手册（拿到表 → 进数据库 → 元数据生效）

> 面向操作者的一步步手册。全程只需：放 CSV、登记一处、跑命令、答问卷。
> 机器自动完成：结构发现 → 候选生成 → 落盘 → 注册 → 校验 → 回归（logs/12）。
>
> 环境约定：Windows / PowerShell（命令逐行执行，不要用 `&&` 串联）；
> 所有 python 命令加 `PYTHONIOENCODING=utf-8` 前缀避免中文乱码。

---

## 总览

```
① 放 CSV           ② 登记 import_data.py      ③ 重建 DuckDB
   (data_sim/)         (TABLES + DDL)             (或单表轻量导入)
                                              ↓
④ 入库验证          ⑤ 生成问卷                  ⑥ 答问卷落盘
   discover            questionnaire               register
                                              ↓
⑦ 自动回归          ⑧ 冒烟提问验证
   validate            querypilot ask
```

---

## ① 放置 CSV 文件

**目录选择（重要）**：

| 目录 | 用途 | 规则 |
|------|------|------|
| `data/` | 官方赛题数据 | **只读，永远不要放/改新文件** |
| `data_sim/` | 模拟/新增表 | 新表放这里（推荐） |

**文件要求**：

- UTF-8 编码、首行为表头、逗号分隔；
- 文件名以表名开头，如 `dim_mgr_info_20260824.csv`（匹配 pattern `dim_mgr_info*.csv`）；
- 表名遵循数仓前缀约定（自动推断层次）：`dim_`（维表）/ `dwd_`（明细事实）/ `dws_`（汇总事实）/ `ads_`（应用宽表）。

示例：

```powershell
# 假设拿到一张客户签约表 dwd_cust_sign_d.csv（1 个文件）
Copy-Item .\dwd_cust_sign_d.csv .\data_sim\
```

---

## ② 登记 import_data.py（自动）

一条命令完成登记（类型自动推断，先在内存库试导入验证，再写入）：

```powershell
PYTHONIOENCODING=utf-8 python scripts/add_table.py data_sim/dwd_cust_sign_d.csv --import
```

脚本自动完成：

- 表名从文件名推断（`xxx_20260824.csv` → `xxx`）；
- **类型推断**（与既有 DDL 约定一致）：`_cd`/`_id` 后缀编码键列 → `VARCHAR`（防前导零丢失），
  日期样式（8 位数字）→ `VARCHAR`，整数 → `INTEGER`/`BIGINT`，小数 → `DECIMAL(20, 4)`；
- 在 `TABLES` 字典末尾插入条目（保注释文本手术），并做语法校验；
- `--import` 同时对现有库做**单表轻量导入**（不动其他表）。

不带 `--import` 则只登记，之后走 ③ 全量重建。`--dry-run` 只打印条目不写盘；
已登记的表会拒绝重复登记。

> 手写方式（备用）：打开 [scripts/import_data.py](scripts/import_data.py) 在 `TABLES`
> 字典末尾照既有条目格式手写（`pattern` / 可选 `csv_dir` / `ddl`），
> 列名顺序与 CSV 表头一致（`read_csv` 按位置插入），类型按上述约定。

---

## ③ 导入 DuckDB

> ② 已带 `--import` 的话本步已完成（单表导入），可直接跳到 ④；
> 需要全量重建时仍用方式 A。

### 方式 A：全量重建（标准路径）

```powershell
PYTHONIOENCODING=utf-8 python scripts/import_data.py
```

⚠️ **重建会先删除整个 `db/competition.duckdb` 再全量导入所有表**，因此：
- `data/` 与 `data_sim/` 的所有 CSV 必须都在；
- **先关掉**正在运行的 serve / chat / 评测进程（DuckDB 文件锁会报错）。

预期输出（末尾）：

```
导入完成，共 11 张表，832,067 行。
```

### 方式 B：单表轻量导入（不动其他表）

即 ② 的 `--import`（`scripts/add_table.py` 内置），不再需要手写 python -c。

---

## ④ 入库验证（A1 结构画像）

```powershell
PYTHONIOENCODING=utf-8 python -m querypilot.table_ops.discover dwd_cust_sign_d
```

核对输出：行数对不对、类型对不对、主键候选/常量列/日期列是否符合预期。
（例如 `data_dt` 应被识别为日期列；快照表会显示常量列及其值。）

---

## ⑤ 生成登记问卷（A9：候选 + 默认答案）

```powershell
PYTHONIOENCODING=utf-8 python -m querypilot.table_ops.cli questionnaire dwd_cust_sign_d
```

输出 Q1-Q7 业务问题和机械候选底稿（Q5 会列出值域验证过的 join 边候选及置信度，
Q6 列出枚举/字典候选）。**逐项核对**，这些就是 ⑥ 要提供的答案。

---

## ⑥ 回答问卷，一条命令落盘 + 校验 + 回归

```powershell
PYTHONIOENCODING=utf-8 python -m querypilot.table_ops.cli register dwd_cust_sign_d --yes `
  --alias 客户签约表 `
  --description "客户签约关系（签约类型与签约日期）。" `
  --granularity 客户级 `
  --col-desc pty_id=客户号 --col-desc sign_type=签约类型 --col-desc sign_date=签约日期 --col-desc data_dt=日期 `
  --edge pty_id:ads_cust_info_d.pty_id:fact:no_default_data_dt `
  --cue 签约,签约关系 `
  --question "有多少客户签了约"
```

（PowerShell 用反引号 `` ` `` 续行；每列都要给 `--col-desc`，否则 A7 校验失败。）

这条命令自动完成：**A5 落盘**（表 YAML + join_graph + pruning + value_descriptors）
→ **A6 同步报告**（7 项，应显示「全部同步生效，零代码改动」）→ **A7/A8 回归**
（静态校验 + YAML↔DB 对齐 + join 边连通 + 剪枝冒烟）。

**关键规则**：

| 项 | 说明 |
|----|------|
| `--edge` 格式 | `列:目标表.目标列[:类型[:规则]]`，类型 `fact`/`dimension`/`lookup` |
| `--enum-meaning` | `列=值:含义,值:含义`，回填 Q6 的 new 枚举 |
| 注册顺序 | **先维表（dim_），后引用它的事实表**——中途 join_graph 短暂不一致会被 A7 拦截 |
| `--dry-run` | 只渲染不写盘，先看要落什么 |
| `--force` | 覆盖已存在的表 YAML（慎用） |
| 维表/事实表自动行为 | dwd/dws 自动进 `fact_tables`（客户枢纽注入生效）；`--cue` 挂剪枝触发词 |

---

## ⑦⑧ 最终冒烟

```powershell
# 剪枝冒烟（确定性，不调 LLM）
PYTHONIOENCODING=utf-8 python -m querypilot.table_ops.validate dwd_cust_sign_d --question "有多少客户签了约"

# 端到端提问（调 LLM，需 .env 的 API key）
PYTHONIOENCODING=utf-8 python -m querypilot.cli ask "签约客户有多少人"
```

若 serve / chat 正在运行：**需重启进程**才能加载新元数据（元数据在进程启动时加载并缓存）。

---

## 常见问题

| 现象 | 原因与处理 |
|------|-----------|
| `table not found in database` | 没跑 ③，或表名/DDL 拼错；用 ④ 先验证入库 |
| 重建报 DuckDB 文件锁错误 | serve/chat/评测进程还开着，关掉再跑 |
| A7 报 `missing description` | ⑥ 漏了某列的 `--col-desc`（每列必填） |
| register 报 `KeyError: 目标表` | 注册顺序反了：先注册边指向的维表 |
| 剪枝冒烟不命中 | 冒烟问句要含 `--cue` 里的触发词（问法需域内典型，如「服务经理名下有多少客户」） |
| CSV 中文乱码 | 文件需 UTF-8；命令加 `PYTHONIOENCODING=utf-8` |
| prompt 里枚举显示空 | Q6 的 new 枚举没回填含义，`--enum-meaning` 提供 |

---

## 涉及文件一览（操作者视角）

| 动作 | 文件 |
|------|------|
| 放数据 | `data_sim/<表名>*.csv` |
| 机器自动写 | `scripts/import_data.py`（TABLES 登记，由 `scripts/add_table.py` 完成）、`metadata/tables/<表名>.yaml`、`metadata/join_graph.yaml`、`metadata/pruning.yaml`、`metadata/value_descriptors.yaml` |
| 全程不碰 | `querypilot/` 任何热路径代码、任何手写 YAML |