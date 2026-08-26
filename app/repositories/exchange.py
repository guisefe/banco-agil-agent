from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from app.models.exchange import ExchangeQuote

AWESOME_API_BASE_URL = "https://economia.awesomeapi.com.br/json/last"
EXCHANGE_TIMEOUT_SECONDS = 5.0
MAX_TRANSPORT_ATTEMPTS = 2


class ExchangeRateRepository(Protocol):
    def get_brl_quote(self, *, currency: str) -> ExchangeQuote: ...


class ExchangeRateUnavailableError(RuntimeError):
    """Raised when a quote cannot be safely obtained from the provider."""


class AwesomeApiExchangeRateRepository:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = EXCHANGE_TIMEOUT_SECONDS,
        api_key: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client or httpx.Client(timeout=timeout_seconds, trust_env=False)
        self._timeout_seconds = timeout_seconds
        self._api_key = api_key

    def get_brl_quote(self, *, currency: str) -> ExchangeQuote:
        if currency not in {"USD", "EUR", "ARS", "GBP", "JPY"}:
            raise ValueError("currency is not supported")
        headers = {"x-api-key": self._api_key} if self._api_key else None
        response = self._request_with_retry(currency=currency, headers=headers)
        if response.status_code != httpx.codes.OK:
            raise ExchangeRateUnavailableError("provider returned an unsuccessful response")
        try:
            payload = response.json()
            quote = _extract_quote(payload, currency=currency)
        except (TypeError, ValueError, KeyError, InvalidOperation) as error:
            raise ExchangeRateUnavailableError("provider returned an invalid quote") from error
        return quote

    def _request_with_retry(
        self,
        *,
        currency: str,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        last_error: httpx.TransportError | None = None
        for _ in range(MAX_TRANSPORT_ATTEMPTS):
            try:
                return self._client.get(
                    f"{AWESOME_API_BASE_URL}/{currency}-BRL",
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            except httpx.TransportError as error:
                last_error = error
        raise ExchangeRateUnavailableError("provider connection failed") from last_error


def _extract_quote(payload: object, *, currency: str) -> ExchangeQuote:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    raw_quote = payload[f"{currency}BRL"]
    if not isinstance(raw_quote, dict):
        raise ValueError("quote must be an object")
    buy_rate = Decimal(str(raw_quote["bid"]))
    sell_rate = Decimal(str(raw_quote["ask"]))
    raw_timestamp = raw_quote["timestamp"]
    quoted_at = datetime.fromtimestamp(int(str(raw_timestamp)), tz=UTC)
    return ExchangeQuote(
        currency=currency,
        buy_rate=buy_rate,
        sell_rate=sell_rate,
        quoted_at=quoted_at,
    )
