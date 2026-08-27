from typing import cast

from app.audit.events import AuditEvent
from app.audit.privacy import MIN_PSEUDONYMIZATION_KEY_BYTES, pseudonymize_subject
from app.audit.writer import AuditWriteError, AuditWriter
from app.models.conversation import ConversationState
from app.models.interview import (
    SCORE_FORMULA_VERSION,
    FinancialProfile,
    calculate_credit_score,
    parse_debt_answer,
    parse_dependents,
    parse_employment_type,
)
from app.repositories.customers import CustomerRepositoryError, InterviewCustomerRepository
from app.tools.conversation import clear_interview_data
from app.tools.money import parse_non_negative_money


class CreditInterviewAgent:
    def __init__(
        self,
        *,
        customer_repository: InterviewCustomerRepository,
        audit_writer: AuditWriter,
        pseudonymization_key: bytes,
    ) -> None:
        if len(pseudonymization_key) < MIN_PSEUDONYMIZATION_KEY_BYTES:
            raise ValueError(
                f"pseudonymization key must contain at least {MIN_PSEUDONYMIZATION_KEY_BYTES} bytes"
            )
        self._customers = customer_repository
        self._audit_writer = audit_writer
        self._pseudonymization_key = pseudonymization_key

    def begin(self, state: ConversationState) -> ConversationState:
        self._ensure_interview_can_respond(state)
        next_state = state.copy()
        next_state["handoff_pending"] = False
        next_state["interpreted_intent"] = None
        next_state["interpreted_currency"] = None
        next_state["interpreted_requested_limit"] = None
        next_state["interview_stage"] = "awaiting_income"
        next_state["assistant_message"] = (
            "Vamos calcular seu score interno com cinco informações. "
            "Qual é sua renda mensal? Se não possui renda, informe 0."
        )
        return next_state

    def respond(self, state: ConversationState, user_message: str) -> ConversationState:
        self._ensure_interview_can_respond(state)
        next_state = state.copy()
        next_state["handoff_pending"] = False
        next_state["turn_number"] += 1
        next_state["user_message"] = "[REDACTED_FINANCIAL_INPUT]"

        if state["interview_stage"] == "awaiting_income":
            return self._collect_income(next_state, user_message)
        if state["interview_stage"] == "awaiting_employment":
            return self._collect_employment(next_state, user_message)
        if state["interview_stage"] == "awaiting_expenses":
            return self._collect_expenses(next_state, user_message)
        if state["interview_stage"] == "awaiting_dependents":
            return self._collect_dependents(next_state, user_message)
        if state["interview_stage"] == "awaiting_debts":
            return self._collect_debts_and_finish(next_state, user_message)
        raise ValueError("credit interview agent is not ready to receive a user message")

    @staticmethod
    def _collect_income(
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            state["monthly_income"] = parse_non_negative_money(user_message)
        except ValueError:
            state["assistant_message"] = (
                "Informe uma renda mensal válida, por exemplo R$ 5.000,00. "
                "Se não possui renda, informe 0."
            )
            return state
        state["interview_stage"] = "awaiting_employment"
        state["assistant_message"] = "Qual é seu tipo de emprego: formal, autônomo ou desempregado?"
        return state

    @staticmethod
    def _collect_employment(
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            state["employment_type"] = parse_employment_type(user_message)
        except ValueError:
            state["assistant_message"] = "Informe uma das opções: formal, autônomo ou desempregado."
            return state
        state["interview_stage"] = "awaiting_expenses"
        state["assistant_message"] = (
            "Qual é o total das suas despesas fixas mensais? Se não possui, informe 0."
        )
        return state

    @staticmethod
    def _collect_expenses(
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            state["fixed_expenses"] = parse_non_negative_money(user_message)
        except ValueError:
            state["assistant_message"] = (
                "Informe um valor válido para as despesas fixas mensais. Se não possui, informe 0."
            )
            return state
        state["interview_stage"] = "awaiting_dependents"
        state["assistant_message"] = "Quantas pessoas dependem financeiramente de você?"
        return state

    @staticmethod
    def _collect_dependents(
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            state["dependents"] = parse_dependents(user_message)
        except ValueError:
            state["assistant_message"] = (
                "Informe o número de dependentes usando um número inteiro, como 0, 1, 2 ou 3."
            )
            return state
        state["interview_stage"] = "awaiting_debts"
        state["assistant_message"] = "Você possui dívidas ativas? Responda sim ou não."
        return state

    def _collect_debts_and_finish(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        try:
            state["has_active_debts"] = parse_debt_answer(user_message)
        except ValueError:
            state["assistant_message"] = "Responda apenas sim ou não sobre as dívidas ativas."
            return state

        profile = self._profile_from(state)
        score = calculate_credit_score(profile)
        cpf = cast(str, state["cpf"])
        try:
            customer = self._customers.get_by_cpf(cpf=cpf)
            if customer is None:
                raise CustomerRepositoryError("customer was not found")
            self._customers.update_credit_score(cpf=cpf, credit_score=score)
        except CustomerRepositoryError:
            state["assistant_message"] = (
                "Não foi possível atualizar seu score agora. Tente novamente em alguns instantes."
            )
            return state

        try:
            self._audit_profile_update(state)
        except AuditWriteError:
            try:
                self._customers.update_credit_score(
                    cpf=cpf,
                    credit_score=customer.credit_score,
                )
            except CustomerRepositoryError:
                state["assistant_message"] = (
                    "Não foi possível concluir a atualização do score com segurança. "
                    "Encerre este atendimento e procure o suporte do Banco Ágil."
                )
                return state
            state["assistant_message"] = (
                "Não foi possível registrar a atualização do score agora. "
                "Tente novamente em alguns instantes."
            )
            return state

        completed_state = clear_interview_data(state)
        completed_state["active_agent"] = "credit"
        completed_state["credit_stage"] = "awaiting_action"
        if completed_state["requested_credit_limit"] is None:
            completed_state["assistant_message"] = (
                "Seu score foi recalculado. Você deseja consultar seu limite "
                "ou solicitar um aumento?"
            )
        else:
            completed_state["assistant_message"] = (
                "Seu score foi recalculado. Vou reanalisar o limite solicitado."
            )
        self._audit_handoff(completed_state)
        return completed_state

    @staticmethod
    def _profile_from(state: ConversationState) -> FinancialProfile:
        monthly_income = state["monthly_income"]
        employment_type = state["employment_type"]
        fixed_expenses = state["fixed_expenses"]
        dependents = state["dependents"]
        has_active_debts = state["has_active_debts"]
        if (
            monthly_income is None
            or employment_type is None
            or fixed_expenses is None
            or dependents is None
            or has_active_debts is None
        ):
            raise ValueError("financial profile is incomplete")
        return FinancialProfile(
            monthly_income=monthly_income,
            employment_type=employment_type,
            fixed_expenses=fixed_expenses,
            dependents=dependents,
            has_active_debts=has_active_debts,
        )

    def _audit_profile_update(self, state: ConversationState) -> None:
        cpf = cast(str, state["cpf"])
        subject_ref = pseudonymize_subject(cpf, key=self._pseudonymization_key)
        self._audit_writer.append(
            AuditEvent(
                event_type="customer_profile_updated",
                conversation_id=state["conversation_id"],
                turn_number=state["turn_number"],
                agent="interview",
                outcome="success",
                reason_code="CREDIT_SCORE_RECALCULATED",
                subject_ref=subject_ref,
                policy_version=SCORE_FORMULA_VERSION,
            )
        )

    def _audit_handoff(self, state: ConversationState) -> None:
        cpf = cast(str, state["cpf"])
        reason_code = (
            "ROUTED_TO_CREDIT_REANALYSIS"
            if state["requested_credit_limit"] is not None
            else "ROUTED_TO_CREDIT"
        )
        try:
            self._audit_writer.append(
                AuditEvent(
                    event_type="agent_handoff",
                    conversation_id=state["conversation_id"],
                    turn_number=state["turn_number"],
                    agent="interview",
                    outcome="success",
                    reason_code=reason_code,
                    subject_ref=pseudonymize_subject(cpf, key=self._pseudonymization_key),
                )
            )
        except AuditWriteError:
            pass

    @staticmethod
    def _ensure_interview_can_respond(state: ConversationState) -> None:
        if state["end_reason"] is not None:
            raise ValueError("conversation has already ended")
        if not state["authenticated"] or state["cpf"] is None:
            raise ValueError("credit interview requires an authenticated customer")
        if state["active_agent"] != "interview":
            raise ValueError("credit interview agent cannot respond outside its scope")
