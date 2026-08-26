from uuid import UUID

from app.models.conversation import initial_state


def test_initial_state_uses_safe_defaults() -> None:
    state = initial_state()

    assert str(UUID(state["conversation_id"])) == state["conversation_id"]
    assert state["turn_number"] == 0
    assert state["user_message"] == ""
    assert state["assistant_message"] == ""

    assert state["authenticated"] is False
    assert state["cpf"] is None
    assert state["birth_date"] is None
    assert state["customer_name"] is None
    assert state["authentication_attempts"] == 0

    assert state["active_agent"] == "triage"
    assert state["triage_stage"] == "greeting"
    assert state["credit_stage"] == "awaiting_action"
    assert state["requested_credit_limit"] is None
    assert state["interview_stage"] == "awaiting_income"
    assert state["monthly_income"] is None
    assert state["employment_type"] is None
    assert state["fixed_expenses"] is None
    assert state["dependents"] is None
    assert state["has_active_debts"] is None
    assert state["end_reason"] is None


def test_initial_creates_unique_conversation_ids() -> None:
    first_state = initial_state()
    second_state = initial_state()

    assert first_state["conversation_id"] != second_state["conversation_id"]
