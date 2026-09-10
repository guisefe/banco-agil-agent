"""Load cases, run interpretation, measure and save. No conversational state is mutated."""

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from app.config import load_settings
from app.services.understanding import (
    ConversationInterpreter,
    DeterministicConversationInterpreter,
    OpenAICompatibleConversationInterpreter,
    ResilientConversationInterpreter,
)
from evaluation.dataset import Case, load_cases
from evaluation.metrics import Result, summarize

ROOT = Path(__file__).resolve().parents[1]


def evaluate(
    cases: list[Case],
    interpreter: ConversationInterpreter,
    provider: OpenAICompatibleConversationInterpreter | None = None,
) -> list[Result]:
    results = []
    for case in cases:
        start = perf_counter()
        actual = None
        source = None
        error = None
        try:
            if case.kind == "intent":
                intent = interpreter.interpret(case.message)
                actual = {
                    "intent": intent.intent,
                    "currency": intent.currency,
                    "requested_limit": str(intent.requested_limit)
                    if intent.requested_limit
                    else None,
                }
                source = intent.source
            else:
                if case.field is None:
                    raise ValueError("Field case has no field")
                field = interpreter.interpret_field(case.message, expected=case.field)
                actual = {"value": field.value}
                source = field.source
        except Exception as exc:
            # One failed request must stay in the denominator; never log provider payloads.
            error = type(exc).__name__
        results.append(
            Result(
                case=case,
                actual=actual,
                source=source,
                error=error,
                latency_ms=(perf_counter() - start) * 1000,
                requests=provider.last_requests if provider else 0,
                input_tokens=provider.last_input_tokens if provider else 0,
                output_tokens=provider.last_output_tokens if provider else 0,
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["local", "llm", "hybrid"], default="local")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation/cases.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version, cases = load_cases(args.dataset)
    local = DeterministicConversationInterpreter()
    interpreter: ConversationInterpreter = local
    provider = None
    model = None
    if args.mode != "local":
        settings = load_settings()
        if not settings.llm_api_key:
            parser.error(
                "Live evaluation requires GROQ_API_KEY or LLM_API_KEY; no fallback run saved"
            )
        model = settings.llm_model
        provider = OpenAICompatibleConversationInterpreter(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=model,
        )
        interpreter = (
            provider
            if args.mode == "llm"
            else ResilientConversationInterpreter(
                primary=provider,
                fallback=local,
            )
        )
    results = evaluate(cases, interpreter, provider)
    summary = summarize(results)
    report = {
        "schema_version": 1,
        "dataset_version": version,
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=ROOT,
            text=True,
        ).strip(),
        "source_sha256": hashlib.sha256(
            b"".join(
                str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes()
                for folder in ("app", "evaluation")
                for path in sorted((ROOT / folder).rglob("*.py"))
            )
        ).hexdigest(),
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=ROOT,
                text=True,
            ).strip()
        ),
        "measured_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "model": model,
        "cost_usd": 0 if args.mode == "local" else None,
        "cost_note": "Local mode has no API cost. Live billing is not inferred from tokens.",
        "limitations": "Development cases; not task completion or held-out accuracy.",
        "summary": summary,
        "results": [
            {
                **asdict(r),
                "case": {
                    "id": r.case.id,
                    "kind": r.case.kind,
                    "category": r.case.category,
                    "expected": r.case.expected,
                },
                "passed": r.passed,
            }
            for r in results
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
