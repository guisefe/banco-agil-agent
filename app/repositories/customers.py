import csv
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from app.models.customer import Customer

REQUIRED_CUSTOMER_COLUMNS = frozenset({"cpf", "nome", "data_nascimento", "limite_credito", "score"})


class CustomerRepositoryError(RuntimeError):
    """Raised when customer data cannot be read safely."""


class CustomerRepository(Protocol):
    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        """Return the matching customer or None when the identity does not match."""


class CsvCustomerRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        try:
            with self._path.open(newline="", encoding="utf-8") as customer_file:
                reader = csv.DictReader(customer_file)
                self._validate_columns(reader.fieldnames)
                matches = [
                    row
                    for row in reader
                    if row.get("cpf", "").strip() == cpf
                    and row.get("data_nascimento", "").strip() == birth_date.isoformat()
                ]
        except (OSError, UnicodeError, csv.Error) as error:
            raise CustomerRepositoryError("customer data is unavailable") from error

        if not matches:
            return None
        if len(matches) > 1:
            raise CustomerRepositoryError("customer identity is duplicated")

        return self._to_customer(matches[0])

    @staticmethod
    def _validate_columns(fieldnames: Sequence[str] | None) -> None:
        if fieldnames is None:
            raise CustomerRepositoryError("customer data has no header")

        missing_columns = REQUIRED_CUSTOMER_COLUMNS.difference(fieldnames)
        if missing_columns:
            raise CustomerRepositoryError("customer data has an invalid schema")

    @staticmethod
    def _to_customer(row: dict[str, str]) -> Customer:
        try:
            return Customer(
                cpf=row["cpf"].strip(),
                name=row["nome"].strip(),
                birth_date=date.fromisoformat(row["data_nascimento"].strip()),
                credit_limit=Decimal(row["limite_credito"].strip()),
                credit_score=int(row["score"].strip()),
            )
        except (KeyError, ValueError, InvalidOperation) as error:
            raise CustomerRepositoryError("customer record is invalid") from error
