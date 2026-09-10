"""Compose provider and local interpretation; keep imports stable for callers."""

import logging
from dataclasses import replace
from typing import cast

import httpx

from app.models.intent import IntentInterpretation
from app.services.interpretation import (
    ConversationInterpreter,
    ExpectedField,
    FieldInterpretation,
    FieldInterpreter,
    IntentInterpreter,
    InterpretationError,
)
from app.services.llm_interpreter import OpenAICompatibleConversationInterpreter
from app.services.local_interpreter import DeterministicConversationInterpreter

__all__ = [
    "ConversationInterpreter",
    "ExpectedField",
    "FieldInterpretation",
    "FieldInterpreter",
    "IntentInterpreter",
    "InterpretationError",
    "OpenAICompatibleConversationInterpreter",
    "DeterministicConversationInterpreter",
    "ResilientConversationInterpreter",
    "INTENT_POLICY_VERSION",
]

INTENT_POLICY_VERSION = "hybrid-intent-v2"

_LOGGER = logging.getLogger(__name__)


class ResilientConversationInterpreter:
    def __init__(
        self,
        *,
        primary: IntentInterpreter,
        fallback: IntentInterpreter,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def interpret(self, message: str) -> IntentInterpretation:
        try:
            return self._primary.interpret(message)
        except InterpretationError as error:
            _log_fallback(error)
            return replace(
                self._fallback.interpret(message),
                source="deterministic_fallback",
            )

    def interpret_field(
        self,
        message: str,
        *,
        expected: ExpectedField,
    ) -> FieldInterpretation:
        primary = cast(FieldInterpreter, self._primary)
        fallback = cast(FieldInterpreter, self._fallback)
        try:
            return primary.interpret_field(message, expected=expected)
        except InterpretationError as error:
            _log_fallback(error)
            return replace(
                fallback.interpret_field(message, expected=expected),
                source="deterministic_fallback",
            )


def _log_fallback(error: InterpretationError) -> None:
    cause = error.__cause__
    cause_name = type(cause).__name__ if cause is not None else type(error).__name__
    status_code = cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else None
    _LOGGER.warning(
        "LLM interpretation failed; deterministic fallback activated (cause=%s, status=%s)",
        cause_name,
        status_code or "unavailable",
    )
