from dataclasses import dataclass

from app.agents.credit import CreditAgent
from app.agents.exchange import ExchangeAgent
from app.agents.interview import CreditInterviewAgent
from app.agents.triage import TriageAgent
from app.audit.writer import JsonlAuditWriter
from app.config import Settings, load_settings
from app.graph.workflow import ConversationWorkflow
from app.repositories.credit import CsvCreditRequestRepository, CsvScorePolicyRepository
from app.repositories.customers import CsvCustomerRepository
from app.repositories.exchange import AwesomeApiExchangeRateRepository
from app.services.understanding import (
    ConversationInterpreter,
    DeterministicConversationInterpreter,
    OpenAICompatibleConversationInterpreter,
    ResilientConversationInterpreter,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Application:
    workflow: ConversationWorkflow
    uses_ephemeral_audit_key: bool
    uses_llm: bool


def build_application(*, settings: Settings | None = None) -> Application:
    resolved_settings = settings or load_settings()
    audit_writer = JsonlAuditWriter(resolved_settings.audit_file)
    customer_repository = CsvCustomerRepository(resolved_settings.customer_file)
    deterministic_interpreter = DeterministicConversationInterpreter()
    conversation_interpreter: ConversationInterpreter
    if resolved_settings.llm_api_key is None:
        conversation_interpreter = deterministic_interpreter
    else:
        conversation_interpreter = ResilientConversationInterpreter(
            primary=OpenAICompatibleConversationInterpreter(
                api_key=resolved_settings.llm_api_key,
                base_url=resolved_settings.llm_base_url,
                model=resolved_settings.llm_model,
            ),
            fallback=deterministic_interpreter,
        )
    triage_agent = TriageAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=resolved_settings.pseudonymization_key,
        intent_interpreter=conversation_interpreter,
    )
    credit_agent = CreditAgent(
        customer_repository=customer_repository,
        score_policy_repository=CsvScorePolicyRepository(resolved_settings.score_policy_file),
        request_repository=CsvCreditRequestRepository(resolved_settings.credit_request_file),
        audit_writer=audit_writer,
        pseudonymization_key=resolved_settings.pseudonymization_key,
        field_interpreter=conversation_interpreter,
        intent_interpreter=conversation_interpreter,
    )
    interview_agent = CreditInterviewAgent(
        customer_repository=customer_repository,
        audit_writer=audit_writer,
        pseudonymization_key=resolved_settings.pseudonymization_key,
        field_interpreter=conversation_interpreter,
    )
    exchange_agent = ExchangeAgent(
        exchange_repository=AwesomeApiExchangeRateRepository(
            api_key=resolved_settings.exchange_api_key,
        ),
        audit_writer=audit_writer,
        pseudonymization_key=resolved_settings.pseudonymization_key,
        field_interpreter=conversation_interpreter,
    )
    return Application(
        workflow=ConversationWorkflow(
            triage_agent=triage_agent,
            credit_agent=credit_agent,
            interview_agent=interview_agent,
            exchange_agent=exchange_agent,
            audit_writer=audit_writer,
            pseudonymization_key=resolved_settings.pseudonymization_key,
        ),
        uses_ephemeral_audit_key=resolved_settings.uses_ephemeral_audit_key,
        uses_llm=resolved_settings.llm_api_key is not None,
    )
