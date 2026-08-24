"""A5 注册落盘 + cue 继承：问卷确认后的答案 → 元数据文件（logs/08 §三）。

边界约定：
  - 输入是「问卷答案」（语义知识，人类确认过），底稿来自 A2 骨架（机械事实）；
  - 只写元数据文件（tables/*.yaml、join_graph.yaml、pruning.yaml、
    value_descriptors.yaml），永不改任何机制代码；
  - 对既有文件做「文本级插入」（在对应块头后插入新条目），保留全部注释。

A5 cue 继承规则（机械）：
  - layer 为 dwd/dws 的事实表 → 自动加入 pruning.yaml fact_tables（客户枢纽注入生效）；
  - 问卷给出 cue_words → 追加 domain_seed_cues 条目（触发词强制补表）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from querypilot.config import get_settings
from querypilot.table_ops.discover import build_skeleton

_FACT_LAYERS = frozenset({"dwd", "dws"})


@dataclass
class SyncCheck:
    """单项注册表同步检查。"""

    name: str
    ok: bool
    detail: str = ""


@dataclass
class RegistrationSyncReport:
    """A6 注册表同步报告：新表被所有动态注册表自动接纳，零代码改动。"""

    table: str
    checks: list[SyncCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[SyncCheck]:
        return [c for c in self.checks if not c.ok]

    def report(self) -> str:
        lines = [f"表 {self.table} 注册表同步报告", "=" * 60]
        for c in self.checks:
            mark = "✓" if c.ok else "✗"
            extra = f"  ({c.detail})" if c.detail and not c.ok else ""
            lines.append(f"  {mark} {c.name}{extra}")
        lines.append("结论: " + ("全部同步生效，零代码改动" if self.ok else f"{len(self.failed)} 项未同步"))
        return "\n".join(lines)


@dataclass
class RegistrationAnswers:
    """新表登记问卷（Q1-Q7）确认后的答案。"""

    table: str
    alias: str  # Q1 表别名（如 服务经理信息表）
    description: str  # Q1 表用途
    domain: str = ""  # Q2 业务域（仅记录，供追溯）
    granularity: str = ""  # Q3 一行代表什么 → usage
    primary_key: list[str] | None = None  # Q3 确认主键（None 用骨架建议值）
    column_descriptions: dict[str, str] = field(default_factory=dict)  # Q4 列含义
    column_aliases: dict[str, list[str]] = field(default_factory=dict)  # Q4 列别名
    join_edges: list[dict[str, Any]] = field(default_factory=list)  # Q5 确认的边（A3 suggested_edge）
    enum_meanings: dict[str, dict[str, str]] = field(default_factory=dict)  # Q6 值 → 含义
    usage: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # Q7 特殊口径
    cue_words: list[str] = field(default_factory=list)  # A5 触发词（默认继承自同域 cue）
    paths: list[dict[str, Any]] = field(default_factory=list)  # 可选：预定义路径


@dataclass
class RegistrationResult:
    """落盘结果（dry_run 时只含渲染文本，不写文件）。"""

    table: str
    table_yaml_path: Path | None
    join_graph_path: Path | None
    pruning_path: Path | None
    value_descriptors_path: Path | None
    table_yaml: str
    join_graph_insert: str
    pruning_insert: str
    value_descriptors_insert: str
    dry_run: bool

    @property
    def cue_inherited(self) -> bool:
        return bool(self.pruning_insert)


# ---------- YAML 文本级插入（保留注释） ----------


def _find_header(lines: list[str], header: str) -> int:
    for i, line in enumerate(lines):
        if line.rstrip("\r\n") == f"{header}:":
            return i
    raise ValueError(f"header '{header}:' not found")


def _insert_after_header(path: Path, header: str, snippet_lines: list[str]) -> None:
    """在 ``header:`` 行之后插入 snippet（对 list/mapping 块头均合法：新条目前置）。"""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    i = _find_header(lines, header)
    lines[i + 1 : i + 1] = snippet_lines
    path.write_text("".join(lines), encoding="utf-8")


def _serialize_item(item: dict[str, Any], indent: int = 2) -> list[str]:
    text = yaml.safe_dump([item], allow_unicode=True, sort_keys=False, default_flow_style=False)
    pad = " " * indent
    return [f"{pad}{line}\n" for line in text.rstrip("\n").splitlines()]


def _serialize_entry(entry: dict[str, Any], indent: int = 2) -> list[str]:
    text = yaml.safe_dump(entry, allow_unicode=True, sort_keys=False, default_flow_style=False)
    pad = " " * indent
    return [f"{pad}{line}\n" for line in text.rstrip("\n").splitlines()]


def _detect_child_indent(lines: list[str], header_idx: int, child_prefix: str) -> int:
    """探测 header 块下既有条目的缩进（list 看 '- '，mapping 看键行）；空块回退 2。"""
    for line in lines[header_idx + 1 :]:
        stripped = line.rstrip("\r\n")
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lstrip().startswith(child_prefix):
            return len(stripped) - len(stripped.lstrip())
        return 2  # 块已结束（碰到非子条目行）
    return 2


def _append_list_item(path: Path, header: str, item: Any) -> None:
    """向 ``header:`` list 块前置一个条目（顺序不影响语义），缩进随既有条目。"""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    i = _find_header(lines, header)
    indent = _detect_child_indent(lines, i, "- ")
    _insert_after_header(path, header, _serialize_item(item, indent))


def _append_mapping_entry(path: Path, header: str, entry: dict[str, Any]) -> None:
    """向 ``header:`` mapping 块前置一个条目，缩进随既有条目。"""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    i = _find_header(lines, header)
    indent = _detect_child_indent(lines, i, "x")  # 任意键行
    _insert_after_header(path, header, _serialize_entry(entry, indent))


def _append_column_ref(path: Path, code_type_id: str, table: str, column: str) -> None:
    """在 value_descriptors.yaml 的 code_types.<id>.column_refs 下追加一条引用。

    类型只存在于 ``unused_code_types``（从未被引用）时，先在 code_types 下建完整条目
    （label 取自 unused_code_types），并从 unused_code_types 移除该行。
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    type_header = f'  "{code_type_id}":'
    if not any(line.rstrip("\r\n") == type_header for line in lines):
        _promote_unused_code_type(path, code_type_id)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    type_header = f'  "{code_type_id}":'
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        if stripped == type_header:
            in_block = True
            continue
        if in_block:
            if stripped == "    column_refs:":
                insert = [f"      - table: {table}\n", f"        column: {column}\n"]
                lines[i + 1 : i + 1] = insert
                path.write_text("".join(lines), encoding="utf-8")
                return
            if stripped and not stripped.startswith("    "):
                break  # 离开该 code_types 块（缩进 < 4）
    raise ValueError(f"column_refs not found under code_types.{code_type_id} in {path}")


