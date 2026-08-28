from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

IntentName = Literal[
    "credit_menu",
    "credit_limit_query",
    "credit_score_query",
    "credit_limit_adjustment",
    "credit_interview",
    "exchange_quote",
    "unknown",
]
IntentSource = Literal["llm", "deterministic", "deterministic_fallback"]
SupportedCurrency = Literal["USD", "EUR", "ARS", "GBP", "JPY"]

ALLOWED_INTENTS = frozenset(
    {
        "credit_menu",
        "credit_limit_query",
        "credit_score_query",
        "credit_limit_adjustment",
        "credit_interview",
        "exchange_quote",
        "unknown",
    }
)
SUPPORTED_CURRENCIES = frozenset({"USD", "EUR", "ARS", "GBP", "JPY"})


@dataclass(frozen=True, slots=True, kw_only=True)
class IntentInterpretation:
    intent: IntentName
    source: IntentSource
    currency: SupportedCurrency | None = None
    requested_limit: Decimal | None = None

    def __post_init__(self) -> None:
        if self.intent not in ALLOWED_INTENTS:
            raise ValueError("intent is not allowed")
        if self.currency is not None and self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError("currency is not supported")
        if self.currency is not None and self.intent != "exchange_quote":
            raise ValueError("currency is only valid for exchange quotes")
        if self.requested_limit is not None:
            if (
                not self.requested_limit.is_finite()
                or self.requested_limit <= 0
                or self.intent != "credit_limit_adjustment"
            ):
                raise ValueError("requested_limit is only valid for a positive limit adjustment")
