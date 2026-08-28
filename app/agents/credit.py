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
from app.models.intent import IntentName
from app.repositories.credit import (
    SCORE_POLICY_VERSION,
    CreditRepositoryError,
    CreditRequestRepository,
    ScorePolicyRepository,
)
from app.repositories.customers import CreditCustomerRepository, CustomerRepositoryError
from app.services.understanding import (
    DeterministicConversationInterpreter,
    FieldInterpreter,
    IntentInterpreter,
)
from app.tools.conversation import normalize_text
from app.tools.money import format_brl, parse_money

CreditAction = Literal["query_limit", "query_score", "adjust"]

_ACTION_TERMS: Mapping[CreditAction, frozenset[str]] = {
    "query_limit": frozenset(
        {"consultar limite", "consulta de limite", "limite atual", "qual meu limite"}
    ),
    "query_score": frozenset(
        {"consultar score", "consulta de score", "qual meu score", "saber meu score", "ver score"}
    ),
    "adjust": frozenset(
        {
            "ajustar",
            "ajuste",
            "aumentar",
            "aumento",
            "reduzir",
            "reducao",
            "diminuir",
            "novo limite",
            "mais limite",
            "solicitar limite",
        }
    ),
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
        intent_interpreter: IntentInterpreter | None = None,
        field_interpreter: FieldInterpreter | None = None,
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
        self._intent_interpreter = intent_interpreter or DeterministicConversationInterpreter()
        self._field_interpreter = field_interpreter or DeterministicConversationInterpreter()

    def respond(
        self,
        state: ConversationState,
        user_message: str,
        *,
        advance_turn: bool = True,
    ) -> ConversationState:
        self._ensure_credit_can_respond(state)
        next_state = state.copy()
        if advance_turn:
            next_state["turn_number"] += 1
        next_state["handoff_pending"] = False
        next_state["user_message"] = user_message

        if state["credit_stage"] == "awaiting_action":
            return self._choose_action(next_state, user_message)
        if state["credit_stage"] == "awaiting_requested_limit":
            return self._analyze_adjustment(next_state, user_message)
        if state["credit_stage"] == "confirming_limit_reduction":
            return self._handle_limit_reduction_confirmation(next_state, user_message)
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
            return self._process_adjustment(next_state, requested_limit, reanalysis=True)

    def _choose_action(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        action = _action_from_interpretation(state["interpreted_intent"])
        state["interpreted_intent"] = None
        state["interpreted_currency"] = None
        if action is None:
            interpretation = self._intent_interpreter.interpret(user_message)
            state["last_interpretation_source"] = interpretation.source
            state["interpreted_requested_limit"] = interpretation.requested_limit
            action = _action_from_interpretation(interpretation.intent)
        if action is None:
            action = _identify_action(user_message)
        if action is None:
            state["assistant_message"] = (
                "Posso consultar ou ajustar seu limite e informar seu score interno. "
                "O que você deseja?"
            )
            return state
        if action == "adjust":
            interpreted_limit = state["interpreted_requested_limit"]
            state["interpreted_requested_limit"] = None
            state["credit_stage"] = "awaiting_requested_limit"
            if interpreted_limit is not None:
                with _CREDIT_DECISION_LOCK:
                    return self._process_adjustment(state, interpreted_limit)
            state["assistant_message"] = "Qual é o novo limite total que você deseja?"
            return state

        state["interpreted_requested_limit"] = None

        customer = self._load_customer(state)
        if customer is None:
            return self._repository_failure(state)
        if action == "query_score":
            if customer.credit_score is None:
                state["credit_stage"] = "offering_interview"
                state["assistant_message"] = (
                    "Você ainda não possui score interno calculado. Isso não é score zero: "
                    "significa que faltam dados para uma decisão automática. Deseja realizar "
                    "a entrevista financeira para calcular seu score de 0 a 1000?"
                )
                return state
            state["assistant_message"] = (
                f"Seu score interno no Banco Ágil é {customer.credit_score} de 1000. "
                "Ele é um dos critérios usados na política de limite. "
                "Posso ajudar com outro assunto?"
            )
            return self._return_to_triage(state, reason_code="CREDIT_SCORE_QUERIED")
        state["assistant_message"] = (
            f"Seu limite atual é {format_brl(customer.credit_limit)}. "
            "Posso ajudar com outro assunto de crédito ou câmbio?"
        )
        return self._return_to_triage(state, reason_code="CREDIT_LIMIT_QUERIED")

    def _analyze_adjustment(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            requested_limit = parse_money(user_message)
        except ValueError:
            interpretation = self._field_interpreter.interpret_field(
                user_message,
                expected="money",
            )
            state["last_interpretation_source"] = interpretation.source
            try:
                requested_limit = parse_money(interpretation.value or "")
            except ValueError:
                state["assistant_message"] = (
                    "Informe um valor válido para o novo limite, por exemplo R$ 5.000,00."
                )
                return state

        with _CREDIT_DECISION_LOCK:
            return self._process_adjustment(state, requested_limit)

    def _process_adjustment(
        self,
        state: ConversationState,
        requested_limit: Decimal,
        *,
        reanalysis: bool = False,
    ) -> ConversationState:

        customer = self._load_customer(state)
        if customer is None:
            return self._repository_failure(state)
        if reanalysis and requested_limit <= customer.credit_limit:
            try:
                pending_requested_at = self._pending_requested_at(state)
                if pending_requested_at is not None:
                    self._requests.finalize_pending(
                        customer_cpf=customer.cpf,
                        requested_at=pending_requested_at,
                        status="aprovado",
                    )
            except CreditRepositoryError:
                return self._repository_failure(state)
            state["requested_credit_limit"] = None
            state["pending_credit_requested_at"] = None
            state["assistant_message"] = (
                f"Seu limite atual de {format_brl(customer.credit_limit)} "
                "já atende ao valor solicitado. Posso ajudar com outro assunto?"
            )
            return self._return_to_triage(
                state,
                reason_code="CREDIT_REANALYSIS_ALREADY_SATISFIED",
                tolerate_audit_failure=True,
            )
        if requested_limit == customer.credit_limit:
            state["requested_credit_limit"] = None
            state["assistant_message"] = (
                f"Seu limite já está ajustado em {format_brl(customer.credit_limit)}. "
                "Posso ajudar com outro assunto?"
            )
            return self._return_to_triage(
                state,
                reason_code="CREDIT_LIMIT_ALREADY_SET",
                tolerate_audit_failure=True,
            )
        if requested_limit < customer.credit_limit:
            state["requested_credit_limit"] = requested_limit
            state["credit_stage"] = "confirming_limit_reduction"
            state["assistant_message"] = (
                f"Seu limite atual é {format_brl(customer.credit_limit)}. "
                f"Você deseja reduzi-lo para {format_brl(requested_limit)}? "
                "Responda sim ou não."
            )
            return state

        if customer.credit_score is None:
            return self._defer_request_for_interview(
                state,
                customer=customer,
                requested_limit=requested_limit,
            )

        try:
            maximum_limit = self._score_policy.maximum_limit_for(score=customer.credit_score)
        except CreditRepositoryError:
            return self._repository_failure(state)

        approved = requested_limit <= maximum_limit
        try:
            pending_requested_at = self._pending_requested_at(state) if reanalysis else None
        except CreditRepositoryError:
            return self._repository_failure(state)
        request = CreditRequest(
            customer_cpf=customer.cpf,
            requested_at=pending_requested_at or datetime.now(UTC),
            current_limit=customer.credit_limit,
            requested_limit=requested_limit,
            status="aprovado" if approved else "rejeitado",
        )
        try:
            self._audit_decision(state, approved=approved)
            if approved:
                self._persist_approved_request(
                    request,
                    finalize_pending=pending_requested_at is not None,
                )
            else:
                self._persist_rejected_request(
                    request,
                    finalize_pending=pending_requested_at is not None,
                )
        except (AuditWriteError, CreditRepositoryError, CustomerRepositoryError):
            return self._repository_failure(state)

        if approved:
            state["requested_credit_limit"] = None
            state["pending_credit_requested_at"] = None
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
            state["pending_credit_requested_at"] = None
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

    def _handle_limit_reduction_confirmation(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        answer = _parse_yes_no(user_message)
        if answer is None:
            interpretation = self._field_interpreter.interpret_field(
                user_message,
                expected="yes_no",
            )
            state["last_interpretation_source"] = interpretation.source
            answer = _parse_yes_no(interpretation.value or "")
        if answer is None:
            state["assistant_message"] = (
                "Você deseja confirmar a redução do limite? Responda sim ou não."
            )
            return state
        if not answer:
            state["requested_credit_limit"] = None
            state["assistant_message"] = (
                "Tudo bem, seu limite atual foi mantido. Posso ajudar com outro assunto?"
            )
            return self._return_to_triage(
                state,
                reason_code="CREDIT_LIMIT_REDUCTION_CANCELLED",
                tolerate_audit_failure=True,
            )

        requested_limit = state["requested_credit_limit"]
        if requested_limit is None:
            return self._repository_failure(state)
        with _CREDIT_DECISION_LOCK:
            customer = self._load_customer(state)
            if customer is None or requested_limit >= customer.credit_limit:
                return self._repository_failure(state)
            try:
                self._customers.update_credit_limit(
                    cpf=customer.cpf,
                    credit_limit=requested_limit,
                )
                try:
                    self._audit_writer.append(
                        AuditEvent(
                            event_type="credit_limit_adjusted",
                            conversation_id=state["conversation_id"],
                            turn_number=state["turn_number"],
                            agent="credit",
                            outcome="success",
                            reason_code="CREDIT_LIMIT_REDUCTION_CONFIRMED",
                            subject_ref=self._subject_ref(state),
                        )
                    )
                except AuditWriteError:
                    self._customers.update_credit_limit(
                        cpf=customer.cpf,
                        credit_limit=customer.credit_limit,
                    )
                    raise
            except (AuditWriteError, CustomerRepositoryError):
                return self._repository_failure(state)

        state["requested_credit_limit"] = None
        state["assistant_message"] = (
            f"Seu limite foi reduzido para {format_brl(requested_limit)}. "
            "Posso ajudar com outro assunto?"
        )
        return self._return_to_triage(
            state,
            reason_code="CREDIT_LIMIT_REDUCED",
            tolerate_audit_failure=True,
        )

    def _persist_approved_request(
        self,
        request: CreditRequest,
        *,
        finalize_pending: bool,
    ) -> None:
        self._customers.update_credit_limit(
            cpf=request.customer_cpf,
            credit_limit=request.requested_limit,
        )
        try:
            if finalize_pending:
                self._requests.finalize_pending(
                    customer_cpf=request.customer_cpf,
                    requested_at=request.requested_at,
                    status="aprovado",
                )
            else:
                self._requests.append(request)
        except CreditRepositoryError:
            self._customers.update_credit_limit(
                cpf=request.customer_cpf,
                credit_limit=request.current_limit,
            )
            raise

    def _persist_rejected_request(
        self,
        request: CreditRequest,
        *,
        finalize_pending: bool,
    ) -> None:
        if finalize_pending:
            self._requests.finalize_pending(
                customer_cpf=request.customer_cpf,
                requested_at=request.requested_at,
                status="rejeitado",
            )
        else:
            self._requests.append(request)

    def _handle_interview_offer(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        answer = _parse_yes_no(user_message)
        if answer is None:
            interpretation = self._field_interpreter.interpret_field(
                user_message,
                expected="yes_no",
            )
            state["last_interpretation_source"] = interpretation.source
            answer = _parse_yes_no(interpretation.value or "")
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

        pending_requested_at = self._pending_requested_at(state)
        if pending_requested_at is not None:
            cpf = state["cpf"]
            if cpf is None:
                return self._repository_failure(state)
            try:
                self._requests.finalize_pending(
                    customer_cpf=cpf,
                    requested_at=pending_requested_at,
                    status="rejeitado",
                )
            except CreditRepositoryError:
                return self._repository_failure(state)
        state["requested_credit_limit"] = None
        state["pending_credit_requested_at"] = None
        state["assistant_message"] = "Tudo bem. Posso ajudar com outro assunto?"
        return self._return_to_triage(state, reason_code="INTERVIEW_DECLINED")

    def _defer_request_for_interview(
        self,
        state: ConversationState,
        *,
        customer: Customer,
        requested_limit: Decimal,
    ) -> ConversationState:
        requested_at = datetime.now(UTC)
        request = CreditRequest(
            customer_cpf=customer.cpf,
            requested_at=requested_at,
            current_limit=customer.credit_limit,
            requested_limit=requested_limit,
            status="pendente",
        )
        try:
            self._audit_writer.append(
                AuditEvent(
                    event_type="credit_assessment_deferred",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="credit",
                    outcome="success",
                    reason_code="MISSING_CREDIT_SCORE",
                    subject_ref=self._subject_ref(state),
                    policy_version=SCORE_POLICY_VERSION,
                )
            )
            self._requests.append(request)
        except (AuditWriteError, CreditRepositoryError):
            return self._repository_failure(state)

        state["requested_credit_limit"] = requested_limit
        state["pending_credit_requested_at"] = requested_at.isoformat()
        state["credit_stage"] = "offering_interview"
        state["assistant_message"] = (
            "Sua solicitação ficou pendente porque ainda não há score interno suficiente "
            "para uma decisão automática. Deseja realizar a entrevista financeira para "
            "calcular um score de 0 a 1000 e reanalisar este mesmo pedido?"
        )
        return state

    @staticmethod
    def _pending_requested_at(state: ConversationState) -> datetime | None:
        value = state["pending_credit_requested_at"]
        if value is None:
            return None
        try:
            requested_at = datetime.fromisoformat(value)
        except ValueError as error:
            raise CreditRepositoryError("pending request timestamp is invalid") from error
        if requested_at.utcoffset() is None:
            raise CreditRepositoryError("pending request timestamp must use a timezone")
        return requested_at.astimezone(UTC)

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
    if any(term in normalized_message.split() for term in {"consultar", "consulta"}) and (
        "query_score" not in matches
    ):
        matches.add("query_limit")
    if len(matches) != 1:
        return None
    return matches.pop()


def _action_from_interpretation(intent: IntentName | None) -> CreditAction | None:
    if intent is None:
        return None
    actions: Mapping[IntentName, CreditAction] = {
        "credit_limit_query": "query_limit",
        "credit_score_query": "query_score",
        "credit_limit_adjustment": "adjust",
    }
    return actions.get(intent)


def _parse_yes_no(message: str) -> bool | None:
    normalized_message = normalize_text(message).translate(str.maketrans("", "", ".,!?"))
    if normalized_message in {"sim", "sim pode", "pode", "quero", "aceito", "pode ser"}:
        return True
    if normalized_message in {"nao", "nao quero", "agora nao", "recuso"}:
        return False
    return None
