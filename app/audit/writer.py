import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.audit.events import AuditEvent

_AUDIT_WRITE_LOCK = Lock()


class AuditWriter(Protocol):
    """Port used by the application to record business events."""

    def append(self, event: AuditEvent) -> None:
        """Append one event to the audit trail."""


class JsonlAuditWriter:
    """Append audit events as one JSON object per line."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["occurred_at"] = event.occurred_at.isoformat()
        serialized_event = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        with _AUDIT_WRITE_LOCK:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(f"{serialized_event}\n")
