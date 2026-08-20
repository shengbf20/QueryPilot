"""Result reasonableness probe (empty / suspicious outcomes → interactive hints)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from querypilot.db import QueryResult

_AGE_RE = re.compile(r"(\d+)\s*岁|年龄\s*(?:大于|超过|>=|>|≥)\s*(\d+)|(\d+)\s*岁以上")
_AMOUNT_RE = re.compile(r"(?:超过|大于|>|≥)\s*(\d+(?:\.\d+)?)\s*(万|亿)?")


@dataclass
class ProbeResult:
    """Interactive probe after a successful SQL execution."""

    triggered: bool
    code: str = "ok"  # ok | empty_result | zero_count | extreme_value
    message: str = ""
    suggestions: list[str] = field(default_factory=list)


def probe_result(
    question: str,
    result: QueryResult,
    *,
    sql: str = "",
) -> ProbeResult:
    """Inspect execution result and optionally suggest relaxing constraints."""
    q = question.strip()

    if result.row_count == 0:
        suggestions = _suggestions_from_question(q)
        if not suggestions:
            suggestions = ["放宽或去掉部分筛选条件后重试", "确认日期/枚举码是否过严"]
        return ProbeResult(
            triggered=True,
            code="empty_result",
            message="当前条件未检索到数据。",
            suggestions=suggestions,
        )

    if _is_zero_count(result):
        suggestions = _suggestions_from_question(q)
        if not suggestions:
            suggestions = ["放宽筛选条件后重试"]
        return ProbeResult(
            triggered=True,
            code="zero_count",
            message="查询成功，但计数结果为 0。",
            suggestions=suggestions,
        )

    extreme = _find_extreme_values(result)
    if extreme:
        return ProbeResult(
            triggered=True,
            code="extreme_value",
            message=f"结果中存在异常量级数值（例如 {extreme}），请核对口径或过滤条件。",
            suggestions=["检查单位是否为元/万元", "确认是否误用了未聚合的明细行"],
        )

    count_error = _check_count_format(sql, result)
    if count_error:
        return count_error

    return ProbeResult(triggered=False, code="ok", message="")


def _is_zero_count(result: QueryResult) -> bool:
    if result.row_count != 1 or len(result.columns) != 1:
        return False
    value = result.rows[0][0]
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)) and value == 0:
        col = result.columns[0].lower()
        return any(key in col for key in ("cnt", "count", "num", "总数", "数量")) or col in {
            "n",
            "c",
        }
    return False


def _find_extreme_values(result: QueryResult) -> str | None:
    """Flag obviously absurd magnitudes (defensive, not a full validator)."""
    for row in result.rows[:50]:
        for col, value in zip(result.columns, row, strict=False):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if value != value:  # NaN
                return f"{col}=NaN"
            if abs(value) >= 1e16:
                return f"{col}={value}"
    return None


def _suggestions_from_question(question: str) -> list[str]:
    suggestions: list[str] = []
    age_match = _AGE_RE.search(question)
    if age_match:
        age = next(g for g in age_match.groups() if g)
        suggestions.append(f"是否需要取消「{age}岁以上/年龄限制」？")
    if any(k in question for k in ("女性", "男性", "男女")):
        suggestions.append("是否需要取消性别限制？")
    if any(k in question for k in ("总资产", "资产", "AUM")):
        suggestions.append("是否需要降低资产门槛或改用最新资产快照？")
    amount = _AMOUNT_RE.search(question)
    if amount and "资产" not in "".join(suggestions):
        num, unit = amount.group(1), amount.group(2) or ""
        suggestions.append(f"是否需要取消「超过 {num}{unit}」这类阈值条件？")
    # de-dupe preserve order
    return list(dict.fromkeys(suggestions))


def _check_count_format(sql: str, result: QueryResult) -> ProbeResult | None:
    """检查 COUNT 查询的结果格式是否正确。

    常见问题：使用 GROUP BY + COUNT(DISTINCT) 导致返回多行（每行都是1），
    而不是期望的单行总数。
    """
    if not sql or result.row_count <= 1:
        return None

    sql_upper = sql.upper()

    # 检测是否是 COUNT 查询（最外层有 COUNT）
    has_count = bool(re.search(r'SELECT\s+COUNT\s*\(', sql_upper))

    # 检测是否有 GROUP BY（在最外层，不在子查询中）
    # 简单检测：如果 SQL 中有 GROUP BY，且返回多行，可能是问题
    has_group_by = 'GROUP BY' in sql_upper

    # 如果有 COUNT 且有 GROUP BY，且返回多行，检查是否所有行都是 1
    if has_count and has_group_by and result.row_count > 1:
        # 检查是否所有行的 COUNT 值都是 1（典型的 GROUP BY + COUNT 错误）
        try:
            all_ones = all(
                row[0] == 1
                for row in result.rows
                if len(row) > 0 and isinstance(row[0], (int, float))
            )
            if all_ones:
                return ProbeResult(
                    triggered=True,
                    code="count_format_error",
                    message=(
                        f"COUNT 查询返回了 {result.row_count} 行（每行都是1），"
                        f"可能是 GROUP BY 使用不当。期望返回单行单列的总数。"
                    ),
                    suggestions=[
                        "检查是否需要使用子查询来统计分组数量",
                        "例如：SELECT COUNT(*) FROM (SELECT ... GROUP BY ...) AS t"
                    ],
                )
        except (TypeError, IndexError):
            pass

    return None
