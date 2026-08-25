from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from app.models.conversation import AgentName

AuditEventType = Literal[
    "conversation_started",
    "authentication_attempted",
    "agent_handoff",
    "conversation_ended",
]

AuditOutcome = Literal[
    "success",
    "failure",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEvent:
    """Immutable business event safe to persist in the audit trail."""

    event_type: AuditEventType
    conversation_id: str
    turn_number: int
    agent: AgentName

    outcome: AuditOutcome | None = None
    reason_code: str | None = None

    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("conversation_id must not be blank")

        if self.turn_number < 0:
            raise ValueError("turn_number must be non-negative")

        if self.outcome == "failure" and not self.reason_code:
            raise ValueError("reason_code is required for failed events")

        if self.reason_code is not None and not self.reason_code.strip():
            raise ValueError("reason_code must not be blank")

        try:
            UUID(self.event_id)
        except ValueError as error:
            raise ValueError("event_id must be a valid UUID") from error

        if self.occurred_at.utcoffset() != timedelta(0):
            raise ValueError("occurred_at must use UTC")
