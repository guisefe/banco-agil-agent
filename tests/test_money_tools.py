from decimal import Decimal

import pytest

from app.tools.money import format_brl, parse_money, parse_non_negative_money


def test_parse_money_accepts_supported_formats() -> None:
    valid_cases = [
        ("5000", Decimal("5000.00")),
        ("5000.5", Decimal("5000.50")),
        ("R$ 5.000,00", Decimal("5000.00")),
        ("5.000", Decimal("5000.00")),
        ("1.000.000,99", Decimal("1000000.99")),
        ("1.000.000", Decimal("1000000.00")),
        ("5,5", Decimal("5.50")),
    ]

    for value, expected in valid_cases:
        assert parse_money(value) == expected


def test_parse_money_rejects_invalid_or_non_positive_values() -> None:
    for value in ["", "abc", "R$ -1", "0", "1,234", "1.2.3", "9" * 100]:
        with pytest.raises(ValueError):
            parse_money(value)


def test_format_brl_uses_decimal_safe_brazilian_format() -> None:
    assert format_brl(Decimal("1234567.8")) == "R$ 1.234.567,80"


def test_parse_non_negative_money_accepts_zero_for_financial_profile() -> None:
    assert parse_non_negative_money("0") == Decimal("0.00")


def test_parse_non_negative_money_rejects_invalid_values() -> None:
    for value in ["-1", "abc", "Infinity"]:
        with pytest.raises(ValueError, match="invalid"):
            parse_non_negative_money(value)
