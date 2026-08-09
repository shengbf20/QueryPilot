"""Reproduce Extra2 P0/P1 failure preconditions (no LLM). Writes debug-5750a4.log via prune/format."""

from __future__ import annotations

import json
import time
from pathlib import Path

from querypilot.metadata_engine import SchemaPruner, load_metadata
from querypilot.metadata_engine.loader import EXPECTED_TABLES
from querypilot.safety.l1_ast import guard_sql

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "debug-5750a4.log"


def _log(hid: str, loc: str, msg: str, data: dict) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "sessionId": "5750a4",
                    "hypothesisId": hid,
                    "location": loc,
                    "message": msg,
                    "data": data,
                    "timestamp": int(time.time() * 1000),
                    "runId": "pre-fix",
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def main() -> None:
    md = load_metadata(load_db_codes=False)
    pruner = SchemaPruner(md)

    q_fe09 = "所属分公司为南京分公司的客户有多少人？"
    pruned = pruner.prune(q_fe09)
    allowed = list(pruned.tables)
    pred = (
        "SELECT COUNT(*) AS cnt FROM ads_cust_info_d AS c "
        "INNER JOIN dim_branch AS b ON c.org_id = b.org_id "
        "WHERE b.up_org_name = '南京分公司'"
    )
    l1 = guard_sql(pred, metadata=md, allowed_tables=allowed)
    _log(
        "H2",
        "_debug_repro_p0p1.py:FE09",
        "FE09 L1 with pruned allowlist",
        {
            "tables": allowed,
            "l1_ok": l1.ok,
            "violations": [v.message for v in l1.violations],
            "full_catalog_would_allow": "ads_cust_info_d" in EXPECTED_TABLES,
        },
    )

    q_fe01 = "个人客户一共有多少人？"
    schema = md.format_table_schema("ads_cust_info_d", include_values=True)
    has_p = "P=" in schema or "P:" in schema or "'P'" in schema or "个人客户" in schema
    # check if enum line under cust_type contains P
    cust_block = ""
    for i, line in enumerate(schema.splitlines()):
        if "cust_type" in line:
            cust_block = "\n".join(schema.splitlines()[i : i + 3])
            break
    _log(
        "H3",
        "_debug_repro_p0p1.py:FE01",
        "FE01 cust_type in rendered schema",
        {
            "cust_block": cust_block,
            "schema_mentions_personal": "个人客户" in schema,
            "schema_mentions_P_code": "P=" in schema or "P:" in schema,
        },
    )

    # H4 metadata vs gold
    fin = md.tables["dws_cust_fin_d"]
    cols = {c.name: c.description for c in fin.columns}
    _log(
        "H4",
        "_debug_repro_p0p1.py:FM08",
        "FM08 column descriptions",
        {"tran_in": cols.get("tran_in"), "assign_in": cols.get("assign_in")},
    )

    # H5 fare aliases
    tran = md.tables["dwd_cust_tran_d"]
    fare = next(c for c in tran.columns if c.name == "buy_fare")
    rake = next(c for c in tran.columns if c.name == "buy_rake")
    _log(
        "H5",
        "_debug_repro_p0p1.py:FM05",
        "fare/rake aliases",
        {
            "buy_fare_aliases": list(fare.aliases),
            "buy_fare_desc": fare.description,
            "buy_rake_aliases": list(rake.aliases),
            "buy_rake_desc": rake.description,
        },
    )
    print("repro done ->", LOG)


if __name__ == "__main__":
    main()
