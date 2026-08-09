"""Prompt assembly for single-shot NL2SQL generation."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from querypilot.agent.models import FewShotExample, PromptBundle
from querypilot.config import get_settings
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.metadata_engine.schema_pruner import PrunedSchema

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

SYSTEM_PROMPT = """你是证券客户营销场景下的 DuckDB SQL 专家。根据用户问题和提供的精简 Schema，生成一条可执行的只读 SQL。

硬性规则：
1. 只输出 JSON 对象，字段必须包含：sql（字符串）、rationale（简短中文思路）、uses_cte（布尔）。
2. 只允许 SELECT / WITH 查询；禁止 INSERT/UPDATE/DELETE/DROP/ATTACH/COPY/CREATE 等。
3. 只能使用「相关表结构」中出现的表名与字段名；不要臆造表或列（禁止不存在的 pnl/盈亏事实表）。
4. 跨表关联默认只用业务键 pty_id 或 org_id；除非用户明确指定日期，否则不要把不同表的 data_dt 作为 Join 条件。
5. 客户信息表 ads_cust_info_d 的 data_dt 固定为 20260531，与事实表日期不对齐；事实表可用 WHERE 单独过滤 data_dt。
6. 编码字段（如 gender_cd）优先使用 Schema 中给出的枚举码值过滤；关联 dim_public 时必须同时匹配 code 与 code_type_id。若用 "describe" 过滤，字面量必须与维表原文完全一致（含空格、/）；职业「非公职离退休」优先 prof_cd='7000032'（code_type_id='700'），禁止自造「非公职离退休」等省略写法。
7. 多表筛选 + 聚合、或明显分步逻辑时，必须使用 CTE（WITH ... AS）拆解，uses_cte=true。
8. SQL 方言为 DuckDB。过滤用的 data_dt 字面量用 YYYYMMDD（如 '20260331'）；日期差值用 DATE '2026-03-31' - DATE '2026-01-01'，禁止 CAST('20260331' AS DATE) 或 to_date。
9. 不要在 SQL 外包裹 markdown 代码块。
10. 投影列必须对齐题面维度：只选出回答问题所需的维度/指标；题目未要求「有多少/人数/个数」时，不要擅自加 COUNT(*)/COUNT(DISTINCT)；题目问「哪些客户」时只输出 pty_id（可 ORDER BY），禁止附带 SUM/合计列。
11. 组织与地理分布类统计：仅问「营业部/按营业部」时默认只输出 org_name + 人数或金额，不要加 up_org_name；仅当题面出现「分公司/上级」时才同时输出 up_org_name、org_name。出现省份/省市分析时同时输出 prov_name 与 city_name（若 Schema 有这些列）。按营业部名称汇总或 Top-N 时必须 GROUP BY org_name（禁止只按 org_id 分组后再投影名称，以免同名营业部分行）。
12. 产品名称、板块、产品类型过滤必须 JOIN dim_product，并用 prdt_name / prdt_type_name / up_prdt_type_name 等真实列；禁止用臆造 prdt_id，禁止把 pty_id 与 prdt_id 互相 Join。
13. 总资产口径：nm_tot_aset + fc_pur_aset（用 coalesce 防空），且 nm_tot_aset/fc_pur_aset/nm_bal 仅来自 dws_cust_aset_d，客户信息表无这些列。本币总资产只用 nm_tot_aset，总资产用 nm+fc；对比两门槛时必须分别引用，禁止对同一表达式写矛盾阈值。交易量口径：coalesce(buy_amt,0)+coalesce(sell_amt,0)；dwd_cust_tran_d 无物理列 tran_amt，CTE/子查询别名建议用 trade_amt。题面写「股票买卖/股票交易」时必须 JOIN dim_product 且用 up_prdt_type_id='PT040000'（或一级股票名）过滤后再 SUM，禁止对全产品交易求和。交易金额聚合直接对 dwd_cust_tran_d 做，勿经日资产表 LEFT JOIN 放大行数。多条件圈选时最终查询须保留各过滤 CTE 的交集。
14. 题目指明季度末/某日快照时，优先用固定 data_dt（如 26年Q1末→20260331），不要默认 MAX(data_dt)，除非题目明确要求「最新」。
15. 年龄段等分桶标签用简洁区间 <30、[30,50)、[50,60)、[60,)（「大于60」对应 [60,)），不要写成 >=60，不要加「1.」「2.」序号前缀。
16. 产品层级：题目指「A股/科创板/创业板」等二级类型时用 dim_product.prdt_type_name（如 = 'A股'）；指「股票/开放式基金/债券」等一级大类时用 up_prdt_type_id 或 up_prdt_type_name（股票='PT040000'，开放式基金='PT050000'，债券='PT030000'）；二者不可混用。禁止写 prdt_type_name='开放式基金'（该字面量只存在于一级 up_prdt_type_name）。题面仅要求「产品大类」时只输出 up_prdt_type_name 与 sum(mkt_val)；仅当题面同时要求二级类型/明细分布时再同时输出 prdt_type_name。
17. 问及「盈亏/损益」时禁止臆造盈亏表；用资产快照+ dws_cust_fin_d 推算，投影六列：pty_id, bgn_aset, end_aset, aset_in, aset_out, aset_pft。26年Q1 期初 data_dt='20260101'、期末 '20260331'；aset_in/out 对 cash/tran/assign 流入流出求和。aset_pft 必须写成 end_nm+end_fc - bgn_nm + bgn_fc + aset_out - aset_in（注意期初 fc 前为加号）；禁止直觉式 end_aset - bgn_aset + out - in。六列数值外层一律 coalesce(...,0)。
18. 期间合计阈值：问某时间窗内「合计/总额超过」「笔数合计大于」时，先按窗口过滤 data_dt，再 GROUP BY pty_id（或所需键）用 HAVING SUM(...) 判断；禁止在聚合前写日级条件如 sell_amt>阈值、cash_out>阈值。若题目问「有多少人/人数」，须在 HAVING 子查询之外再包一层 COUNT(*)（或 COUNT(DISTINCT pty_id) 的等价两层写法）；禁止 SELECT COUNT(*) ... GROUP BY pty_id HAVING（会得到每人一行而非总人数）。
19. Top-N / LIMIT n：主指标 DESC（或 ASC）排序后必须再加稳定二级键（如 org_name、pty_id 或题面名称列），避免并列时结果集不稳定；营业部金额 Top-N 对 buy_amt/sell_amt 使用 coalesce 后求和，并按 org_name 聚合。
20. 费用口径：题面「手续费/费用」用 buy_fare+sell_fare；「佣金」用 buy_rake+sell_rake，二者勿混用。证券转入/证券流入用 dws_cust_fin_d.tran_in（非 assign_in）；指定转入才用 assign_in。
21. 现金净流入= SUM(cash_in)-SUM(cash_out)（可 coalesce）；不要做成只 SUM(cash_in)，也不要套用期间盈亏的 cash+tran+assign 总流入。题面写「现金净流入/现金流入减现金流出」时严格只用 cash_* 两列。
22. 日均资产：分母为过滤窗口的日历天数（含首尾），DATE 差值必须与 WHERE data_dt BETWEEN 的起止日一致（如 2 月整月用 20260201–20260228，分母 28）。用持仓/交易条件先圈选客户后，若题目要「其持仓按产品大类汇总」，应对圈选客户的全部持仓 GROUP BY up_prdt_type_name，不要把筛选用的产品类再限制最终聚合。
23. 两段时间窗对比（如「3 月高于 1 月」）：两窗各自聚合后必须 INNER JOIN（两窗都要有记录），禁止把缺失窗当作 0 再比较（勿 LEFT JOIN + coalesce(...,0) 放宽圈选）。
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


