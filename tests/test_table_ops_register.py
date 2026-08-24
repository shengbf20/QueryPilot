"""A5 注册落盘测试：问卷答案 → 元数据文件，逆向对照 0da90af 手写事实。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from querypilot.config import get_settings
from querypilot.metadata_engine import load_all_tables
from querypilot.metadata_engine.join_graph_loader import load_join_graph
from querypilot.metadata_engine.pruning_config import load_pruning_config
from querypilot.table_ops.register import (
    RegistrationAnswers,
    _append_column_ref,
    register_table,
)

requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(), reason="competition.duckdb not imported yet"
)


@pytest.fixture()
def metadata_copy(tmp_path: Path) -> Path:
    """真实 metadata/ 的副本（含手写 sim 表，先删掉待重注册的两张）。"""
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    (copy / "tables" / "dim_mgr_info.yaml").unlink()
    (copy / "tables" / "dwd_cust_mgr_rel_d.yaml").unlink()
    # 从 join_graph / pruning / value_descriptors 中移除手写 sim 条目，模拟「新表未注册」
    _strip_sim_entries(copy)
    return copy


def _strip_sim_entries(copy: Path) -> None:
    """从副本的既有文件里抹掉手写 sim 注册痕迹（模拟接入前状态）。"""
    # join_graph：删 tables 条目 + 3 条边 + 2 条 path（文本级重写为解析-重排太重，
    # 直接用 yaml round-trip：本文件无关键注释依赖）
    graph_path = copy / "join_graph.yaml"
    graph = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
    for name in ("dim_mgr_info", "dwd_cust_mgr_rel_d"):
        graph["tables"].pop(name, None)
    graph["edges"] = [
        e for e in graph["edges"] if e["from"] not in ("dim_mgr_info", "dwd_cust_mgr_rel_d")
        and e["to"] not in ("dim_mgr_info", "dwd_cust_mgr_rel_d")
    ]
    graph["paths"] = {
        pid: p
        for pid, p in graph["paths"].items()
        if "dim_mgr_info" not in p["tables"] and "dwd_cust_mgr_rel_d" not in p["tables"]
    }
    graph_path.write_text(
        yaml.safe_dump(graph, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    pruning_path = copy / "pruning.yaml"
    pruning = yaml.safe_load(pruning_path.read_text(encoding="utf-8"))
    pruning["fact_tables"] = [t for t in pruning["fact_tables"] if t != "dwd_cust_mgr_rel_d"]
    pruning["domain_seed_cues"] = [
        c for c in pruning["domain_seed_cues"] if c["table"] not in ("dim_mgr_info", "dwd_cust_mgr_rel_d")
    ]
    pruning_path.write_text(
        yaml.safe_dump(pruning, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


# ---------- 问卷答案（= 0da90af 人类当时手写进 YAML 的语义知识） ----------


def mgr_answers() -> RegistrationAnswers:
    return RegistrationAnswers(
        table="dim_mgr_info",
        alias="服务经理信息表",
        description="服务经理基础信息（归属营业部、职级），用于按经理维度分析。",
        domain="服务经理",
        granularity="经理级",
        column_descriptions={
            "mgr_id": "服务经理ID",
            "mgr_name": "服务经理姓名",
            "org_id": "归属营业部ID",
            "mgr_title": "职级",
        },
        join_edges=[
            {
                "id": "dim_mgr_info_to_dim_branch",
                "from": "dim_mgr_info",
                "to": "dim_branch",
                "type": "dimension",
                "join": {"org_id": "org_id"},
                "rules": ["no_default_data_dt"],
            }
        ],
        enum_meanings={"mgr_title": {"VP": "副总裁级", "高级经理": "高级经理", "经理": "经理"}},
        usage=["按经理维度圈选与分析"],
        cue_words=["服务经理", "客户经理", "经理"],
    )


def rel_answers() -> RegistrationAnswers:
    return RegistrationAnswers(
        table="dwd_cust_mgr_rel_d",
        alias="客户服务关系表",
        description="客户与服务经理的服务关系（快照日全量）。",
        domain="服务经理",
        granularity="客户级",
        column_descriptions={
            "data_dt": "日期",
            "pty_id": "客户号",
            "mgr_id": "服务经理ID",
        },
        join_edges=[
            {
                "id": "dwd_cust_mgr_rel_d_to_ads_cust_info_d",
                "from": "dwd_cust_mgr_rel_d",
                "to": "ads_cust_info_d",
                "type": "fact",
                "join": {"pty_id": "pty_id"},
                "rules": ["no_default_data_dt"],
            },
            {
                "id": "dwd_cust_mgr_rel_d_to_dim_mgr_info",
                "from": "dwd_cust_mgr_rel_d",
                "to": "dim_mgr_info",
                "type": "dimension",
                "join": {"mgr_id": "mgr_id"},
            },
        ],
        usage=["客户与服务经理关系圈选"],
        cue_words=["服务关系", "名下客户", "服务经理", "客户经理"],
    )


# ---------- 端到端：重注册 sim 域，对照手写事实 ----------


@requires_db
class TestReregisterSimDomain:
    def test_mgr_table_registered(self, metadata_copy: Path):
        register_table(mgr_answers(), metadata_dir=metadata_copy)

        meta = load_all_tables(metadata_copy / "tables")["dim_mgr_info"]
        assert meta.alias == "服务经理信息表"
        assert meta.layer == "dim"
        assert list(meta.primary_key) == ["mgr_id"]
        by_name = {c.name: c for c in meta.columns}
        assert by_name["mgr_id"].description == "服务经理ID"
        assert by_name["mgr_title"].enum_values["VP"] == "副总裁级"
        assert by_name["org_id"].description == "归属营业部ID"

    def test_mgr_edge_and_cue_registered(self, metadata_copy: Path):
        register_table(mgr_answers(), metadata_dir=metadata_copy)

        graph = load_join_graph(metadata_copy / "join_graph.yaml")
        assert "dim_mgr_info" in graph.tables
        assert graph.tables["dim_mgr_info"].alias == "服务经理信息表"
        edges = [
            e for e in graph.edges.values()
            if e.from_table == "dim_mgr_info" or e.to_table == "dim_mgr_info"
        ]
        assert any(e.join == {"org_id": "org_id"} for e in edges)

        # A5 cue 继承：触发词 → 强制补表
        config = load_pruning_config(metadata_copy / "pruning.yaml")
        assert any(
            table == "dim_mgr_info"
            for cues, table in config.domain_seed_cues
            if "服务经理" in cues
        )
        # dim 层不进 fact_tables
        assert "dim_mgr_info" not in config.fact_tables

    def test_rel_table_fact_and_cue(self, metadata_copy: Path):
        register_table(rel_answers(), metadata_dir=metadata_copy)

        meta = load_all_tables(metadata_copy / "tables")["dwd_cust_mgr_rel_d"]
        assert meta.alias == "客户服务关系表"
        assert meta.layer == "dwd"

        graph = load_join_graph(metadata_copy / "join_graph.yaml")
        assert "dwd_cust_mgr_rel_d" in graph.tables
        joins = [
            dict(e.join)
            for e in graph.edges.values()
            if e.from_table == "dwd_cust_mgr_rel_d"
        ]
        assert {"pty_id": "pty_id"} in joins
        assert {"mgr_id": "mgr_id"} in joins

        # A5 cue 继承：dwd 事实表 → fact_tables + 客户枢纽注入生效
        config = load_pruning_config(metadata_copy / "pruning.yaml")
        assert "dwd_cust_mgr_rel_d" in config.fact_tables
        assert any(
            table == "dwd_cust_mgr_rel_d"
            for cues, table in config.domain_seed_cues
            if "服务关系" in cues
        )

    def test_registered_yaml_is_loader_parseable_and_valid(self, metadata_copy: Path):
        """两张表重注册后，副本整体可被 loader 解析（校验由 A7 负责）。"""
        register_table(mgr_answers(), metadata_dir=metadata_copy)
        register_table(rel_answers(), metadata_dir=metadata_copy)

        tables = load_all_tables(metadata_copy / "tables")
        assert {"dim_mgr_info", "dwd_cust_mgr_rel_d"} <= set(tables)
        graph = load_join_graph(metadata_copy / "join_graph.yaml")
        assert {"dim_mgr_info", "dwd_cust_mgr_rel_d"} <= set(graph.tables)

    def test_original_metadata_untouched(self, metadata_copy: Path):
        """只写副本，真实 metadata/ 不被改动。"""
        register_table(mgr_answers(), metadata_dir=metadata_copy)
        real = load_all_tables()
        assert real["dim_mgr_info"].alias == "服务经理信息表"  # 手写版仍在
        assert not (get_settings().metadata_dir / "tables" / "test_extra.yaml").exists()


# ---------- 安全性与 dry_run ----------


@requires_db
def test_refuse_overwrite_without_force(tmp_path: Path):
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    answers = mgr_answers()
    with pytest.raises(FileExistsError):
        register_table(answers, metadata_dir=copy)


@requires_db
def test_dry_run_writes_nothing(tmp_path: Path):
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    _strip_sim_entries(copy)
    (copy / "tables" / "dim_mgr_info.yaml").unlink()

    result = register_table(mgr_answers(), metadata_dir=copy, dry_run=True)
    assert result.dry_run
    assert "服务经理信息表" in result.table_yaml
    assert "dim_mgr_info" in result.pruning_insert
    assert not (copy / "tables" / "dim_mgr_info.yaml").exists()


# ---------- 文本插入辅助（保注释） ----------


def test_insert_preserves_comments(tmp_path: Path):
    p = tmp_path / "pruning.yaml"
    p.write_text(
        "# 顶部注释\nfact_tables:\n  - a\n\n# 触发词\ndomain_seed_cues: []\n",
        encoding="utf-8",
    )
    from querypilot.table_ops.register import _append_list_item

    _append_list_item(p, "fact_tables", "new_table")
    text = p.read_text(encoding="utf-8")
    assert "# 顶部注释" in text
    assert yaml.safe_load(text)["fact_tables"] == ["new_table", "a"]


def test_insert_adapts_to_zero_indent_lists(tmp_path: Path):
    """round-trip dump 出的 0 缩进列表也能插入（缩进自适应）。"""
    p = tmp_path / "g.yaml"
    p.write_text("edges:\n- id: a\n  to: t\n", encoding="utf-8")
    from querypilot.table_ops.register import _append_list_item

    _append_list_item(p, "edges", {"id": "b", "to": "u"})
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["edges"] == [{"id": "b", "to": "u"}, {"id": "a", "to": "t"}]


def test_append_column_ref(tmp_path: Path):
    p = tmp_path / "value_descriptors.yaml"
    shutil.copy(get_settings().metadata_dir / "value_descriptors.yaml", p)
    _append_column_ref(p, "600", "new_table", "edu_level_cd")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    refs = raw["code_types"]["600"]["column_refs"]
    assert {"table": "new_table", "column": "edu_level_cd"} in refs
    # 既有引用不动
    assert {"table": "ads_cust_info_d", "column": "edu_cd"} in refs


def test_append_column_ref_missing_block_raises(tmp_path: Path):
    p = tmp_path / "vd.yaml"
    p.write_text('code_types:\n  "999":\n    label: 无引用块\n', encoding="utf-8")
    with pytest.raises(ValueError, match="column_refs not found"):
        _append_column_ref(p, "999", "t", "c")


# ---------- A6 注册表同步验证 ----------


from querypilot.table_ops.register import verify_registration  # noqa: E402


@requires_db
@pytest.mark.parametrize("table", ["dim_mgr_info", "dwd_cust_mgr_rel_d"])
def test_sync_report_ok_on_real_metadata(table):
    """逆向验证：手写注册的 sim 表在真实元数据上全项同步。"""
    report = verify_registration(table)
    assert report.ok, [c.name for c in report.failed]


@requires_db
def test_sync_report_fails_before_registration(metadata_copy: Path):
    """未注册状态：loader / join_graph / L1 白名单均不收录。"""
    report = verify_registration("dim_mgr_info", metadata_dir=metadata_copy)
    assert not report.ok
    failed_names = {c.name for c in report.failed}
    assert "loader 目录扫描发现" in failed_names
    assert "join_graph 表注册" in failed_names
    assert "L1 表白名单收录" in failed_names


@requires_db
def test_sync_report_ok_after_registration(metadata_copy: Path):
    """A5 落盘 → A6 全项同步（零代码改动闭环）。"""
    register_table(mgr_answers(), metadata_dir=metadata_copy)
    register_table(rel_answers(), metadata_dir=metadata_copy)
    for table in ("dim_mgr_info", "dwd_cust_mgr_rel_d"):
        report = verify_registration(table, metadata_dir=metadata_copy)
        assert report.ok, [c.name for c in report.failed]
        assert "全部同步生效" in report.report()


def test_sync_report_unknown_table(tmp_path: Path):
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    report = verify_registration("no_such_table", metadata_dir=copy)
    assert not report.ok
    assert report.failed[0].name == "loader 目录扫描发现"
