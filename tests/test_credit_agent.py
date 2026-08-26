from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from threading import Event, Lock, Thread
from typing import Any, cast

import pytest

from app.agents.credit import CreditAgent
from app.audit.events import AuditEvent
from app.audit.writer import AuditWriteError
from app.models.conversation import ConversationState, initial_state
from app.models.credit import CreditRequest
from app.models.customer import Customer
from app.repositories.credit import CreditRepositoryError
from app.repositories.customers import CustomerRepositoryError

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class CustomerRepositoryStub:
    customer: Customer | None
    get_error: bool = False
    update_error: bool = False
    updates: list[Decimal] = field(default_factory=list)

    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        if self.get_error:
            raise CustomerRepositoryError("unavailable")
        if self.customer is None or self.customer.cpf != cpf:
            return None
        return self.customer

    def update_credit_limit(self, *, cpf: str, credit_limit: Decimal) -> None:
        if self.update_error or self.customer is None or self.customer.cpf != cpf:
            raise CustomerRepositoryError("update failed")
        self.updates.append(credit_limit)
        self.customer = replace(self.customer, credit_limit=credit_limit)


@dataclass
class BlockingCustomerRepositoryStub(CustomerRepositoryStub):
    first_read_started: Event = field(default_factory=Event)
    second_read_started: Event = field(default_factory=Event)
    release_first_read: Event = field(default_factory=Event)
    read_lock: Lock = field(default_factory=Lock)
    read_count: int = 0

    def get_by_cpf(self, *, cpf: str) -> Customer | None:
        with self.read_lock:
            self.read_count += 1
            read_number = self.read_count
        if read_number == 1:
            self.first_read_started.set()
            if not self.release_first_read.wait(timeout=1):
                raise CustomerRepositoryError("test synchronization failed")
        else:
            self.second_read_started.set()
        return super().get_by_cpf(cpf=cpf)


@dataclass
class ScorePolicyRepositoryStub:
    maximum_limit: Decimal = Decimal("5000.00")
    error: bool = False

    def maximum_limit_for(self, *, score: int) -> Decimal:
        if self.error:
            raise CreditRepositoryError("policy unavailable")
        return self.maximum_limit


@dataclass
class CreditRequestRepositoryStub:
    error: bool = False
    requests: list[CreditRequest] = field(default_factory=list)

    def append(self, request: CreditRequest) -> None:
        if self.error:
            raise CreditRepositoryError("request unavailable")
        self.requests.append(request)


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


def make_customer() -> Customer:
    return Customer(
        cpf="00000000000",
        name="Ana Exemplo",
        birth_date=date(1990, 5, 20),
        credit_limit=Decimal("2500.00"),
        credit_score=650,
    )


def make_state() -> ConversationState:
    state = initial_state()
    state["authenticated"] = True
    state["cpf"] = "00000000000"
    state["birth_date"] = "1990-05-20"
    state["customer_name"] = "Ana Exemplo"
    state["active_agent"] = "credit"
    state["triage_stage"] = "awaiting_intent"
    return state


def make_agent(
    *,
    customer_repository: CustomerRepositoryStub | None = None,
    score_policy_repository: ScorePolicyRepositoryStub | None = None,
    request_repository: CreditRequestRepositoryStub | None = None,
    audit_writer: AuditWriterStub | None = None,
) -> tuple[
    CreditAgent,
    CustomerRepositoryStub,
    ScorePolicyRepositoryStub,
    CreditRequestRepositoryStub,
    AuditWriterStub,
]:
    customers = customer_repository or CustomerRepositoryStub(make_customer())
    policy = score_policy_repository or ScorePolicyRepositoryStub()
    requests = request_repository or CreditRequestRepositoryStub()
    audit = audit_writer or AuditWriterStub()
    agent = CreditAgent(
        customer_repository=customers,
        score_policy_repository=policy,
        request_repository=requests,
        audit_writer=audit,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )
    return agent, customers, policy, requests, audit


def start_limit_request(agent: CreditAgent) -> ConversationState:
    return agent.respond(make_state(), "Quero aumentar meu limite")


