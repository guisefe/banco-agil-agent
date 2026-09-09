from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class CreditDecision:
    approved: bool

    @property
    def reason_code(self) -> Literal["WITHIN_SCORE_LIMIT", "EXCEEDS_SCORE_LIMIT"]:
        return "WITHIN_SCORE_LIMIT" if self.approved else "EXCEEDS_SCORE_LIMIT"


def evaluate_increase(*, requested_limit: Decimal, maximum_limit: Decimal) -> CreditDecision:
    """Evaluate a positive requested limit against an already resolved policy ceiling."""
    if not requested_limit.is_finite() or requested_limit <= 0:
        raise ValueError("requested_limit must be finite and positive")
    if not maximum_limit.is_finite() or maximum_limit < 0:
        raise ValueError("maximum_limit must be finite and non-negative")
    return CreditDecision(approved=requested_limit <= maximum_limit)
