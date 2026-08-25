from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.audit.events import AuditEvent


def make_event() -> AuditEvent:
    return AuditEvent(
        event_type="conversation_started",
        conversation_id="conversation-123",
        turn_number=0,
        agent="triage",
    )


def test_audit_event_generates_traceability_fields() -> None:
    event = make_event()

    assert str(UUID(event.event_id)) == event.event_id
    assert event.occurred_at.tzinfo is UTC
    assert event.outcome is None
    assert event.reason_code is None
    assert event.subject_ref is None
    assert event.policy_version is None


def test_audit_event_is_immutable() -> None:
    event = make_event()

    with pytest.raises(FrozenInstanceError):
        event.reason_code = "changed"  # type: ignore[misc]


def test_audit_event_rejects_blank_conversation_id() -> None:
    with pytest.raises(ValueError, match="conversation_id"):
        AuditEvent(
            event_type="conversation_started",
            conversation_id=" ",
            turn_number=0,
            agent="triage",
        )


def test_audit_event_rejects_negative_turn_number() -> None:
    with pytest.raises(ValueError, match="turn_number"):
        AuditEvent(
            event_type="conversation_started",
            conversation_id="conversation-123",
            turn_number=-1,
            agent="triage",
        )


def test_failed_audit_event_requires_reason_code() -> None:
    with pytest.raises(ValueError, match="reason_code"):
        AuditEvent(
            event_type="authentication_attempted",
            conversation_id="conversation-123",
            turn_number=1,
            agent="triage",
            outcome="failure",
        )


def test_audit_event_rejects_blank_reason_code() -> None:
    with pytest.raises(ValueError, match="machine-readable"):
        AuditEvent(
            event_type="authentication_attempted",
            conversation_id="conversation-123",
            turn_number=1,
            agent="triage",
            outcome="success",
            reason_code=" ",
        )


def test_audit_event_rejects_free_text_reason_code() -> None:
    with pytest.raises(ValueError, match="machine-readable"):
        AuditEvent(
            event_type="authentication_attempted",
            conversation_id="conversation-123",
            turn_number=1,
            agent="triage",
            outcome="failure",
            reason_code="CPF not found for Maria",
        )


@pytest.mark.parametrize("field", ["subject_ref", "policy_version"])
def test_audit_event_rejects_blank_optional_reference_fields(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        AuditEvent(
            event_type="conversation_started",
            conversation_id="conversation-123",
            turn_number=0,
            agent="triage",
            **{field: " "},
        )


def test_credit_decision_requires_explainable_metadata() -> None:
    with pytest.raises(ValueError, match="approved or rejected"):
        AuditEvent(
            event_type="credit_decision_made",
            conversation_id="conversation-123",
            turn_number=4,
            agent="credit",
            outcome="success",
        )

    with pytest.raises(ValueError, match="policy_version"):
        AuditEvent(
            event_type="credit_decision_made",
            conversation_id="conversation-123",
            turn_number=4,
            agent="credit",
            outcome="rejected",
            reason_code="SCORE_BELOW_THRESHOLD",
        )


def test_credit_decision_accepts_reason_and_policy_version() -> None:
    event = AuditEvent(
        event_type="credit_decision_made",
        conversation_id="conversation-123",
        turn_number=4,
        agent="credit",
        outcome="rejected",
        reason_code="SCORE_BELOW_THRESHOLD",
        subject_ref="hmac-sha256:abc123",
        policy_version="credit-policy-v1",
    )

    assert event.policy_version == "credit-policy-v1"


def test_audit_event_rejects_invalid_event_id() -> None:
    with pytest.raises(ValueError, match="event_id"):
        AuditEvent(
            event_type="conversation_started",
            conversation_id="conversation-123",
            turn_number=0,
            agent="triage",
            event_id="invalid",
        )


def test_audit_event_rejects_timestamp_without_utc() -> None:
    with pytest.raises(ValueError, match="occurred_at"):
        AuditEvent(
            event_type="conversation_started",
            conversation_id="conversation-123",
            turn_number=0,
            agent="triage",
            occurred_at=datetime(2026, 8, 25),
        )
