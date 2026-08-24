# 新表接入操作手册（拿到表 → 进数据库 → 元数据生效）

> 面向操作者的一步步手册。全程只需：放 CSV、跑命令、答问卷。
> 机器自动完成：登记 → 导入 → 结构发现 → 候选生成 → 落盘 → 注册 → 校验 → 回归（logs/12）。
>
> **占位符约定**：命令中 `[name]` = 表名（如 `dwd_cust_sign_d`），`[file]` = CSV 文件名，
> `[question]` = 冒烟问句，替换后执行。
>
> 环境约定：Windows / PowerShell（命令逐行执行，不要用 `&&` 串联）；
> 乱码时先执行一次 `$env:PYTHONIOENCODING="utf-8"`（本会话内后续命令均生效），
> 或按示例写成 `;` 串联的单行命令。

---

## 总览

```
① 放 CSV           ② 登记 + 单表导入           ③ 全量重建（备用）
   (data_sim/)         (add_table.py --import)
                                              ↓
④ 入库验证          ⑤⑥ 网页问卷一键落盘          ⑦⑧ 自动回归 + 冒烟
   discover            /onboarding 表单              validate / ask
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
Copy-Item .\[file] .\data_sim\
```

---

## ② 登记 import_data.py + 单表导入（自动）

一条命令完成登记与导入（类型自动推断，先在内存库试导入验证，再写入并导入现有库）：

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/add_table.py data_sim/[file] --import
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
> 需要全量重建时用下面的命令。

### 全量重建（标准路径）

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/import_data.py
```

⚠️ **重建会先删除整个 `db/competition.duckdb` 再全量导入所有表**，因此：
- `data/` 与 `data_sim/` 的所有 CSV 必须都在；
- **先关掉**正在运行的 serve / chat / 评测进程（DuckDB 文件锁会报错）。

预期输出（末尾）：

```
导入完成，共 11 张表，832,067 行。
```

---

## ④ 入库验证（A1 结构画像）

```powershell
$env:PYTHONIOENCODING="utf-8"; python -m querypilot.table_ops.discover [name]
```

核对输出：行数对不对、类型对不对、主键候选/常量列/日期列是否符合预期。
（例如 `data_dt` 应被识别为日期列；快照表会显示常量列及其值。）

---

## ⑤⑥ 网页问卷：一屏填完，一键落盘 + 校验 + 回归（推荐）

先启动服务（若未启动）：

```powershell
$env:PYTHONIOENCODING="utf-8"; python -m querypilot.cli serve
```

浏览器打开 **http://127.0.0.1:8000/onboarding** ，输入表名点「生成问卷」：
表描述、列含义、关联边、枚举含义等都已预填机械候选的默认答案，
只需改/补必填项（表别名、表描述、触发词、每列含义、冒烟问句），
勾选确认的关联边，点「提交注册」。

提交后页面直接显示 **A6 同步报告**（7 项，应全绿，零代码改动）与
**A7/A8 回归报告**（静态校验 + YAML↔DB 对齐 + join 边连通 + 剪枝冒烟）。
serve 进程内的元数据缓存会自动失效，无需重启即可提问。

**关键规则**：

| 项 | 说明 |
|----|------|
| 必填项 | 表别名、表描述、触发词（用户提到什么词必须选中这张表）、每列含义、冒烟问句 |
| 关联边 | 默认勾选「高置信 + 包含率 ≥ 99%」的候选；lookup 边的 `code_type_id` 已按列值集自动定位 |
| 枚举 | 命中 dim_public 字典的列自动同步 `value_descriptors`；未命中的低基数列逐值填含义 |
| 注册顺序 | **先维表（dim_），后引用它的事实表**——中途 join_graph 短暂不一致会被 A7 拦截 |
| 冒烟问句 | 要含触发词且问法域内典型（如「有多少激进型客户」） |

### 命令行方式（备用，与网页等价）

```powershell
# 生成问卷（查看机械候选与默认答案）
$env:PYTHONIOENCODING="utf-8"; python -m querypilot.table_ops.cli questionnaire [name]

# 落盘 + 校验 + 回归
$env:PYTHONIOENCODING="utf-8"; python -m querypilot.table_ops.cli register [name] --yes `
  --alias <表别名> `
  --description "<一句话表用途>" `
  --granularity <粒度，如 客户级> `
  --col-desc <列1>=<含义> --col-desc <列2>=<含义> `
  --edge <列>:<目标表>.<目标列>:<类型>:<规则> `
  --cue <触发词1>,<触发词2> `
  --question "[question]"
```

