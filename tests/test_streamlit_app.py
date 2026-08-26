from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.models.exchange import ExchangeQuote
from app.repositories.exchange import AwesomeApiExchangeRateRepository

PROJECT_ROOT = Path(__file__).parent.parent


def make_app_test() -> AppTest:
    return AppTest.from_file(PROJECT_ROOT / "streamlit_app.py", default_timeout=10)


def test_streamlit_app_starts_triage_without_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUDIT_PSEUDONYMIZATION_KEY",
        "stable-test-pseudonymization-key-32-bytes",
    )
    app = make_app_test().run()

    assert not app.exception
    assert app.title[0].value == "🏦 Banco Ágil"
    assert len(app.chat_message) == 1
    assert "CPF" in app.chat_message[0].markdown[0].value
    assert app.chat_input[0].disabled is False
    assert not app.warning


def test_streamlit_app_masks_identity_and_completes_credit_query() -> None:
    app = make_app_test().run()

    app.chat_input[0].set_value("00000000000").run()
    assert "***.***.***-**" in app.chat_message[1].markdown[0].value

    app.chat_input[0].set_value("20/05/1990").run()
    assert "**/**/****" in app.chat_message[3].markdown[0].value

    app.chat_input[0].set_value("Quero consultar meu limite").run()

    assert not app.exception
    assert app.chat_input[0].disabled is False

    app.chat_input[0].set_value("consultar limite atual").run()

    assert not app.exception
    assert "R$ 2.500,00" in app.chat_message[-1].markdown[0].value


def test_streamlit_app_can_start_new_conversation_after_end() -> None:
    app = make_app_test().run()
    app.chat_input[0].set_value("encerrar").run()

    assert app.chat_input[0].disabled is True
    assert app.success

    app.button[0].click().run()

    assert not app.exception
    assert app.chat_input[0].disabled is False
    assert len(app.chat_message) == 1


def test_streamlit_app_completes_exchange_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get_quote(
        repository: AwesomeApiExchangeRateRepository,
        *,
        currency: str,
    ) -> ExchangeQuote:
        return ExchangeQuote(
            currency=currency,
            buy_rate=Decimal("5.1234"),
            sell_rate=Decimal("5.1334"),
            quoted_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        )

    monkeypatch.setattr(AwesomeApiExchangeRateRepository, "get_brl_quote", get_quote)
    app = make_app_test().run()
    app.chat_input[0].set_value("00000000000").run()
    app.chat_input[0].set_value("20/05/1990").run()

    app.chat_input[0].set_value("cotação do dólar").run()

    assert not app.exception
    assert app.chat_input[0].disabled is False

    app.chat_input[0].set_value("USD").run()

    assert not app.exception
    assert "Cotação de USD" in app.chat_message[-1].markdown[0].value
    assert app.chat_input[0].disabled is False
    assert not app.info
