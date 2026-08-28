from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from app.models.exchange import ExchangeQuote

AWESOME_API_BASE_URL = "https://economia.awesomeapi.com.br/json/last"
BCB_PTAX_BASE_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
    "dataFinalCotacao=@dataFinalCotacao)"
)
EXCHANGE_TIMEOUT_SECONDS = 5.0
MAX_TRANSPORT_ATTEMPTS = 2
_BRASILIA_TIMEZONE = timezone(timedelta(hours=-3))


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
        self._client = client or httpx.Client(timeout=timeout_seconds)
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


class BcbPtaxExchangeRateRepository:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = EXCHANGE_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._timeout_seconds = timeout_seconds

    def get_brl_quote(self, *, currency: str) -> ExchangeQuote:
        if currency not in {"USD", "EUR", "ARS", "GBP", "JPY"}:
            raise ValueError("currency is not supported")
        response = self._request_with_retry(currency=currency)
        if response.status_code != httpx.codes.OK:
            raise ExchangeRateUnavailableError("BCB returned an unsuccessful response")
        try:
            return _extract_bcb_quote(response.json(), currency=currency)
        except (TypeError, ValueError, KeyError, InvalidOperation) as error:
            raise ExchangeRateUnavailableError("BCB returned an invalid quote") from error

    def _request_with_retry(self, *, currency: str) -> httpx.Response:
        today = date.today()
        params = {
            "@moeda": f"'{currency}'",
            "@dataInicial": f"'{(today - timedelta(days=10)):%m-%d-%Y}'",
            "@dataFinalCotacao": f"'{today:%m-%d-%Y}'",
            "$top": "1",
            "$orderby": "dataHoraCotacao desc",
            "$format": "json",
        }
        last_error: httpx.TransportError | None = None
        for _ in range(MAX_TRANSPORT_ATTEMPTS):
            try:
                return self._client.get(
                    BCB_PTAX_BASE_URL,
                    params=params,
                    timeout=self._timeout_seconds,
                )
            except httpx.TransportError as error:
                last_error = error
        raise ExchangeRateUnavailableError("BCB connection failed") from last_error


class FallbackExchangeRateRepository:
    def __init__(
        self,
        *,
        primary: ExchangeRateRepository,
        fallback: ExchangeRateRepository,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def get_brl_quote(self, *, currency: str) -> ExchangeQuote:
        try:
            return self._primary.get_brl_quote(currency=currency)
        except ExchangeRateUnavailableError:
            return self._fallback.get_brl_quote(currency=currency)


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


def _extract_bcb_quote(payload: object, *, currency: str) -> ExchangeQuote:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    values = payload["value"]
    if not isinstance(values, list) or not values:
        raise ValueError("payload must contain a quote")
    raw_quote = values[0]
    if not isinstance(raw_quote, dict):
        raise ValueError("quote must be an object")
    quoted_at = datetime.fromisoformat(str(raw_quote["dataHoraCotacao"]))
    if quoted_at.tzinfo is None:
        quoted_at = quoted_at.replace(tzinfo=_BRASILIA_TIMEZONE)
    return ExchangeQuote(
        currency=currency,
        buy_rate=Decimal(str(raw_quote["cotacaoCompra"])),
        sell_rate=Decimal(str(raw_quote["cotacaoVenda"])),
        quoted_at=quoted_at.astimezone(UTC),
    )
