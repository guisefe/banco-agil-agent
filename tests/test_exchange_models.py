from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.exchange import ExchangeQuote


def test_exchange_quote_accepts_a_valid_utc_quote() -> None:
    quote = ExchangeQuote(
        currency="USD",
        buy_rate=Decimal("5.1234"),
        sell_rate=Decimal("5.1334"),
        quoted_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
    )

    assert quote.currency == "USD"


def test_exchange_quote_rejects_invalid_values() -> None:
    invalid_cases: list[dict[str, object]] = [
        {"currency": "CAD"},
        {"buy_rate": Decimal("0")},
        {"sell_rate": Decimal("Infinity")},
        {"quoted_at": datetime(2026, 8, 26, 12, 0, tzinfo=timezone(timedelta(hours=1)))},
    ]

    for overrides in invalid_cases:
        values: dict[str, object] = {
            "currency": "USD",
            "buy_rate": Decimal("5.1234"),
            "sell_rate": Decimal("5.1334"),
            "quoted_at": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        }
        values.update(overrides)
        with pytest.raises(ValueError):
            ExchangeQuote(**values)  # type: ignore[arg-type]
