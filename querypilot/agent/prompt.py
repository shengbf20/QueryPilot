"""Prompt assembly for single-shot NL2SQL generation."""

from __future__ import annotations

from pathlib import Path

import yaml

from querypilot.agent.models import FewShotExample, PromptBundle
from querypilot.config import get_settings
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.metadata_engine.schema_pruner import PrunedSchema

SYSTEM_PROMPT = """你是证券客户营销场景下的 DuckDB SQL 专家。根据用户问题和提供的精简 Schema，生成一条可执行的只读 SQL。

硬性规则：
1. 只输出 JSON 对象，字段必须包含：sql（字符串）、rationale（简短中文思路）、uses_cte（布尔）。
2. 只允许 SELECT / WITH 查询；禁止 INSERT/UPDATE/DELETE/DROP/ATTACH/COPY/CREATE 等。
3. 只能使用「相关表结构」中出现的表名与字段名；不要臆造表或列。
4. 跨表关联默认只用业务键 pty_id 或 org_id；除非用户明确指定日期，否则不要把不同表的 data_dt 作为 Join 条件。
5. 客户信息表 ads_cust_info_d 的 data_dt 固定为 20260531，与事实表日期不对齐。
6. 编码字段（如 gender_cd）优先使用 Schema 中给出的枚举码值过滤；关联 dim_public 时必须同时匹配 code 与 code_type_id。
7. 多表筛选 + 聚合、或明显分步逻辑时，必须使用 CTE（WITH ... AS）拆解，uses_cte=true。
8. SQL 方言为 DuckDB；不要使用 MySQL/Oracle 专有函数。
9. 不要在 SQL 外包裹 markdown 代码块。
"""


def load_few_shots(path: Path | None = None) -> list[FewShotExample]:
    """Load few-shot examples from metadata/few_shots/examples.yaml."""
    path = path or (get_settings().metadata_dir / "few_shots" / "examples.yaml")
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    examples: list[FewShotExample] = []
    for item in raw.get("examples") or []:
        examples.append(
            FewShotExample(
                question=str(item["question"]).strip(),
                sql=str(item["sql"]).strip(),
                rationale=str(item.get("rationale", "")).strip(),
            )
        )
    return examples


def build_prompt(
    question: str,
    pruned: PrunedSchema,
    metadata: MetadataBundle,
    *,
    few_shots: list[FewShotExample] | None = None,
    include_values: bool = True,
    max_few_shots: int = 3,
) -> PromptBundle:
    """Assemble system + user prompts from pruned schema and few-shots."""
    q = question.strip()
    if not q:
        raise ValueError("question must be non-empty")

    shots = few_shots if few_shots is not None else load_few_shots()
    shots = shots[: max(0, max_few_shots)]

    schema_block = pruned.format_for_prompt(
        metadata,
        include_values=include_values,
        include_join_hints=True,
    )

    parts: list[str] = [
        f"用户问题:\n{q}",
        "",
        schema_block,
    ]

    if shots:
        parts.append("")
        parts.append("参考示例（Few-Shot）:")
        for i, ex in enumerate(shots, start=1):
            parts.append(f"\n示例 {i} 问题: {ex.question}")
            if ex.rationale:
                parts.append(f"思路: {ex.rationale}")
            parts.append(f"SQL:\n{ex.sql}")

    parts.extend(
        [
            "",
            "请输出 JSON，例如:",
            '{"sql":"SELECT ...","rationale":"...","uses_cte":false}',
        ]
    )

    return PromptBundle(
        system=SYSTEM_PROMPT,
        user="\n".join(parts),
        question=q,
        tables=list(pruned.tables),
        few_shot_count=len(shots),
    )