def test_credit_agent_queries_limit_and_returns_to_triage() -> None:
    agent, _, _, _, audit = make_agent()

    state = agent.respond(make_state(), "consultar meu limite atual")

    assert state["active_agent"] == "triage"
    assert state["turn_number"] == 1
    assert "R$ 2.500,00" in state["assistant_message"]
    assert audit.events[-1].reason_code == "CREDIT_LIMIT_QUERIED"
    assert "00000000000" not in repr(audit.events)


@pytest.mark.parametrize(
    "message",
    ["ajuda", "consultar e aumentar meu limite"],
)
def test_credit_agent_clarifies_unknown_or_ambiguous_action(message: str) -> None:
    agent, _, _, _, _ = make_agent()

    state = agent.respond(make_state(), message)

    assert state["active_agent"] == "credit"
    assert "consultar" in state["assistant_message"]


def test_credit_agent_collects_requested_limit() -> None:
    agent, _, _, _, _ = make_agent()

    state = start_limit_request(agent)

    assert state["credit_stage"] == "awaiting_requested_limit"
    assert "novo limite" in state["assistant_message"]


@pytest.mark.parametrize("message", ["valor inválido", "0"])
def test_credit_agent_rejects_invalid_requested_limit(message: str) -> None:
    agent, _, _, requests, _ = make_agent()
    state = start_limit_request(agent)

    state = agent.respond(state, message)

    assert state["credit_stage"] == "awaiting_requested_limit"
    assert not requests.requests


def test_credit_agent_requires_increase_over_current_limit() -> None:
    agent, _, _, requests, _ = make_agent()
    state = start_limit_request(agent)

    state = agent.respond(state, "2000")

    assert "maior que o atual" in state["assistant_message"]
    assert not requests.requests


def test_credit_agent_approves_persists_and_audits_request() -> None:
    agent, customers, _, requests, audit = make_agent()
    state = start_limit_request(agent)

    state = agent.respond(state, "R$ 5.000,00")

    assert state["active_agent"] == "triage"
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("5000.00")
    assert requests.requests[0].status == "aprovado"
    decision = next(event for event in audit.events if event.event_type == "credit_decision_made")
    assert decision.outcome == "approved"
    assert decision.reason_code == "WITHIN_SCORE_LIMIT"
    assert decision.policy_version == "score-limit-csv-v1"
    assert "5000" not in repr(decision)


def test_credit_agent_rejects_and_routes_to_interview_after_consent() -> None:
    agent, customers, _, requests, audit = make_agent()
    state = start_limit_request(agent)
    state = agent.respond(state, "6000")

    assert state["credit_stage"] == "offering_interview"
    assert state["requested_credit_limit"] == Decimal("6000.00")
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("2500.00")
    assert requests.requests[0].status == "rejeitado"
    assert audit.events[-1].outcome == "rejected"

    state = agent.respond(state, "talvez")
    assert "sim ou não" in state["assistant_message"]

    state = agent.respond(state, "sim")
    assert state["active_agent"] == "interview"
    assert audit.events[-1].reason_code == "ROUTED_TO_INTERVIEW"


def test_credit_agent_returns_to_triage_when_interview_is_declined() -> None:
    agent, _, _, _, audit = make_agent()
    state = start_limit_request(agent)
    state = agent.respond(state, "6000")

    state = agent.respond(state, "não quero")

    assert state["active_agent"] == "triage"
    assert state["requested_credit_limit"] is None
    assert audit.events[-1].reason_code == "INTERVIEW_DECLINED"


@pytest.mark.parametrize("missing", [True, False])
def test_credit_agent_handles_missing_or_unavailable_customer(missing: bool) -> None:
    repository = CustomerRepositoryStub(
        None if missing else make_customer(),
        get_error=not missing,
    )
    agent, _, _, _, _ = make_agent(customer_repository=repository)

    state = agent.respond(make_state(), "consultar limite")

    assert "Não foi possível" in state["assistant_message"]


def test_credit_agent_handles_missing_customer_during_request() -> None:
    agent, _, _, requests, _ = make_agent(customer_repository=CustomerRepositoryStub(None))
    state = start_limit_request(agent)

    state = agent.respond(state, "5000")

    assert "Não foi possível" in state["assistant_message"]
    assert not requests.requests


