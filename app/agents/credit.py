from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from threading import Lock
from typing import Literal

from app.audit.events import AuditEvent
from app.audit.privacy import MIN_PSEUDONYMIZATION_KEY_BYTES, pseudonymize_subject
from app.audit.writer import AuditWriteError, AuditWriter
from app.models.conversation import ConversationState
from app.models.credit import CreditRequest
from app.models.customer import Customer
from app.repositories.credit import (
    SCORE_POLICY_VERSION,
    CreditRepositoryError,
    CreditRequestRepository,
    ScorePolicyRepository,
)
from app.repositories.customers import CreditCustomerRepository, CustomerRepositoryError
from app.tools.conversation import normalize_text
from app.tools.money import format_brl, parse_money

CreditAction = Literal["query", "increase"]

_ACTION_TERMS: Mapping[CreditAction, frozenset[str]] = {
    "query": frozenset({"consultar", "consulta", "limite atual"}),
    "increase": frozenset({"aumentar", "aumento", "novo limite", "solicitar"}),
}
_CREDIT_DECISION_LOCK = Lock()


class CreditAgent:
    def __init__(
        self,
        *,
        customer_repository: CreditCustomerRepository,
        score_policy_repository: ScorePolicyRepository,
        request_repository: CreditRequestRepository,
        audit_writer: AuditWriter,
        pseudonymization_key: bytes,
    ) -> None:
        if len(pseudonymization_key) < MIN_PSEUDONYMIZATION_KEY_BYTES:
            raise ValueError(
                f"pseudonymization key must contain at least {MIN_PSEUDONYMIZATION_KEY_BYTES} bytes"
            )
        self._customers = customer_repository
        self._score_policy = score_policy_repository
        self._requests = request_repository
        self._audit_writer = audit_writer
        self._pseudonymization_key = pseudonymization_key

    def respond(self, state: ConversationState, user_message: str) -> ConversationState:
        self._ensure_credit_can_respond(state)
        next_state = state.copy()
        next_state["turn_number"] += 1
        next_state["user_message"] = user_message

        if state["credit_stage"] == "awaiting_action":
            return self._choose_action(next_state, user_message)
        if state["credit_stage"] == "awaiting_requested_limit":
            return self._analyze_request(next_state, user_message)
        if state["credit_stage"] == "offering_interview":
            return self._handle_interview_offer(next_state, user_message)
        raise ValueError("credit agent is not ready to receive a user message")

    def reanalyze_pending_request(self, state: ConversationState) -> ConversationState:
        self._ensure_credit_can_respond(state)
        requested_limit = state["requested_credit_limit"]
        if requested_limit is None:
            raise ValueError("credit reanalysis requires a pending requested limit")
        next_state = state.copy()
        next_state["credit_stage"] = "awaiting_requested_limit"
        with _CREDIT_DECISION_LOCK:
            return self._decide_request(next_state, requested_limit, reanalysis=True)

    def _choose_action(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        action = _identify_action(user_message)
        if action is None:
            state["assistant_message"] = (
                "Você deseja consultar seu limite atual ou solicitar um aumento?"
            )
            return state
        if action == "increase":
            state["credit_stage"] = "awaiting_requested_limit"
            state["assistant_message"] = "Qual é o novo limite total que você deseja?"
            return state

        customer = self._load_customer(state)
        if customer is None:
            return self._repository_failure(state)
        state["assistant_message"] = (
            f"Seu limite atual é {format_brl(customer.credit_limit)}. "
            "Posso ajudar com outro assunto de crédito ou câmbio?"
        )
        return self._return_to_triage(state, reason_code="CREDIT_LIMIT_QUERIED")

    def _analyze_request(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            requested_limit = parse_money(user_message)
        except ValueError:
            state["assistant_message"] = (
                "Informe um valor válido para o novo limite, por exemplo R$ 5.000,00."
            )
            return state

        with _CREDIT_DECISION_LOCK:
            return self._decide_request(state, requested_limit)

    def _decide_request(
        self,
        state: ConversationState,
        requested_limit: Decimal,
        *,
        reanalysis: bool = False,
    ) -> ConversationState:

        customer = self._load_customer(state)
        if customer is None:
            return self._repository_failure(state)
        if requested_limit <= customer.credit_limit:
            if reanalysis:
                state["requested_credit_limit"] = None
                state["assistant_message"] = (
                    f"Seu limite atual de {format_brl(customer.credit_limit)} "
                    "já atende ao valor solicitado. Posso ajudar com outro assunto?"
                )
                return self._return_to_triage(
                    state,
                    reason_code="CREDIT_REANALYSIS_ALREADY_SATISFIED",
                    tolerate_audit_failure=True,
                )
            state["assistant_message"] = (
                f"O novo limite deve ser maior que o atual, de {format_brl(customer.credit_limit)}."
            )
            return state

        try:
            maximum_limit = self._score_policy.maximum_limit_for(score=customer.credit_score)
        except CreditRepositoryError:
            return self._repository_failure(state)

        approved = requested_limit <= maximum_limit
        request = CreditRequest(
            customer_cpf=customer.cpf,
            requested_at=datetime.now(UTC),
            current_limit=customer.credit_limit,
            requested_limit=requested_limit,
            status="aprovado" if approved else "rejeitado",
        )
        try:
            self._audit_decision(state, approved=approved)
            if approved:
                self._persist_approved_request(request)
            else:
                self._requests.append(request)
        except (AuditWriteError, CreditRepositoryError, CustomerRepositoryError):
            return self._repository_failure(state)

        if approved:
            state["requested_credit_limit"] = None
            state["assistant_message"] = (
                f"Sua solicitação foi aprovada. Seu novo limite é "
                f"{format_brl(requested_limit)}. Posso ajudar com outro assunto?"
            )
            return self._return_to_triage(
                state,
                reason_code=(
                    "CREDIT_REANALYSIS_APPROVED" if reanalysis else "CREDIT_REQUEST_APPROVED"
                ),
                tolerate_audit_failure=True,
            )

        if reanalysis:
            state["requested_credit_limit"] = None
            state["assistant_message"] = (
                "Mesmo após o recálculo do score, o limite solicitado ainda não pôde ser "
                "aprovado. Posso ajudar com outro assunto?"
            )
            return self._return_to_triage(
                state,
                reason_code="CREDIT_REANALYSIS_REJECTED",
                tolerate_audit_failure=True,
            )

        state["requested_credit_limit"] = requested_limit
        state["credit_stage"] = "offering_interview"
        state["assistant_message"] = (
            "A solicitação foi rejeitada porque excede o limite permitido para seu score. "
            "Você deseja realizar uma entrevista financeira para recalcular o score?"
        )
        return state

    def _persist_approved_request(self, request: CreditRequest) -> None:
        self._customers.update_credit_limit(
            cpf=request.customer_cpf,
            credit_limit=request.requested_limit,
        )
        try:
            self._requests.append(request)
        except CreditRepositoryError:
            self._customers.update_credit_limit(
                cpf=request.customer_cpf,
                credit_limit=request.current_limit,
            )
            raise

    def _handle_interview_offer(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        answer = _parse_yes_no(user_message)
        if answer is None:
            state["assistant_message"] = (
                "Você deseja realizar a entrevista financeira? Responda sim ou não."
            )
            return state
        if answer:
            try:
                self._audit_handoff(state, reason_code="ROUTED_TO_INTERVIEW")
            except AuditWriteError:
                return self._repository_failure(state)
            state["active_agent"] = "interview"
            state["assistant_message"] = (
                "Certo. Vamos iniciar sua entrevista financeira. Qual é sua renda mensal?"
            )
            return state

        state["requested_credit_limit"] = None
        state["assistant_message"] = "Tudo bem. Posso ajudar com outro assunto?"
        return self._return_to_triage(state, reason_code="INTERVIEW_DECLINED")

    def _load_customer(self, state: ConversationState) -> Customer | None:
        cpf = state["cpf"]
        if cpf is None:
            return None
        try:
            return self._customers.get_by_cpf(cpf=cpf)
        except CustomerRepositoryError:
            return None

    def _audit_decision(self, state: ConversationState, *, approved: bool) -> None:
        self._audit_writer.append(
            AuditEvent(
                event_type="credit_decision_made",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="credit",
                outcome="approved" if approved else "rejected",
                reason_code="WITHIN_SCORE_LIMIT" if approved else "EXCEEDS_SCORE_LIMIT",
                subject_ref=self._subject_ref(state),
                policy_version=SCORE_POLICY_VERSION,
            )
        )

    def _audit_handoff(self, state: ConversationState, *, reason_code: str) -> None:
        self._audit_writer.append(
            AuditEvent(
                event_type="agent_handoff",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="credit",
                outcome="success",
                reason_code=reason_code,
                subject_ref=self._subject_ref(state),
            )
        )

    def _return_to_triage(
        self,
        state: ConversationState,
        *,
        reason_code: str,
        tolerate_audit_failure: bool = False,
    ) -> ConversationState:
        try:
            self._audit_handoff(state, reason_code=reason_code)
        except AuditWriteError:
            if not tolerate_audit_failure:
                return self._repository_failure(state)
        state["active_agent"] = "triage"
        state["triage_stage"] = "awaiting_intent"
        state["credit_stage"] = "awaiting_action"
        return state

    def _subject_ref(self, state: ConversationState) -> str:
        cpf = state["cpf"]
        if cpf is None:
            raise ValueError("authenticated customer cpf is required")
        return pseudonymize_subject(cpf, key=self._pseudonymization_key)

    @staticmethod
    def _repository_failure(state: ConversationState) -> ConversationState:
        state["assistant_message"] = (
            "Não foi possível processar a operação de crédito agora. "
            "Tente novamente em alguns instantes."
        )
        return state

    @staticmethod
    def _ensure_credit_can_respond(state: ConversationState) -> None:
        if state["end_reason"] is not None:
            raise ValueError("conversation has already ended")
        if not state["authenticated"] or state["cpf"] is None:
            raise ValueError("credit agent requires an authenticated customer")
        if state["active_agent"] != "credit":
            raise ValueError("credit agent cannot respond outside its scope")


def _identify_action(message: str) -> CreditAction | None:
    normalized_message = normalize_text(message)
    matches = {
        action
        for action, terms in _ACTION_TERMS.items()
        if any(term in normalized_message for term in terms)
    }
    if len(matches) != 1:
        return None
    return matches.pop()


def _parse_yes_no(message: str) -> bool | None:
    normalized_message = normalize_text(message)
    if normalized_message in {"sim", "quero", "aceito", "pode ser"}:
        return True
    if normalized_message in {"nao", "nao quero", "agora nao", "recuso"}:
        return False
    return None
