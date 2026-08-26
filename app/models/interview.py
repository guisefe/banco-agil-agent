from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, cast

EmploymentType = Literal["formal", "autonomo", "desempregado"]

SCORE_FORMULA_VERSION = "credit-interview-score-v1"
INCOME_WEIGHT = Decimal("30")
EMPLOYMENT_WEIGHTS: Mapping[EmploymentType, Decimal] = {
    "formal": Decimal("300"),
    "autonomo": Decimal("200"),
    "desempregado": Decimal("0"),
}
DEPENDENT_WEIGHTS: Mapping[int, Decimal] = {
    0: Decimal("100"),
    1: Decimal("80"),
    2: Decimal("60"),
}
DEBT_WEIGHTS: Mapping[bool, Decimal] = {
    True: Decimal("-100"),
    False: Decimal("100"),
}
_MINIMUM_SCORE = Decimal("0")
_MAXIMUM_SCORE = Decimal("1000")


@dataclass(frozen=True, slots=True, kw_only=True)
class FinancialProfile:
    monthly_income: Decimal
    employment_type: EmploymentType
    fixed_expenses: Decimal
    dependents: int
    has_active_debts: bool

    def __post_init__(self) -> None:
        if not self.monthly_income.is_finite() or self.monthly_income < 0:
            raise ValueError("monthly_income must be finite and non-negative")
        if self.employment_type not in EMPLOYMENT_WEIGHTS:
            raise ValueError("employment_type is invalid")
        if not self.fixed_expenses.is_finite() or self.fixed_expenses < 0:
            raise ValueError("fixed_expenses must be finite and non-negative")
        if isinstance(self.dependents, bool) or self.dependents < 0:
            raise ValueError("dependents must be non-negative")
        if not isinstance(self.has_active_debts, bool):
            raise ValueError("has_active_debts must be boolean")


def calculate_credit_score(profile: FinancialProfile) -> int:
    income_component = (
        profile.monthly_income / (profile.fixed_expenses + Decimal("1"))
    ) * INCOME_WEIGHT
    raw_score = (
        income_component
        + EMPLOYMENT_WEIGHTS[profile.employment_type]
        + _dependent_weight(profile.dependents)
        + DEBT_WEIGHTS[profile.has_active_debts]
    )
    bounded_score = max(_MINIMUM_SCORE, min(_MAXIMUM_SCORE, raw_score))
    return int(bounded_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_employment_type(value: str) -> EmploymentType:
    normalized = value.strip().casefold()
    normalized = normalized.replace("ô", "o")
    if normalized not in EMPLOYMENT_WEIGHTS:
        raise ValueError("invalid employment type")
    return cast(EmploymentType, normalized)


def parse_dependents(value: str) -> int:
    normalized = value.strip()
    if normalized.endswith("+"):
        normalized = normalized[:-1]
    if not normalized.isascii() or not normalized.isdigit():
        raise ValueError("invalid number of dependents")
    return int(normalized)


def parse_debt_answer(value: str) -> bool:
    normalized = value.strip().casefold().replace("ã", "a")
    if normalized == "sim":
        return True
    if normalized == "nao":
        return False
    raise ValueError("invalid debt answer")


def _dependent_weight(dependents: int) -> Decimal:
    return DEPENDENT_WEIGHTS.get(dependents, Decimal("30"))
