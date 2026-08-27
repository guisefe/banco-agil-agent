from app.models.conversation import ConversationState
from app.tools.conversation import is_end_request
from app.tools.identity import IdentityInputError, normalize_cpf, parse_birth_date


def safe_user_message_for_display(
    state: ConversationState,
    user_message: str,
) -> str:
    if is_end_request(user_message):
        return user_message
    if state["triage_stage"] == "awaiting_cpf":
        return f"CPF informado: {_partially_mask_cpf(user_message)}"
    if state["triage_stage"] == "awaiting_birth_date":
        return f"Data de nascimento informada: {_partially_mask_birth_date(user_message)}"
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


def _partially_mask_cpf(value: str) -> str:
    try:
        cpf = normalize_cpf(value)
    except IdentityInputError:
        return "***.***.***-**"
    return f"***.***.***-{cpf[-2:]}"


def _partially_mask_birth_date(value: str) -> str:
    try:
        birth_date = parse_birth_date(value)
    except IdentityInputError:
        return "**/**/****"
    return f"**/**/{birth_date.year:04d}"
