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
    if state["active_agent"] == "interview":
        labels = {
            "awaiting_income": "Renda mensal informada.",
            "awaiting_employment": "Tipo de emprego informado.",
            "awaiting_expenses": "Despesas fixas informadas.",
            "awaiting_dependents": "Número de dependentes informado.",
            "awaiting_debts": "Situação de dívidas informada.",
        }
        return labels[state["interview_stage"]]
    return user_message
