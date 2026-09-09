# Case: bounded language interpretation in a banking workflow

## Problem and scope

Demonstrate an assistant that understands requests while a deterministic policy controls credit
limits. This is a synthetic local simulation. There is no claim of deployment, real customers,
validated underwriting, cost reduction or production readiness.

## Two-minute demonstration

1. Show the application and the effective interpretation mode.
2. Authenticate as Ana; request an allowed increase and inspect the persisted synthetic result.
3. Restart with fresh demo fixtures; show a rejected increase and the interview offer.
4. Show Mariana's absent-score path: absence differs from a score of zero.
5. Point to provider failure/invalid-response tests and the offline demo. Disabling a key proves
   local mode only; it does not reproduce a live-provider outage.
6. Explain the pure policy and application use case, then show the CI result for the presented commit.

Use `uv run python -m scripts.demo_credit` for a repeatable offline evidence check.

## What to explain in an interview

- Why an LLM may interpret language but does not approve credit.
- Why Decimal and explicit policy boundaries matter at the approval threshold.
- Why an audit decision event does not prove persistence completion.
- What CSV compensation can and cannot recover from.
- Why regex redaction does not imply that all sensitive data is excluded from a prompt.

## Evidence still needed before publishing quantitative AI claims

A versioned Portuguese evaluation corpus, independent expected labels, task completion measures,
separate local/live-provider runs, failures and fallback frequency, p50/p95 latency, model/config
and commit identifiers. Record all outcomes, not just successful examples. No accuracy percentage
or business impact should be inferred from unit-test coverage or the three scripted scenarios.