def _find_block_header(text: str, header: str) -> int:
    """行首块头位置（避免 unused_code_types 被当作 code_types 子串命中）。"""
    idx = -1
    for m in __import__("re").finditer(rf"^{header}:", text, __import__("re").MULTILINE):
        idx = m.start()
    return idx


def _promote_unused_code_type(path: Path, code_type_id: str) -> None:
    """把 ``unused_code_types`` 里的类型升级为 code_types 完整条目（带首个 column_refs）。

    label 从 unused_code_types 的中文描述取得；同时删除 unused 行，
    三方一致性（表 YAML / join_graph filter / column_refs）由 metadata_validator 兜底。
    """
    import re as _re

    text = path.read_text(encoding="utf-8")
    match = _re.search(
        rf'^(\s*)"?{code_type_id}"?:\s*(.+)$', text, _re.MULTILINE
    )
    # 只认 unused_code_types 块里的行：向上找最近的块头判断
    if not match:
        raise ValueError(f"code_type {code_type_id} not found in {path}")

    before = text[: match.start()]
    unused_block = _find_block_header(before, "unused_code_types")
    code_block = _find_block_header(before, "code_types")
    if unused_block == -1 or (code_block != -1 and unused_block < code_block):
        raise ValueError(f"code_type {code_type_id} has no code_types block and is not in unused_code_types")

    label = match.group(2).strip()
    entry = (
        f'  "{code_type_id}":\n'
        f"    label: {label}\n"
        f"    column_refs:\n"
    )
    lines = text.splitlines(keepends=True)
    # 删 unused 行，在 code_types 块头后插入新条目
    del_idx = next(i for i, line in enumerate(lines) if line.rstrip("\r\n") == match.group(0))
    unused_line = lines.pop(del_idx)
    insert_idx = _find_header(lines, "code_types") + 1
    lines.insert(insert_idx, entry)
    path.write_text("".join(lines), encoding="utf-8")
    assert unused_line  # noqa: S101 - 仅为明确删除的是上面匹配的行


# ---------- 组装与落盘 ----------


