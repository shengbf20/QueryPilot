"""Load table metadata from YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from querypilot.config import get_settings
from querypilot.metadata_engine.models import ColumnMeta, TableMeta

EXPECTED_TABLES = [
    "ads_cust_info_d",
    "dim_branch",
    "dim_product",
    "dim_public",
    "dwd_cust_hold_d",
    "dwd_cust_tran_d",
    "dws_cust_aset_d",
    "dws_cust_fin_d",
]

# Canonical column lists aligned with scripts/import_data.py
DB_COLUMNS: dict[str, list[str]] = {
    "dim_product": [
        "prdt_id", "prdt_name", "sor_prdt_id", "market_id",
        "prdt_type_id", "prdt_type_name", "up_prdt_type_id", "up_prdt_type_name",
    ],
    "ads_cust_info_d": [
        "data_dt", "pty_id", "sor_pty_id", "cust_lvl_cd", "cust_status", "cust_type",
        "prov_name", "city_name", "birth_dt", "cust_age", "name",
        "gender_cd", "edu_cd", "prof_cd", "org_id",
    ],
    "dws_cust_fin_d": [
        "data_dt", "pty_id", "sys_source", "cash_in", "cash_out",
        "tran_in", "tran_out", "assign_in", "assign_out",
    ],
    "dwd_cust_hold_d": [
        "data_dt", "pty_id", "prdt_id", "sys_source", "ccy", "hold_cnt", "mkt_val",
    ],
    "dwd_cust_tran_d": [
        "data_dt", "pty_id", "prdt_id", "sys_source", "ccy",
        "buy_cnt", "buy_mnt", "buy_rake", "buy_amt", "buy_fare",
        "sell_cnt", "sell_mnt", "sell_rake", "sell_amt", "sell_fare",
    ],
    "dws_cust_aset_d": [
        "data_dt", "pty_id", "nm_tot_aset", "nm_bal", "fc_pur_aset", "fc_bal",
    ],
    "dim_public": ["code", "code_type_id", "describe"],
    "dim_branch": [
        "data_dt", "org_id", "org_name", "up_org_id", "up_org_name",
    ],
}


def _parse_column(raw: dict) -> ColumnMeta:
    return ColumnMeta(
        name=raw["name"],
        type=raw["type"],
        description=raw["description"],
        aliases=raw.get("aliases", []),
        code_type_id=raw.get("code_type_id"),
        lookup=raw.get("lookup"),
        enum_ref=raw.get("enum_ref"),
        enum_values=raw.get("enum_values", {}),
        format=raw.get("format"),
        sql_name=raw.get("sql_name"),
    )


def _parse_table(raw: dict) -> TableMeta:
    return TableMeta(
        table=raw["table"],
        alias=raw["alias"],
        layer=raw["layer"],
        description=raw["description"],
        primary_key=raw["primary_key"],
        columns=[_parse_column(c) for c in raw["columns"]],
        usage=raw.get("usage", []),
        notes=raw.get("notes", []),
    )


def load_table_meta(path: Path) -> TableMeta:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _parse_table(raw)


def load_all_tables(tables_dir: Path | None = None) -> dict[str, TableMeta]:
    tables_dir = tables_dir or (get_settings().metadata_dir / "tables")
    result: dict[str, TableMeta] = {}
    for table_name in EXPECTED_TABLES:
        path = tables_dir / f"{table_name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Missing metadata file: {path}")
        meta = load_table_meta(path)
        if meta.table != table_name:
            raise ValueError(f"{path.name}: table field '{meta.table}' != expected '{table_name}'")
        result[table_name] = meta
    return result
