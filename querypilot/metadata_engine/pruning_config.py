"""Pruning knowledge config, externalized to metadata/pruning.yaml.

只承载「领域知识」（表身份 / 触发词 / 同义词）；
裁剪机制仍在 schema_pruner.py。文件缺失时回退到与历史硬编码一致的默认值。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from querypilot.config import get_settings

# 以下默认值与外置前的 schema_pruner.py 硬编码常量逐字一致，仅作文件缺失时的兜底。
_DEFAULT_FALLBACK_TABLE = "ads_cust_info_d"
_DEFAULT_FACT_TABLES = ("dws_cust_aset_d", "dws_cust_fin_d", "dwd_cust_hold_d", "dwd_cust_tran_d")
_DEFAULT_ORG_DIM_TABLES = ("dim_branch",)
_DEFAULT_CUSTOMER_CUES = ("客户", "人群", "用户", "投资者")
_DEFAULT_AUTO_SEED_BLOCKLIST = ("dim_public",)
_DEFAULT_DOMAIN_SEED_CUES: tuple[tuple[tuple[str, ...], str], ...] = (
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
_DEFAULT_QUERY_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("女性", "男性", "男女"), ("性别",)),
    (("购买", "买过", "买了", "买入过"), ("买入", "交易")),
    (("卖过", "卖掉", "卖出过"), ("卖出", "交易")),
    (("持有",), ("持仓",)),
    (("入金", "出金", "净流入"), ("资金", "现金流入", "现金流出")),
    (("盈亏", "损益", "收益情况"), ("资金", "资产", "资金流入", "资金流出")),
    (("AUM", "净资产", "资产规模"), ("总资产", "资产")),
    (("会员", "VIP", "高净值"), ("客户等级",)),
    (("交易量", "交易过", "交易额", "成交额"), ("交易", "买入", "卖出", "客户交易")),
    (("科创板", "创业板", "主板", "A股"), ("产品类型", "产品二级分类", "产品")),
    (("产品大类", "产品类型", "证券"), ("产品", "产品大类", "产品一级分类")),
)


@dataclass(frozen=True)
class PruningConfig:
    """裁剪领域知识（表身份 / 触发词 / 同义词）。"""

    default_fallback_table: str = _DEFAULT_FALLBACK_TABLE
    fact_tables: frozenset[str] = frozenset(_DEFAULT_FACT_TABLES)
    org_dim_tables: frozenset[str] = frozenset(_DEFAULT_ORG_DIM_TABLES)
    customer_cues: tuple[str, ...] = _DEFAULT_CUSTOMER_CUES
    auto_seed_blocklist: frozenset[str] = frozenset(_DEFAULT_AUTO_SEED_BLOCKLIST)
    domain_seed_cues: tuple[tuple[tuple[str, ...], str], ...] = _DEFAULT_DOMAIN_SEED_CUES
    query_expansions: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = _DEFAULT_QUERY_EXPANSIONS


@lru_cache(maxsize=8)
def load_pruning_config(path: Path | None = None) -> PruningConfig:
    """读取 metadata/pruning.yaml；缺失或为空时返回内置默认值。"""
    path = path or (get_settings().metadata_dir / "pruning.yaml")
    if not path.exists():
        return PruningConfig()

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    domain_seed_cues: list[tuple[tuple[str, ...], str]] = []
    for item in raw.get("domain_seed_cues") or []:
        domain_seed_cues.append((tuple(item["cues"]), str(item["table"])))

    query_expansions: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for item in raw.get("query_expansions") or []:
        query_expansions.append((tuple(item["triggers"]), tuple(item["terms"])))

    return PruningConfig(
        default_fallback_table=str(raw.get("default_fallback_table", _DEFAULT_FALLBACK_TABLE)),
        fact_tables=frozenset(str(t) for t in raw.get("fact_tables") or _DEFAULT_FACT_TABLES),
        org_dim_tables=frozenset(str(t) for t in raw.get("org_dim_tables") or _DEFAULT_ORG_DIM_TABLES),
        customer_cues=tuple(str(c) for c in raw.get("customer_cues") or _DEFAULT_CUSTOMER_CUES),
        auto_seed_blocklist=frozenset(
            str(t) for t in raw.get("auto_seed_blocklist") or _DEFAULT_AUTO_SEED_BLOCKLIST
        ),
        domain_seed_cues=tuple(domain_seed_cues) or _DEFAULT_DOMAIN_SEED_CUES,
        query_expansions=tuple(query_expansions) or _DEFAULT_QUERY_EXPANSIONS,
    )
