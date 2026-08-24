"""Tests for externalized pruning config (metadata/pruning.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

from querypilot.metadata_engine import (
    PruningConfig,
    SchemaPruner,
    load_metadata,
    load_pruning_config,
)


def test_load_pruning_config_defaults_match_repo_yaml():
    """仓库 pruning.yaml 覆盖内置默认值（外置搬运无行为变化的迁移检查）。

    内置默认值是外置前的历史基线；repo YAML 允许在其上追加新表知识
    （如服务经理域），因此断言超集而非全等。
    """
    config = load_pruning_config()
    builtin = PruningConfig()
    assert config.default_fallback_table == builtin.default_fallback_table
    assert config.fact_tables >= builtin.fact_tables
    assert config.org_dim_tables == builtin.org_dim_tables
    assert config.customer_cues == builtin.customer_cues
    assert config.auto_seed_blocklist == builtin.auto_seed_blocklist
    assert set(config.domain_seed_cues) >= set(builtin.domain_seed_cues)
    assert set(config.query_expansions) >= set(builtin.query_expansions)


def test_load_pruning_config_missing_file_falls_back(tmp_path: Path):
    config = load_pruning_config(tmp_path / "nonexistent.yaml")
    assert config == PruningConfig()


def test_config_drives_domain_seed_cues(tmp_path: Path):
    """外置生效性：改 YAML 的 domain_seed_cues 会改变裁剪结果。"""
    md = load_metadata(load_db_codes=False)

    # 无自定义配置时，无关问句不该选中 dim_branch
    base = SchemaPruner(md).prune("xyzabc完全无关问句12345", min_score=99.0, fallback_table="")
    assert "dim_branch" not in base.tables

    # 自定义配置：给 dim_branch 挂一个唯一触发词，同时把兜底表禁掉
    custom_path = tmp_path / "pruning.yaml"
    custom_path.write_text(
        yaml.safe_dump(
            {
                "default_fallback_table": "",
                "domain_seed_cues": [
                    {"cues": ["魔法关键词"], "table": "dim_branch"},
                ],
            }
        ),
        encoding="utf-8",
    )
    config = load_pruning_config(custom_path)
    pruner = SchemaPruner(md, pruning_config=config)
    result = pruner.prune("魔法关键词")
    assert "dim_branch" in result.tables
    # 触发词未出现时不注入
    result2 = pruner.prune("客户年龄分布")
    assert "dim_branch" not in result2.seed_tables


def test_config_drives_query_expansion(tmp_path: Path):
    """外置生效性：改 YAML 的 query_expansions 会改变 search_text。"""
    md = load_metadata(load_db_codes=False)
    custom_path = tmp_path / "pruning.yaml"
    custom_path.write_text(
        yaml.safe_dump(
            {
                "query_expansions": [
                    {"triggers": ["魔法关键词"], "terms": ["性别"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    config = load_pruning_config(custom_path)
    pruner = SchemaPruner(md, pruning_config=config)
    result = pruner.prune("魔法关键词")
    assert "性别" in result.search_text
