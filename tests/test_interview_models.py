from decimal import Decimal

import pytest

from app.models.interview import (
    FinancialProfile,
    calculate_credit_score,
    parse_debt_answer,
    parse_dependents,
    parse_employment_type,
)


def make_profile(**overrides: object) -> FinancialProfile:
    values: dict[str, object] = {
        "monthly_income": Decimal("5000.00"),
        "employment_type": "formal",
        "fixed_expenses": Decimal("2500.00"),
        "dependents": 1,
        "has_active_debts": False,
    }
    values.update(overrides)
    return FinancialProfile(**values)  # type: ignore[arg-type]


def test_score_formula_uses_challenge_weights_and_half_up_rounding() -> None:
    profile = make_profile()

    assert calculate_credit_score(profile) == 540


def test_score_formula_clamps_result_to_supported_range() -> None:
    assert (
        calculate_credit_score(
            make_profile(
                monthly_income=Decimal("1000000"),
                fixed_expenses=Decimal("0"),
            )
        )
        == 1000
    )
    assert (
        calculate_credit_score(
            make_profile(
                monthly_income=Decimal("0"),
                employment_type="desempregado",
                dependents=3,
                has_active_debts=True,
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"monthly_income": Decimal("-0.01")}, "monthly_income"),
        ({"monthly_income": Decimal("Infinity")}, "monthly_income"),
        ({"employment_type": "invalid"}, "employment_type"),
        ({"fixed_expenses": Decimal("-0.01")}, "fixed_expenses"),
        ({"fixed_expenses": Decimal("NaN")}, "fixed_expenses"),
        ({"dependents": -1}, "dependents"),
        ({"dependents": True}, "dependents"),
        ({"has_active_debts": "sim"}, "has_active_debts"),
    ],
)
def test_financial_profile_rejects_invalid_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_profile(**overrides)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("formal", "formal"), ("AUTÔNOMO", "autonomo"), ("desempregado", "desempregado")],
)
def test_parse_employment_type_accepts_supported_values(value: str, expected: str) -> None:
    assert parse_employment_type(value) == expected


def test_parse_employment_type_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="employment"):
        parse_employment_type("informal")


@pytest.mark.parametrize(("value", "expected"), [("0", 0), ("2", 2), ("3+", 3)])
def test_parse_dependents_accepts_non_negative_integer(value: str, expected: int) -> None:
    assert parse_dependents(value) == expected


@pytest.mark.parametrize("value", ["", "-1", "1.5", "dois", "²"])
def test_parse_dependents_rejects_invalid_value(value: str) -> None:
    with pytest.raises(ValueError, match="dependents"):
        parse_dependents(value)


@pytest.mark.parametrize(("value", "expected"), [("sim", True), ("NÃO", False)])
def test_parse_debt_answer_accepts_yes_or_no(value: str, expected: bool) -> None:
    assert parse_debt_answer(value) is expected


def test_parse_debt_answer_rejects_ambiguous_value() -> None:
    with pytest.raises(ValueError, match="debt"):
        parse_debt_answer("talvez")
