from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from app.agents.triage import TriageAgent
from app.audit.events import AuditEvent
from app.models.conversation import ConversationState, initial_state
from app.models.customer import Customer
from app.repositories.customers import CustomerRepositoryError

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class RecordingAuditWriter:
    events: list[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class StubCustomerRepository:
    def __init__(
        self,
        *,
        customer: Customer | None = None,
        error: CustomerRepositoryError | None = None,
    ) -> None:
        self.customer = customer
        self.error = error
        self.calls = 0

    def find_by_identity(self, *, cpf: str, birth_date: date) -> Customer | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.customer is None:
            return None
        if self.customer.cpf == cpf and self.customer.birth_date == birth_date:
            return self.customer
        return None


def make_customer() -> Customer:
    return Customer(
        cpf="00000000000",
        name="Ana Exemplo",
        birth_date=date(1990, 5, 20),
        credit_limit=Decimal("2500.00"),
        credit_score=650,
    )


def make_agent(
    *,
    customer: Customer | None = None,
    repository_error: CustomerRepositoryError | None = None,
) -> tuple[TriageAgent, StubCustomerRepository, RecordingAuditWriter]:
    repository = StubCustomerRepository(customer=customer, error=repository_error)
    audit_writer = RecordingAuditWriter()
    agent = TriageAgent(
        customer_repository=repository,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )
    return agent, repository, audit_writer


def started_state(agent: TriageAgent) -> ConversationState:
    return agent.start(initial_state())


def authenticate(agent: TriageAgent) -> ConversationState:
    state = started_state(agent)
    state = agent.respond(state, "000.000.000-00")
    return agent.respond(state, "20/05/1990")


def test_triage_starts_with_greeting_and_audit_event() -> None:
    agent, _, audit_writer = make_agent()

    state = started_state(agent)

    assert state["triage_stage"] == "awaiting_cpf"
    assert "CPF" in state["assistant_message"]
    assert audit_writer.events[0].event_type == "conversation_started"


def test_triage_rejects_invalid_cpf_without_consuming_attempt() -> None:
    agent, repository, _ = make_agent()
    state = started_state(agent)

    state = agent.respond(state, "123")

    assert state["triage_stage"] == "awaiting_cpf"
    assert state["authentication_attempts"] == 0
    assert repository.calls == 0


def test_triage_rejects_invalid_date_without_consuming_attempt() -> None:
    agent, repository, _ = make_agent()
    state = started_state(agent)
    state = agent.respond(state, "00000000000")

    state = agent.respond(state, "20-05-1990")

    assert state["triage_stage"] == "awaiting_birth_date"
    assert state["authentication_attempts"] == 0
    assert repository.calls == 0


def test_triage_authenticates_and_routes_credit_after_identity_confirmation() -> None:
    agent, _, audit_writer = make_agent(customer=make_customer())

    state = authenticate(agent)

    assert state["authenticated"] is True
    assert state["cpf"] == "00000000000"
    assert state["birth_date"] == "1990-05-20"
    assert state["customer_name"] == "Ana Exemplo"
    assert state["triage_stage"] == "awaiting_intent"

    state = agent.respond(state, "Quero aumentar meu limite de crédito")

    assert state["active_agent"] == "credit"
    assert [event.event_type for event in audit_writer.events] == [
        "conversation_started",
        "authentication_attempted",
        "agent_handoff",
    ]
    assert all("00000000000" not in repr(event) for event in audit_writer.events)
    assert audit_writer.events[1].reason_code == "IDENTITY_CONFIRMED"
    assert audit_writer.events[2].reason_code == "ROUTED_TO_CREDIT"


def test_triage_ends_after_third_consecutive_identity_failure() -> None:
    agent, _, audit_writer = make_agent()
    state = started_state(agent)

    for expected_attempt in range(1, 4):
        state = agent.respond(state, "00000000000")
        state = agent.respond(state, "20/05/1990")
        assert state["authentication_attempts"] == expected_attempt

    assert state["end_reason"] == "authentication_attempts_exceeded"
    assert state["authenticated"] is False
    assert state["cpf"] is None
    assert state["birth_date"] is None
    assert "três tentativas" in state["assistant_message"]
    assert [event.event_type for event in audit_writer.events].count(
        "authentication_attempted"
    ) == 3
    assert audit_writer.events[-1].event_type == "conversation_ended"
    assert audit_writer.events[-1].reason_code == "AUTHENTICATION_ATTEMPTS_EXCEEDED"


def test_repository_failure_does_not_consume_customer_attempt() -> None:
    agent, repository, audit_writer = make_agent(
        repository_error=CustomerRepositoryError("unavailable")
    )
    state = started_state(agent)
    state = agent.respond(state, "00000000000")

    state = agent.respond(state, "20/05/1990")

    assert repository.calls == 1
    assert state["authentication_attempts"] == 0
    assert state["triage_stage"] == "awaiting_birth_date"
    assert "Tente novamente" in state["assistant_message"]
    assert audit_writer.events[-1].reason_code == "CUSTOMER_REPOSITORY_UNAVAILABLE"


@pytest.mark.parametrize(
    ("message", "expected_agent"),
    [
        ("Quero fazer uma entrevista financeira", "interview"),
        ("Quero uma entrevista de crédito", "interview"),
        ("Quero falar sobre crédito", "credit"),
        ("Qual é a cotação do dólar?", "exchange"),
    ],
)
def test_triage_routes_supported_intents(
    message: str,
    expected_agent: str,
) -> None:
    agent, _, _ = make_agent(customer=make_customer())
    state = authenticate(agent)

    state = agent.respond(state, message)

    assert state["active_agent"] == expected_agent


@pytest.mark.parametrize(
    "message",
    ["Preciso de ajuda", "Quero ver meu limite e a cotação do dólar"],
)
def test_triage_requests_clarification_for_unknown_or_ambiguous_intent(
    message: str,
) -> None:
    agent, _, _ = make_agent(customer=make_customer())
    state = authenticate(agent)

    state = agent.respond(state, message)

    assert state["active_agent"] == "triage"
    assert state["triage_stage"] == "awaiting_intent"
    assert "Qual opção" in state["assistant_message"]


def test_user_can_end_conversation_before_authentication() -> None:
    agent, _, audit_writer = make_agent()
    state = started_state(agent)

    state = agent.respond(state, "Quero encerrar")

    assert state["end_reason"] == "user_requested"
    assert audit_writer.events[-1].event_type == "conversation_ended"
    assert audit_writer.events[-1].subject_ref is None


def test_user_can_end_conversation_after_cpf_collection() -> None:
    agent, _, audit_writer = make_agent()
    state = started_state(agent)
    state = agent.respond(state, "00000000000")

    state = agent.respond(state, "sair")

    assert state["end_reason"] == "user_requested"
    assert state["cpf"] is None
    assert audit_writer.events[-1].subject_ref is not None
    assert "00000000000" not in audit_writer.events[-1].subject_ref


def test_triage_rejects_short_pseudonymization_key() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        TriageAgent(
            customer_repository=StubCustomerRepository(),
            audit_writer=RecordingAuditWriter(),
            pseudonymization_key=b"short",
        )


def test_triage_rejects_invalid_lifecycle_calls() -> None:
    agent, _, _ = make_agent(customer=make_customer())
    initial = initial_state()

    with pytest.raises(ValueError, match="not ready"):
        agent.respond(initial, "00000000000")

    state = started_state(agent)
    with pytest.raises(ValueError, match="initial conversation state"):
        agent.start(state)

    ended_state = agent.respond(state, "fim")
    with pytest.raises(ValueError, match="already ended"):
        agent.respond(ended_state, "oi")

    authenticated_state = authenticate(agent)
    handed_off_state = agent.respond(authenticated_state, "crédito")
    with pytest.raises(ValueError, match="after a handoff"):
        agent.respond(handed_off_state, "oi")


def test_triage_rejects_birth_date_stage_without_cpf() -> None:
    agent, _, _ = make_agent()
    state = started_state(agent)
    state["triage_stage"] = "awaiting_birth_date"

    with pytest.raises(ValueError, match="cpf is required"):
        agent.respond(state, "20/05/1990")
