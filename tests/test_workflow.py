from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from app.agents.triage import TriageAgent
from app.audit.events import AuditEvent
from app.graph.workflow import AgentUnavailableError, ConversationWorkflow
from app.models.customer import Customer

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class RecordingAuditWriter:
    events: list[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class CustomerRepositoryStub:
    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        if cpf != "00000000000" or birth_date != date(1990, 5, 20):
            return None
        return Customer(
            cpf=cpf,
            name="Ana Exemplo",
            birth_date=birth_date,
            credit_limit=Decimal("2500.00"),
            credit_score=650,
        )


def make_workflow() -> ConversationWorkflow:
    triage_agent = TriageAgent(
        customer_repository=CustomerRepositoryStub(),
        audit_writer=RecordingAuditWriter(),
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )
    return ConversationWorkflow(triage_agent=triage_agent)


def test_workflow_runs_triage_turns_through_langgraph() -> None:
    workflow = make_workflow()

    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "Quero consultar meu limite")

    assert state["authenticated"] is True
    assert state["active_agent"] == "credit"
    assert state["turn_number"] == 3


def test_workflow_rejects_unimplemented_destination_agent() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "cotação do dólar")

    with pytest.raises(AgentUnavailableError, match="exchange"):
        workflow.respond(state, "USD")


def test_workflow_rejects_message_after_end() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "encerrar")

    with pytest.raises(ValueError, match="already ended"):
        workflow.respond(state, "oi")