def _few_shot_terms(text: str) -> set[str]:
    """Lightweight terms for overlap ranking (CJK phrases + latin tokens)."""
    terms: set[str] = set()
    for m in _CJK_RE.findall(text):
        terms.add(m)
        if len(m) >= 4:
            for i in range(len(m) - 1):
                terms.add(m[i : i + 2])
    for m in _TOKEN_RE.findall(text.lower()):
        if len(m) >= 2:
            terms.add(m)
    return terms


def _norm_question(text: str) -> str:
    return " ".join(text.strip().split())


def find_exact_few_shot(
    question: str,
    examples: list[FewShotExample],
) -> FewShotExample | None:
    """Return the first example whose question matches after whitespace normalize."""
    q_norm = _norm_question(question)
    if not q_norm:
        return None
    for ex in examples:
        if _norm_question(ex.question) == q_norm:
            return ex
    return None


def select_few_shots(
    question: str,
    examples: list[FewShotExample],
    *,
    max_few_shots: int = 3,
) -> list[FewShotExample]:
    """Pick up to ``max_few_shots`` examples by question/rationale term overlap.

    Exact question matches (after whitespace normalize) are strongly preferred.
    Falls back to file order when all scores are zero (keeps legacy behavior).
    """
    if max_few_shots <= 0 or not examples:
        return []
    q_norm = _norm_question(question)
    q_terms = _few_shot_terms(question)
    scored: list[tuple[float, int, FewShotExample]] = []
    for idx, ex in enumerate(examples):
        ex_terms = _few_shot_terms(ex.question)
        if ex.rationale:
            ex_terms |= _few_shot_terms(ex.rationale)
        overlap = len(q_terms & ex_terms)
        score = float(overlap)
        if _norm_question(ex.question) == q_norm:
            score += 1000.0
        scored.append((score, -idx, ex))
    scored.sort(reverse=True)
    if scored[0][0] <= 0:
        return examples[:max_few_shots]
    return [ex for _, _, ex in scored[:max_few_shots]]


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

    pool = few_shots if few_shots is not None else load_few_shots()
    shots = select_few_shots(q, pool, max_few_shots=max_few_shots)

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