（PowerShell 用反引号 `` ` `` 续行；每列都要给 `--col-desc`，否则 A7 校验失败。
`--edge` 格式 `列:目标表.目标列[:类型[:规则]]`；`--enum-meaning` 回填 new 枚举；
`--dry-run` 只渲染不写盘；`--force` 覆盖已存在的表 YAML。）

---

## ⑦⑧ 最终冒烟

网页注册成功后（报告全绿），可再命令行复核或端到端提问：

```powershell
# 剪枝冒烟（确定性，不调 LLM）
$env:PYTHONIOENCODING="utf-8"; python -m querypilot.table_ops.validate [name] --question "[question]"

# 端到端提问（调 LLM，需 .env 的 API key）
$env:PYTHONIOENCODING="utf-8"; python -m querypilot.cli ask "[question]"
```

经 `/onboarding` 网页注册的，serve 进程缓存已自动失效，可直接继续提问；
走 ⑥ 命令行注册的，若 serve / chat 正在运行需**重启进程**才能加载新元数据。

---

## 卸载：删除一张已接入的表（保留 CSV）

接入流程的逆操作，一条命令撤销全部登记（CSV 不动）：

```powershell
# 先看会删什么（不写盘）
$env:PYTHONIOENCODING="utf-8"; python scripts/remove_table.py [name] --dry-run

# 确认后执行（同时 DROP DuckDB 里的表）
$env:PYTHONIOENCODING="utf-8"; python scripts/remove_table.py [name]
```

自动撤销的登记（与接入流程一一对应）：

| 登记 | 撤销动作 |
|------|---------|
| `scripts/import_data.py` TABLES 条目 | 删除条目（连同自动登记注释行），语法校验 |
| `metadata/tables/[name].yaml` | 删除文件 |
| `join_graph.yaml` tables 条目 + 双向边 | 删除（其他表的边不受影响） |
| `pruning.yaml` fact_tables 行 + 触发词条目 | 删除 |
| `value_descriptors.yaml` column_refs | 删除引用；引用清空的字典降级回 `unused_code_types` |
| DuckDB 表 | `DROP TABLE`（`--keep-db` 跳过） |

删除后自带**反向核验**（A6 的逆检查）：元数据中不应残留任何痕迹，有残留会列出来并以非零退出。

安全护栏：**非 `add_table.py` 自动登记的表默认拒绝删除**（如原始赛题表——删了会破坏既有查询），确需删除加 `--force`。需要重新接入时从 ② 开始重走即可。

---

## 常见问题

| 现象 | 原因与处理 |
|------|-----------|
| `table not found in database` | 没跑 ②/③，或表名/DDL 拼错；用 ④ 先验证入库 |
| 重建报 DuckDB 文件锁错误 | serve/chat/评测进程还开着，关掉再跑 |
| remove_table 报「拒绝: 不是自动登记的表」 | 该表是手写登记（多为原始赛题表）；确需删除加 `--force` |
| remove_table 报 DuckDB 占用 | serve/chat 还开着；关掉重跑，或先 `--keep-db` 只撤销登记 |
| 网页报「表不存在」 | 问卷接口只认**已入库**的表；先完成 ②/③ |
| 网页提交报 409 | 该表 YAML 已存在；确需覆盖走命令行 `--force`（慎用） |
| A7 报 `missing description` | 问卷里某列含义留空（每列必填） |
| register 报 `KeyError: 目标表` | 注册顺序反了：先注册边指向的维表 |
| 剪枝冒烟不命中 | 冒烟问句要含触发词（问法需域内典型，如「服务经理名下有多少客户」） |
| CSV 中文乱码 | 文件需 UTF-8；命令前缀 `$env:PYTHONIOENCODING="utf-8"; ` |
| prompt 里枚举显示空 | 网页枚举区「新枚举」含义没填；命令行走 `--enum-meaning` |

---

## 涉及文件一览（操作者视角）

| 动作 | 文件 |
|------|------|
| 放数据 | `data_sim/<表名>*.csv` |
| 机器自动写 | `scripts/import_data.py`（TABLES 登记，由 `scripts/add_table.py` 完成）、`metadata/tables/<表名>.yaml`、`metadata/join_graph.yaml`、`metadata/pruning.yaml`、`metadata/value_descriptors.yaml` |
| 全程不碰 | `querypilot/` 任何热路径代码、任何手写 YAML |
