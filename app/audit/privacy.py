import hashlib
import hmac

MIN_PSEUDONYMIZATION_KEY_BYTES = 32


def pseudonymize_subject(identifier: str, *, key: bytes) -> str:
    """Create a stable, non-reversible reference without persisting the identifier."""
    normalized_identifier = "".join(identifier.split())
    if not normalized_identifier:
        raise ValueError("identifier must not be blank")

    if len(key) < MIN_PSEUDONYMIZATION_KEY_BYTES:
        raise ValueError(
            f"pseudonymization key must contain at least {MIN_PSEUDONYMIZATION_KEY_BYTES} bytes"
        )

    digest = hmac.new(
        key,
        normalized_identifier.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"
