from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.repositories.exchange import (
    AWESOME_API_BASE_URL,
    AwesomeApiExchangeRateRepository,
    ExchangeRateUnavailableError,
)


def make_response(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == f"{AWESOME_API_BASE_URL}/USD-BRL"
    return httpx.Response(
        200,
        json={"USDBRL": {"bid": "5.1234", "ask": "5.1334", "timestamp": "1787745600"}},
    )


def test_repository_returns_validated_quote_and_optional_api_key() -> None:
    observed_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_headers.update(request.headers)
        return make_response(request)

    repository = AwesomeApiExchangeRateRepository(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="demo-key",
    )

    quote = repository.get_brl_quote(currency="USD")

    assert quote.buy_rate == Decimal("5.1234")
    assert quote.sell_rate == Decimal("5.1334")
    assert quote.quoted_at == datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    assert observed_headers["x-api-key"] == "demo-key"


def test_repository_rejects_unsupported_currency_before_network_call() -> None:
    repository = AwesomeApiExchangeRateRepository(
        client=httpx.Client(transport=httpx.MockTransport(make_response))
    )

    for currency in ["CAD", ""]:
        with pytest.raises(ValueError, match="supported"):
            repository.get_brl_quote(currency=currency)


def test_repository_wraps_unsuccessful_or_invalid_provider_responses() -> None:
    invalid_responses = [
        httpx.Response(500),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"USDBRL": []}),
        httpx.Response(200, json={"USDBRL": {"bid": "invalid", "ask": "5", "timestamp": "1"}}),
    ]

    for response in invalid_responses:
        repository = AwesomeApiExchangeRateRepository(
            client=httpx.Client(
                transport=httpx.MockTransport(lambda _, response=response: response)
            )
        )
        with pytest.raises(ExchangeRateUnavailableError):
            repository.get_brl_quote(currency="USD")


def test_repository_retries_transport_failure_once() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("offline")
        return httpx.Response(
            200,
            json={"USDBRL": {"bid": "5", "ask": "5.1", "timestamp": "1787745600"}},
        )

    repository = AwesomeApiExchangeRateRepository(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert repository.get_brl_quote(currency="USD").currency == "USD"
    assert attempts == 2


def test_repository_wraps_repeated_transport_failure() -> None:
    repository = AwesomeApiExchangeRateRepository(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))
            )
        )
    )

    with pytest.raises(ExchangeRateUnavailableError, match="connection"):
        repository.get_brl_quote(currency="USD")


def test_repository_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        AwesomeApiExchangeRateRepository(timeout_seconds=0)
