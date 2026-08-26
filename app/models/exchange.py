from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class ExchangeQuote:
    """A validated BRL quote returned by an external provider."""

    currency: str
    buy_rate: Decimal
    sell_rate: Decimal
    quoted_at: datetime

    def __post_init__(self) -> None:
        if self.currency not in {"USD", "EUR", "ARS", "GBP", "JPY"}:
            raise ValueError("currency is not supported")
        if not self.buy_rate.is_finite() or self.buy_rate <= 0:
            raise ValueError("buy_rate must be positive and finite")
        if not self.sell_rate.is_finite() or self.sell_rate <= 0:
            raise ValueError("sell_rate must be positive and finite")
        if self.quoted_at.utcoffset() != timedelta(0):
            raise ValueError("quoted_at must use UTC")
