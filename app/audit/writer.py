import json
import os
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.audit.events import AuditEvent

_AUDIT_WRITE_LOCK = Lock()


class AuditWriteError(RuntimeError):
    """Raised when an audit event cannot be persisted safely."""


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
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not self._path.exists():
                    self._path.touch(mode=0o600)

                with self._path.open("a", encoding="utf-8") as audit_file:
                    audit_file.write(f"{serialized_event}\n")
                    audit_file.flush()
                    os.fsync(audit_file.fileno())
            except OSError as error:
                raise AuditWriteError("failed to persist audit event") from error
