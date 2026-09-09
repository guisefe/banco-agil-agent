# ADR-001 — Isolate credit increase evaluation and persistence

Status: accepted for the local demonstration.

## Context

CreditAgent previously owned conversation routing, policy comparison, audit event construction
and approved/rejected request persistence. This made a persistence change require editing a
conversational component. Existing behavior tests already exercise compensation, absent score,
reanalysis and concurrent requests.

## Decision

Extract `evaluate_increase` as a pure Decimal policy with a typed decision/reason code. Extract
`ProcessCreditIncrease` as an application use case using the existing repository and audit
Protocols. It owns policy lookup, decision auditing, final status and compensation. It does not
import LangGraph, Streamlit, ConversationState or a model provider.

CreditAgent maps conversation data into the use case and maps the result back into the dialogue.
The existing process-local critical section remains around customer read and execution. Direct
callers must supply the same synchronization; this extraction adds no concurrency guarantee.
Missing-score routing, limit reduction and interview coordination remain in the agents for a
later focused change. No generic repository or extra agent framework is introduced.

## Consequences

The audit event precedes persistence and describes a policy decision, not a committed change.
If request persistence fails after the limit update, the previous limit is restored. Restoration
can itself fail; CSV compensation is not an atomic or crash-safe transaction. A production
implementation requires a transactional persistence boundary and completion event/outbox design.

Existing public agent constructors, CSV columns, reason codes and user-facing flows remain stable.
The repository slug remains stable for existing links; the technical title is Banking Service
Agent and Banco Ágil remains the fictional demo organization.
