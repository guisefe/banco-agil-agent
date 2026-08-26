from decimal import Decimal

import pytest

from app.tools.money import format_brl, parse_money


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5000", Decimal("5000.00")),
        ("5000.5", Decimal("5000.50")),
        ("R$ 5.000,00", Decimal("5000.00")),
        ("5.000", Decimal("5000.00")),
        ("1.000.000,99", Decimal("1000000.99")),
        ("1.000.000", Decimal("1000000.00")),
        ("5,5", Decimal("5.50")),
    ],
)
def test_parse_money_accepts_supported_formats(value: str, expected: Decimal) -> None:
    assert parse_money(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "abc", "R$ -1", "0", "1,234", "1.2.3", "9" * 100],
)
def test_parse_money_rejects_invalid_or_non_positive_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_money(value)


def test_format_brl_uses_decimal_safe_brazilian_format() -> None:
    assert format_brl(Decimal("1234567.8")) == "R$ 1.234.567,80"