def test_credit_agent_handles_unavailable_policy() -> None:
    agent, _, _, requests, _ = make_agent(
        score_policy_repository=ScorePolicyRepositoryStub(error=True)
    )
    state = start_limit_request(agent)

    state = agent.respond(state, "5000")

    assert "Não foi possível" in state["assistant_message"]
    assert not requests.requests


def test_credit_agent_blocks_decision_when_audit_is_unavailable() -> None:
    agent, customers, _, requests, _ = make_agent(audit_writer=AuditWriterStub(error=True))
    state = start_limit_request(agent)

    state = agent.respond(state, "5000")

    assert "Não foi possível" in state["assistant_message"]
    assert not requests.requests
    assert not customers.updates


def test_credit_agent_rolls_back_limit_when_request_record_fails() -> None:
    agent, customers, _, _, _ = make_agent(
        request_repository=CreditRequestRepositoryStub(error=True)
    )
    state = start_limit_request(agent)

    state = agent.respond(state, "5000")

    assert "Não foi possível" in state["assistant_message"]
    assert customers.updates == [Decimal("5000.00"), Decimal("2500.00")]
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("2500.00")


def test_credit_agent_handles_customer_update_failure() -> None:
    customers = CustomerRepositoryStub(make_customer(), update_error=True)
    agent, _, _, requests, _ = make_agent(customer_repository=customers)
    state = start_limit_request(agent)

    state = agent.respond(state, "5000")

    assert "Não foi possível" in state["assistant_message"]
    assert not requests.requests


def test_credit_agent_handles_rejected_request_record_failure() -> None:
    agent, _, _, _, _ = make_agent(request_repository=CreditRequestRepositoryStub(error=True))
    state = start_limit_request(agent)

    state = agent.respond(state, "6000")

    assert "Não foi possível" in state["assistant_message"]


def test_credit_agent_handles_handoff_audit_failure() -> None:
    audit = AuditWriterStub()
    agent, _, _, _, _ = make_agent(audit_writer=audit)
    state = start_limit_request(agent)
    state = agent.respond(state, "6000")
    audit.error = True

    state = agent.respond(state, "sim")

    assert state["active_agent"] == "credit"
    assert "Não foi possível" in state["assistant_message"]


def test_credit_agent_handles_return_handoff_audit_failure() -> None:
    agent, _, _, _, _ = make_agent(audit_writer=AuditWriterStub(error=True))

    state = agent.respond(make_state(), "consultar limite")

    assert state["active_agent"] == "credit"
    assert "Não foi possível" in state["assistant_message"]


def test_credit_agent_keeps_committed_approval_when_handoff_audit_fails() -> None:
    audit = AuditWriterStub(fail_on_append=2)
    agent, customers, _, requests, _ = make_agent(audit_writer=audit)
    state = start_limit_request(agent)

    state = agent.respond(state, "5000")

    assert state["active_agent"] == "triage"
    assert "aprovada" in state["assistant_message"]
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("5000.00")
    assert requests.requests[0].status == "aprovado"


def test_credit_agent_serializes_concurrent_decisions_against_latest_limit() -> None:
    customers = BlockingCustomerRepositoryStub(make_customer())
    agent, _, _, requests, _ = make_agent(customer_repository=customers)
    first_state = start_limit_request(agent)
    second_state = start_limit_request(agent)
    results: list[ConversationState] = []

    first = Thread(target=lambda: results.append(agent.respond(first_state, "5000")))
    second = Thread(target=lambda: results.append(agent.respond(second_state, "4000")))
    first.start()
    assert customers.first_read_started.wait(timeout=1)
    second.start()

    assert not customers.second_read_started.wait(timeout=0.05)
    customers.release_first_read.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("5000.00")
    assert len(requests.requests) == 1
    assert {state["active_agent"] for state in results} == {"credit", "triage"}


