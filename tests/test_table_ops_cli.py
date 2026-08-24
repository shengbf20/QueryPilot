"""A9 问卷生成 + 登记 CLI 测试（机械问卷 / LLM 翻译降级 / CLI 编排）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from querypilot.config import get_settings
from querypilot.table_ops.prompts import (
    format_questionnaire,
    generate_questionnaire,
    mechanical_questionnaire,
)
from tests.test_table_ops_register import _strip_sim_entries

requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(), reason="competition.duckdb not imported yet"
)


# ---------- 机械问卷（零 LLM 底稿） ----------


@requires_db
def test_mechanical_questionnaire_structure():
    q = mechanical_questionnaire("dwd_cust_mgr_rel_d")
    assert [item["id"] for item in q["questions"]] == [f"Q{i}" for i in range(1, 8)]
    by_id = {item["id"]: item for item in q["questions"]}
    # Q4 覆盖全部列
    assert {i["column"] for i in by_id["Q4"]["items"]} == {"data_dt", "pty_id", "mgr_id"}
    # Q5 含两侧 high 候选（键注册表 + 值域验证）
    targets = {i["target"] for i in by_id["Q5"]["items"]}
    assert "ads_cust_info_d.pty_id" in targets
    assert "dim_mgr_info.mgr_id" in targets
    # Q7 默认答案带快照口径
    assert "20260531" in by_id["Q7"]["default"]


@requires_db
def test_mechanical_questionnaire_enum_items():
    q = mechanical_questionnaire("dim_mgr_info")
    by_id = {item["id"]: item for item in q["questions"]}
    enums = {i["column"]: i for i in by_id["Q6"]["items"]}
    assert "mgr_title" in enums  # A4 new 枚举骨架
    assert set(enums["mgr_title"]["values"]) == {"VP", "高级经理", "经理"}


@requires_db
def test_format_questionnaire_text():
    text = format_questionnaire(mechanical_questionnaire("dwd_cust_mgr_rel_d"))
    for marker in ("Q1.", "Q2.", "Q3.", "Q4.", "Q5.", "Q6.", "Q7.", "pty_id → ads_cust_info_d"):
        assert marker in text


# ---------- LLM 翻译（出错无害：降级机械问卷） ----------


class _FakeClient:
    pass


@pytest.fixture()
def llm_chat_module(monkeypatch):
    """querypilot.llm.chat 模块（包属性 chat 是同名函数，须经 sys.modules 取模块）。"""
    import sys

    mod = sys.modules.get("querypilot.llm.chat")
    if mod is None:
        import importlib

        mod = importlib.import_module("querypilot.llm.chat")
    return mod


@requires_db
def test_llm_translation_overrides_question_text(monkeypatch, llm_chat_module):
    """LLM 只翻译 question/default 文本；机械候选（Q4/Q5 items）原样保留。"""

    def fake_generate_json(prompt, *, system=None, client=None, **kwargs):
        assert "dwd_cust_mgr_rel_d" in prompt
        assert "Q5" in prompt  # 机械候选进了 prompt
        return {
            "questions": [
                {"id": "Q1", "question": "这张表是干嘛用的？", "default": "客户和经理的对应关系"},
                {"id": "Q2", "question": "属于哪块业务？"},
            ]
        }

    monkeypatch.setattr(llm_chat_module, "generate_json", fake_generate_json)
    q = generate_questionnaire("dwd_cust_mgr_rel_d", client=_FakeClient())
    by_id = {item["id"]: item for item in q["questions"]}
    assert by_id["Q1"]["question"] == "这张表是干嘛用的？"
    assert by_id["Q1"]["default"] == "客户和经理的对应关系"
    # 机械候选不受 LLM 输出影响
    assert "ads_cust_info_d.pty_id" in {i["target"] for i in by_id["Q5"]["items"]}


@requires_db
def test_llm_failure_falls_back_to_mechanical(monkeypatch, llm_chat_module):
    def broken(prompt, *, system=None, client=None, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(llm_chat_module, "generate_json", broken)
    q = generate_questionnaire("dwd_cust_mgr_rel_d", client=_FakeClient())
    mechanical = mechanical_questionnaire("dwd_cust_mgr_rel_d")
    assert q == mechanical


@requires_db
def test_llm_invalid_output_falls_back(monkeypatch, llm_chat_module):
    def bad_json(prompt, *, system=None, client=None, **kwargs):
        return {"unexpected": []}

    monkeypatch.setattr(llm_chat_module, "generate_json", bad_json)
    q = generate_questionnaire("dwd_cust_mgr_rel_d", client=_FakeClient())
    assert [i["id"] for i in q["questions"]] == [f"Q{i}" for i in range(1, 8)]


# ---------- CLI ----------


@requires_db
def test_cli_questionnaire_subprocess():
    proc = subprocess.run(
        [sys.executable, "-m", "querypilot.table_ops.cli", "questionnaire", "dim_mgr_info"],
        capture_output=True,
        encoding="utf-8",
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    for marker in ("Q1.", "Q7.", "mgr_title"):
        assert marker in proc.stdout


@requires_db
def test_cli_register_dry_run(tmp_path: Path):
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    (copy / "tables" / "dim_mgr_info.yaml").unlink()
    _strip_sim_entries(copy)

    from querypilot.table_ops.cli import main

    code = main(
        [
            "register",
            "dim_mgr_info",
            "--metadata-dir",
            str(copy),
            "--yes",
            "--dry-run",
            "--alias",
            "服务经理信息表",
            "--description",
            "服务经理基础信息",
            "--col-desc",
            "mgr_id=服务经理ID",
            "--edge",
            "org_id:dim_branch.org_id:dimension:no_default_data_dt",
            "--cue",
            "服务经理,经理",
        ]
    )
    assert code == 0
    assert not (copy / "tables" / "dim_mgr_info.yaml").exists()  # dry-run 不落盘


@requires_db
def test_cli_register_full_flow(tmp_path: Path, capsys):
    """CLI 全链路：问卷答案 → 落盘 → A6 同步 → A7/A8 回归（先维表后事实表）。"""
    copy = tmp_path / "metadata"
    shutil.copytree(get_settings().metadata_dir, copy)
    for name in ("dim_mgr_info", "dwd_cust_mgr_rel_d"):
        (copy / "tables" / f"{name}.yaml").unlink()
    _strip_sim_entries(copy)

    from querypilot.table_ops.cli import main

    code = main(
        [
            "register",
            "dim_mgr_info",
            "--metadata-dir",
            str(copy),
            "--yes",
            "--alias",
            "服务经理信息表",
            "--description",
            "服务经理基础信息（归属营业部、职级）。",
            "--granularity",
            "经理级",
            "--col-desc",
            "mgr_id=服务经理ID",
            "--col-desc",
            "mgr_name=服务经理姓名",
            "--col-desc",
            "org_id=归属营业部ID",
            "--col-desc",
            "mgr_title=职级",
            "--enum-meaning",
            "mgr_title=VP:副总裁级,高级经理:高级经理,经理:经理",
            "--edge",
            "org_id:dim_branch.org_id:dimension:no_default_data_dt",
            "--cue",
            "服务经理,客户经理,经理",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "全部同步生效" in out
    assert "回归通过" in out

    code = main(
        [
            "register",
            "dwd_cust_mgr_rel_d",
            "--metadata-dir",
            str(copy),
            "--yes",
            "--alias",
            "客户服务关系表",
            "--description",
            "客户与服务经理的服务关系（快照日全量）。",
            "--granularity",
            "客户级",
            "--col-desc",
            "pty_id=客户号",
            "--col-desc",
            "mgr_id=服务经理ID",
            "--col-desc",
            "data_dt=日期",
            "--edge",
            "pty_id:ads_cust_info_d.pty_id:fact:no_default_data_dt",
            "--edge",
            "mgr_id:dim_mgr_info.mgr_id:dimension",
            "--cue",
            "服务关系,名下客户,服务经理,客户经理",
            "--question",
            "服务经理名下有多少客户",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "全部同步生效" in out
    assert "回归通过" in out
