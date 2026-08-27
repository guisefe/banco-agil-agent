from datetime import date
from decimal import Decimal

import pytest

from app.models.customer import Customer


def make_customer(**overrides: object) -> Customer:
    values: dict[str, object] = {
        "cpf": "00000000000",
        "name": "Ana Exemplo",
        "birth_date": date(1990, 5, 20),
        "credit_limit": Decimal("2500.00"),
        "credit_score": 650,
    }
    values.update(overrides)
    return Customer(**values)  # type: ignore[arg-type]


def test_customer_rejects_invalid_business_values() -> None:
    invalid_cases: list[tuple[dict[str, object], str]] = [
        ({"cpf": " "}, "cpf"),
        ({"name": " "}, "name"),
        ({"credit_limit": Decimal("-0.01")}, "credit_limit"),
        ({"credit_limit": Decimal("Infinity")}, "credit_limit"),
        ({"credit_score": -1}, "credit_score"),
        ({"credit_score": 1001}, "credit_score"),
    ]

    for overrides, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            make_customer(**overrides)


def test_customer_accepts_valid_boundaries() -> None:
    customer = make_customer(credit_limit=Decimal("0"), credit_score=1000)

    assert customer.credit_limit == 0
    assert customer.credit_score == 1000
