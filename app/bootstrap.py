from dataclasses import dataclass

from app.agents.credit import CreditAgent
from app.agents.triage import TriageAgent
from app.audit.writer import JsonlAuditWriter
from app.config import Settings, load_settings
from app.graph.workflow import ConversationWorkflow
from app.repositories.credit import CsvCreditRequestRepository, CsvScorePolicyRepository
from app.repositories.customers import CsvCustomerRepository


@dataclass(frozen=True, slots=True, kw_only=True)
class Application:
    workflow: ConversationWorkflow
    uses_ephemeral_audit_key: bool


def build_application(*, settings: Settings | None = None) -> Application:
    resolved_settings = settings or load_settings()
    audit_writer = JsonlAuditWriter(resolved_settings.audit_file)
    customer_repository = CsvCustomerRepository(resolved_settings.customer_file)
    triage_agent = TriageAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=resolved_settings.pseudonymization_key,
    )
    credit_agent = CreditAgent(
        customer_repository=customer_repository,
        score_policy_repository=CsvScorePolicyRepository(resolved_settings.score_policy_file),
        request_repository=CsvCreditRequestRepository(resolved_settings.credit_request_file),
        audit_writer=audit_writer,
        pseudonymization_key=resolved_settings.pseudonymization_key,
    )
    return Application(
        workflow=ConversationWorkflow(
            triage_agent=triage_agent,
            credit_agent=credit_agent,
            audit_writer=audit_writer,
            pseudonymization_key=resolved_settings.pseudonymization_key,
        ),
        uses_ephemeral_audit_key=resolved_settings.uses_ephemeral_audit_key,
    )
