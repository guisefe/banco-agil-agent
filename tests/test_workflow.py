from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

import pytest

from app.agents.credit import CreditAgent
from app.agents.interview import CreditInterviewAgent
from app.agents.triage import TriageAgent
from app.audit.events import AuditEvent
from app.graph.workflow import AgentUnavailableError, ConversationWorkflow
from app.models.credit import CreditRequest
from app.models.customer import Customer
from app.repositories.credit import CreditRepositoryError
from app.repositories.customers import CustomerRepositoryError

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class RecordingAuditWriter:
    events: list[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class CustomerRepositoryStub:
    def __init__(self) -> None:
        self.customer = Customer(
            cpf="00000000000",
            name="Ana Exemplo",
            birth_date=date(1990, 5, 20),
            credit_limit=Decimal("2500.00"),
            credit_score=650,
        )

    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        if cpf != "00000000000" or birth_date != date(1990, 5, 20):
            return None
        return self.customer

    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        return self.customer if cpf == self.customer.cpf else None

    def update_credit_limit(self, *, cpf: str, credit_limit: Decimal) -> None:
        if cpf != self.customer.cpf:
            raise CustomerRepositoryError("not found")
        self.customer = replace(self.customer, credit_limit=credit_limit)

    def update_credit_score(self, *, cpf: str, credit_score: int) -> None:
        if cpf != self.customer.cpf:
            raise CustomerRepositoryError("not found")
        self.customer = replace(self.customer, credit_score=credit_score)


class ScorePolicyRepositoryStub:
    def maximum_limit_for(self, *, score: int) -> Decimal:
        if not 0 <= score <= 1000:
            raise CreditRepositoryError("invalid score")
        return Decimal("10000.00") if score >= 700 else Decimal("5000.00")


class CreditRequestRepositoryStub:
    def __init__(self) -> None:
        self.requests: list[CreditRequest] = []

    def append(self, request: CreditRequest) -> None:
        self.requests.append(request)


def make_workflow() -> ConversationWorkflow:
    audit_writer = RecordingAuditWriter()
    customer_repository = CustomerRepositoryStub()
    triage_agent = TriageAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )
    credit_agent = CreditAgent(
        customer_repository=customer_repository,
        score_policy_repository=ScorePolicyRepositoryStub(),
        request_repository=CreditRequestRepositoryStub(),
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )
    interview_agent = CreditInterviewAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )
    return ConversationWorkflow(
        triage_agent=triage_agent,
        credit_agent=credit_agent,
        interview_agent=interview_agent,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )


def test_workflow_runs_triage_turns_through_langgraph() -> None:
    workflow = make_workflow()

    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "Quero consultar meu limite")

    assert state["authenticated"] is True
    assert state["active_agent"] == "credit"
    assert state["turn_number"] == 3

    state = workflow.respond(state, "consultar limite atual")

    assert state["active_agent"] == "triage"
    assert "R$ 2.500,00" in state["assistant_message"]


def test_workflow_rejects_unimplemented_destination_agent() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "cotação do dólar")

    with pytest.raises(AgentUnavailableError, match="exchange"):
        workflow.respond(state, "USD")


def test_workflow_runs_interview_and_reanalyzes_pending_limit() -> None:
    workflow = make_workflow()
    state = workflow.start()
    for message in (
        "00000000000",
        "20/05/1990",
        "aumento de limite",
        "aumentar",
        "6000",
        "sim",
        "10000",
        "formal",
        "1000",
        "0",
        "não",
    ):
        state = workflow.respond(state, message)

    assert state["active_agent"] == "triage"
    assert state["requested_credit_limit"] is None
    assert "aprovada" in state["assistant_message"]


def test_workflow_completes_direct_interview_without_pending_limit() -> None:
    workflow = make_workflow()
    state = workflow.start()
    for message in (
        "00000000000",
        "20/05/1990",
        "entrevista financeira",
        "10000",
        "formal",
        "1000",
        "0",
        "não",
    ):
        state = workflow.respond(state, message)

    assert state["active_agent"] == "credit"
    assert state["requested_credit_limit"] is None
    assert "score foi recalculado" in state["assistant_message"]


def test_workflow_rejects_message_after_end() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "encerrar")

    with pytest.raises(ValueError, match="already ended"):
        workflow.respond(state, "oi")


def test_workflow_allows_global_end_request_after_credit_handoff() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "crédito")

    state = workflow.respond(state, "encerrar")

    assert state["end_reason"] == "user_requested"
    assert state["cpf"] is None


def test_workflow_allows_global_end_request_during_interview() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "entrevista")
    state = workflow.respond(state, "5000")

    state = workflow.respond(state, "encerrar")

    assert state["end_reason"] == "user_requested"
    assert state["monthly_income"] is None


def test_workflow_does_not_block_end_when_audit_is_unavailable() -> None:
    workflow = make_workflow()
    workflow._audit_writer = FailingAuditWriter()
    state = workflow.start()

    state = workflow.respond(state, "encerrar")

    assert state["end_reason"] == "user_requested"


class FailingAuditWriter:
    def append(self, event: AuditEvent) -> None:
        from app.audit.writer import AuditWriteError

        raise AuditWriteError("unavailable")
