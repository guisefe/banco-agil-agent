from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.graph.workflow import ConversationWorkflow
from app.models.exchange import ExchangeQuote
from app.repositories.exchange import BcbPtaxExchangeRateRepository
from app.services.understanding import (
    InterpretationError,
    OpenAICompatibleConversationInterpreter,
)

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
    assert len(app.chat_message) == 0
    assert app.chat_input[0].placeholder == "Envie uma mensagem para iniciar o atendimento"
    assert app.chat_input[0].disabled is False
    assert not app.warning
    assert any("fallback local" in item.value for item in app.markdown)

    app.chat_input[0].set_value("Olá").run()

    assert "CPF" in app.chat_message[-1].markdown[0].value
    assert app.chat_input[0].placeholder == "Digite sua mensagem"


def test_streamlit_app_shows_when_llm_mode_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_interpretation(
        interpreter: OpenAICompatibleConversationInterpreter,
        message: str,
    ) -> None:
        raise InterpretationError("simulated provider failure")

    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    monkeypatch.setattr(
        OpenAICompatibleConversationInterpreter,
        "interpret",
        fail_interpretation,
    )

    app = make_app_test().run()

    assert not app.exception
    assert any("LLM configurada" in item.value for item in app.markdown)

    app.chat_input[0].set_value("00000000000").run()
    app.chat_input[0].set_value("20/05/1990").run()
    app.chat_input[0].set_value("quero saber meu score").run()

    assert not app.exception
    assert any("LLM falhou" in item.value for item in app.markdown)


def test_streamlit_app_masks_identity_and_completes_credit_query() -> None:
    app = make_app_test().run()

    app.chat_input[0].set_value("00000000000").run()
    assert "***.***.***-00" in app.chat_message[0].markdown[0].value

    app.chat_input[0].set_value("20/05/1990").run()
    assert "**/**/1990" in app.chat_message[2].markdown[0].value
    assert "Olá, Ana!" in app.chat_message[3].markdown[0].value

    app.chat_input[0].set_value("Quero consultar meu limite").run()

    assert not app.exception
    assert app.chat_input[0].disabled is False
    assert "R$ 2.500,00" in app.chat_message[-1].markdown[0].value


def test_streamlit_app_can_start_new_conversation_after_end() -> None:
    app = make_app_test().run()
    app.chat_input[0].set_value("encerrar").run()

    assert app.chat_input[0].disabled is True
    assert app.success

    app.button[0].click().run()

    assert not app.exception
    assert app.chat_input[0].disabled is False
    assert len(app.chat_message) == 0


def test_streamlit_app_can_reset_an_active_conversation() -> None:
    app = make_app_test().run()
    app.chat_input[0].set_value("00000000000").run()

    assert len(app.chat_message) == 2

    app.button[0].click().run()

    assert not app.exception
    assert app.chat_input[0].disabled is False
    assert len(app.chat_message) == 0


def test_streamlit_app_blocks_after_three_identity_mismatches() -> None:
    app = make_app_test().run()

    for _ in range(3):
        app.chat_input[0].set_value("00000000000").run()
        app.chat_input[0].set_value("01/01/2000").run()

    assert not app.exception
    assert app.chat_input[0].disabled is True
    assert "três tentativas" in app.chat_message[-1].markdown[0].value


def test_streamlit_app_completes_exchange_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get_quote(
        repository: BcbPtaxExchangeRateRepository,
        *,
        currency: str,
    ) -> ExchangeQuote:
        return ExchangeQuote(
            currency=currency,
            buy_rate=Decimal("5.1234"),
            sell_rate=Decimal("5.1334"),
            quoted_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        )

    monkeypatch.setattr(BcbPtaxExchangeRateRepository, "get_brl_quote", get_quote)
    app = make_app_test().run()
    app.chat_input[0].set_value("00000000000").run()
    app.chat_input[0].set_value("20/05/1990").run()

    app.chat_input[0].set_value("cotação do dólar").run()

    assert not app.exception
    assert app.chat_input[0].disabled is False
    assert "Cotação de USD" in app.chat_message[-1].markdown[0].value
    assert app.chat_input[0].disabled is False
    assert not app.info


def test_streamlit_app_answers_score_query_without_repetition() -> None:
    app = make_app_test().run()
    app.chat_input[0].set_value("00000000000").run()
    app.chat_input[0].set_value("20/05/1990").run()

    app.chat_input[0].set_value("quero saber meu score").run()

    assert not app.exception
    assert "650 de 1000" in app.chat_message[-1].markdown[0].value
    assert app.chat_input[0].disabled is False


def test_streamlit_app_recovers_from_unexpected_workflow_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_respond(
        workflow: ConversationWorkflow,
        state: object,
        user_message: str,
    ) -> object:
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(ConversationWorkflow, "respond", fail_respond)
    app = make_app_test().run()

    app.chat_input[0].set_value("00000000000").run()

    assert not app.exception
    assert "sessão continua ativa" in app.chat_message[-1].markdown[0].value
    assert app.chat_input[0].disabled is False
