"""A9 业务问卷生成（logs/08 §三 / §五）。

LLM 定位：只把机械候选翻译成人类语言的问题与默认答案，全部落在确认环内，
出错无害——LLM 失败或缺失时降级为机械问卷，流水线 100% 可运行。
"""

from __future__ import annotations

from typing import Any

import duckdb

from querypilot.config import get_settings
from querypilot.table_ops.candidates import enum_candidates, key_candidates
from querypilot.table_ops.discover import build_skeleton, discover_table

# Q2 候选业务域（与 pruning.yaml domain_seed_cues 的域分组对应）
_DOMAINS = ["客户", "资产", "持仓", "交易", "资金流", "组织", "产品", "服务经理"]


def mechanical_questionnaire(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata_dir: Any = None,
) -> dict[str, Any]:
    """机械问卷底稿：A1 画像 + A3 键候选 + A4 枚举候选 → Q1-Q7 与默认答案。"""
    from querypilot.db import get_connection

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        profile = discover_table(table, con=con)
        keys = key_candidates(table, con=con)
        key_cols = {c.column for c in keys}
        enums = enum_candidates(table, con=con, key_columns=key_cols)
        skeleton = build_skeleton(table, con=con)
    finally:
        if own_con:
            con.close()

    neighbors = sorted({c.target_table for c in keys if c.confidence != "low"})
    pk = skeleton.get("primary_key") or []

    questions: list[dict[str, Any]] = [
        {
            "id": "Q1",
            "question": "这张表是做什么的？",
            "default": (
                f"{table}：{profile.suggested_layer or '未知'} 层，"
                f"{profile.row_count} 行，{len(profile.columns)} 列"
                + (f"，主键候选 {', '.join(pk)}" if pk else "，无单列唯一键")
            ),
            "answer_type": "text",
        },
        {
            "id": "Q2",
            "question": "它属于哪个业务域？",
            "default": "按关联表推断: " + ("、".join(neighbors) if neighbors else "无关联表"),
            "answer_type": "choice",
            "options": _DOMAINS,
        },
        {
            "id": "Q3",
            "question": "一行代表什么（粒度）？",
            "default": f"主键: {', '.join(pk)}" if pk else "组合主键需人工确认",
            "answer_type": "text",
        },
        {
            "id": "Q4",
            "question": "以下列的含义对吗？",
            "answer_type": "list",
            "items": [
                {
                    "column": c["name"],
                    "default": c["description"]
                    or f"{c['name']}（{c['type']}）",
                }
                for c in skeleton["columns"]
            ],
        },
        {
            "id": "Q5",
            "question": "以下关联关系对吗？",
            "answer_type": "list",
            "items": [
                {
                    "column": c.column,
                    "target": f"{c.target_table}.{c.target_column}",
                    "confidence": c.confidence,
                    "containment": c.containment,
                    "edge_type": c.edge_type,
                }
                for c in keys
                if c.confidence != "low"
            ],
        },
        {
            "id": "Q6",
            "question": "以下列的值需要字典解释吗？",
            "answer_type": "list",
            "items": [
                {
                    "column": c.column,
                    "kind": c.kind,
                    "default": c.label or "待填编码含义",
                    "values": dict(list(c.value_meanings.items())[:8]),
                }
                for c in enums
            ],
        },
        {
            "id": "Q7",
            "question": "有没有特殊口径要说明？",
            "default": "；".join(skeleton.get("notes") or []) or "无",
            "answer_type": "text",
        },
    ]
    return {"table": table, "questions": questions}


def format_questionnaire(questionnaire: dict[str, Any]) -> str:
    """问卷的人类可读文本。"""
    lines = [f"新表登记问答: {questionnaire['table']}", "=" * 60]
    for q in questionnaire["questions"]:
        lines.append("")
        lines.append(f"{q['id']}. {q['question']}")
        if q.get("options"):
            lines.append(f"   选项: {' / '.join(q['options'])}")
        if "default" in q:
            lines.append(f"   [默认] {q['default']}")
        for item in q.get("items") or []:
            if "target" in item:  # Q5 join 边候选
                lines.append(
                    f"   - {item['column']} → {item['target']}"
                    f"（置信 {item['confidence']}，包含率 {item['containment']:.0%}，"
                    f"类型 {item['edge_type']}）"
                )
            else:  # Q4 列 / Q6 枚举
                values = item.get("values") or {}
                suffix = f"  值域: {values}" if values else ""
                lines.append(f"   - {item['column']}: {item['default']}{suffix}")
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "你是数仓元数据登记助手。输入是一张新表的机械画像与候选（JSON）。"
    "你的唯一任务：把候选翻译成业务人员能懂的问题与默认答案，"
    "不得增删任何候选条目、不得改动候选的机械字段（列名/目标表/置信度）。"
    "输出 JSON：{\"questions\": [{\"id\", \"question\", \"default\"}, ...]}，"
    "id 保持 Q1-Q7 不变。"
)


def generate_questionnaire(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """LLM 翻译问卷；LLM 不可用/输出异常时降级为机械问卷（出错无害）。"""
    questionnaire = mechanical_questionnaire(table, con=con)
    try:
        import json

        from querypilot.llm.chat import generate_json

        prompt = (
            f"新表机械画像与候选问卷如下，请翻译为业务问题与默认答案：\n\n"
            f"{json.dumps(questionnaire, ensure_ascii=False, indent=2)}"
        )
        llm_result = generate_json(prompt, system=_SYSTEM_PROMPT, client=client)
        questions = llm_result.get("questions")
        if isinstance(questions, list) and questions:
            # 以机械问卷为骨架回填翻译文本（LLM 只贡献 question/default 文本）
            by_id = {}
            for item in questions:
                if isinstance(item, dict) and item.get("id"):
                    by_id[item["id"]] = item
            for q in questionnaire["questions"]:
                translated = by_id.get(q["id"]) or {}
                if translated.get("question"):
                    q["question"] = str(translated["question"])
                if translated.get("default") and q.get("answer_type") == "text":
                    q["default"] = str(translated["default"])
        return questionnaire
    except Exception:
        return questionnaire
