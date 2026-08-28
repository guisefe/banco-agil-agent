import unicodedata

from app.models.conversation import ConversationState, EndReason

_END_REQUESTS = frozenset(
    {
        "encerrar",
        "encerrar atendimento",
        "fim",
        "finalizar",
        "parar",
        "quero encerrar",
        "quero sair",
        "sair",
    }
)

USER_REQUESTED_END_MESSAGE = (
    "Tudo certo! Seu atendimento foi finalizado. Obrigado por conversar com o Banco Ágil. "
    "Tenha um ótimo dia!"
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(without_accents.casefold().strip().split())


def is_end_request(message: str) -> bool:
    return normalize_text(message) in _END_REQUESTS


def end_conversation(
    state: ConversationState,
    *,
    reason: EndReason,
    assistant_message: str,
) -> ConversationState:
    ended_state = clear_interview_data(state)
    ended_state["assistant_message"] = assistant_message
    ended_state["end_reason"] = reason
    ended_state["authenticated"] = False
    ended_state["cpf"] = None
    ended_state["birth_date"] = None
    ended_state["customer_name"] = None
    ended_state["requested_credit_limit"] = None
    ended_state["pending_credit_requested_at"] = None
    ended_state["handoff_pending"] = False
    ended_state["interpreted_intent"] = None
    ended_state["interpreted_currency"] = None
    return ended_state


def clear_interview_data(state: ConversationState) -> ConversationState:
    cleared_state = state.copy()
    cleared_state["interview_stage"] = "awaiting_income"
    cleared_state["monthly_income"] = None
    cleared_state["employment_type"] = None
    cleared_state["fixed_expenses"] = None
    cleared_state["dependents"] = None
    cleared_state["has_active_debts"] = None
    return cleared_state