def _merge_skeleton_with_answers(answers: RegistrationAnswers, skeleton: dict[str, Any]) -> dict[str, Any]:
    """骨架（物理字段）+ 答案（语义字段）→ 完整表 YAML dict。"""
    skeleton["alias"] = answers.alias
    skeleton["description"] = answers.description
    if answers.primary_key is not None:
        skeleton["primary_key"] = list(answers.primary_key)

    usage = list(answers.usage)
    if answers.granularity and answers.granularity not in usage:
        usage.insert(0, answers.granularity)
    skeleton["usage"] = usage

    notes = list(skeleton.get("notes") or [])
    notes.extend(answers.notes)
    skeleton["notes"] = notes

    for col in skeleton["columns"]:
        name = col["name"]
        desc = answers.column_descriptions.get(name, "")
        if desc:
            col["description"] = desc
        aliases = answers.column_aliases.get(name)
        if aliases:
            col["aliases"] = list(aliases)
        # Q6：new 枚举含义回填
        meanings = answers.enum_meanings.get(name)
        if meanings and isinstance(col.get("enum_values"), dict):
            col["enum_values"] = {
                v: meanings.get(v, "") for v in col["enum_values"]
            }
    return skeleton


def _graph_table_entry(answers: RegistrationAnswers, skeleton: dict[str, Any]) -> dict[str, Any]:
    role = answers.granularity or answers.description
    return {
        answers.table: {
            "alias": answers.alias,
            "layer": skeleton["layer"],
            "primary_key": list(skeleton["primary_key"]),
            "role": role[:40],
        }
    }


