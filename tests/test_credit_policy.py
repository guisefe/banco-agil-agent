from decimal import Decimal

import pytest

from app.models.credit_policy import evaluate_increase


@pytest.mark.parametrize(
    ("requested", "ceiling", "approved", "reason"),
    [
        ("4999.99", "5000", True, "WITHIN_SCORE_LIMIT"),
        ("5000", "5000", True, "WITHIN_SCORE_LIMIT"),
        ("5000.01", "5000", False, "EXCEEDS_SCORE_LIMIT"),
        ("0.01", "0", False, "EXCEEDS_SCORE_LIMIT"),
    ],
)
def test_policy_cent_boundaries(requested: str, ceiling: str, approved: bool, reason: str) -> None:
    decision = evaluate_increase(requested_limit=Decimal(requested), maximum_limit=Decimal(ceiling))
    assert decision.approved is approved
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    ("requested", "ceiling"),
    [
        ("NaN", "5000"),
        ("Infinity", "5000"),
        ("0", "5000"),
        ("-1", "5000"),
        ("1", "NaN"),
        ("1", "Infinity"),
        ("1", "-1"),
    ],
)
def test_policy_rejects_invalid_amounts(requested: str, ceiling: str) -> None:
    with pytest.raises(ValueError):
        evaluate_increase(requested_limit=Decimal(requested), maximum_limit=Decimal(ceiling))
