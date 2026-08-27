import csv
from pathlib import Path

from app.bootstrap import Application, build_application
from app.config import Settings
from app.models.conversation import ConversationState

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


def build_test_application(tmp_path: Path) -> tuple[Application, Settings]:
    customer_file = tmp_path / "clientes.csv"
    customer_file.write_text(
        "cpf,nome,data_nascimento,limite_credito,score\n"
        "00000000000,Ana Exemplo,1990-05-20,2500.00,650\n",
        encoding="utf-8",
    )
    score_policy_file = tmp_path / "score_limite.csv"
    score_policy_file.write_text(
        "score_minimo,score_maximo,limite_maximo\n0,1000,5000.00\n",
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


def authenticate_and_route_to_credit(application: Application) -> ConversationState:
    state = application.workflow.start()
    state = application.workflow.respond(state, "00000000000")
    state = application.workflow.respond(state, "20/05/1990")
    return application.workflow.respond(state, "Quero aumentar meu limite")


def test_approved_credit_flow_updates_customer_request_and_safe_audit(tmp_path: Path) -> None:
    application, settings = build_test_application(tmp_path)
    state = authenticate_and_route_to_credit(application)

    state = application.workflow.respond(state, "R$ 5.000,00")

    assert state["active_agent"] == "triage"
    assert "aprovada" in state["assistant_message"]
    with settings.customer_file.open(newline="", encoding="utf-8") as customer_file:
        customer = next(csv.DictReader(customer_file))
    assert customer["limite_credito"] == "5000.00"
    with settings.credit_request_file.open(newline="", encoding="utf-8") as request_file:
        request = next(csv.DictReader(request_file))
    assert request["status_pedido"] == "aprovado"
    assert request["novo_limite_solicitado"] == "5000.00"

    serialized_audit = settings.audit_file.read_text(encoding="utf-8")
    assert "credit_decision_made" in serialized_audit
    assert "score-limit-csv-v1" in serialized_audit
    assert "00000000000" not in serialized_audit
    assert "5000" not in serialized_audit


def test_rejected_credit_flow_offers_interview_handoff(tmp_path: Path) -> None:
    application, settings = build_test_application(tmp_path)
    state = authenticate_and_route_to_credit(application)
    state = application.workflow.respond(state, "6000")

    assert state["credit_stage"] == "offering_interview"
    assert "entrevista" in state["assistant_message"]

    state = application.workflow.respond(state, "sim")

    assert state["active_agent"] == "interview"
    with settings.credit_request_file.open(newline="", encoding="utf-8") as request_file:
        request = next(csv.DictReader(request_file))
    assert request["status_pedido"] == "rejeitado"
