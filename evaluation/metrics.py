from dataclasses import dataclass
from math import ceil

from evaluation.dataset import Case


@dataclass(frozen=True)
class Result:
    case: Case
    actual: dict[str, str | None] | None
    source: str | None
    latency_ms: float
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    requests: int = 0

    @property
    def passed(self) -> bool:
        return self.error is None and self.actual == self.case.expected


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, ceil(len(values) * fraction) - 1)], 3)


def summarize(results: list[Result]) -> dict[str, object]:
    intents = [r for r in results if r.case.kind == "intent"]
    fields = [r for r in results if r.case.kind == "field"]
    expected_unknown = [r for r in intents if r.case.expected["intent"] == "unknown"]
    actual_unknown = [r for r in intents if r.actual and r.actual.get("intent") == "unknown"]
    correct_unknown = sum(r.case.expected["intent"] == "unknown" for r in actual_unknown)
    categories = sorted({r.case.category for r in results})
    return {
        "cases": len(results),
        "exact_matches": sum(r.passed for r in results),
        "exact_match_rate": sum(r.passed for r in results) / len(results) if results else None,
        "intent_label_accuracy": (
            sum(
                bool(r.actual and r.actual.get("intent") == r.case.expected["intent"])
                for r in intents
            )
            / len(intents)
            if intents
            else None
        ),
        "field_exact_match_rate": sum(r.passed for r in fields) / len(fields) if fields else None,
        "unknown_precision": correct_unknown / len(actual_unknown) if actual_unknown else None,
        "unknown_recall": correct_unknown / len(expected_unknown) if expected_unknown else None,
        "errors": sum(r.error is not None for r in results),
        "fallbacks": sum(r.source == "deterministic_fallback" for r in results),
        "latency_ms_p50": percentile([r.latency_ms for r in results], 0.5),
        "latency_ms_p95": percentile([r.latency_ms for r in results], 0.95),
        "http_requests": sum(r.requests for r in results),
        "input_tokens": (
            sum(r.input_tokens or 0 for r in results)
            if all(r.input_tokens is not None for r in results)
            else None
        ),
        "output_tokens": (
            sum(r.output_tokens or 0 for r in results)
            if all(r.output_tokens is not None for r in results)
            else None
        ),
        "by_category": {
            category: {
                "cases": sum(r.case.category == category for r in results),
                "exact_matches": sum(r.passed for r in results if r.case.category == category),
            }
            for category in categories
        },
    }
