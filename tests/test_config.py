from pathlib import Path

import pytest

from app.config import (
    AUDIT_KEY_ENVIRONMENT_VARIABLE,
    ConfigurationError,
    load_settings,
)


def test_settings_use_ephemeral_key_when_environment_is_missing(tmp_path: Path) -> None:
    settings = load_settings(project_root=tmp_path, environment={})

    assert settings.uses_ephemeral_audit_key is True
    assert len(settings.pseudonymization_key) == 32
    assert settings.customer_file == tmp_path / "data" / "clientes.csv"
    assert settings.score_policy_file == tmp_path / "data" / "score_limite.csv"
    assert settings.credit_request_file == tmp_path / "data" / "solicitacoes_aumento_limite.csv"
    assert settings.audit_file == tmp_path / "data" / "audit_events.jsonl"


def test_settings_use_configured_stable_key(tmp_path: Path) -> None:
    configured_key = "stable-secret-key-with-at-least-32-bytes"

    settings = load_settings(
        project_root=tmp_path,
        environment={AUDIT_KEY_ENVIRONMENT_VARIABLE: configured_key},
    )

    assert settings.uses_ephemeral_audit_key is False
    assert settings.pseudonymization_key == configured_key.encode()


def test_settings_reject_short_configured_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=AUDIT_KEY_ENVIRONMENT_VARIABLE):
        load_settings(
            project_root=tmp_path,
            environment={AUDIT_KEY_ENVIRONMENT_VARIABLE: "short"},
        )
