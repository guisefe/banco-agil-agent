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
    ended_state = state.copy()
    ended_state["assistant_message"] = assistant_message
    ended_state["end_reason"] = reason
    ended_state["authenticated"] = False
    ended_state["cpf"] = None
    ended_state["birth_date"] = None
    ended_state["customer_name"] = None
    ended_state["requested_credit_limit"] = None
    return ended_state
