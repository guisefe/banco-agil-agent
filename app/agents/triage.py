from collections.abc import Mapping
from typing import Literal

from app.audit.events import AuditEvent
from app.audit.privacy import MIN_PSEUDONYMIZATION_KEY_BYTES, pseudonymize_subject
from app.audit.writer import AuditWriteError, AuditWriter
from app.models.conversation import ConversationState
from app.models.intent import IntentInterpretation, IntentName
from app.repositories.customers import CustomerRepository, CustomerRepositoryError
from app.services.intent import (
    INTENT_POLICY_VERSION,
    DeterministicIntentInterpreter,
    IntentInterpreter,
)
from app.tools.conversation import end_conversation, is_end_request
from app.tools.identity import IdentityInputError, normalize_cpf, parse_birth_date

MAX_AUTHENTICATION_ATTEMPTS = 3

DestinationAgent = Literal["credit", "interview", "exchange"]


class TriageAgent:
    def __init__(
        self,
        *,
        customer_repository: CustomerRepository,
        audit_writer: AuditWriter,
        pseudonymization_key: bytes,
        intent_interpreter: IntentInterpreter | None = None,
    ) -> None:
        if len(pseudonymization_key) < MIN_PSEUDONYMIZATION_KEY_BYTES:
            raise ValueError(
                f"pseudonymization key must contain at least {MIN_PSEUDONYMIZATION_KEY_BYTES} bytes"
            )

        self._customer_repository = customer_repository
        self._audit_writer = audit_writer
        self._pseudonymization_key = pseudonymization_key
        self._intent_interpreter = intent_interpreter or DeterministicIntentInterpreter()

    def start(self, state: ConversationState) -> ConversationState:
        if state["triage_stage"] != "greeting" or state["end_reason"] is not None:
            raise ValueError("triage can only start from the initial conversation state")

        started_state = state.copy()
        started_state["assistant_message"] = (
            "Olá! Sou o assistente do Banco Ágil. Para começar, informe seu CPF."
        )
        started_state["triage_stage"] = "awaiting_cpf"
        self._append_event(
            AuditEvent(
                event_type="conversation_started",
                conversation_id=started_state["conversation_id"],
                turn_number=started_state["turn_number"],
                agent="triage",
                outcome="success",
            )
        )
        return started_state

    def respond(self, state: ConversationState, user_message: str) -> ConversationState:
        self._ensure_triage_can_respond(state)

        next_state = state.copy()
        next_state["turn_number"] += 1
        next_state["user_message"] = user_message

        if is_end_request(user_message):
            return self._finish_by_user_request(next_state)

        if state["triage_stage"] == "awaiting_cpf":
            return self._collect_cpf(next_state, user_message)
        if state["triage_stage"] == "awaiting_birth_date":
            return self._authenticate(next_state, user_message)
        if state["triage_stage"] == "awaiting_intent":
            return self._route_intent(next_state, user_message)

        raise ValueError("triage is not ready to receive a user message")

    def _collect_cpf(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            cpf = normalize_cpf(user_message)
        except IdentityInputError:
            state["user_message"] = "[REDACTED_CPF_INPUT]"
            state["assistant_message"] = (
                "O CPF deve conter 11 números. Confira o valor e tente novamente."
            )
            return state

        state["user_message"] = "[REDACTED_CPF]"
        state["cpf"] = cpf
        state["triage_stage"] = "awaiting_birth_date"
        state["assistant_message"] = "Agora informe sua data de nascimento no formato DD/MM/AAAA."
        return state

    def _authenticate(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        state["user_message"] = "[REDACTED_BIRTH_DATE_INPUT]"
        try:
            birth_date = parse_birth_date(user_message)
        except IdentityInputError:
            state["assistant_message"] = (
                "Não reconheci a data. Use o formato DD/MM/AAAA, por exemplo 20/05/1990."
            )
            return state

        state["user_message"] = "[REDACTED_BIRTH_DATE]"
        cpf = state["cpf"]
        if cpf is None:
            raise ValueError("cpf is required before authentication")

        subject_ref = pseudonymize_subject(cpf, key=self._pseudonymization_key)
        try:
            customer = self._customer_repository.find_by_identity(
                cpf=cpf,
                birth_date=birth_date,
            )
        except CustomerRepositoryError:
            self._append_event(
                AuditEvent(
                    event_type="authentication_attempted",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="triage",
                    outcome="failure",
                    reason_code="CUSTOMER_REPOSITORY_UNAVAILABLE",
                    subject_ref=subject_ref,
                )
            )
            state["assistant_message"] = (
                "Não consegui consultar seus dados agora. Tente novamente em alguns instantes."
            )
            return state

        if customer is None:
            return self._record_failed_authentication(state, subject_ref)

        state["authenticated"] = True
        state["birth_date"] = birth_date.isoformat()
        state["customer_name"] = customer.name
        state["triage_stage"] = "awaiting_intent"
        state["assistant_message"] = (
            f"Autenticação concluída, {customer.name}. Como posso ajudar com crédito ou câmbio?"
        )
        self._append_event(
            AuditEvent(
                event_type="authentication_attempted",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="triage",
                outcome="success",
                reason_code="IDENTITY_CONFIRMED",
                subject_ref=subject_ref,
            )
        )
        return state

    def _record_failed_authentication(
        self,
        state: ConversationState,
        subject_ref: str,
    ) -> ConversationState:
        state["authentication_attempts"] += 1
        self._append_event(
            AuditEvent(
                event_type="authentication_attempted",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="triage",
                outcome="failure",
                reason_code="IDENTITY_MISMATCH",
                subject_ref=subject_ref,
            )
        )

        if state["authentication_attempts"] >= MAX_AUTHENTICATION_ATTEMPTS:
            ended_state = end_conversation(
                state,
                reason="authentication_attempts_exceeded",
                assistant_message=(
                    "Não foi possível confirmar seus dados após três tentativas. "
                    "Por segurança, encerraremos este atendimento."
                ),
            )
            self._append_event(
                AuditEvent(
                    event_type="conversation_ended",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="triage",
                    outcome="failure",
                    reason_code="AUTHENTICATION_ATTEMPTS_EXCEEDED",
                    subject_ref=subject_ref,
                )
            )
            return ended_state

        remaining_attempts = MAX_AUTHENTICATION_ATTEMPTS - state["authentication_attempts"]
        state["cpf"] = None
        state["birth_date"] = None
        state["triage_stage"] = "awaiting_cpf"
        state["assistant_message"] = (
            "Não foi possível confirmar os dados. "
            f"Você ainda tem {remaining_attempts} tentativa(s). Informe o CPF novamente."
        )
        return state

    def _route_intent(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        interpretation = self._intent_interpreter.interpret(user_message)
        self._record_intent_interpretation(state, interpretation)
        destination = _destination_for(interpretation.intent)
        if destination is None:
            state["interpreted_intent"] = None
            state["interpreted_currency"] = None
            state["interpreted_requested_limit"] = None
            state["assistant_message"] = (
                "Posso ajudar com limite ou aumento de crédito, entrevista financeira "
                "ou cotação de moedas. Qual opção você deseja?"
            )
            return state

        state["active_agent"] = destination
        state["handoff_pending"] = True
        state["interpreted_intent"] = interpretation.intent
        state["interpreted_currency"] = interpretation.currency
        state["interpreted_requested_limit"] = interpretation.requested_limit
        state["assistant_message"] = _handoff_message(destination)
        self._append_event(
            AuditEvent(
                event_type="agent_handoff",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="triage",
                outcome="success",
                reason_code=f"ROUTED_TO_{destination.upper()}",
                subject_ref=self._subject_ref(state),
            )
        )
        return state

    def _record_intent_interpretation(
        self,
        state: ConversationState,
        interpretation: IntentInterpretation,
    ) -> None:
        if interpretation.source == "deterministic":
            return
        reason_code = (
            "INTENT_INTERPRETED_BY_LLM"
            if interpretation.source == "llm"
            else "LLM_INTENT_FALLBACK_USED"
        )
        try:
            self._append_event(
                AuditEvent(
                    event_type="intent_interpreted",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="triage",
                    outcome="success",
                    reason_code=reason_code,
                    subject_ref=self._subject_ref(state),
                    policy_version=INTENT_POLICY_VERSION,
                )
            )
        except AuditWriteError:
            pass

    def _finish_by_user_request(self, state: ConversationState) -> ConversationState:
        ended_state = end_conversation(
            state,
            reason="user_requested",
            assistant_message="Atendimento encerrado. Obrigado por falar com o Banco Ágil!",
        )
        self._append_event(
            AuditEvent(
                event_type="conversation_ended",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="triage",
                outcome="success",
                reason_code="USER_REQUESTED",
                subject_ref=self._subject_ref(state),
            )
        )
        return ended_state

    def _subject_ref(self, state: ConversationState) -> str | None:
        cpf = state["cpf"]
        if cpf is None:
            return None
        return pseudonymize_subject(cpf, key=self._pseudonymization_key)

    @staticmethod
    def _ensure_triage_can_respond(state: ConversationState) -> None:
        if state["end_reason"] is not None:
            raise ValueError("conversation has already ended")
        if state["active_agent"] != "triage":
            raise ValueError("triage cannot respond after a handoff")

    def _append_event(self, event: AuditEvent) -> None:
        self._audit_writer.append(event)


def _destination_for(intent: IntentName) -> DestinationAgent | None:
    if intent in {
        "credit_menu",
        "credit_limit_query",
        "credit_score_query",
        "credit_limit_increase",
    }:
        return "credit"
    if intent == "credit_interview":
        return "interview"
    if intent == "exchange_quote":
        return "exchange"
    return None


def _handoff_message(destination: DestinationAgent) -> str:
    messages: Mapping[DestinationAgent, str] = {
        "credit": "Certo. Vamos consultar ou revisar seu limite de crédito.",
        "interview": ("Certo. Vamos iniciar sua entrevista financeira. Qual é sua renda mensal?"),
        "exchange": "Certo. Qual moeda você deseja consultar?",
    }
    return messages[destination]
