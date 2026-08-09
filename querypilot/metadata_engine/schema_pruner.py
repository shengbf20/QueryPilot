"""Schema Pruner: retrieve relevant tables from a NL question and expand via Join-Graph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.metadata_engine.join_graph import JoinPlan
from querypilot.metadata_engine.metrics import metrics_for_tables
from querypilot.metadata_engine.models import ColumnMeta, TableMeta

# Soft query expansions for common marketing phrasings (trigger -> extra search terms).
_QUERY_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("女性", "男性", "男女"), ("性别",)),
    (("购买", "买过", "买了", "买入过"), ("买入", "交易")),
    (("卖过", "卖掉", "卖出过"), ("卖出", "交易")),
    (("持有",), ("持仓",)),
    (("入金", "出金", "净流入"), ("资金", "现金流入", "现金流出")),
    (("盈亏", "损益", "收益情况"), ("资金", "资产", "资金流入", "资金流出")),
    (("AUM", "净资产", "资产规模"), ("总资产", "资产")),
    (("会员", "VIP", "高净值"), ("客户等级",)),
    # Product / board / trade cues (gold Q&A 5–7 often omit the literal table aliases).
    (("交易量", "交易过", "交易额", "成交额"), ("交易", "买入", "卖出", "客户交易")),
    (("科创板", "创业板", "主板", "A股"), ("产品类型", "产品二级分类", "产品")),
    (("产品大类", "产品类型", "证券"), ("产品", "产品大类", "产品一级分类")),
)

# Domain cues → force-include tables even when keyword score is low or top_k is full.
_DOMAIN_SEED_CUES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("交易", "买入", "卖出", "买卖", "交易量", "交易额", "成交额", "客户交易"), "dwd_cust_tran_d"),
    (("持有", "持仓", "市值"), "dwd_cust_hold_d"),
    (
        (
            "产品",
            "产品大类",
            "产品类型",
            "产品二级分类",
            "产品一级分类",
            "基金",
            "证券",
            "科创板",
            "创业板",
            "主板",
            "A股",
            "持仓",
            "持有",
        ),
        "dim_product",
    ),
    (("盈亏", "损益", "入金", "出金", "净流入", "资金流入", "资金流出"), "dws_cust_fin_d"),
    (("盈亏", "损益", "收益情况"), "dws_cust_aset_d"),
)

# Dim dictionary is usually injected via value descriptors, not as a join seed.
_AUTO_SEED_BLOCKLIST = frozenset({"dim_public"})

_FACT_TABLES = frozenset(
    {
        "dws_cust_aset_d",
        "dws_cust_fin_d",
        "dwd_cust_hold_d",
        "dwd_cust_tran_d",
    }
)

_CUSTOMER_CUES = ("客户", "人群", "用户", "投资者")

_DEFAULT_FALLBACK_TABLE = "ads_cust_info_d"

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class ColumnHit:
    table: str
    column: str
    score: float
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableHit:
    table: str
    score: float
    matched_terms: tuple[str, ...] = ()
    column_hits: tuple[ColumnHit, ...] = ()


@dataclass
class PrunedSchema:
    """Pruned schema context ready for Prompt assembly."""

    question: str
    search_text: str
    seed_tables: list[str]
    tables: list[str]
    join_plan: JoinPlan
    table_hits: list[TableHit] = field(default_factory=list)
    column_hits: list[ColumnHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def format_for_prompt(
        self,
        metadata: MetadataBundle,
        *,
        include_values: bool = True,
        include_join_hints: bool = True,
    ) -> str:
        """Render pruned tables (+ join hints / rules) for the LLM."""
        parts: list[str] = []
        if include_join_hints and self.notes:
            parts.append("业务约定:\n" + "\n".join(f"- {n}" for n in self.notes))

        schema_text = metadata.format_schema_for_tables(self.tables, include_values=include_values)
        if schema_text:
            parts.append("相关表结构:\n" + schema_text)

        if include_join_hints and self.join_plan.join_clauses:
            parts.append("建议 Join:\n" + "\n".join(f"- {c}" for c in self.join_plan.join_clauses))

        return "\n\n".join(parts)


@dataclass
class _Term:
    text: str
    weight: float


@dataclass
class _IndexedTable:
    name: str
    terms: list[_Term]
    columns: dict[str, list[_Term]]


class SchemaPruner:
    """Keyword / alias retrieval + Join-Graph completion."""

    def __init__(self, metadata: MetadataBundle) -> None:
        self.metadata = metadata
        self._index = []
        for meta in metadata.tables.values():
            role = ""
            graph_table = metadata.join_graph.tables.get(meta.table)
            if graph_table is not None:
                role = graph_table.role
            self._index.append(_build_indexed_table(meta, role=role))

    def prune(
        self,
        question: str,
        *,
        top_k: int = 4,
        min_score: float = 1.5,
        expand: bool = True,
        fallback_table: str | None = _DEFAULT_FALLBACK_TABLE,
    ) -> PrunedSchema:
        """Return seed tables for ``question``, optionally expanded via Join-Graph."""
        q = question.strip()
        if not q:
            raise ValueError("question must be non-empty")

        search_text = _expand_query(q)
        table_hits = self._score_tables(search_text)
        seeds = self._select_seeds(table_hits, top_k=top_k, min_score=min_score)
        seeds = _ensure_customer_hub(seeds, search_text)
        seeds = _ensure_domain_seeds(seeds, search_text, self.metadata)

        if not seeds and fallback_table and fallback_table in self.metadata.tables:
            seeds = [fallback_table]

        if expand and seeds:
            join_plan = self.metadata.expand_tables(seeds)
            tables = list(join_plan.tables)
        else:
            join_plan = JoinPlan(tables=list(seeds), edges=[], join_clauses=[])
            tables = list(seeds)

        column_hits = [ch for th in table_hits for ch in th.column_hits if th.table in set(tables)]
        notes = _collect_notes(self.metadata, tables)

        return PrunedSchema(
            question=q,
            search_text=search_text,
            seed_tables=seeds,
            tables=tables,
            join_plan=join_plan,
            table_hits=[th for th in table_hits if th.table in set(tables) or th.table in set(seeds)],
            column_hits=column_hits,
            notes=notes,
        )

    def _score_tables(self, search_text: str) -> list[TableHit]:
        hits: list[TableHit] = []
        for indexed in self._index:
            table_score = 0.0
            matched: list[str] = []
            for term in indexed.terms:
                gain = _phrase_score(search_text, term.text) * term.weight
                if gain > 0:
                    table_score += gain
                    matched.append(term.text)

            column_hits: list[ColumnHit] = []
            for col_name, terms in indexed.columns.items():
                col_score = 0.0
                col_matched: list[str] = []
                for term in terms:
                    gain = _phrase_score(search_text, term.text) * term.weight
                    if gain > 0:
                        col_score += gain
                        col_matched.append(term.text)
                if col_score > 0:
                    column_hits.append(
                        ColumnHit(
                            table=indexed.name,
                            column=col_name,
                            score=round(col_score, 4),
                            matched_terms=tuple(dict.fromkeys(col_matched)),
                        )
                    )
                    table_score += col_score

            column_hits.sort(key=lambda h: h.score, reverse=True)
            hits.append(
                TableHit(
                    table=indexed.name,
                    score=round(table_score, 4),
                    matched_terms=tuple(dict.fromkeys(matched)),
                    column_hits=tuple(column_hits),
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    def _select_seeds(
        self,
        table_hits: list[TableHit],
        *,
        top_k: int,
        min_score: float,
    ) -> list[str]:
        seeds: list[str] = []
        for hit in table_hits:
            if hit.table in _AUTO_SEED_BLOCKLIST:
                # Only keep dim_public when the table itself is strongly mentioned.
                if hit.score < max(min_score * 2, 4.0) and not any(
                    t in {"公共维表", "dim_public"} for t in hit.matched_terms
                ):
                    continue
            if hit.score < min_score:
                continue
            seeds.append(hit.table)
            if len(seeds) >= top_k:
                break
        return seeds


def prune_schema(
    question: str,
    metadata: MetadataBundle | None = None,
    **kwargs: object,
) -> PrunedSchema:
    """Convenience wrapper: load metadata if needed, then prune (cached by default)."""
    from querypilot.cache.metadata_cache import get_pruned_schema

    md = metadata or __load_metadata_lazy()
    return get_pruned_schema(question, md, **kwargs)  # type: ignore[arg-type]


def __load_metadata_lazy() -> MetadataBundle:
    from querypilot.metadata_engine.bundle import load_metadata

    return load_metadata(load_db_codes=False)


def _build_indexed_table(meta: TableMeta, *, role: str = "") -> _IndexedTable:
    terms: list[_Term] = [
        _Term(meta.table, 5.0),
        _Term(meta.alias, 5.0),
    ]
    for stem in _alias_stems(meta.alias):
        terms.append(_Term(stem, 3.0))
    if role:
        for chunk in _split_phrases(role):
            terms.append(_Term(chunk, 2.5))
    for usage in meta.usage:
        for chunk in _split_phrases(usage):
            terms.append(_Term(chunk, 2.0))
    for chunk in _split_phrases(meta.description):
        if len(chunk) >= 2:
            terms.append(_Term(chunk, 1.2))

    columns: dict[str, list[_Term]] = {}
    for col in meta.columns:
        columns[col.name] = _column_terms(col)

    return _IndexedTable(name=meta.table, terms=_dedupe_terms(terms), columns=columns)


def _alias_stems(alias: str) -> list[str]:
    """Index alias without trailing「表」, e.g. 客户信息表 -> 客户信息."""
    if alias.endswith("表") and len(alias) > 1:
        return [alias[:-1]]
    return []


def _ensure_customer_hub(seeds: list[str], search_text: str) -> list[str]:
    """If a fact table is selected and the question talks about customers, keep the hub table."""
    if "ads_cust_info_d" in seeds:
        return seeds
    mentions_customer = any(cue in search_text for cue in _CUSTOMER_CUES)
    has_fact = any(name in _FACT_TABLES for name in seeds)
    if mentions_customer and has_fact:
        return ["ads_cust_info_d", *seeds]
    return seeds


def _ensure_domain_seeds(
    seeds: list[str],
    search_text: str,
    metadata: MetadataBundle,
) -> list[str]:
    """Append domain-required tables beyond top_k when NL cues match.

    Fixes gold cases where product/trade tables score 0 (named securities / boards)
    or fall just below the seed cutoff while higher-scoring hubs fill top_k.
    """
    out = list(seeds)
    for cues, table in _DOMAIN_SEED_CUES:
        if table in out or table not in metadata.tables:
            continue
        if any(cue in search_text for cue in cues):
            out.append(table)
    return out


def _column_terms(col: ColumnMeta) -> list[_Term]:
    terms: list[_Term] = [
        _Term(col.name, 3.5),
        _Term(col.description, 2.0) if len(col.description) <= 12 else _Term(col.description[:12], 1.0),
    ]
    for alias in col.aliases:
        terms.append(_Term(alias, 4.0))
    for chunk in _split_phrases(col.description):
        if 2 <= len(chunk) <= 8:
            terms.append(_Term(chunk, 1.5))
    return _dedupe_terms(terms)


def _dedupe_terms(terms: list[_Term]) -> list[_Term]:
    best: dict[str, _Term] = {}
    for term in terms:
        key = term.text.strip().lower()
        if len(key) < 2:
            continue
        prev = best.get(key)
        if prev is None or term.weight > prev.weight:
            best[key] = _Term(term.text.strip(), term.weight)
    return list(best.values())


def _split_phrases(text: str) -> list[str]:
    parts = re.split(r"[，,。；;、/\s]+", text.strip())
    return [p for p in parts if p]


def _expand_query(question: str) -> str:
    extra: list[str] = []
    for triggers, terms in _QUERY_EXPANSIONS:
        if any(t in question for t in triggers):
            extra.extend(terms)
    if not extra:
        return question
    return question + " " + " ".join(dict.fromkeys(extra))


def _phrase_score(text: str, phrase: str) -> float:
    """Score a phrase hit inside ``text`` (case-insensitive; CJK substring)."""
    p = phrase.strip()
    if len(p) < 2:
        return 0.0

    lower_text = text.lower()
    lower_phrase = p.lower()

    if lower_phrase in lower_text:
        # Prefer longer, more specific phrases.
        return 1.0 + min(len(p), 10) / 10.0

    # Light token overlap for English / snake_case identifiers.
    if _TOKEN_RE.fullmatch(p):
        tokens = set(_TOKEN_RE.findall(lower_text))
        if lower_phrase in tokens:
            return 1.2
        # partial token: aset in asset-like queries already handled by aliases

    # CJK bigram soft match for longer descriptions (weak signal).
    cjk = _CJK_RE.findall(p)
    if len(p) >= 4 and cjk:
        bigrams = {p[i : i + 2] for i in range(len(p) - 1)}
        hits = sum(1 for bg in bigrams if bg in text)
        if hits >= max(2, len(bigrams) // 2):
            return 0.35 * hits / max(len(bigrams), 1)

    return 0.0


def _collect_notes(metadata: MetadataBundle, tables: list[str]) -> list[str]:
    notes: list[str] = []
    for rule in metadata.join_graph.rules.values():
        notes.append(rule.description)

    seen: set[str] = set()
    for name in tables:
        meta = metadata.tables.get(name)
        if meta is None:
            continue
        for note in meta.notes:
            if note not in seen:
                notes.append(note)
                seen.add(note)

    for metric in metrics_for_tables(getattr(metadata, "metrics", []) or [], tables):
        line = metric.format_for_prompt()
        if line not in seen:
            notes.append(line)
            seen.add(line)
    return notes
