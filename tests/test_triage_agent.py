from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.agents.triage import TriageAgent
from app.audit.events import AuditEvent
from app.audit.writer import AuditWriteError
from app.models.conversation import ConversationState, initial_state
from app.models.customer import Customer
from app.models.intent import IntentInterpretation
from app.repositories.customers import CustomerRepositoryError
from app.services.understanding import IntentInterpreter

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class RecordingAuditWriter:
    events: list[AuditEvent] = field(default_factory=list)
    failing_event_type: str | None = None

    def append(self, event: AuditEvent) -> None:
        if event.event_type == self.failing_event_type:
            raise AuditWriteError("simulated audit failure")
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
    intent_interpreter: IntentInterpreter | None = None,
) -> tuple[TriageAgent, StubCustomerRepository, RecordingAuditWriter]:
    repository = StubCustomerRepository(customer=customer, error=repository_error)
    audit_writer = RecordingAuditWriter()
    agent = TriageAgent(
        customer_repository=repository,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
        intent_interpreter=intent_interpreter,
    )
    return agent, repository, audit_writer


def started_state(agent: TriageAgent) -> ConversationState:
    return agent.activate(initial_state(), "Olá")


def authenticate(agent: TriageAgent) -> ConversationState:
    state = agent.activate(initial_state(), "000.000.000-00")
    return agent.respond(state, "20/05/1990")


def test_triage_activates_after_user_greeting_and_records_audit_event() -> None:
    agent, _, audit_writer = make_agent()

    state = started_state(agent)

    assert state["triage_stage"] == "awaiting_cpf"
    assert "CPF" in state["assistant_message"]
    assert state["pending_initial_request"] == "Olá"
    assert state["last_interpretation_source"] is None
    assert audit_writer.events[0].event_type == "conversation_started"


def test_triage_rejects_invalid_cpf_without_consuming_attempt() -> None:
    agent, repository, _ = make_agent()
    state = started_state(agent)

    state = agent.respond(state, "123")

    assert state["triage_stage"] == "awaiting_cpf"
    assert state["user_message"] == "[REDACTED_CPF_INPUT]"
    assert state["authentication_attempts"] == 0
    assert repository.calls == 0


def test_triage_rejects_invalid_date_without_consuming_attempt() -> None:
    agent, repository, _ = make_agent()
    state = started_state(agent)
    state = agent.respond(state, "00000000000")

    state = agent.respond(state, "20-05-1990")

    assert state["triage_stage"] == "awaiting_birth_date"
    assert state["user_message"] == "[REDACTED_BIRTH_DATE_INPUT]"
    assert state["authentication_attempts"] == 0
    assert repository.calls == 0


def test_triage_authenticates_and_routes_credit_after_identity_confirmation() -> None:
    agent, _, audit_writer = make_agent(customer=make_customer())

    state = authenticate(agent)

    assert state["authenticated"] is True
    assert state["user_message"] == "[REDACTED_BIRTH_DATE]"
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


def test_triage_routes_supported_intents() -> None:
    scenarios = [
        ("Quero fazer uma entrevista financeira", "interview"),
        ("Quero uma entrevista de crédito", "interview"),
        ("Quero falar sobre crédito", "credit"),
        ("Qual é a cotação do dólar?", "exchange"),
    ]

    for message, expected_agent in scenarios:
        agent, _, _ = make_agent(customer=make_customer())
        state = agent.respond(authenticate(agent), message)
        assert state["active_agent"] == expected_agent


def test_triage_routes_explicit_score_recalculation_to_interview() -> None:
    agent, _, _ = make_agent(customer=make_customer())
    state = authenticate(agent)

    state = agent.respond(state, "quero recalcular score")

    assert state["active_agent"] == "interview"


@dataclass
class StubIntentInterpreter:
    interpretation: IntentInterpretation
    messages: list[str] = field(default_factory=list)

    def interpret(self, message: str) -> IntentInterpretation:
        self.messages.append(message)
        return self.interpretation


def test_triage_uses_llm_interpretation_only_after_authentication() -> None:
    interpreter = StubIntentInterpreter(
        IntentInterpretation(intent="credit_limit_adjustment", source="llm")
    )
    agent, _, audit = make_agent(
        customer=make_customer(),
        intent_interpreter=interpreter,
    )
    state = authenticate(agent)

    state = agent.respond(state, "preciso de um fôlego maior no cartão")

    assert interpreter.messages == ["preciso de um fôlego maior no cartão"]
    assert state["active_agent"] == "credit"
    assert state["interpreted_intent"] == "credit_limit_adjustment"
    assert [event.event_type for event in audit.events[-2:]] == [
        "intent_interpreted",
        "agent_handoff",
    ]
    assert audit.events[-2].reason_code == "INTENT_INTERPRETED_BY_LLM"
    assert "fôlego" not in repr(audit.events)


def test_triage_records_deterministic_fallback_without_exposing_message() -> None:
    interpreter = StubIntentInterpreter(
        IntentInterpretation(
            intent="credit_score_query",
            source="deterministic_fallback",
        )
    )
    agent, _, audit = make_agent(
        customer=make_customer(),
        intent_interpreter=interpreter,
    )
    state = authenticate(agent)

    state = agent.respond(state, "qual é meu score secreto?")

    assert state["active_agent"] == "credit"
    assert audit.events[-2].reason_code == "LLM_INTENT_FALLBACK_USED"
    assert "secreto" not in repr(audit.events)


def test_triage_does_not_block_llm_routing_when_telemetry_audit_fails() -> None:
    interpreter = StubIntentInterpreter(
        IntentInterpretation(intent="credit_limit_query", source="llm")
    )
    agent, _, audit = make_agent(
        customer=make_customer(),
        intent_interpreter=interpreter,
    )
    state = authenticate(agent)
    audit.failing_event_type = "intent_interpreted"

    state = agent.respond(state, "qual é meu limite?")

    assert state["active_agent"] == "credit"


def test_triage_requests_clarification_for_unknown_or_ambiguous_intent() -> None:
    for message in ["Preciso de ajuda", "Quero ver meu limite e a cotação do dólar"]:
        agent, _, _ = make_agent(customer=make_customer())
        state = agent.respond(authenticate(agent), message)
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
