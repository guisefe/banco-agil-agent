from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest

from app.agents.interview import CreditInterviewAgent
from app.audit.events import AuditEvent
from app.audit.writer import AuditWriteError
from app.models.conversation import ConversationState, initial_state
from app.models.customer import Customer
from app.repositories.customers import CustomerRepositoryError

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class CustomerRepositoryStub:
    error: bool = False
    fail_on_update: int | None = None
    updates: list[int] = field(default_factory=list)
    update_count: int = 0
    customer: Customer | None = field(
        default_factory=lambda: Customer(
            cpf="00000000000",
            name="Ana Exemplo",
            birth_date=date(1990, 5, 20),
            credit_limit=Decimal("2500.00"),
            credit_score=650,
        )
    )

    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        if self.error:
            raise CustomerRepositoryError("read failed")
        if self.customer is None or self.customer.cpf != cpf:
            return None
        return self.customer

    def update_credit_score(self, *, cpf: str, credit_score: int) -> None:
        self.update_count += 1
        if (
            self.error
            or self.update_count == self.fail_on_update
            or self.customer is None
            or self.customer.cpf != cpf
        ):
            raise CustomerRepositoryError("update failed")
        self.updates.append(credit_score)
        self.customer = replace(self.customer, credit_score=credit_score)


@dataclass
class AuditWriterStub:
    error: bool = False
    fail_on_append: int | None = None
    events: list[AuditEvent] = field(default_factory=list)
    append_count: int = 0

    def append(self, event: AuditEvent) -> None:
        self.append_count += 1
        if self.error or self.append_count == self.fail_on_append:
            raise AuditWriteError("audit unavailable")
        self.events.append(event)


def make_state(*, requested_limit: Decimal | None = None) -> ConversationState:
    state = initial_state()
    state["authenticated"] = True
    state["cpf"] = "00000000000"
    state["customer_name"] = "Ana Exemplo"
    state["active_agent"] = "interview"
    state["triage_stage"] = "awaiting_intent"
    state["requested_credit_limit"] = requested_limit
    return state


def make_agent(
    *,
    customer_repository: CustomerRepositoryStub | None = None,
    audit_writer: AuditWriterStub | None = None,
) -> tuple[CreditInterviewAgent, CustomerRepositoryStub, AuditWriterStub]:
    customers = customer_repository or CustomerRepositoryStub()
    audit = audit_writer or AuditWriterStub()
    return (
        CreditInterviewAgent(
            customer_repository=customers,
            audit_writer=audit,
            pseudonymization_key=PSEUDONYMIZATION_KEY,
        ),
        customers,
        audit,
    )


def complete_interview(
    agent: CreditInterviewAgent,
    state: ConversationState,
) -> ConversationState:
    for answer in ("5000", "formal", "2500", "1", "não"):
        state = agent.respond(state, answer)
    return state


def test_interview_collects_profile_updates_score_and_returns_to_credit() -> None:
    agent, customers, audit = make_agent()

    state = complete_interview(agent, make_state())

    assert customers.updates == [540]
    assert state["active_agent"] == "credit"
    assert state["credit_stage"] == "awaiting_action"
    assert state["interview_stage"] == "awaiting_income"
    assert state["monthly_income"] is None
    assert "consultar" in state["assistant_message"]
    assert [event.event_type for event in audit.events] == [
        "customer_profile_updated",
        "agent_handoff",
    ]
    assert audit.events[0].policy_version == "credit-interview-score-v1"
    for event in audit.events:
        assert event.subject_ref != "00000000000"
        assert not hasattr(event, "monthly_income")
        assert not hasattr(event, "fixed_expenses")
        assert not hasattr(event, "credit_score")


def test_interview_preserves_pending_limit_for_credit_reanalysis() -> None:
    agent, _, _ = make_agent()

    state = complete_interview(agent, make_state(requested_limit=Decimal("6000.00")))

    assert state["requested_credit_limit"] == Decimal("6000.00")
    assert "reanalisar" in state["assistant_message"]


@pytest.mark.parametrize(
    ("answers", "stage", "message"),
    [
        (("invalid",), "awaiting_income", "renda"),
        (("5000", "informal"), "awaiting_employment", "opções"),
        (("5000", "formal", "invalid"), "awaiting_expenses", "despesas"),
        (("5000", "formal", "2500", "1.5"), "awaiting_dependents", "inteiro"),
        (("5000", "formal", "2500", "1", "talvez"), "awaiting_debts", "sim ou não"),
    ],
)
def test_interview_reprompts_invalid_answers_without_advancing(
    answers: tuple[str, ...],
    stage: str,
    message: str,
) -> None:
    agent, customers, _ = make_agent()
    state = make_state()

    for answer in answers:
        state = agent.respond(state, answer)

    assert state["interview_stage"] == stage
    assert message in state["assistant_message"]
    assert not customers.updates
    assert state["user_message"] == "[REDACTED_FINANCIAL_INPUT]"


