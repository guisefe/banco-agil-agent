import json
from pathlib import Path

import pytest

from app.models.intent import IntentInterpretation
from app.services.understanding import (
    DeterministicConversationInterpreter,
    InterpretationError,
)
from evaluation.dataset import Case, load_cases
from evaluation.metrics import Result, summarize
from evaluation.run import evaluate


def test_metrics_keep_errors_in_denominator_and_distinguish_abstention() -> None:
    unknown = Case(
        "unknown",
        "intent",
        "ambiguous",
        "ambiguous",
        {"intent": "unknown", "currency": None, "requested_limit": None},
    )
    known = Case(
        "known",
        "intent",
        "clear",
        "score",
        {"intent": "credit_score_query", "currency": None, "requested_limit": None},
    )
    results = [
        Result(unknown, unknown.expected, "deterministic", 1),
        Result(known, unknown.expected, "deterministic", 2),
        Result(known, None, None, 100, error="InterpretationError"),
    ]
    report = summarize(results)
    assert report["exact_match_rate"] == 1 / 3
    assert report["unknown_precision"] == 0.5
    assert report["unknown_recall"] == 1
    assert report["errors"] == 1
    assert report["latency_ms_p50"] == 2
    assert report["latency_ms_p95"] == 100
    assert report["input_tokens"] is None
    assert summarize([])["exact_match_rate"] is None


def test_runner_records_failure_and_continues_without_error_details() -> None:
    class FailingInterpreter(DeterministicConversationInterpreter):
        def interpret(self, message: str) -> IntentInterpretation:
            raise InterpretationError("private provider payload must not enter the report")

    cases = [
        Case("intent", "intent", "clear", "score", {"intent": "credit_score_query"}),
        Case("field", "field", "numeric", "12.50", {"value": "12.50"}, "money"),
    ]
    results = evaluate(cases, FailingInterpreter())
    assert results[0].error == "InterpretationError"
    assert results[0].actual is None
    assert results[1].passed
    assert results[1].input_tokens == 0


def test_dataset_loads_fifty_unique_cases() -> None:
    version, cases = load_cases(Path("evaluation/cases.json"))
    assert version == "pt-br-v1"
    assert len(cases) == len({case.id for case in cases}) == 50
    assert sum(case.kind == "intent" for case in cases) == 30


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": "v1", "cases": []},
        {
            "version": "v1",
            "cases": [
                {
                    "id": "x",
                    "kind": "field",
                    "category": "c",
                    "message": "x",
                    "field": "password",
                    "expected": {"value": None},
                }
            ],
        },
    ],
)
def test_dataset_rejects_invalid_contracts(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_cases(path)
