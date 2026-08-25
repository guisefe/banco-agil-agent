import json
from pathlib import Path

from app.audit.events import AuditEvent
from app.audit.writer import JsonlAuditWriter


def test_jsonl_writer_creates_parent_and_appends_events(tmp_path: Path) -> None:
    audit_path = tmp_path / "nested" / "audit_events.jsonl"
    writer = JsonlAuditWriter(audit_path)

    writer.append(
        AuditEvent(
            event_type="conversation_started",
            conversation_id="conversation-123",
            turn_number=0,
            agent="triage",
        )
    )
    writer.append(
        AuditEvent(
            event_type="authentication_attempted",
            conversation_id="conversation-123",
            turn_number=1,
            agent="triage",
            outcome="failure",
            reason_code="CPF_NOT_FOUND",
        )
    )

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert records[0]["event_type"] == "conversation_started"
    assert records[1]["outcome"] == "failure"
    assert records[1]["reason_code"] == "CPF_NOT_FOUND"
    assert records[1]["occurred_at"].endswith("+00:00")
    assert "cpf" not in records[1]
    assert "birth_date" not in records[1]
