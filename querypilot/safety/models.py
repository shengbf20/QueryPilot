"""Safety fence result types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GuardViolation:
    """A single L1/L2 finding."""

    code: str
    message: str
    severity: str = "block"  # block | warn


@dataclass(frozen=True)
class ColumnFix:
    """Automatic column-name correction applied by L1."""

    original: str
    fixed: str
    table: str | None = None


@dataclass
class L1GuardResult:
    """Outcome of the L1 AST safety fence."""

    ok: bool
    sql: str
    original_sql: str
    violations: list[GuardViolation] = field(default_factory=list)
    fixes: list[ColumnFix] = field(default_factory=list)

    @property
    def blocking_violations(self) -> list[GuardViolation]:
        return [v for v in self.violations if v.severity == "block"]


@dataclass
class L2GuardResult:
    """Outcome of L2 EXPLAIN (+ optional single 1-Shot correction)."""

    ok: bool
    sql: str
    original_sql: str
    explain_error: str | None = None
    corrected: bool = False
    correction_rationale: str = ""
    degraded: bool = False
    message: str = ""
    attempts: int = 1
    l1_after_correction: L1GuardResult | None = None
