from app.models.conversation import initial_state
from app.tools.conversation import end_conversation, is_end_request, normalize_text


def test_normalize_text_removes_accents_case_and_extra_spaces() -> None:
    assert normalize_text("  COTAÇÃO   de DÓLAR ") == "cotacao de dolar"


def test_end_request_requires_an_explicit_command() -> None:
    assert is_end_request("Quero encerrar") is True
    assert is_end_request("não quero encerrar") is False


def test_end_conversation_returns_updated_copy() -> None:
    original_state = initial_state()
    original_state["authenticated"] = True
    original_state["cpf"] = "00000000000"
    original_state["birth_date"] = "1990-05-20"
    original_state["customer_name"] = "Ana Exemplo"

    ended_state = end_conversation(
        original_state,
        reason="user_requested",
        assistant_message="Encerrado.",
    )

    assert ended_state["end_reason"] == "user_requested"
    assert ended_state["assistant_message"] == "Encerrado."
    assert ended_state["authenticated"] is False
    assert ended_state["cpf"] is None
    assert ended_state["birth_date"] is None
    assert ended_state["customer_name"] is None
    assert original_state["end_reason"] is None
