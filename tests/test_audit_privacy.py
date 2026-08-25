import pytest

from app.audit.privacy import pseudonymize_subject

KEY = b"test-only-pseudonymization-key-32-bytes"


def test_pseudonymization_is_stable_and_does_not_expose_identifier() -> None:
    identifier = "000.000.001-91"

    first_reference = pseudonymize_subject(identifier, key=KEY)
    second_reference = pseudonymize_subject(f"  {identifier}  ", key=KEY)

    assert first_reference == second_reference
    assert first_reference.startswith("hmac-sha256:")
    assert identifier not in first_reference


def test_pseudonymization_changes_with_key() -> None:
    identifier = "000.000.001-91"

    first_reference = pseudonymize_subject(identifier, key=KEY)
    second_reference = pseudonymize_subject(
        identifier,
        key=b"another-test-only-key-with-32-bytes",
    )

    assert first_reference != second_reference


def test_pseudonymization_rejects_blank_identifier() -> None:
    with pytest.raises(ValueError, match="identifier"):
        pseudonymize_subject(" ", key=KEY)


def test_pseudonymization_rejects_short_key() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        pseudonymize_subject("000.000.001-91", key=b"short-key")
