from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.credit import CreditRequest, ScoreBand


def make_request(**overrides: object) -> CreditRequest:
    values: dict[str, object] = {
        "customer_cpf": "00000000000",
        "requested_at": datetime.now(UTC),
        "current_limit": Decimal("2500.00"),
        "requested_limit": Decimal("3000.00"),
        "status": "aprovado",
    }
    values.update(overrides)
    return CreditRequest(**values)  # type: ignore[arg-type]


def test_credit_request_accepts_valid_final_decision() -> None:
    request = make_request()

    assert request.status == "aprovado"


def test_credit_request_rejects_invalid_values() -> None:
    invalid_cases: list[tuple[dict[str, object], str]] = [
        ({"customer_cpf": " "}, "customer_cpf"),
        (
            {"requested_at": datetime.now(timezone(timedelta(hours=-3)))},
            "UTC",
        ),
        ({"current_limit": Decimal("-0.01")}, "non-negative"),
        ({"current_limit": Decimal("Infinity")}, "non-negative"),
        ({"requested_limit": Decimal("2500.00")}, "greater than"),
        ({"requested_limit": Decimal("NaN")}, "greater than"),
    ]

    for overrides, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            make_request(**overrides)


def test_score_band_accepts_valid_values() -> None:
    band = ScoreBand(
        minimum_score=0,
        maximum_score=299,
        maximum_limit=Decimal("1000.00"),
    )

    assert band.maximum_limit == Decimal("1000.00")


def test_score_band_rejects_invalid_ranges() -> None:
    for minimum, maximum in [(-1, 100), (200, 100), (0, 1001)]:
        with pytest.raises(ValueError, match="between 0 and 1000"):
            ScoreBand(
                minimum_score=minimum,
                maximum_score=maximum,
                maximum_limit=Decimal("1000.00"),
            )


def test_score_band_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ScoreBand(
            minimum_score=0,
            maximum_score=100,
            maximum_limit=Decimal("-0.01"),
        )


def test_score_band_rejects_non_finite_limit() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ScoreBand(
            minimum_score=0,
            maximum_score=100,
            maximum_limit=Decimal("Infinity"),
        )
