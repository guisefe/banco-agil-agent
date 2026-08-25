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
