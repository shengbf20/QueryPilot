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
3. 只能使用「相关表结构」中出现的表名与字段名；不要臆造表或列（禁止不存在的 pnl/盈亏事实表）。
4. 跨表关联默认只用业务键 pty_id 或 org_id；除非用户明确指定日期，否则不要把不同表的 data_dt 作为 Join 条件。
5. 客户信息表 ads_cust_info_d 的 data_dt 固定为 20260531，与事实表日期不对齐；事实表可用 WHERE 单独过滤 data_dt。
6. 编码字段（如 gender_cd）优先使用 Schema 中给出的枚举码值过滤；关联 dim_public 时必须同时匹配 code 与 code_type_id。
7. 多表筛选 + 聚合、或明显分步逻辑时，必须使用 CTE（WITH ... AS）拆解，uses_cte=true。
8. SQL 方言为 DuckDB；不要使用 MySQL/Oracle 专有函数。日期字面量用 YYYYMMDD（如 20260331），不要写成 2026-03-31。
9. 不要在 SQL 外包裹 markdown 代码块。
10. 投影列必须对齐题面维度：只选出回答问题所需的维度/指标；题目未要求「有多少/人数/个数」时，不要擅自加 COUNT(*)/COUNT(DISTINCT)；题目问「哪些客户」时优先输出 pty_id 列表。
11. 组织与地理分布类统计：题目出现分公司/营业部时输出 up_org_name、org_name；出现省份/省市分析时同时输出 prov_name 与 city_name（若 Schema 有这些列）。
12. 产品名称、板块、产品类型过滤必须 JOIN dim_product，并用 prdt_name / prdt_type_name / up_prdt_type_name 等真实列；禁止用臆造 prdt_id，禁止把 pty_id 与 prdt_id 互相 Join。
13. 总资产口径：nm_tot_aset + fc_pur_aset（用 coalesce 防空）；交易量口径：buy_amt + sell_amt。
14. 题目指明季度末/某日快照时，优先用固定 data_dt（如 26年Q1末→20260331），不要默认 MAX(data_dt)，除非题目明确要求「最新」。
15. 年龄段等分桶标签用简洁区间 <30、[30,50)、[50,60)、[60,)（「大于60」对应 [60,)），不要写成 >=60，不要加「1.」「2.」序号前缀。
16. 科创板/A股等用 dim_product.prdt_type_name；产品大类分布同时输出 up_prdt_type_name、prdt_type_name 与 sum(mkt_val)。
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
