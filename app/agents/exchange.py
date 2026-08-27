from datetime import UTC
from decimal import Decimal
from typing import Literal

from app.audit.events import AuditEvent
from app.audit.privacy import MIN_PSEUDONYMIZATION_KEY_BYTES, pseudonymize_subject
from app.audit.writer import AuditWriteError, AuditWriter
from app.models.conversation import ConversationState
from app.models.exchange import ExchangeQuote
from app.repositories.exchange import ExchangeRateRepository, ExchangeRateUnavailableError
from app.tools.conversation import normalize_text

_SUPPORTED_CURRENCIES = frozenset({"USD", "EUR", "ARS", "GBP", "JPY"})
_CURRENCY_TERMS = {
    "USD": frozenset({"usd", "dolar", "dólar", "dolar americano", "dólar americano"}),
    "EUR": frozenset({"eur", "euro"}),
    "ARS": frozenset({"ars", "peso argentino", "pesos argentinos"}),
    "GBP": frozenset({"gbp", "libra", "libra esterlina"}),
    "JPY": frozenset({"jpy", "iene", "yen"}),
}
_UNSUPPORTED_CURRENCY_TERMS = frozenset({"canadense", "australiano", "neozelandes"})


class ExchangeAgent:
    def __init__(
        self,
        *,
        exchange_repository: ExchangeRateRepository,
        audit_writer: AuditWriter,
        pseudonymization_key: bytes,
    ) -> None:
        if len(pseudonymization_key) < MIN_PSEUDONYMIZATION_KEY_BYTES:
            raise ValueError(
                f"pseudonymization key must contain at least {MIN_PSEUDONYMIZATION_KEY_BYTES} bytes"
            )
        self._exchange_repository = exchange_repository
        self._audit_writer = audit_writer
        self._pseudonymization_key = pseudonymization_key

    def respond(
        self,
        state: ConversationState,
        user_message: str,
        *,
        advance_turn: bool = True,
    ) -> ConversationState:
        self._ensure_exchange_can_respond(state)
        next_state = state.copy()
        if advance_turn:
            next_state["turn_number"] += 1
        next_state["handoff_pending"] = False
        next_state["user_message"] = user_message

        currency = _identify_currency(user_message)
        if currency is None:
            next_state["assistant_message"] = (
                "Informe uma moeda suportada: dólar (USD), euro (EUR), peso argentino "
                "(ARS), libra (GBP) ou iene (JPY)."
            )
            return next_state

        try:
            quote = self._exchange_repository.get_brl_quote(currency=currency)
        except ExchangeRateUnavailableError:
            self._audit_quote(
                next_state,
                outcome="failure",
                reason_code="EXCHANGE_PROVIDER_UNAVAILABLE",
            )
            next_state["assistant_message"] = (
                "Não foi possível consultar a cotação agora. Tente novamente em alguns instantes."
            )
            return next_state

        self._audit_quote(next_state, outcome="success", reason_code="EXCHANGE_QUOTE_PROVIDED")
        next_state["assistant_message"] = _format_quote(quote)
        return self._return_to_triage(next_state)

    def _audit_quote(
        self,
        state: ConversationState,
        *,
        outcome: Literal["success", "failure"],
        reason_code: str,
    ) -> None:
        try:
            self._audit_writer.append(
                AuditEvent(
                    event_type="exchange_quote_requested",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="exchange",
                    outcome=outcome,
                    reason_code=reason_code,
                    subject_ref=self._subject_ref(state),
                )
            )
        except AuditWriteError:
            pass

    def _return_to_triage(self, state: ConversationState) -> ConversationState:
        try:
            self._audit_writer.append(
                AuditEvent(
                    event_type="agent_handoff",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="exchange",
                    outcome="success",
                    reason_code="EXCHANGE_QUOTE_COMPLETED",
                    subject_ref=self._subject_ref(state),
                )
            )
        except AuditWriteError:
            pass
        state["active_agent"] = "triage"
        state["triage_stage"] = "awaiting_intent"
        return state

    def _subject_ref(self, state: ConversationState) -> str:
        cpf = state["cpf"]
        if cpf is None:
            raise ValueError("authenticated customer cpf is required")
        return pseudonymize_subject(cpf, key=self._pseudonymization_key)

    @staticmethod
    def _ensure_exchange_can_respond(state: ConversationState) -> None:
        if state["end_reason"] is not None:
            raise ValueError("conversation has already ended")
        if not state["authenticated"] or state["cpf"] is None:
            raise ValueError("exchange agent requires an authenticated customer")
        if state["active_agent"] != "exchange":
            raise ValueError("exchange agent cannot respond outside its scope")


def _identify_currency(message: str) -> str | None:
    normalized_message = normalize_text(message)
    if any(term in normalized_message for term in _UNSUPPORTED_CURRENCY_TERMS):
        return None
    matches = {
        currency
        for currency, terms in _CURRENCY_TERMS.items()
        if any(term in normalized_message for term in terms)
    }
    return matches.pop() if len(matches) == 1 else None


def _format_quote(quote: ExchangeQuote) -> str:
    timestamp = quote.quoted_at.astimezone(UTC).strftime("%d/%m/%Y às %H:%M UTC")
    return (
        f"Cotação de {quote.currency} em reais: compra R$ {_format_brl_rate(quote.buy_rate)} e "
        f"venda R$ {_format_brl_rate(quote.sell_rate)}, atualizada em {timestamp}. "
        "Posso ajudar com outro assunto?"
    )


def _format_brl_rate(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001')):.4f}".replace(".", ",")
