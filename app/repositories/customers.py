import csv
import os
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Protocol

from app.models.customer import Customer

REQUIRED_CUSTOMER_COLUMNS = frozenset({"cpf", "nome", "data_nascimento", "limite_credito", "score"})
_CUSTOMER_WRITE_LOCK = Lock()


class CustomerRepositoryError(RuntimeError):
    """Raised when customer data cannot be read safely."""


class CustomerRepository(Protocol):
    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        """Return the matching customer or None when the identity does not match."""


class CreditCustomerRepository(Protocol):
    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        """Return one customer by CPF or None when it does not exist."""

    def update_credit_limit(self, *, cpf: str, credit_limit: Decimal) -> None:
        """Persist the approved credit limit for one customer."""


class InterviewCustomerRepository(Protocol):
    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        """Return one customer by CPF or None when it does not exist."""

    def update_credit_score(self, *, cpf: str, credit_score: int | None) -> None:
        """Persist the recalculated score for one customer."""


class CsvCustomerRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        customers = self._read_customers()
        matches = [
            customer
            for customer in customers
            if customer.cpf == cpf and customer.birth_date == birth_date
        ]
        return self._one_or_none(matches, duplicate_message="customer identity is duplicated")

    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        matches = [customer for customer in self._read_customers() if customer.cpf == cpf]
        return self._one_or_none(matches, duplicate_message="customer cpf is duplicated")

    def update_credit_limit(self, *, cpf: str, credit_limit: Decimal) -> None:
        if not credit_limit.is_finite() or credit_limit < 0:
            raise CustomerRepositoryError("credit limit must be non-negative")
        self._update_field(
            cpf=cpf,
            field_name="limite_credito",
            value=f"{credit_limit:.2f}",
        )

    def update_credit_score(self, *, cpf: str, credit_score: int | None) -> None:
        if credit_score is not None and (
            isinstance(credit_score, bool) or not 0 <= credit_score <= 1000
        ):
            raise CustomerRepositoryError("credit score must be between 0 and 1000")
        self._update_field(
            cpf=cpf,
            field_name="score",
            value="" if credit_score is None else str(credit_score),
        )

    def _update_field(self, *, cpf: str, field_name: str, value: str) -> None:
        with _CUSTOMER_WRITE_LOCK:
            rows, fieldnames = self._read_rows()
            matches = [row for row in rows if row.get("cpf", "").strip() == cpf]
            if not matches:
                raise CustomerRepositoryError("customer was not found")
            if len(matches) > 1:
                raise CustomerRepositoryError("customer cpf is duplicated")
            matches[0][field_name] = value
            self._replace_rows(rows, fieldnames=fieldnames)

    def _read_customers(self) -> list[Customer]:
        rows, _ = self._read_rows()
        return [self._to_customer(row) for row in rows]

    def _read_rows(self) -> tuple[list[dict[str, str]], list[str]]:
        try:
            with self._path.open(newline="", encoding="utf-8") as customer_file:
                reader = csv.DictReader(customer_file)
                self._validate_columns(reader.fieldnames)
                fieldnames = list(reader.fieldnames or ())
                return list(reader), fieldnames
        except (OSError, UnicodeError, csv.Error) as error:
            raise CustomerRepositoryError("customer data is unavailable") from error

    @staticmethod
    def _one_or_none(matches: list[Customer], *, duplicate_message: str) -> Customer | None:
        if not matches:
            return None
        if len(matches) > 1:
            raise CustomerRepositoryError(duplicate_message)
        return matches[0]

    def _replace_rows(self, rows: list[dict[str, str]], *, fieldnames: list[str]) -> None:
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                writer = csv.DictWriter(
                    temporary_file,
                    fieldnames=fieldnames,
                )
                writer.writeheader()
                writer.writerows(rows)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            temporary_path.replace(self._path)
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise CustomerRepositoryError("customer data could not be updated") from error

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
                credit_score=(int(row["score"].strip()) if row["score"].strip() else None),
            )
        except (KeyError, ValueError, InvalidOperation) as error:
            raise CustomerRepositoryError("customer record is invalid") from error