def test_credit_agent_approves_pending_request_after_score_reanalysis() -> None:
    agent, customers, _, requests, audit = make_agent(
        score_policy_repository=ScorePolicyRepositoryStub(maximum_limit=Decimal("10000.00"))
    )
    state = make_state()
    state["requested_credit_limit"] = Decimal("6000.00")

    state = agent.reanalyze_pending_request(state)

    assert state["active_agent"] == "triage"
    assert state["requested_credit_limit"] is None
    assert "aprovada" in state["assistant_message"]
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("6000.00")
    assert requests.requests[0].status == "aprovado"
    assert audit.events[-1].reason_code == "CREDIT_REANALYSIS_APPROVED"


def test_credit_agent_finishes_after_reanalysis_remains_rejected() -> None:
    agent, customers, _, requests, audit = make_agent()
    state = make_state()
    state["requested_credit_limit"] = Decimal("6000.00")

    state = agent.reanalyze_pending_request(state)

    assert state["active_agent"] == "triage"
    assert state["requested_credit_limit"] is None
    assert "ainda não pôde" in state["assistant_message"]
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("2500.00")
    assert requests.requests[0].status == "rejeitado"
    assert audit.events[-1].reason_code == "CREDIT_REANALYSIS_REJECTED"


def test_credit_agent_recognizes_request_already_satisfied_during_reanalysis() -> None:
    customer = replace(make_customer(), credit_limit=Decimal("7000.00"))
    agent, _, _, requests, audit = make_agent(customer_repository=CustomerRepositoryStub(customer))
    state = make_state()
    state["requested_credit_limit"] = Decimal("6000.00")

    state = agent.reanalyze_pending_request(state)

    assert state["active_agent"] == "triage"
    assert state["requested_credit_limit"] is None
    assert "já atende" in state["assistant_message"]
    assert not requests.requests
    assert audit.events[-1].reason_code == "CREDIT_REANALYSIS_ALREADY_SATISFIED"


def test_credit_agent_requires_pending_limit_for_reanalysis() -> None:
    agent, _, _, _, _ = make_agent()

    with pytest.raises(ValueError, match="pending requested limit"):
        agent.reanalyze_pending_request(make_state())


def test_credit_agent_keeps_reanalysis_result_when_handoff_audit_fails() -> None:
    audit = AuditWriterStub(fail_on_append=2)
    agent, customers, _, requests, _ = make_agent(
        score_policy_repository=ScorePolicyRepositoryStub(maximum_limit=Decimal("10000.00")),
        audit_writer=audit,
    )
    state = make_state()
    state["requested_credit_limit"] = Decimal("6000.00")

    state = agent.reanalyze_pending_request(state)

    assert state["active_agent"] == "triage"
    assert customers.customer is not None
    assert customers.customer.credit_limit == Decimal("6000.00")
    assert requests.requests[0].status == "aprovado"


def test_credit_agent_requires_cpf_for_subject_reference() -> None:
    agent, _, _, _, _ = make_agent()
    state = make_state()
    state["cpf"] = None

    with pytest.raises(ValueError, match="cpf is required"):
        agent._subject_ref(state)

    assert agent._load_customer(state) is None


def test_credit_agent_rejects_invalid_lifecycle_and_configuration() -> None:
    agent, _, _, _, _ = make_agent()
    ended = make_state()
    ended["end_reason"] = "user_requested"
    with pytest.raises(ValueError, match="already ended"):
        agent.respond(ended, "oi")

    unauthenticated = make_state()
    unauthenticated["authenticated"] = False
    with pytest.raises(ValueError, match="authenticated"):
        agent.respond(unauthenticated, "oi")

    wrong_agent = make_state()
    wrong_agent["active_agent"] = "triage"
    with pytest.raises(ValueError, match="outside its scope"):
        agent.respond(wrong_agent, "oi")

    invalid_stage = cast(Any, make_state())
    invalid_stage["credit_stage"] = "invalid"
    with pytest.raises(ValueError, match="not ready"):
        agent.respond(invalid_stage, "oi")

    with pytest.raises(ValueError, match="at least 32 bytes"):
        CreditAgent(
            customer_repository=CustomerRepositoryStub(make_customer()),
            score_policy_repository=ScorePolicyRepositoryStub(),
            request_repository=CreditRequestRepositoryStub(),
            audit_writer=AuditWriterStub(),
            pseudonymization_key=b"short",
        )
