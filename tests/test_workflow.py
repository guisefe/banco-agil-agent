from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

import pytest

from app.agents.credit import CreditAgent
from app.agents.exchange import ExchangeAgent
from app.agents.interview import CreditInterviewAgent
from app.agents.triage import TriageAgent
from app.audit.events import AuditEvent
from app.graph.workflow import ConversationWorkflow
from app.models.conversation import initial_state
from app.models.credit import CreditRequest
from app.models.customer import Customer
from app.models.exchange import ExchangeQuote
from app.models.intent import IntentInterpretation
from app.repositories.credit import CreditRepositoryError
from app.repositories.customers import CustomerRepositoryError
from app.services.understanding import (
    ConversationInterpreter,
    ExpectedField,
    FieldInterpretation,
)

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

    def update_credit_score(self, *, cpf: str, credit_score: int | None) -> None:
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

    def finalize_pending(
        self,
        *,
        customer_cpf: str,
        requested_at: datetime,
        status: Literal["aprovado", "rejeitado"],
    ) -> None:
        for index, request in enumerate(self.requests):
            if (
                request.customer_cpf == customer_cpf
                and request.requested_at == requested_at
                and request.status == "pendente"
            ):
                self.requests[index] = replace(request, status=status)
                return
        raise CreditRepositoryError("pending request unavailable")


class ExchangeRepositoryStub:
    def get_brl_quote(self, *, currency: str) -> ExchangeQuote:
        return ExchangeQuote(
            currency=currency,
            buy_rate=Decimal("5.1234"),
            sell_rate=Decimal("5.1334"),
            quoted_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        )


def make_workflow(
    *,
    intent_interpreter: ConversationInterpreter | None = None,
) -> ConversationWorkflow:
    audit_writer = RecordingAuditWriter()
    customer_repository = CustomerRepositoryStub()
    triage_agent = TriageAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
        intent_interpreter=intent_interpreter,
    )
    credit_agent = CreditAgent(
        customer_repository=customer_repository,
        score_policy_repository=ScorePolicyRepositoryStub(),
        request_repository=CreditRequestRepositoryStub(),
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
        field_interpreter=intent_interpreter,
        intent_interpreter=intent_interpreter,
    )
    interview_agent = CreditInterviewAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
        field_interpreter=intent_interpreter,
    )
    exchange_agent = ExchangeAgent(
        exchange_repository=ExchangeRepositoryStub(),
        audit_writer=audit_writer,
        pseudonymization_key=PSEUDONYMIZATION_KEY,
        field_interpreter=intent_interpreter,
    )
    return ConversationWorkflow(
        triage_agent=triage_agent,
        credit_agent=credit_agent,
        interview_agent=interview_agent,
        exchange_agent=exchange_agent,
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
    assert state["active_agent"] == "triage"
    assert state["turn_number"] == 3
    assert "R$ 2.500,00" in state["assistant_message"]


def test_workflow_runs_exchange_quote_and_returns_to_triage() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")
    state = workflow.respond(state, "cotação do dólar")

    assert state["active_agent"] == "triage"
    assert "Cotação de USD" in state["assistant_message"]


def test_workflow_answers_score_query_in_same_turn_as_triage_handoff() -> None:
    workflow = make_workflow()
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")

    state = workflow.respond(state, "quero saber meu score")

    assert state["turn_number"] == 3
    assert state["active_agent"] == "triage"
    assert "650 de 1000" in state["assistant_message"]


@dataclass
class LlmIntentInterpreterStub:
    def interpret(self, message: str) -> IntentInterpretation:
        normalized = message.casefold()
        if "entrevista" in normalized:
            return IntentInterpretation(intent="credit_interview", source="llm")
        if "estados unidos" in normalized:
            return IntentInterpretation(
                intent="exchange_quote",
                source="llm",
                currency="USD",
            )
        return IntentInterpretation(
            intent="credit_limit_increase",
            source="llm",
            requested_limit=Decimal("4000.00"),
        )

    def interpret_field(
        self,
        message: str,
        *,
        expected: ExpectedField,
    ) -> FieldInterpretation:
        values = {
            "money": "1000.00" if "gasto" in message.casefold() else "10000.00",
            "employment": "formal",
            "dependents": "0",
            "yes_no": "nao" if "não" in message.casefold() else "sim",
            "currency": "USD",
        }
        return FieldInterpretation(value=values[expected], source="llm")


def test_workflow_uses_llm_intent_and_executes_handoff_in_same_turn() -> None:
    workflow = make_workflow(intent_interpreter=LlmIntentInterpreterStub())
    state = workflow.start()
    state = workflow.respond(state, "00000000000")
    state = workflow.respond(state, "20/05/1990")

    state = workflow.respond(state, "preciso de um fôlego de quatro mil no cartão")

    assert state["turn_number"] == 3
    assert state["active_agent"] == "triage"
    assert "R$ 4.000,00" in state["assistant_message"]


def test_workflow_routes_existing_exchange_state_from_graph_start() -> None:
    workflow = make_workflow(intent_interpreter=LlmIntentInterpreterStub())
    state = initial_state()
    state["authenticated"] = True
    state["cpf"] = "00000000000"
    state["active_agent"] = "exchange"

    state = workflow.respond(state, "a moeda dos Estados Unidos")

    assert "Cotação de USD" in state["assistant_message"]


def test_workflow_after_triage_fallback_is_end() -> None:
    state = initial_state()
    state["handoff_pending"] = True

    assert ConversationWorkflow._route_after_triage(state) == "end"


def test_workflow_runs_interview_and_reanalyzes_pending_limit() -> None:
    workflow = make_workflow()
    state = workflow.start()
    for message in (
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
    ):
        state = workflow.respond(state, message)

    assert state["active_agent"] == "triage"
    assert state["requested_credit_limit"] is None
    assert "aprovada" in state["assistant_message"]


def test_workflow_completes_direct_interview_without_pending_limit() -> None:
    workflow = make_workflow(intent_interpreter=LlmIntentInterpreterStub())
    state = workflow.start()
    for message in (
        "00000000000",
        "20/05/1990",
        "entrevista financeira",
        "recebo dez mil por mês",
        "trabalho registrado",
        "gasto mil reais por mês",
        "ninguém depende de mim",
        "não tenho dívidas",
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
