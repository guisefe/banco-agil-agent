import csv
import json
from pathlib import Path

from app.bootstrap import Application, build_application
from app.config import Settings
from app.models.conversation import ConversationState

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


def build_test_application(
    tmp_path: Path,
    *,
    initial_score: str = "650",
) -> tuple[Application, Settings]:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        f"00000000000,Ana Exemplo,1990-05-20,2500.00,{initial_score}\n",
        encoding="utf-8",
    )
    score_policy_file = tmp_path / "score_limite.csv"
    score_policy_file.write_text(
        "score_minimo,score_maximo,limite_maximo\n0,699,5000.00\n700,1000,10000.00\n",
        encoding="utf-8",
    )
    settings = Settings(
        project_root=tmp_path,
        customer_file=customer_file,
        score_policy_file=score_policy_file,
        credit_request_file=tmp_path / "solicitacoes_aumento_limite.csv",
        audit_file=tmp_path / "audit.jsonl",
        exchange_api_key=None,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
        uses_ephemeral_audit_key=False,
    )
    return build_application(settings=settings), settings


def send_messages(
    application: Application,
    messages: tuple[str, ...],
) -> ConversationState:
    state = application.workflow.start()
    for message in messages:
        state = application.workflow.respond(state, message)
    return state


def test_interview_updates_score_and_approves_original_request(tmp_path: Path) -> None:
    application, settings = build_test_application(tmp_path)

    state = send_messages(
        application,
        (
            "00000000000",
            "20/05/1990",
            "aumento de limite",
            "6000",
            "sim",
            "10000",
            "formal",
            "1000",
            "0",
            "não",
        ),
    )

    assert state["active_agent"] == "triage"
    assert "aprovada" in state["assistant_message"]
    with settings.customer_file.open(newline="", encoding="utf-8") as customer_file:
        customer = next(csv.DictReader(customer_file))
    assert customer["score"] == "800"
    assert customer["limite_credito"] == "6000.00"

    with settings.credit_request_file.open(newline="", encoding="utf-8") as request_file:
        requests = list(csv.DictReader(request_file))
    assert [request["status_pedido"] for request in requests] == ["rejeitado", "aprovado"]

    events = [
        json.loads(line) for line in settings.audit_file.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["policy_version"] == "credit-interview-score-v1" for event in events)
    forbidden_fields = {
        "cpf",
        "monthly_income",
        "fixed_expenses",
        "dependents",
        "has_active_debts",
        "credit_score",
    }
    for event in events:
        assert forbidden_fields.isdisjoint(event)
        assert event["subject_ref"] != "00000000000"


def test_direct_interview_returns_to_credit_without_creating_request(tmp_path: Path) -> None:
    application, settings = build_test_application(tmp_path)

    state = send_messages(
        application,
        (
            "00000000000",
            "20/05/1990",
            "entrevista financeira",
            "5000",
            "autônomo",
            "2500",
            "2",
            "sim",
        ),
    )

    assert state["active_agent"] == "credit"
    assert "score foi recalculado" in state["assistant_message"]
    assert not settings.credit_request_file.exists()


def test_missing_score_request_is_finalized_after_interview(tmp_path: Path) -> None:
    application, settings = build_test_application(tmp_path, initial_score="")

    state = send_messages(
        application,
        (
            "00000000000",
            "20/05/1990",
            "quero aumentar meu limite",
            "6000",
            "sim",
            "10000",
            "formal",
            "1000",
            "0",
            "não",
        ),
    )

    assert state["active_agent"] == "triage"
    assert "aprovada" in state["assistant_message"]
    with settings.customer_file.open(newline="", encoding="utf-8") as customer_file:
        customer = next(csv.DictReader(customer_file))
    assert 0 <= int(customer["score"]) <= 1000

    with settings.credit_request_file.open(newline="", encoding="utf-8") as request_file:
        requests = list(csv.DictReader(request_file))
    assert len(requests) == 1
    assert requests[0]["status_pedido"] == "aprovado"
