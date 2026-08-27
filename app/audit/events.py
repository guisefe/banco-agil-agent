import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from app.models.conversation import AgentName

AuditEventType = Literal[
    "conversation_started",
    "authentication_attempted",
    "agent_handoff",
    "credit_decision_made",
    "credit_assessment_deferred",
    "customer_profile_updated",
    "exchange_quote_requested",
    "conversation_ended",
]

AuditOutcome = Literal[
    "success",
    "failure",
    "approved",
    "rejected",
]

_REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEvent:
    """Immutable business event safe to persist in the audit trail."""

    event_type: AuditEventType
    conversation_id: str
    turn_number: int
    agent: AgentName

    outcome: AuditOutcome | None = None
    reason_code: str | None = None
    subject_ref: str | None = None
    policy_version: str | None = None

    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("conversation_id must not be blank")

        if self.turn_number < 0:
            raise ValueError("turn_number must be non-negative")

        if self.outcome in {"failure", "rejected"} and not self.reason_code:
            raise ValueError("reason_code is required for failure or rejection")

        if self.reason_code is not None and not _REASON_CODE_PATTERN.fullmatch(self.reason_code):
            raise ValueError("reason_code must be an uppercase machine-readable code")

        if self.subject_ref is not None and not self.subject_ref.strip():
            raise ValueError("subject_ref must not be blank")

        if self.policy_version is not None and not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")

        if self.event_type == "credit_decision_made":
            if self.outcome not in {"approved", "rejected"}:
                raise ValueError("credit decisions require an approved or rejected outcome")
            if self.policy_version is None:
                raise ValueError("credit decisions require policy_version")

        try:
            UUID(self.event_id)
        except ValueError as error:
            raise ValueError("event_id must be a valid UUID") from error

        if self.occurred_at.utcoffset() != timedelta(0):
            raise ValueError("occurred_at must use UTC")
