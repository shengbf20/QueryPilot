"""A8 onboarding 回归编排测试（A7 静态校验 + join 冒烟 + 剪枝冒烟 + 旧集回归编排）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from querypilot.config import get_settings
from querypilot.table_ops.register import register_table
from querypilot.table_ops.validate import (
    baseline_regression,
    prune_smoke,
    run_onboarding_regression,
    smoke_join_check,
)
from tests.test_table_ops_register import mgr_answers, rel_answers, _strip_sim_entries

requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(), reason="competition.duckdb not imported yet"
)

REL_SMOKE_QUESTIONS = [
    "服务经理名下有多少客户",
    "客户经理服务的客户总资产是多少",
    "各服务经理管理多少客户",
]


@pytest.fixture()
def metadata_copy(tmp_path: Path) -> Path:
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    (copy / "tables" / "dim_mgr_info.yaml").unlink()
    (copy / "tables" / "dwd_cust_mgr_rel_d.yaml").unlink()
    _strip_sim_entries(copy)
    return copy


# ---------- join 边连通冒烟 ----------


@requires_db
def test_smoke_join_counts_real_graph():
    """真实图上 sim 表每条边连通，rel↔customer 连接行数 = 300（模拟数据全量）。"""
    results = dict(((e.id, n) for e, n in smoke_join_check("dwd_cust_mgr_rel_d")))
    assert results["rel_to_customer"] == 300
    assert results["rel_to_mgr"] == 300

    mgr_results = {e.id: n for e, n in smoke_join_check("dim_mgr_info")}
    assert mgr_results["mgr_to_branch"] == 20


@requires_db
def test_smoke_join_detects_dead_edge(metadata_copy: Path):
    """构造坏边（错误 join 列语义：mgr_id 对 org_id）→ 连通数应显著小于行数。"""
    register_table(rel_answers(), metadata_dir=metadata_copy)
    register_table(mgr_answers(), metadata_dir=metadata_copy)
    graph_path = metadata_copy / "join_graph.yaml"
    graph = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
    # 覆盖 rel→mgr 边为错误键
    for e in graph["edges"]:
        if e["from"] == "dwd_cust_mgr_rel_d" and e["to"] == "dim_mgr_info":
            e["join"] = {"mgr_id": "mgr_title"}  # 语义错列
    graph_path.write_text(
        yaml.safe_dump(graph, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    results = {e.id: n for e, n in smoke_join_check("dwd_cust_mgr_rel_d", metadata_dir=metadata_copy)}
    broken = {eid: n for eid, n in results.items() if n == 0}
    assert "dwd_cust_mgr_rel_d_to_dim_mgr_info" in broken


# ---------- 剪枝冒烟 ----------


@requires_db
@pytest.mark.parametrize("question", REL_SMOKE_QUESTIONS)
def test_prune_smoke_hits_rel_table(question):
    assert prune_smoke("dwd_cust_mgr_rel_d", [question]) [question] is True


@requires_db
def test_prune_smoke_detects_missing_cue(metadata_copy: Path):
    """副本未注册 cue → 问句不命中（负例）。"""
    hits = prune_smoke(
        "dwd_cust_mgr_rel_d", ["服务经理名下有多少客户"], metadata_dir=metadata_copy
    )
    assert hits["服务经理名下有多少客户"] is False


# ---------- A7 + A8 编排 ----------


@requires_db
def test_full_regression_ok_after_registration(metadata_copy: Path):
    """A5 注册 → A7/A8 编排全绿（模拟 logs/08 DoD 的零代码闭环）。"""
    register_table(mgr_answers(), metadata_dir=metadata_copy)
    register_table(rel_answers(), metadata_dir=metadata_copy)
    report = run_onboarding_regression(
        "dwd_cust_mgr_rel_d",
        smoke_questions=REL_SMOKE_QUESTIONS,
        metadata_dir=metadata_copy,
    )
    assert report.ok, [c.name for c in report.failed]
    assert "回归通过" in report.report()


@requires_db
def test_regression_fails_on_broken_yaml(metadata_copy: Path):
    """坏列定义（YAML 有、DB 无）→ 静态/对齐检查失败。"""
    register_table(mgr_answers(), metadata_dir=metadata_copy)
    broken = metadata_copy / "tables" / "dim_mgr_info.yaml"
    raw = yaml.safe_load(broken.read_text(encoding="utf-8"))
    raw["columns"].append({"name": "ghost_col", "type": "VARCHAR", "description": "不存在的列"})
    broken.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    report = run_onboarding_regression("dim_mgr_info", metadata_dir=metadata_copy)
    assert not report.ok
    assert any(not c.ok and "对齐" in c.name for c in report.checks)


@requires_db
def test_regression_fails_on_unknown_table(metadata_copy: Path):
    report = run_onboarding_regression("no_such_table", metadata_dir=metadata_copy)
    assert not report.ok
    assert any(c.name == "表 YAML 存在" and not c.ok for c in report.checks)


# ---------- 旧集回归编排（dry-run，零 LLM） ----------


def test_baseline_regression_dry_run():
    ok, output = baseline_regression(dry_run=True)
    assert ok, output
    assert "baseline saved" in output
