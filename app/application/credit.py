from dataclasses import replace

from app.audit.events import AuditEvent
from app.audit.writer import AuditWriter
from app.models.credit import CreditRequest
from app.models.credit_policy import CreditDecision, evaluate_increase
from app.repositories.credit import (
    SCORE_POLICY_VERSION,
    CreditRepositoryError,
    CreditRequestRepository,
    ScorePolicyRepository,
)
from app.repositories.customers import CreditCustomerRepository


class ProcessCreditIncrease:
    """Evaluate, audit and persist an increase under the caller's critical section.

    The decision event records policy evaluation, not transaction completion.
    CSV compensation is best effort and does not provide crash-safe transactions.
    """

    def __init__(
        self,
        *,
        customers: CreditCustomerRepository,
        requests: CreditRequestRepository,
        policy: ScorePolicyRepository,
        audit: AuditWriter,
    ) -> None:
        self._customers = customers
        self._requests = requests
        self._policy = policy
        self._audit = audit

    def execute(
        self,
        request: CreditRequest,
        *,
        score: int,
        conversation_id: str,
        turn_number: int,
        subject_ref: str,
        finalize_pending: bool,
    ) -> CreditDecision:
        decision = evaluate_increase(
            requested_limit=request.requested_limit,
            maximum_limit=self._policy.maximum_limit_for(score=score),
        )
        evaluated_request = replace(
            request, status="aprovado" if decision.approved else "rejeitado"
        )
        self._audit.append(
            AuditEvent(
                event_type="credit_decision_made",
                conversation_id=conversation_id,
                turn_number=turn_number,
                agent="credit",
                outcome="approved" if decision.approved else "rejected",
                reason_code=decision.reason_code,
                subject_ref=subject_ref,
                policy_version=SCORE_POLICY_VERSION,
            )
        )
        if decision.approved:
            self._customers.update_credit_limit(
                cpf=request.customer_cpf, credit_limit=request.requested_limit
            )
        try:
            if finalize_pending:
                self._requests.finalize_pending(
                    customer_cpf=request.customer_cpf,
                    requested_at=request.requested_at,
                    status="aprovado" if decision.approved else "rejeitado",
                )
            else:
                self._requests.append(evaluated_request)
        except CreditRepositoryError:
            if decision.approved:
                self._customers.update_credit_limit(
                    cpf=request.customer_cpf, credit_limit=request.current_limit
                )
            raise
        return decision
