"""/onboarding 自助接入 UI 后端测试（GET 页面 / 问卷 / 注册全流程）。

自建试验床：把 data_sim 的风险表 CSV 导入真实库的临时副本，
注册只写入元数据副本（metadata_dir 指向 tmp_path），不触碰仓库 metadata/ 与 db/。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from querypilot.config import get_settings, ROOT_DIR
from querypilot.api.onboarding_routes import router

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TABLE = "dwd_cust_risk_assess_d"
RISK_CSV = ROOT_DIR / "data_sim" / f"{TABLE}.csv"


@pytest.fixture(scope="module")
def _risk_db_path(tmp_path_factory):
    """真实库副本 + 导入风险表 CSV（模块级建一次，测试只读）。"""
    db = tmp_path_factory.mktemp("db") / "risk_test.duckdb"
    shutil.copy(get_settings().db_path, db)
    con = duckdb.connect(str(db))
    try:
        con.execute(
            f"CREATE TABLE {TABLE} (data_dt VARCHAR, pty_id VARCHAR, risk_lvl_cd VARCHAR,"
            " risk_score INTEGER, assess_dt VARCHAR, expire_dt VARCHAR)"
        )
        con.execute(
            f"INSERT INTO {TABLE} SELECT * FROM read_csv(?, header = true, sample_size = -1)",
            [str(RISK_CSV)],
        )
    finally:
        con.close()
    return db


@pytest.fixture()
def risk_db(_risk_db_path: Path, monkeypatch) -> Path:
    """把进程 DUCKDB_PATH 指到副本（get_settings 每次现读 env，立即生效）。"""
    monkeypatch.setenv("DUCKDB_PATH", str(_risk_db_path))
    return _risk_db_path


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def metadata_dir(tmp_path: Path) -> Path:
    """元数据副本：去掉新表 YAML（若有），模拟「表已入库、元数据未登记」状态。"""
    meta = tmp_path / "metadata"
    shutil.copytree(ROOT_DIR / "metadata", meta)
    meta.joinpath("tables", f"{TABLE}.yaml").unlink(missing_ok=True)
    return meta


def _form_body(questionnaire: dict, metadata_dir: Path) -> dict:
    """模拟 onboarding.html 表单提交体（含必填项人工答案 + 机械候选默认勾选）。"""
    qs = {q["id"]: q for q in questionnaire["questions"]}
    column_descriptions = {
        "data_dt": "数据日期",
        "pty_id": "客户号",
        "risk_lvl_cd": "风险等级代码",
        "risk_score": "风险评分",
        "assess_dt": "评估日期",
        "expire_dt": "失效日期",
    }
    join_edges = [
        c["suggested_edge"]
        for c in qs["Q5"]["items"]
        if c.get("suggested_edge") and c["confidence"] == "high" and c["containment"] >= 0.99
    ]
    return {
        "table": questionnaire["table"],
        "alias": "客户风险评估",
        "description": "dwd 层客户风险评估表，记录客户风险等级与评分",
        "granularity": "客户级",
        "column_descriptions": column_descriptions,
        "join_edges": join_edges,
        "enum_meanings": {},
        "cue_words": ["风险", "风险评估", "风险等级", "激进型"],
        "notes": [],
        "smoke_questions": ["有多少激进型客户？"],
        "metadata_dir": str(metadata_dir),
    }


# ---------- GET /onboarding（静态页面） ----------


def test_onboarding_page_served(client: TestClient):
    resp = client.get("/onboarding")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "onboarding" in resp.text.lower()
    # 页面应包含问卷生成与提交两个入口
    assert "/api/onboarding/questionnaire" in resp.text
    assert "/api/onboarding/register" in resp.text


# ---------- GET /api/onboarding/questionnaire ----------


def test_questionnaire_requires_table(client: TestClient):
    resp = client.get("/api/onboarding/questionnaire", params={"table": "  "})
    assert resp.status_code == 400
    assert not resp.json()["ok"]


def test_questionnaire_unknown_table_404(client: TestClient):
    resp = client.get("/api/onboarding/questionnaire", params={"table": "no_such_table"})
    assert resp.status_code == 404
    assert not resp.json()["ok"]


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_questionnaire_returns_q1_to_q7(client: TestClient, risk_db: Path):
    resp = client.get("/api/onboarding/questionnaire", params={"table": TABLE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"]
    questionnaire = body["questionnaire"]
    assert questionnaire["table"] == "dwd_cust_risk_assess_d"
    ids = [q["id"] for q in questionnaire["questions"]]
    assert ids == [f"Q{i}" for i in range(1, 8)]
    # Q5 关联候选应携带完整 suggested_edge（lookup 边 filter 定位到 400 字典）
    qs = {q["id"]: q for q in questionnaire["questions"]}
    lookup = [
        c for c in qs["Q5"]["items"]
        if c.get("suggested_edge", {}).get("type") == "lookup"
    ]
    assert lookup, "dim_public lookup 候选缺失"
    assert lookup[0]["suggested_edge"]["filter"] == {"code_type_id": "400"}


# ---------- POST /api/onboarding/register ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
class TestRegisterFlow:
    def test_register_full_flow_ok(
        self, client: TestClient, metadata_dir: Path, risk_db: Path
    ):
        resp = client.get("/api/onboarding/questionnaire", params={"table": TABLE})
        body = _form_body(resp.json()["questionnaire"], metadata_dir)

        resp = client.post("/api/onboarding/register", json=body)
        assert resp.status_code == 200
        out = resp.json()
        assert out["ok"], out
        assert out["cue_inherited"] is True
        assert len(out["files_written"]) == 3  # tables/ + join_graph + pruning
        assert all(c["ok"] for c in out["sync"]["checks"])
        assert all(c["ok"] for c in out["regression"]["checks"])
        # 只写副本，不碰仓库元数据
        for path in out["files_written"]:
            assert str(metadata_dir) in path

    def test_register_duplicate_409(
        self, client: TestClient, metadata_dir: Path, risk_db: Path
    ):
        resp = client.get("/api/onboarding/questionnaire", params={"table": TABLE})
        body = _form_body(resp.json()["questionnaire"], metadata_dir)
        assert client.post("/api/onboarding/register", json=body).status_code == 200
        resp = client.post("/api/onboarding/register", json=body)
        assert resp.status_code == 409
        assert "already exists" in resp.json()["error"]

    @pytest.mark.parametrize(
        "patch",
        [
            {"alias": ""},
            {"description": ""},
            {"cue_words": []},
        ],
        ids=["no-alias", "no-description", "no-cue-words"],
    )
    def test_register_missing_required_400(
        self, client: TestClient, metadata_dir: Path, risk_db: Path, patch: dict
    ):
        resp = client.get("/api/onboarding/questionnaire", params={"table": TABLE})
        body = _form_body(resp.json()["questionnaire"], metadata_dir) | patch
        resp = client.post("/api/onboarding/register", json=body)
        assert resp.status_code == 400
        assert not resp.json()["ok"]
        # 校验失败时不应有任何落盘
        assert not metadata_dir.joinpath("tables", f"{TABLE}.yaml").exists()