def test_interview_accepts_zero_income_and_expenses() -> None:
    agent, customers, _ = make_agent()
    state = make_state()

    for answer in ("0", "desempregado", "0", "3+", "sim"):
        state = agent.respond(state, answer)

    assert customers.updates == [0]
    assert state["active_agent"] == "credit"


def test_interview_keeps_final_stage_when_score_update_fails() -> None:
    agent, customers, _ = make_agent(customer_repository=CustomerRepositoryStub(error=True))
    state = make_state()

    state = complete_interview(agent, state)

    assert state["active_agent"] == "interview"
    assert state["interview_stage"] == "awaiting_debts"
    assert "Não foi possível" in state["assistant_message"]
    assert not customers.updates


def test_interview_rolls_back_score_when_critical_audit_fails() -> None:
    agent, customers, audit = make_agent(audit_writer=AuditWriterStub(error=True))

    state = complete_interview(agent, make_state())

    assert customers.updates == [540, 650]
    assert customers.customer is not None
    assert customers.customer.credit_score == 650
    assert state["active_agent"] == "interview"
    assert "registrar" in state["assistant_message"]
    assert not audit.events


def test_interview_keeps_completed_score_when_handoff_audit_fails() -> None:
    audit = AuditWriterStub(fail_on_append=2)
    agent, customers, _ = make_agent(audit_writer=audit)

    state = complete_interview(agent, make_state())

    assert customers.updates == [540]
    assert state["active_agent"] == "credit"


def test_interview_reports_unrecoverable_rollback_failure() -> None:
    customers = CustomerRepositoryStub(fail_on_update=2)
    agent, _, _ = make_agent(
        customer_repository=customers,
        audit_writer=AuditWriterStub(error=True),
    )

    state = complete_interview(agent, make_state())

    assert customers.updates == [540]
    assert "com segurança" in state["assistant_message"]


@pytest.mark.parametrize("missing", [True, False])
def test_interview_handles_missing_or_unavailable_customer(missing: bool) -> None:
    customers = CustomerRepositoryStub(
        error=not missing,
        customer=None if missing else CustomerRepositoryStub().customer,
    )
    agent, _, _ = make_agent(customer_repository=customers)

    state = complete_interview(agent, make_state())

    assert state["active_agent"] == "interview"
    assert "Não foi possível" in state["assistant_message"]


def test_interview_rejects_invalid_lifecycle_and_configuration() -> None:
    agent, _, _ = make_agent()

    ended = make_state()
    ended["end_reason"] = "user_requested"
    with pytest.raises(ValueError, match="already ended"):
        agent.respond(ended, "5000")

    unauthenticated = make_state()
    unauthenticated["authenticated"] = False
    with pytest.raises(ValueError, match="authenticated"):
        agent.respond(unauthenticated, "5000")

    wrong_agent = make_state()
    wrong_agent["active_agent"] = "credit"
    with pytest.raises(ValueError, match="outside its scope"):
        agent.respond(wrong_agent, "5000")

    invalid_stage = cast(Any, make_state())
    invalid_stage["interview_stage"] = "invalid"
    with pytest.raises(ValueError, match="not ready"):
        agent.respond(invalid_stage, "5000")

    with pytest.raises(ValueError, match="at least 32 bytes"):
        CreditInterviewAgent(
            customer_repository=CustomerRepositoryStub(),
            audit_writer=AuditWriterStub(),
            pseudonymization_key=b"short",
        )


def test_interview_rejects_incomplete_profile_and_missing_cpf() -> None:
    agent, _, _ = make_agent()
    incomplete = make_state()
    incomplete["interview_stage"] = "awaiting_debts"

    with pytest.raises(ValueError, match="incomplete"):
        agent.respond(incomplete, "não")

    completed = make_state()
    completed["monthly_income"] = Decimal("5000")
    completed["employment_type"] = "formal"
    completed["fixed_expenses"] = Decimal("2500")
    completed["dependents"] = 1
    completed["has_active_debts"] = False
    completed["cpf"] = None

    with pytest.raises(ValueError, match="authenticated"):
        agent._ensure_interview_can_respond(completed)
