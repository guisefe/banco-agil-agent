from datetime import date

import pytest

from app.tools.identity import IdentityInputError, normalize_cpf, parse_birth_date


def test_normalize_cpf_removes_formatting() -> None:
    assert normalize_cpf("000.000.000-00") == "00000000000"


@pytest.mark.parametrize("value", ["", "123", "123456789012", "１２３４５６７８９０１"])
def test_normalize_cpf_rejects_values_without_eleven_digits(value: str) -> None:
    with pytest.raises(IdentityInputError, match="11 digits"):
        normalize_cpf(value)


@pytest.mark.parametrize(
    "value",
    ["20/05/1990", "1990-05-20"],
)
def test_parse_birth_date_accepts_supported_formats(value: str) -> None:
    assert parse_birth_date(value, today=date(2026, 8, 25)) == date(1990, 5, 20)


def test_parse_birth_date_rejects_invalid_format() -> None:
    with pytest.raises(IdentityInputError, match="DD/MM/YYYY"):
        parse_birth_date("20-05-1990", today=date(2026, 8, 25))


def test_parse_birth_date_rejects_future_date() -> None:
    with pytest.raises(IdentityInputError, match="future"):
        parse_birth_date("26/08/2026", today=date(2026, 8, 25))
