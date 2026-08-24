"""A3 业务键候选 + A4 枚举候选：纯机械发现新表的关联与字典配置（logs/08 §三）。

A3 两层信号：
  1. 名字信号 —— 键注册表由 join_graph edges 动态推导（不新增维护点）
  2. 值域信号 —— DISTINCT 值集包含性验证（解决「列名同 ≠ 语义同」，如 data_dt）

置信度：同名命中 >= 0.70 high / 盲扫 >= 0.90 high / 0.30 起 medium（问卷强制确认）。
日期列（全值 YYYYMMDD）按 no_default_data_dt 约定排除出键候选。

A4 枚举候选（列值域 ↔ dim_public / static_enums 比对）：
  - dict  —— 列值集 ⊆ dim_public 某code_type 的码集 → 建议 code_type_id + lookup
  - static—— 列值集 ⊆ value_descriptors.static_enums 某枚举 → 建议 enum_ref
  - new   —— 低基数非键非日期列未命中任何字典 → enum_values 骨架，含义由人填（Q6）
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

import duckdb

from querypilot.metadata_engine.bundle import MetadataBundle

_HIGH_VALUE = 0.90  # 盲扫（值域）命中需高门槛，与撞名/撞值区分
_HIGH_NAME = 0.70  # 同名命中 + 值域验证双重信号，容忍事实表孤儿行（实测 tran 0.787 / fin 0.767）
_MEDIUM = 0.30
_BLIND_MIN_DISTINCT = 2  # 盲扫至少 2 个 distinct 值，避免常量列平凡包含

# A4 枚举候选
_ENUM_MEDIUM = 0.80  # 字典部分命中（有孤儿码）报 medium
_ENUM_MAX_DISTINCT = 20  # 「新枚举」候选的基数上限：超过则视为普通文本/数值列

# 已知日期不对齐的表：与它们 join 的边建议挂 no_default_data_dt（域知识）
_DATE_MISALIGNED_TABLES = frozenset({"ads_cust_info_d", "dim_branch"})

_DATE_RE = re.compile(r"^\d{8}$")


@dataclass(frozen=True)
class KeyTarget:
    """键注册表条目：某表的某列可作为键，关联到目标表的某列。"""

    column: str
    table: str
    target_table: str
    target_column: str
    edge_type: str = ""
    filter: dict[str, str] = field(default_factory=dict)


@dataclass
class ColumnProfile:
    """新表列画像（一次 DISTINCT 探测得到）。"""

    distinct_values: set[str]
    null_count: int
    total_rows: int

    @property
    def distinct_count(self) -> int:
        return len(self.distinct_values)

    @property
    def is_unique(self) -> bool:
        return self.distinct_count + self.null_count == self.total_rows

    @property
    def is_date(self) -> bool:
        return self.distinct_count > 0 and all(_DATE_RE.match(v) for v in self.distinct_values)


@dataclass
class KeyCandidate:
    """一条 join 边候选（含建议的 join_graph 字段）。"""

    column: str
    target_table: str
    target_column: str
    containment: float
    cardinality: str
    edge_type: str
    confidence: str  # high / medium / low
    match_type: str  # name（同名命中）/ value（值域盲扫命中）
    reason: str
    suggested_edge: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnumCandidate:
    """一条枚举/字典候选（含建议的表 YAML 列字段）。"""

    column: str
    kind: str  # dict（dim_public）/ static（static_enums）/ new（待人工填含义）
    match_key: str  # code_type_id / static枚举名 / ""
    label: str  # 字典业务名（如 性别），new 为空
    distinct_count: int
    containment: float  # 列值集对码集的包含率
    confidence: str  # high / medium
    reason: str
    value_meanings: dict[str, str]  # 值 → 含义（new 候选含义为空串，待人填）
    suggested_column: dict[str, Any] = field(default_factory=dict)


def build_key_registry(metadata: MetadataBundle | None = None) -> list[KeyTarget]:
    """从 join_graph edges 机械推导键注册表（双向，无需 DB）。"""
    if metadata is None:
        from querypilot.metadata_engine import load_metadata

        metadata = load_metadata(load_db_codes=False)

    targets: dict[tuple[str, str, str, str], KeyTarget] = {}
    for edge in metadata.join_graph.edges.values():
        for left_col, right_col in edge.join.items():
            forward = KeyTarget(
                column=left_col,
                table=edge.from_table,
                target_table=edge.to_table,
                target_column=right_col,
                edge_type=edge.edge_type,
                filter=dict(edge.filter),
            )
            backward = KeyTarget(
                column=right_col,
                table=edge.to_table,
                target_table=edge.from_table,
                target_column=left_col,
                edge_type=edge.edge_type,
                filter={},
            )
            for t in (forward, backward):
                key = (t.column, t.table, t.target_table, t.target_column)
                targets[key] = t
    return sorted(targets.values(), key=lambda t: (t.column, t.table, t.target_table))


def _profile_columns(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, ColumnProfile]:
    """每列一次 DISTINCT 探测（列数量小，开销可忽略）。"""
    cols = [
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
    ]
    if not cols:
        raise ValueError(f"table not found in database: {table}")

    total = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    profiles: dict[str, ColumnProfile] = {}
    for col in cols:
        distinct_vals = {
            str(row[0])
            for row in con.execute(
                f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL'
            ).fetchall()
        }
        null_count = con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL'
        ).fetchone()[0]
        profiles[col] = ColumnProfile(
            distinct_values=distinct_vals,
            null_count=null_count,
            total_rows=total,
        )
    return profiles


def _classify(containment: float, match_type: str = "value") -> str:
    high = _HIGH_NAME if match_type == "name" else _HIGH_VALUE
    if containment >= high:
        return "high"
    if containment >= _MEDIUM:
        return "medium"
    return "low"


def _cardinality(new_unique: bool, target_unique: bool) -> str:
    if new_unique and target_unique:
        return "1:1"
    if target_unique:
        return "N:1"
    return "M:N"


def _suggest_edge(
    table: str,
    target: KeyTarget,
    edge_type: str,
    *,
    join_key: str,
    filter_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    rules: list[str] = []
    if edge_type == "lookup":
        rules = ["dim_public_lookup"]
    elif table in _DATE_MISALIGNED_TABLES or target.target_table in _DATE_MISALIGNED_TABLES:
        rules = ["no_default_data_dt"]
    if edge_type == "lookup":
        # filter 优先用按列值集定位的 code_type（注册表模板是任意一条 lookup
        # 边的 filter，dim_public 多个字典共用 code 列，模板值会撞错字典）
        filt = dict(filter_override) if filter_override is not None else dict(target.filter)
    else:
        filt = {}
    return {
        "id": f"{table}_to_{target.target_table}",
        "from": table,
        "to": target.target_table,
        "join": {join_key: target.target_column},
        "type": edge_type,
        "rules": rules,
        "filter": filt,
    }


def key_candidates(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata: MetadataBundle | None = None,
) -> list[KeyCandidate]:
    """产出 ``table`` 的 join 边候选（纯机械，零 LLM）。"""
    from querypilot.db import get_connection

    if metadata is None:
        from querypilot.metadata_engine import load_metadata

        metadata = load_metadata(load_db_codes=False)

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        registry = build_key_registry(metadata)
        profiles = _profile_columns(con, table)

        # 目标值集 + 目标侧唯一性（每目标一次查询）
        target_sets: dict[tuple[str, str], set[str]] = {}
        target_unique: dict[tuple[str, str], bool] = {}
        for t in registry:
            key = (t.target_table, t.target_column)
            if key in target_sets:
                continue
            values = {
                str(row[0])
                for row in con.execute(
                    f'SELECT DISTINCT "{t.target_column}" FROM "{t.target_table}" '
                    f'WHERE "{t.target_column}" IS NOT NULL'
                ).fetchall()
            }
            target_sets[key] = values
            cnt, dst = con.execute(
                f'SELECT COUNT(*), COUNT(DISTINCT "{t.target_column}") FROM "{t.target_table}"'
            ).fetchone()
            target_unique[key] = cnt == dst

        # dim_public 按字典分组的码集（lookup 边 filter 定位用；无 lookup 目标则不查）
        codes_by_type: dict[str, set[str]] = {}
        if any(t.edge_type == "lookup" and t.target_table == "dim_public" for t in registry):
            for ctid, code in con.execute(
                'SELECT code_type_id, code FROM dim_public WHERE code IS NOT NULL'
            ).fetchall():
                codes_by_type.setdefault(str(ctid), set()).add(str(code))

        candidates: list[KeyCandidate] = []

        def _best_code_type(vals: set[str]) -> tuple[str, float] | None:
            """列值集对 dim_public 各字典码集的包含率最高者。"""
            best: tuple[str, float] | None = None
            if not vals:
                return best
            for ctid, codes in sorted(codes_by_type.items()):
                containment = len(vals & codes) / len(vals)
                if best is None or containment > best[1]:
                    best = (ctid, containment)
            return best

        def _probe(col: str, target: KeyTarget, match_type: str) -> KeyCandidate | None:
            profile = profiles[col]
            tkey = (target.target_table, target.target_column)
            tvals = target_sets[tkey]
            if not profile.distinct_values or not tvals:
                return None
            overlap = len(profile.distinct_values & tvals)
            containment = overlap / len(profile.distinct_values)
            if containment < _MEDIUM and match_type == "value":
                return None  # 盲扫只报 >= medium 的
            confidence = _classify(containment, match_type)
            cardinality = _cardinality(profile.is_unique, target_unique[tkey])
            # edge_type 建议：按目标表 layer 推（lookup 边保留原类型）
            if target.edge_type == "lookup":
                edge_type = "lookup"
            else:
                target_layer = metadata.tables.get(target.target_table)
                layer = target_layer.layer if target_layer else ""
                edge_type = "dimension" if layer == "dim" else "fact"
            reason = (
                f"同名键 + 值集包含率 {containment:.0%}"
                if match_type == "name"
                else f"值域盲扫命中（非同名）包含率 {containment:.0%}"
            )
            # lookup 边按列值集定位 filter.code_type_id（与 A4 字典判定同口径）
            filter_override: dict[str, str] | None = None
            if edge_type == "lookup" and target.target_table == "dim_public":
                hit = _best_code_type(profile.distinct_values)
                if hit and hit[1] >= _ENUM_MEDIUM:
                    ctid, ct_containment = hit
                    filter_override = {"code_type_id": ctid}
                    label = metadata.values.code_types.get(ctid)
                    if label is None:
                        label = metadata.values.unused_code_types.get(ctid, "")
                        label_text = f"{label}({ctid})" if label else ctid
                    else:
                        label_text = f"{label.label}({ctid})"
                    reason += f"；码值定位字典 {label_text}（包含率 {ct_containment:.0%}）"
            return KeyCandidate(
                column=col,
                target_table=target.target_table,
                target_column=target.target_column,
                containment=round(containment, 4),
                cardinality=cardinality,
                edge_type=edge_type,
                confidence=confidence,
                match_type=match_type,
                reason=reason,
                suggested_edge=_suggest_edge(
                    table, target, edge_type, join_key=col, filter_override=filter_override
                ),
            )

        # 名字命中 → 包含性验证；未命中的列做值域盲扫。
        # 注册表条目来自既有边（新表不在图中），只要列名命中即为目标模板；
        # 排除指向自身的目标，并按目标去重（同一目标可来自多条边）。
        def _dedupe_targets(targets: list[KeyTarget]) -> list[KeyTarget]:
            best: dict[tuple[str, str], KeyTarget] = {}
            for t in targets:
                key = (t.target_table, t.target_column)
                prev = best.get(key)
                # 优先保留带 filter 的 lookup 条目
                if prev is None or (t.filter and not prev.filter):
                    best[key] = t
            return sorted(best.values(), key=lambda t: (t.target_table, t.target_column))

        for col, profile in profiles.items():
            if profile.is_date:
                continue  # 日期列不作 join 键（no_default_data_dt），报告见 key_report
            named = _dedupe_targets(
                [t for t in registry if t.column == col and t.target_table != table]
            )
            if named:
                for target in named:
                    cand = _probe(col, target, "name")
                    if cand:
                        candidates.append(cand)
            elif profile.distinct_count >= _BLIND_MIN_DISTINCT:
                for target in _dedupe_targets(
                    [t for t in registry if t.target_table != table]
                ):
                    cand = _probe(col, target, "value")
                    if cand:
                        candidates.append(cand)

        order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(key=lambda c: (order[c.confidence], -c.containment, c.column))
        return candidates
    finally:
        if own_con:
            con.close()


def key_report(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata: MetadataBundle | None = None,
) -> str:
    """人类可读的候选报告（问卷 Q5 的机械底稿）。"""
    from querypilot.db import get_connection

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        profiles = _profile_columns(con, table)
        date_cols = [c for c, p in profiles.items() if p.is_date]
        candidates = key_candidates(table, con=con, metadata=metadata)
    finally:
        if own_con:
            con.close()

    lines = [f"表 {table} 键候选报告", "=" * 60]
    if date_cols:
        lines.append(f"已排除（日期列，不作 join 键）: {', '.join(date_cols)}")
    if not candidates:
        lines.append("未发现任何键候选。")
        return "\n".join(lines)
    lines.append(
        f"{'置信':6} {'列':16} {'→ 目标表.列':40} {'包含率':>7} {'基数':5} 类型/命中"
    )
    lines.append("-" * 100)
    for c in candidates:
        lines.append(
            f"{c.confidence:6} {c.column:16} → {c.target_table}.{c.target_column:22}"
            f"{c.containment:>7.0%} {c.cardinality:5} {c.edge_type}/{c.match_type}"
        )
    lines.append("")
    lines.append("建议 join_graph 边（高置信项）:")
    for c in candidates:
        if c.confidence == "high":
            rules = f", rules={c.suggested_edge['rules']}" if c.suggested_edge["rules"] else ""
            filt = f", filter={c.suggested_edge['filter']}" if c.suggested_edge["filter"] else ""
            lines.append(
                f"  - {c.suggested_edge['id']}: {table}.{c.column} → "
                f"{c.target_table}.{c.target_column} "
                f"(type={c.edge_type}{rules}{filt})"
            )
    return "\n".join(lines)


# ---------- A4 枚举候选（logs/08 §三 A4：distinct 探数 ↔ 字典值域比对） ----------


def _enum_classify(containment: float, distinct_count: int) -> str:
    """全量命中且 >= 2 个值才 high；单值平凡包含 / 孤儿码只报 medium。"""
    if containment == 1.0 and distinct_count >= 2:
        return "high"
    return "medium"


def enum_candidates(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata: MetadataBundle | None = None,
    key_columns: set[str] | None = None,
) -> list[EnumCandidate]:
    """产出 ``table`` 的枚举/字典候选（纯机械，零 LLM）。

    字典码集直接查 dim_public（不依赖 metadata 的 load_db_codes 开关）；
    标签与静态枚举来自 value_descriptors.yaml。
    ``key_columns``（A3 键候选的列）中的列不再产 "new" 枚举候选——
    键列的值域是标识符（如 mgr_id），不是待解释的枚举。
    """
    from querypilot.db import get_connection

    if metadata is None:
        from querypilot.metadata_engine import load_metadata

        metadata = load_metadata(load_db_codes=False)

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        profiles = _profile_columns(con, table)
        codes_by_type: dict[str, dict[str, str]] = {}
        for ctid, code, describe in con.execute(
            'SELECT code_type_id, code, "describe" FROM dim_public'
        ).fetchall():
            codes_by_type.setdefault(str(ctid), {})[str(code)] = str(describe)
        labels = {cid: m.label for cid, m in metadata.values.code_types.items()}
        labels.update(metadata.values.unused_code_types)
        static_enums = metadata.values.static_enums

        candidates: list[EnumCandidate] = []

        def _add(
            col: str,
            kind: str,
            match_key: str,
            label: str,
            profile: ColumnProfile,
            containment: float,
            reason: str,
            meanings: dict[str, str],
        ) -> None:
            if kind == "dict":
                suggested: dict[str, Any] = {"code_type_id": match_key, "lookup": "dim_public"}
            elif kind == "static":
                suggested = {"enum_ref": match_key}
            else:
                suggested = {"enum_values": dict(meanings)}
            candidates.append(
                EnumCandidate(
                    column=col,
                    kind=kind,
                    match_key=match_key,
                    label=label,
                    distinct_count=profile.distinct_count,
                    containment=round(containment, 4),
                    confidence=_enum_classify(containment, profile.distinct_count),
                    reason=reason,
                    value_meanings=meanings,
                    suggested_column=suggested,
                )
            )

        for col, profile in profiles.items():
            if profile.is_date or profile.is_unique or profile.distinct_count == 0:
                continue  # 日期/键/全空列不做枚举候选
            vals = profile.distinct_values

            # 1) dim_public 字典：列值集对码集的包含率
            dict_hit = False
            for ctid, codes in sorted(codes_by_type.items()):
                overlap = len(vals & codes.keys())
                containment = overlap / len(vals)
                if containment < _ENUM_MEDIUM:
                    continue
                label = labels.get(ctid, "")
                _add(
                    col,
                    "dict",
                    ctid,
                    label,
                    profile,
                    containment,
                    f"值集 {overlap}/{len(vals)} 落入 dim_public 字典 {label}({ctid})",
                    {v: codes.get(v, "") for v in sorted(vals)},
                )
                dict_hit = True
            if dict_hit:
                continue

            # 2) 静态枚举（value_descriptors.static_enums）
            static_hit = False
            for name, pairs in sorted(static_enums.items()):
                keys = set(pairs)
                overlap = len(vals & keys)
                containment = overlap / len(vals)
                if containment < _ENUM_MEDIUM:
                    continue
                _add(
                    col,
                    "static",
                    name,
                    name,
                    profile,
                    containment,
                    f"值集 {overlap}/{len(vals)} 命中静态枚举 {name}",
                    {v: pairs.get(v, "") for v in sorted(vals)},
                )
                static_hit = True
            if static_hit:
                continue

            # 3) 未命中任何字典的低基数列 → 新枚举骨架，含义由人填（问卷 Q6）
            if key_columns and col in key_columns:
                continue  # 键列（A3 候选）不是枚举
            if profile.distinct_count <= _ENUM_MAX_DISTINCT:
                meanings = {v: "" for v in sorted(vals)}
                _add(
                    col,
                    "new",
                    "",
                    "",
                    profile,
                    0.0,
                    f"低基数（{profile.distinct_count} 个值）且未命中任何字典，"
                    "需人工确认是否枚举并补含义",
                    meanings,
                )

        order = {"high": 0, "medium": 1}
        candidates.sort(key=lambda c: (order[c.confidence], c.kind, c.column))
        return candidates
    finally:
        if own_con:
            con.close()


def enum_report(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata: MetadataBundle | None = None,
    key_columns: set[str] | None = None,
) -> str:
    """人类可读的枚举候选报告（问卷 Q6 的机械底稿）。"""
    candidates = enum_candidates(table, con=con, metadata=metadata, key_columns=key_columns)

    lines = [f"表 {table} 枚举候选报告", "=" * 60]
    if not candidates:
        lines.append("未发现枚举/字典候选。")
        return "\n".join(lines)
    lines.append(f"{'置信':6} {'列':18} {'类型':7} {'字典/枚举':18} 值域")
    lines.append("-" * 100)
    for c in candidates:
        shown = ", ".join(
            f"{v}={m}" if m else v for v, m in list(c.value_meanings.items())[:6]
        )
        suffix = " ..." if len(c.value_meanings) > 6 else ""
        key = c.match_key if c.kind != "new" else "(新)"
        lines.append(
            f"{c.confidence:6} {c.column:18} {c.kind:7} {key:18} {shown}{suffix}"
        )
    lines.append("")
    lines.append("建议列配置（高置信项）:")
    for c in candidates:
        if c.confidence == "high":
            lines.append(f"  - {table}.{c.column}: {c.suggested_column}")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m querypilot.table_ops.candidates",
        description="新表登记机械候选报告（A3 键 + A4 枚举）",
    )
    parser.add_argument("table", help="表名（需已导入 DuckDB）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--keys-only", action="store_true", help="只输出键候选报告")
    group.add_argument("--enums-only", action="store_true", help="只输出枚举候选报告")
    args = parser.parse_args(argv)

    if not args.enums_only:
        print(key_report(args.table))
        print()
    if not args.keys_only:
        # 键候选列不再报 "new" 枚举（键列值域是标识符，不是待解释枚举）
        key_cols = {c.column for c in key_candidates(args.table)}
        print(enum_report(args.table, key_columns=key_cols))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
