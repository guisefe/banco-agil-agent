import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.audit.privacy import MIN_PSEUDONYMIZATION_KEY_BYTES

AUDIT_KEY_ENVIRONMENT_VARIABLE = "AUDIT_PSEUDONYMIZATION_KEY"
EXCHANGE_API_KEY_ENVIRONMENT_VARIABLE = "EXCHANGE_API_KEY"


class ConfigurationError(RuntimeError):
    """Raised when application configuration is unsafe or invalid."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    project_root: Path
    customer_file: Path
    score_policy_file: Path
    credit_request_file: Path
    audit_file: Path
    exchange_api_key: str | None
    pseudonymization_key: bytes
    uses_ephemeral_audit_key: bool


def load_settings(
    *,
    project_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Settings:
    resolved_root = project_root or Path(__file__).resolve().parent.parent
    source_environment = environment if environment is not None else os.environ
    configured_key = source_environment.get(AUDIT_KEY_ENVIRONMENT_VARIABLE)

    if configured_key is None:
        pseudonymization_key = secrets.token_bytes(MIN_PSEUDONYMIZATION_KEY_BYTES)
        uses_ephemeral_key = True
    else:
        pseudonymization_key = configured_key.encode("utf-8")
        uses_ephemeral_key = False
        if len(pseudonymization_key) < MIN_PSEUDONYMIZATION_KEY_BYTES:
            raise ConfigurationError(
                f"{AUDIT_KEY_ENVIRONMENT_VARIABLE} must contain at least "
                f"{MIN_PSEUDONYMIZATION_KEY_BYTES} bytes"
            )

    return Settings(
        project_root=resolved_root,
        customer_file=resolved_root / "data" / "clientes.csv",
        score_policy_file=resolved_root / "data" / "score_limite.csv",
        credit_request_file=resolved_root / "data" / "solicitacoes_aumento_limite.csv",
        audit_file=resolved_root / "data" / "audit_events.jsonl",
        exchange_api_key=source_environment.get(EXCHANGE_API_KEY_ENVIRONMENT_VARIABLE),
        pseudonymization_key=pseudonymization_key,
        uses_ephemeral_audit_key=uses_ephemeral_key,
    )
