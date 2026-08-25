from app.models.conversation import ConversationState
from app.tools.conversation import is_end_request


def safe_user_message_for_display(
    state: ConversationState,
    user_message: str,
) -> str:
    if is_end_request(user_message):
        return user_message
    if state["triage_stage"] == "awaiting_cpf":
        return "CPF informado: ***.***.***-**"
    if state["triage_stage"] == "awaiting_birth_date":
        return "Data de nascimento informada: **/**/****"
    return user_message
