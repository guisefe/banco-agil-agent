from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.agents.exchange import ExchangeAgent
from app.audit.events import AuditEvent
from app.audit.writer import AuditWriteError
from app.models.conversation import ConversationState, initial_state
from app.models.exchange import ExchangeQuote
from app.repositories.exchange import ExchangeRateUnavailableError

PSEUDONYMIZATION_KEY = b"test-only-pseudonymization-key-32-bytes"


@dataclass
class RecordingAuditWriter:
    events: list[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class QuoteRepository:
    def get_brl_quote(self, *, currency: str) -> ExchangeQuote:
        return ExchangeQuote(
            currency=currency,
            buy_rate=Decimal("5.1234"),
            sell_rate=Decimal("5.1334"),
            quoted_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        )


class UnavailableQuoteRepository:
    def get_brl_quote(self, *, currency: str) -> ExchangeQuote:
        raise ExchangeRateUnavailableError("offline")


class FailingAuditWriter:
    def append(self, event: AuditEvent) -> None:
        raise AuditWriteError("unavailable")


def authenticated_exchange_state() -> ConversationState:
    state = initial_state()
    state["authenticated"] = True
    state["cpf"] = "00000000000"
    state["active_agent"] = "exchange"
    state["triage_stage"] = "awaiting_intent"
    return state


def make_agent(
    *,
    repository: object = QuoteRepository(),
    audit_writer: object = RecordingAuditWriter(),
) -> ExchangeAgent:
    return ExchangeAgent(
        exchange_repository=repository,  # type: ignore[arg-type]
        audit_writer=audit_writer,  # type: ignore[arg-type]
        pseudonymization_key=PSEUDONYMIZATION_KEY,
    )


@pytest.mark.parametrize("message", ["dólar", "USD", "euro", "peso argentino", "libra", "iene"])
def test_exchange_agent_accepts_supported_currency_terms(message: str) -> None:
    state = make_agent().respond(authenticated_exchange_state(), message)

    assert state["active_agent"] == "triage"
    assert "compra R$ 5,1234" in state["assistant_message"]
    assert "venda R$ 5,1334" in state["assistant_message"]


def test_exchange_agent_keeps_session_open_for_unsupported_currency() -> None:
    state = make_agent().respond(authenticated_exchange_state(), "dólar canadense")

    assert state["active_agent"] == "exchange"
    assert "suportada" in state["assistant_message"]


def test_exchange_agent_reports_provider_failure_without_leaking_error() -> None:
    audit_writer = RecordingAuditWriter()
    state = make_agent(repository=UnavailableQuoteRepository(), audit_writer=audit_writer).respond(
        authenticated_exchange_state(), "USD"
    )

    assert state["active_agent"] == "exchange"
    assert "offline" not in state["assistant_message"]
    assert audit_writer.events[-1].reason_code == "EXCHANGE_PROVIDER_UNAVAILABLE"


def test_exchange_agent_does_not_block_quote_when_non_critical_audit_fails() -> None:
    state = make_agent(audit_writer=FailingAuditWriter()).respond(
        authenticated_exchange_state(), "USD"
    )

    assert state["active_agent"] == "triage"
    assert "Cotação" in state["assistant_message"]


def test_exchange_agent_requires_its_own_authenticated_scope() -> None:
    agent = make_agent()
    state = initial_state()

    with pytest.raises(ValueError, match="authenticated"):
        agent.respond(state, "USD")

    state["authenticated"] = True
    state["cpf"] = "00000000000"
    state["active_agent"] = "credit"
    with pytest.raises(ValueError, match="outside its scope"):
        agent.respond(state, "USD")


def test_exchange_agent_defends_the_audit_invariant_for_missing_cpf() -> None:
    state = authenticated_exchange_state()
    state["cpf"] = None

    with pytest.raises(ValueError, match="cpf"):
        make_agent()._subject_ref(state)

    state["cpf"] = "00000000000"
    state["end_reason"] = "user_requested"
    with pytest.raises(ValueError, match="ended"):
        make_agent().respond(state, "USD")


def test_exchange_agent_rejects_short_pseudonymization_key() -> None:
    with pytest.raises(ValueError, match="at least"):
        ExchangeAgent(
            exchange_repository=QuoteRepository(),
            audit_writer=RecordingAuditWriter(),
            pseudonymization_key=b"short",
        )
