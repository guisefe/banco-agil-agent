from app.models.conversation import initial_state
from app.ui.privacy import safe_user_message_for_display


def test_ui_masks_cpf_and_birth_date() -> None:
    state = initial_state()
    state["triage_stage"] = "awaiting_cpf"
    assert "00000000000" not in safe_user_message_for_display(state, "00000000000")

    state["triage_stage"] = "awaiting_birth_date"
    assert "20/05/1990" not in safe_user_message_for_display(state, "20/05/1990")


def test_ui_preserves_regular_and_end_messages() -> None:
    state = initial_state()
    state["triage_stage"] = "awaiting_intent"

    assert safe_user_message_for_display(state, "Quero crédito") == "Quero crédito"

    state["triage_stage"] = "awaiting_cpf"
    assert safe_user_message_for_display(state, "encerrar") == "encerrar"


def test_ui_masks_each_financial_interview_answer() -> None:
    state = initial_state()
    state["active_agent"] = "interview"
    expected_labels = {
        "awaiting_income": "Renda mensal informada.",
        "awaiting_employment": "Tipo de emprego informado.",
        "awaiting_expenses": "Despesas fixas informadas.",
        "awaiting_dependents": "Número de dependentes informado.",
        "awaiting_debts": "Situação de dívidas informada.",
    }

    for stage, label in expected_labels.items():
        state["interview_stage"] = stage  # type: ignore[typeddict-item]
        assert safe_user_message_for_display(state, "sensitive value") == label
