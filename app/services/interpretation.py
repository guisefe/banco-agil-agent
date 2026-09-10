from dataclasses import dataclass
from typing import Literal, Protocol

from app.models.intent import IntentInterpretation, IntentSource

ExpectedField = Literal["money", "employment", "dependents", "yes_no", "currency"]


class InterpretationError(RuntimeError):
    """Raised when a provider cannot return a safe structured interpretation."""


class IntentInterpreter(Protocol):
    def interpret(self, message: str) -> IntentInterpretation:
        """Return one validated non-critical intent classification."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FieldInterpretation:
    value: str | None
    source: IntentSource


class FieldInterpreter(Protocol):
    def interpret_field(self, message: str, *, expected: ExpectedField) -> FieldInterpretation:
        """Normalize one expected conversational field without applying business rules."""


class ConversationInterpreter(IntentInterpreter, FieldInterpreter, Protocol):
    """Interpret routing intents and stage-specific conversational fields."""
