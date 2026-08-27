import csv
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.credit import CreditRequest
from app.repositories.credit import (
    CreditRepositoryError,
    CsvCreditRequestRepository,
    CsvScorePolicyRepository,
)


def test_score_policy_resolves_boundary_scores(tmp_path: Path) -> None:
    path = tmp_path / "score_limite.csv"
    path.write_text(
        "score_minimo,score_maximo,limite_maximo\n0,499,2500.00\n500,1000,10000.00\n",
        encoding="utf-8",
    )
    repository = CsvScorePolicyRepository(path)

    assert repository.maximum_limit_for(score=0) == Decimal("2500.00")
    assert repository.maximum_limit_for(score=500) == Decimal("10000.00")
    assert repository.maximum_limit_for(score=1000) == Decimal("10000.00")


@pytest.mark.parametrize("score", [-1, 1001])
def test_score_policy_rejects_out_of_range_score(tmp_path: Path, score: int) -> None:
    repository = CsvScorePolicyRepository(tmp_path / "unused.csv")

    with pytest.raises(CreditRepositoryError, match="between"):
        repository.maximum_limit_for(score=score)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "score_minimo,score_maximo\n0,1000\n",
        "score_minimo,score_maximo,limite_maximo\ninvalid,1000,5000\n",
        "score_minimo,score_maximo,limite_maximo\n0,1000,Infinity\n",
    ],
)
def test_score_policy_reports_invalid_data(tmp_path: Path, content: str) -> None:
    path = tmp_path / "score_limite.csv"
    path.write_text(content, encoding="utf-8")
    repository = CsvScorePolicyRepository(path)

    with pytest.raises(CreditRepositoryError):
        repository.maximum_limit_for(score=650)


def test_score_policy_requires_exactly_one_matching_band(tmp_path: Path) -> None:
    path = tmp_path / "score_limite.csv"
    path.write_text(
        "score_minimo,score_maximo,limite_maximo\n0,700,5000\n600,1000,10000\n",
        encoding="utf-8",
    )
    repository = CsvScorePolicyRepository(path)

    with pytest.raises(CreditRepositoryError, match="exactly one"):
        repository.maximum_limit_for(score=650)


def test_score_policy_wraps_missing_file(tmp_path: Path) -> None:
    repository = CsvScorePolicyRepository(tmp_path / "missing.csv")

    with pytest.raises(CreditRepositoryError, match="unavailable"):
        repository.maximum_limit_for(score=650)


def make_credit_request() -> CreditRequest:
    return CreditRequest(
        customer_cpf="00000000000",
        requested_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        current_limit=Decimal("2500.00"),
        requested_limit=Decimal("5000.00"),
        status="aprovado",
    )


def test_credit_request_repository_creates_schema_and_appends_rows(tmp_path: Path) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    repository = CsvCreditRequestRepository(path)

    repository.append(make_credit_request())
    repository.append(make_credit_request())

    with path.open(newline="", encoding="utf-8") as request_file:
        rows = list(csv.DictReader(request_file))
    assert len(rows) == 2
    assert rows[0] == {
        "cpf_cliente": "00000000000",
        "data_hora_solicitacao": "2026-08-26T12:00:00+00:00",
        "limite_atual": "2500.00",
        "novo_limite_solicitado": "5000.00",
        "status_pedido": "aprovado",
    }


def test_credit_request_repository_rejects_existing_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    path.write_text("wrong,header\n", encoding="utf-8")
    repository = CsvCreditRequestRepository(path)

    with pytest.raises(CreditRepositoryError, match="invalid schema"):
        repository.append(make_credit_request())


def test_credit_request_repository_wraps_write_failure(tmp_path: Path) -> None:
    path = tmp_path / "requests"
    path.mkdir()
    repository = CsvCreditRequestRepository(path)

    with pytest.raises(CreditRepositoryError, match="could not be recorded"):
        repository.append(make_credit_request())


def test_credit_request_repository_finalizes_exact_pending_row(tmp_path: Path) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    repository = CsvCreditRequestRepository(path)
    pending = CreditRequest(
        customer_cpf="00000000000",
        requested_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        current_limit=Decimal("2500.00"),
        requested_limit=Decimal("6000.00"),
        status="pendente",
    )
    repository.append(pending)

    repository.finalize_pending(
        customer_cpf=pending.customer_cpf,
        requested_at=pending.requested_at,
        status="aprovado",
    )

    with path.open(newline="", encoding="utf-8") as request_file:
        row = next(csv.DictReader(request_file))
    assert row["status_pedido"] == "aprovado"
    assert not list(tmp_path.glob("*.tmp"))


def test_credit_request_repository_rejects_missing_pending_row(tmp_path: Path) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    path.write_text(
        ",".join(
            (
                "cpf_cliente",
                "data_hora_solicitacao",
                "limite_atual",
                "novo_limite_solicitado",
                "status_pedido",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    repository = CsvCreditRequestRepository(path)

    with pytest.raises(CreditRepositoryError, match="not found exactly once"):
        repository.finalize_pending(
            customer_cpf="00000000000",
            requested_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
            status="rejeitado",
        )


def test_credit_request_repository_rejects_invalid_header_when_finalizing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    path.write_text("wrong,header\n", encoding="utf-8")
    repository = CsvCreditRequestRepository(path)

    with pytest.raises(CreditRepositoryError, match="invalid schema"):
        repository.finalize_pending(
            customer_cpf="00000000000",
            requested_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
            status="rejeitado",
        )


def test_credit_request_repository_cleans_temp_file_when_finalize_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    repository = CsvCreditRequestRepository(path)
    pending = CreditRequest(
        customer_cpf="00000000000",
        requested_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        current_limit=Decimal("2500.00"),
        requested_limit=Decimal("6000.00"),
        status="pendente",
    )
    repository.append(pending)

    def fail_replace(source: Path, target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(CreditRepositoryError, match="could not be finalized"):
        repository.finalize_pending(
            customer_cpf=pending.customer_cpf,
            requested_at=pending.requested_at,
            status="aprovado",
        )
    assert not list(tmp_path.glob("*.tmp"))


def test_credit_request_repository_wraps_failure_before_finalize_temp_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "solicitacoes_aumento_limite.csv"
    repository = CsvCreditRequestRepository(path)
    pending = CreditRequest(
        customer_cpf="00000000000",
        requested_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        current_limit=Decimal("2500.00"),
        requested_limit=Decimal("6000.00"),
        status="pendente",
    )
    repository.append(pending)

    def fail_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        raise OSError("simulated mkdir failure")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(CreditRepositoryError, match="could not be finalized"):
        repository.finalize_pending(
            customer_cpf=pending.customer_cpf,
            requested_at=pending.requested_at,
            status="rejeitado",
        )
