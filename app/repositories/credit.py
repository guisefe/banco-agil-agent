import csv
import os
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Literal, Protocol

from app.models.credit import CreditRequest, ScoreBand

SCORE_POLICY_VERSION = "score-limit-csv-v1"
REQUIRED_SCORE_COLUMNS = frozenset({"score_minimo", "score_maximo", "limite_maximo"})
CREDIT_REQUEST_COLUMNS = (
    "cpf_cliente",
    "data_hora_solicitacao",
    "limite_atual",
    "novo_limite_solicitado",
    "status_pedido",
)
_REQUEST_WRITE_LOCK = Lock()


class CreditRepositoryError(RuntimeError):
    """Raised when credit policy or request data cannot be handled safely."""


class ScorePolicyRepository(Protocol):
    def maximum_limit_for(self, *, score: int) -> Decimal:
        """Return the maximum limit allowed by the active score policy."""


class CreditRequestRepository(Protocol):
    def append(self, request: CreditRequest) -> None:
        """Persist one final credit request using the challenge schema."""

    def finalize_pending(
        self,
        *,
        customer_cpf: str,
        requested_at: datetime,
        status: Literal["aprovado", "rejeitado"],
    ) -> None:
        """Replace exactly one pending request with its final status."""


class CsvScorePolicyRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def maximum_limit_for(self, *, score: int) -> Decimal:
        if not 0 <= score <= 1000:
            raise CreditRepositoryError("score must be between 0 and 1000")
        bands = self._read_bands()
        matches = [band for band in bands if band.minimum_score <= score <= band.maximum_score]
        if len(matches) != 1:
            raise CreditRepositoryError("credit policy does not define exactly one score band")
        return matches[0].maximum_limit

    def _read_bands(self) -> list[ScoreBand]:
        try:
            with self._path.open(newline="", encoding="utf-8") as policy_file:
                reader = csv.DictReader(policy_file)
                self._validate_columns(reader.fieldnames)
                return [
                    ScoreBand(
                        minimum_score=int(row["score_minimo"].strip()),
                        maximum_score=int(row["score_maximo"].strip()),
                        maximum_limit=Decimal(row["limite_maximo"].strip()),
                    )
                    for row in reader
                ]
        except (OSError, UnicodeError, csv.Error, KeyError, ValueError, InvalidOperation) as error:
            raise CreditRepositoryError("credit policy data is unavailable or invalid") from error

    @staticmethod
    def _validate_columns(fieldnames: Sequence[str] | None) -> None:
        if fieldnames is None or REQUIRED_SCORE_COLUMNS.difference(fieldnames):
            raise CreditRepositoryError("credit policy data has an invalid schema")


class CsvCreditRequestRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, request: CreditRequest) -> None:
        row = {
            "cpf_cliente": request.customer_cpf,
            "data_hora_solicitacao": request.requested_at.isoformat(),
            "limite_atual": f"{request.current_limit:.2f}",
            "novo_limite_solicitado": f"{request.requested_limit:.2f}",
            "status_pedido": request.status,
        }
        with _REQUEST_WRITE_LOCK:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                write_header = not self._path.exists() or self._path.stat().st_size == 0
                if self._path.exists() and not write_header:
                    self._validate_existing_header()
                with self._path.open("a", newline="", encoding="utf-8") as request_file:
                    writer = csv.DictWriter(request_file, fieldnames=CREDIT_REQUEST_COLUMNS)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(row)
                    request_file.flush()
                    os.fsync(request_file.fileno())
            except (OSError, UnicodeError, csv.Error) as error:
                raise CreditRepositoryError("credit request could not be recorded") from error

    def finalize_pending(
        self,
        *,
        customer_cpf: str,
        requested_at: datetime,
        status: Literal["aprovado", "rejeitado"],
    ) -> None:
        requested_at_value = requested_at.isoformat()
        with _REQUEST_WRITE_LOCK:
            temporary_path: Path | None = None
            try:
                rows = self._read_rows()
                matches = [
                    row
                    for row in rows
                    if row["cpf_cliente"] == customer_cpf
                    and row["data_hora_solicitacao"] == requested_at_value
                    and row["status_pedido"] == "pendente"
                ]
                if len(matches) != 1:
                    raise CreditRepositoryError("pending credit request was not found exactly once")
                matches[0]["status_pedido"] = status
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
                        fieldnames=CREDIT_REQUEST_COLUMNS,
                    )
                    writer.writeheader()
                    writer.writerows(rows)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                temporary_path.replace(self._path)
            except CreditRepositoryError:
                raise
            except (OSError, UnicodeError, csv.Error, KeyError, ValueError) as error:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise CreditRepositoryError(
                    "pending credit request could not be finalized"
                ) from error

    def _read_rows(self) -> list[dict[str, str]]:
        with self._path.open(newline="", encoding="utf-8") as request_file:
            reader = csv.DictReader(request_file)
            if list(reader.fieldnames or ()) != list(CREDIT_REQUEST_COLUMNS):
                raise CreditRepositoryError("credit request data has an invalid schema")
            return list(reader)

    def _validate_existing_header(self) -> None:
        with self._path.open(newline="", encoding="utf-8") as request_file:
            reader = csv.reader(request_file)
            header = next(reader, None)
        if header != list(CREDIT_REQUEST_COLUMNS):
            raise CreditRepositoryError("credit request data has an invalid schema")