def _pruning_updates(
    answers: RegistrationAnswers,
    skeleton: dict[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    """A5 cue 继承：事实表登记 + 触发词条目。返回 (fact_tables 插入行, cue 条目)。"""
    fact_lines: list[str] = []
    if skeleton["layer"] in _FACT_LAYERS and answers.table:
        fact_lines = [f"  - {answers.table}\n"]

    cue_entry = None
    if answers.cue_words:
        cue_entry = {"cues": list(answers.cue_words), "table": answers.table}
    return fact_lines, cue_entry


def register_table(
    answers: RegistrationAnswers,
    *,
    metadata_dir: Path | None = None,
    con: Any = None,
    dry_run: bool = False,
    force: bool = False,
) -> RegistrationResult:
    """问卷答案 → 写入全部元数据文件（A5 落盘，A6 注册由目录扫描自动生效）。

    A4 dict 候选（值域命中 dim_public）自动同步 value_descriptors.column_refs，
    保证表 YAML code_type_id / join_graph filter / column_refs 三方一致。
    """
    from querypilot.table_ops.candidates import enum_candidates, key_candidates

    metadata_dir = metadata_dir or get_settings().metadata_dir
    tables_dir = metadata_dir / "tables"
    table_path = tables_dir / f"{answers.table}.yaml"
    graph_path = metadata_dir / "join_graph.yaml"
    pruning_path = metadata_dir / "pruning.yaml"
    value_path = metadata_dir / "value_descriptors.yaml"

    if table_path.exists() and not force and not dry_run:
        raise FileExistsError(f"{table_path} already exists (pass force=True to overwrite)")

    skeleton = build_skeleton(answers.table, con=con)

    # A4 dict 候选：值域命中 dim_public 的列 → 需要 column_refs 同步
    key_cols = {c.column for c in key_candidates(answers.table, con=con)}
    enums = enum_candidates(answers.table, con=con, key_columns=key_cols)
    dict_enums = {c.column: c.match_key for c in enums if c.kind == "dict"}

    table_yaml_dict = _merge_skeleton_with_answers(answers, skeleton)
    table_yaml = yaml.safe_dump(
        table_yaml_dict, allow_unicode=True, sort_keys=False, default_flow_style=False
    )

    graph_entry = _graph_table_entry(answers, table_yaml_dict)
    graph_insert = yaml.safe_dump(
        graph_entry, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    edge_lines: list[str] = []
    for edge in answers.join_edges:
        edge_lines.extend(_serialize_item(edge))

    fact_lines, cue_entry = _pruning_updates(answers, table_yaml_dict)
    fact_insert = f"fact_tables: + {answers.table}\n" if fact_lines else ""
    cue_insert = yaml.safe_dump([cue_entry], allow_unicode=True, sort_keys=False) if cue_entry else ""
    pruning_insert = fact_insert + cue_insert

    vd_lines: list[str] = []
    for column, code_type_id in dict_enums.items():
        vd_lines.append(f"# column_ref appended by table_ops register: {answers.table}.{column}\n")

    if dry_run:
        return RegistrationResult(
            table=answers.table,
            table_yaml_path=table_path,
            join_graph_path=graph_path,
            pruning_path=pruning_path,
            value_descriptors_path=value_path,
            table_yaml=table_yaml,
            join_graph_insert=graph_insert + "".join(edge_lines),
            pruning_insert=pruning_insert,
            value_descriptors_insert="".join(vd_lines),
            dry_run=True,
        )

    tables_dir.mkdir(parents=True, exist_ok=True)
    table_path.write_text(table_yaml, encoding="utf-8")

    _append_mapping_entry(graph_path, "tables", graph_entry)
    for edge in answers.join_edges:
        _append_list_item(graph_path, "edges", edge)
    for path in answers.paths:
        _append_mapping_entry(graph_path, "paths", path)

    if fact_lines:
        _append_list_item(pruning_path, "fact_tables", answers.table)
    if cue_entry:
        _append_list_item(pruning_path, "domain_seed_cues", cue_entry)

    for column, code_type_id in dict_enums.items():
        _append_column_ref(value_path, code_type_id, answers.table, column)

    # 元数据文件已变，进程内缓存必须失效（serve/chat 需重启或调用 clear_caches）
    from querypilot.cache.metadata_cache import clear_caches
    from querypilot.metadata_engine.pruning_config import load_pruning_config

    clear_caches()
    load_pruning_config.cache_clear()

    return RegistrationResult(
        table=answers.table,
        table_yaml_path=table_path,
        join_graph_path=graph_path,
        pruning_path=pruning_path,
        value_descriptors_path=value_path,
        table_yaml=table_yaml,
        join_graph_insert=graph_insert + "".join(edge_lines),
        pruning_insert=pruning_insert,
        value_descriptors_insert="".join(vd_lines),
        dry_run=False,
    )


# ---------- A6 注册表同步验证 ----------


def verify_registration(
    table: str,
    *,
    metadata_dir: Path | None = None,
) -> RegistrationSyncReport:
    """注册后同步检查：新表应被全部动态注册表自动接纳（目录扫描 / join_graph /
    pruning 配置 / L1 白名单 / prompt 渲染），全程零代码改动。
    """
    from querypilot.metadata_engine import discover_table_names, load_all_tables
    from querypilot.metadata_engine.bundle import load_metadata_uncached
    from querypilot.metadata_engine.join_graph_loader import load_join_graph
    from querypilot.metadata_engine.pruning_config import load_pruning_config
    from querypilot.safety.l1_ast import build_column_catalog

    metadata_dir = metadata_dir or get_settings().metadata_dir
    tables_dir = metadata_dir / "tables"
    report = RegistrationSyncReport(table=table)

    # 1. loader 目录扫描发现
    names = discover_table_names(tables_dir)
    report.checks.append(SyncCheck("loader 目录扫描发现", table in names))

    # 2. 表 YAML 可解析
    tables = load_all_tables(tables_dir)
    meta = tables.get(table)
    report.checks.append(
        SyncCheck("表 YAML 可解析", meta is not None, f"{table}.yaml 缺失或解析失败")
    )

    # 3. join_graph 注册（表 + 关联边两端齐全）
    graph = load_join_graph(metadata_dir / "join_graph.yaml")
    in_graph = table in graph.tables
    report.checks.append(SyncCheck("join_graph 表注册", in_graph, "tables 块缺该表"))
    if in_graph:
        broken = [
            e.id
            for e in graph.edges.values()
            if table in (e.from_table, e.to_table)
            and (e.from_table not in tables or e.to_table not in tables)
        ]
        report.checks.append(
            SyncCheck("join_graph 边两端均已注册", not broken, f"边 {broken} 引用未注册表")
        )

    # 4. pruning 配置可加载且身份正确（事实表应在 fact_tables）
    config = load_pruning_config(metadata_dir / "pruning.yaml")
    is_fact = meta is not None and meta.layer in _FACT_LAYERS
    if is_fact:
        report.checks.append(
            SyncCheck("pruning fact_tables 收录", table in config.fact_tables)
        )
    else:
        report.checks.append(SyncCheck("pruning 配置可加载", True))

    # 5. L1 白名单由 catalog 派生（catalog 来自表 YAML 目录扫描）
    bundle = load_metadata_uncached(
        tables_dir=tables_dir,
        join_graph_path=metadata_dir / "join_graph.yaml",
        value_config_path=metadata_dir / "value_descriptors.yaml",
        load_db_codes=False,
    )
    catalog = build_column_catalog(bundle)
    report.checks.append(
        SyncCheck("L1 表白名单收录", table in catalog, "allowlist 由目录扫描派生，不应缺失")
    )

    # 6. prompt 渲染（最终进入 LLM 的表结构片段）
    try:
        schema_text = bundle.format_table_schema(table, include_values=False)
        rendered = table in schema_text
    except KeyError:
        schema_text, rendered = "", False
    report.checks.append(SyncCheck("prompt 表结构渲染", rendered))

    return report
