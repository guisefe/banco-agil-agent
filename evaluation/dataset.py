import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from app.models.intent import ALLOWED_INTENTS, SUPPORTED_CURRENCIES
from app.services.understanding import ExpectedField


@dataclass(frozen=True)
class Case:
    id: str
    kind: Literal["intent", "field"]
    category: str
    message: str
    expected: dict[str, str | None]
    field: ExpectedField | None = None


def load_cases(path: Path) -> tuple[str, list[Case]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("version"), str):
        raise ValueError("Dataset must declare a version")
    rows = payload.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Dataset must contain cases")
    cases = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each case must be an object")
        for key in ("id", "category", "message"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Case requires non-empty {key}")
        if row["id"] in seen:
            raise ValueError("Case IDs must be unique")
        seen.add(row["id"])
        expected = row.get("expected")
        if not isinstance(expected, dict) or any(
            value is not None and not isinstance(value, str) for value in expected.values()
        ):
            raise ValueError("Expected outputs must contain strings or null")
        kind = row.get("kind")
        if kind == "intent":
            if set(expected) != {"intent", "currency", "requested_limit"}:
                raise ValueError("Intent case requires the complete output contract")
            if expected["intent"] not in ALLOWED_INTENTS:
                raise ValueError("Unknown expected intent")
            if (
                expected["currency"] is not None
                and expected["currency"] not in SUPPORTED_CURRENCIES
            ):
                raise ValueError("Unknown expected currency")
        elif kind == "field":
            if row.get("field") not in {"money", "employment", "dependents", "yes_no", "currency"}:
                raise ValueError("Unknown field")
            if set(expected) != {"value"}:
                raise ValueError("Field case requires value")
        else:
            raise ValueError("Unknown case kind")
        cases.append(
            Case(
                id=row["id"],
                kind=cast(Literal["intent", "field"], kind),
                category=row["category"],
                message=row["message"],
                expected=expected,
                field=row.get("field"),
            )
        )
    return payload["version"], cases
