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

    customer_by_cpf = repository.get_by_cpf(cpf="00000000000")
    assert customer_by_cpf == customer


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


def test_csv_repository_reports_controlled_data_errors(tmp_path: Path) -> None:
    invalid_cases = [
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
    ]

    for content, message in invalid_cases:
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


def test_csv_repository_updates_credit_limit_atomically(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    repository.update_credit_limit(
        cpf="00000000000",
        credit_limit=Decimal("5000.00"),
    )

    customer = repository.get_by_cpf(cpf="00000000000")
    assert customer is not None
    assert customer.credit_limit == Decimal("5000.00")
    assert not list(tmp_path.glob("*.tmp"))


def test_csv_repository_updates_credit_score_atomically(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    repository.update_credit_score(cpf="00000000000", credit_score=840)

    customer = repository.get_by_cpf(cpf="00000000000")
    assert customer is not None
    assert customer.credit_score == 840
    assert customer.credit_limit == Decimal("2500.00")
    assert not list(tmp_path.glob("*.tmp"))


def test_csv_repository_supports_missing_score_and_restores_blank_value(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "22222222222,Mariana Souza,1995-02-14,1200.00,\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    customer = repository.get_by_cpf(cpf="22222222222")
    assert customer is not None
    assert customer.credit_score is None

    repository.update_credit_score(cpf="22222222222", credit_score=500)
    repository.update_credit_score(cpf="22222222222", credit_score=None)

    restored = repository.get_by_cpf(cpf="22222222222")
    assert restored is not None
    assert restored.credit_score is None


def test_csv_repository_preserves_extra_columns_when_updating_limit(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score,segmento\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650,premium\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    repository.update_credit_limit(
        cpf="00000000000",
        credit_limit=Decimal("5000.00"),
    )

    assert customer_file.read_text(encoding="utf-8").splitlines() == [
        "cpf,nome,data_nascimento,limite_credito,score,segmento",
        "00000000000,Ana Exemplo,1990-05-20,5000.00,650,premium",
    ]


def test_csv_repository_returns_none_for_unknown_cpf(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    assert repository.get_by_cpf(cpf="99999999999") is None


def test_csv_repository_rejects_invalid_credit_updates(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    with pytest.raises(CustomerRepositoryError, match="non-negative"):
        repository.update_credit_limit(
            cpf="00000000000",
            credit_limit=Decimal("-0.01"),
        )
    with pytest.raises(CustomerRepositoryError, match="non-negative"):
        repository.update_credit_limit(
            cpf="00000000000",
            credit_limit=Decimal("Infinity"),
        )
    with pytest.raises(CustomerRepositoryError, match="not found"):
        repository.update_credit_limit(
            cpf="99999999999",
            credit_limit=Decimal("5000.00"),
        )


def test_csv_repository_rejects_invalid_score_updates(tmp_path: Path) -> None:
    repository = CsvCustomerRepository(tmp_path / "unused.csv")

    for score in [-1, 1001, True]:
        with pytest.raises(CustomerRepositoryError, match="between 0 and 1000"):
            repository.update_credit_score(cpf="00000000000", credit_score=score)


def test_csv_repository_rejects_duplicate_cpf_for_credit_operations(tmp_path: Path) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana,1990-05-20,2500.00,650\n"
        "00000000000,Ana duplicada,1991-05-20,3000.00,700\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    with pytest.raises(CustomerRepositoryError, match="cpf is duplicated"):
        repository.get_by_cpf(cpf="00000000000")
    with pytest.raises(CustomerRepositoryError, match="cpf is duplicated"):
        repository.update_credit_limit(
            cpf="00000000000",
            credit_limit=Decimal("5000.00"),
        )


def test_csv_repository_cleans_temporary_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    def fail_replace(source: Path, target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(CustomerRepositoryError, match="could not be updated"):
        repository.update_credit_limit(
            cpf="00000000000",
            credit_limit=Decimal("5000.00"),
        )
    assert not list(tmp_path.glob("*.tmp"))


def test_csv_repository_wraps_failure_before_temporary_file_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    repository = CsvCustomerRepository(customer_file)

    def fail_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        raise OSError("simulated mkdir failure")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(CustomerRepositoryError, match="could not be updated"):
        repository.update_credit_limit(
            cpf="00000000000",
            credit_limit=Decimal("5000.00"),
        )
