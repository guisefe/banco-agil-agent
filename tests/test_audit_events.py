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
    with pytest.raises(ValueError, match="reason_code"):
        AuditEvent(
            event_type="authentication_attempted",
            conversation_id="conversation-123",
            turn_number=1,
            agent="triage",
            outcome="success",
            reason_code=" ",
        )


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
