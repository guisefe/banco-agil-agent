import re
from collections.abc import Mapping
from decimal import Decimal

from app.models.intent import IntentInterpretation, IntentName, SupportedCurrency
from app.services.interpretation import ExpectedField, FieldInterpretation
from app.tools.conversation import normalize_text
from app.tools.money import parse_money, parse_non_negative_money

_CURRENCY_TERMS: Mapping[SupportedCurrency, frozenset[str]] = {
    "USD": frozenset({"usd", "dolar", "dolar americano"}),
    "EUR": frozenset({"eur", "euro"}),
    "ARS": frozenset({"ars", "peso argentino", "pesos argentinos"}),
    "GBP": frozenset({"gbp", "libra", "libra esterlina"}),
    "JPY": frozenset({"jpy", "iene", "yen"}),
}


class DeterministicConversationInterpreter:
    def interpret(self, message: str) -> IntentInterpretation:
        normalized = normalize_text(message)
        if _needs_clarification(normalized):
            return IntentInterpretation(intent="unknown", source="deterministic")
        currency = _identify_currency(normalized)
        intents: set[IntentName] = set()

        if "score" in normalized and any(
            verb in normalized for verb in ("recalcular", "atualizar", "melhorar")
        ):
            intents.add("credit_interview")
        elif "entrevista" in normalized:
            intents.add("credit_interview")

        if any(
            term in normalized
            for term in (
                "cambio",
                "cotacao",
                "moeda",
                "dolar",
                "euro",
                "peso argentino",
                "libra",
                "iene",
                "yen",
            )
        ):
            intents.add("exchange_quote")

        if "score" in normalized and "credit_interview" not in intents:
            intents.add("credit_score_query")

        adjustment_terms = (
            "aumentar",
            "aumento",
            "ajustar",
            "ajuste",
            "reduzir",
            "reducao",
            "diminuir",
            "novo limite",
            "mais limite",
            "subir meu limite",
            "limite maior",
            "folego maior",
        )
        has_adjustment_request = any(term in normalized for term in adjustment_terms) or (
            "limite" in normalized and any(character.isdigit() for character in normalized)
        )
        if has_adjustment_request:
            intents.add("credit_limit_adjustment")
            if any(term in normalized for term in ("consultar", "consulta")):
                intents.add("credit_limit_query")
        elif "limite" in normalized:
            intents.add("credit_limit_query")
        elif "credito" in normalized and "credit_interview" not in intents:
            intents.add("credit_menu")

        if len(intents) != 1:
            return IntentInterpretation(intent="unknown", source="deterministic")
        intent = intents.pop()
        return IntentInterpretation(
            intent=intent,
            source="deterministic",
            currency=currency if intent == "exchange_quote" else None,
            requested_limit=(
                _extract_explicit_limit(normalized) if intent == "credit_limit_adjustment" else None
            ),
        )

    def interpret_field(self, message: str, *, expected: ExpectedField) -> FieldInterpretation:
        normalized = normalize_text(message)
        value: str | None = None
        if expected == "money":
            try:
                value = str(parse_non_negative_money(message))
            except ValueError:
                pass
        elif expected == "employment":
            if re.search(r"\b(nao|nem|ou)\b", normalized):
                return FieldInterpretation(value=None, source="deterministic")
            if any(term in normalized for term in ("clt", "registrado", "carteira assinada")):
                value = "formal"
            elif any(term in normalized for term in ("autonomo", "por conta", "freelancer")):
                value = "autonomo"
            elif any(term in normalized for term in ("desempregado", "sem emprego")):
                value = "desempregado"
        elif expected == "dependents":
            numbers = {
                "nenhum": "0",
                "zero": "0",
                "um": "1",
                "uma": "1",
                "dois": "2",
                "duas": "2",
                "tres": "3",
                "quatro": "4",
                "cinco": "5",
            }
            matches = {
                number for word, number in numbers.items() if re.search(rf"\b{word}\b", normalized)
            }
            matches.update(re.findall(r"\b[0-9]+\b", normalized))
            if len(matches) == 1 and not re.search(r"\b(ou|talvez|nao)\b", normalized):
                value = matches.pop()
        elif expected == "yes_no":
            if normalized in {"sim", "quero", "aceito", "pode ser", "tenho", "possuo"}:
                value = "sim"
            elif normalized in {
                "nao",
                "nao quero",
                "agora nao",
                "nao tenho",
                "nao possuo",
            }:
                value = "nao"
        elif expected == "currency":
            if not any(term in normalized for term in ("canadense", "australiano", "neozelandes")):
                value = _identify_currency(normalized)
        return FieldInterpretation(value=value, source="deterministic")


def _identify_currency(message: str) -> SupportedCurrency | None:
    matches = {
        currency
        for currency, terms in _CURRENCY_TERMS.items()
        if any(re.search(rf"\b{re.escape(term)}\b", message) for term in terms)
    }
    return matches.pop() if len(matches) == 1 else None


def _extract_explicit_limit(message: str) -> Decimal | None:
    # Several numbers or written multipliers need clarification, not a guessed amount.
    amounts = re.findall(r"[0-9][0-9.,]*", message)
    if len(amounts) != 1 or re.search(r"\b(mil|milhao|milhoes)\b", message):
        return None
    try:
        return parse_money(amounts[0].rstrip(",."))
    except ValueError:
        return None


def _needs_clarification(message: str) -> bool:
    """Conservative local routing; not a general prompt-injection detector."""
    if re.search(r"\b(nao|nem|ou|talvez|ignore|finja)\b", message):
        return True
    if message.startswith("se "):
        return True
    increase = any(term in message for term in ("aumentar", "aumento", "subir"))
    decrease = any(term in message for term in ("reduzir", "reducao", "diminuir"))
    return increase and decrease
