from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.repositories.customers import CsvCustomerRepository, CustomerRepositoryError


def test_csv_repository_finds_customer_by_exact_identity(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    customer = repository.find_by_identity(
        cpf="00000000000",
        birth_date=date(1990, 5, 20),
    )

    assert customer is not None
    assert customer.name == "Ana Exemplo"
    assert customer.credit_limit == Decimal("2500.00")
    assert customer.credit_score == 650


def test_csv_repository_returns_none_for_identity_mismatch(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    customer = repository.find_by_identity(
        cpf="00000000000",
        birth_date=date(1991, 5, 20),
    )

    assert customer is None


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "no header"),
        ("cpf,nome\n00000000000,Ana\n", "invalid schema"),
        (
            "cpf,nome,data_nascimento,limite_credito,score\n"
            "00000000000,Ana,1990-05-20,invalid,650\n",
            "record is invalid",
        ),
        (
            "cpf,nome,data_nascimento,limite_credito,score\n"
            "00000000000,Ana,1990-05-20,1000,650\n"
            "00000000000,Ana duplicada,1990-05-20,1000,650\n",
            "duplicated",
        ),
    ],
)
def test_csv_repository_reports_controlled_data_errors(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(content, encoding="utf-8")
    repository = CsvCustomerRepository(customer_file)

    with pytest.raises(CustomerRepositoryError, match=message):
        repository.find_by_identity(
            cpf="00000000000",
            birth_date=date(1990, 5, 20),
        )


def test_csv_repository_wraps_file_errors(tmp_path: Path) -> None:
    repository = CsvCustomerRepository(tmp_path / "missing.csv")

    with pytest.raises(CustomerRepositoryError, match="unavailable"):
        repository.find_by_identity(
            cpf="00000000000",
            birth_date=date(1990, 5, 20),
        )
