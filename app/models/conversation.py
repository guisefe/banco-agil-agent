from decimal import Decimal
from typing import Literal, TypedDict
from uuid import uuid4

from app.models.intent import IntentName, IntentSource, SupportedCurrency
from app.models.interview import EmploymentType

AgentName = Literal[
    "triage",
    "credit",
    "interview",
    "exchange",
]

TriageStage = Literal[
    "greeting",
    "awaiting_cpf",
    "awaiting_birth_date",
    "awaiting_intent",
]

CreditStage = Literal[
    "awaiting_action",
    "awaiting_requested_limit",
    "offering_interview",
]

InterviewStage = Literal[
    "awaiting_income",
    "awaiting_employment",
    "awaiting_expenses",
    "awaiting_dependents",
    "awaiting_debts",
]

ExchangeStage = Literal["awaiting_currency"]

EndReason = Literal[
    "user_requested",
    "authentication_attempts_exceeded",
    "unrecoverable_error",
]


class ConversationState(TypedDict):
    conversation_id: str
    turn_number: int

    user_message: str
    assistant_message: str

    authenticated: bool
    cpf: str | None
    birth_date: str | None
    customer_name: str | None
    authentication_attempts: int

    active_agent: AgentName
    triage_stage: TriageStage
    credit_stage: CreditStage
    requested_credit_limit: Decimal | None
    pending_credit_requested_at: str | None
    handoff_pending: bool
    interpreted_intent: IntentName | None
    interpreted_currency: SupportedCurrency | None
    interpreted_requested_limit: Decimal | None
    last_intent_source: IntentSource | None
    interview_stage: InterviewStage
    monthly_income: Decimal | None
    employment_type: EmploymentType | None
    fixed_expenses: Decimal | None
    dependents: int | None
    has_active_debts: bool | None
    exchange_stage: ExchangeStage

    end_reason: EndReason | None


def initial_state() -> ConversationState:
    return {
        "conversation_id": str(uuid4()),
        "turn_number": 0,
        "user_message": "",
        "assistant_message": "",
        "authenticated": False,
        "cpf": None,
        "birth_date": None,
        "customer_name": None,
        "authentication_attempts": 0,
        "active_agent": "triage",
        "triage_stage": "greeting",
        "credit_stage": "awaiting_action",
        "requested_credit_limit": None,
        "pending_credit_requested_at": None,
        "handoff_pending": False,
        "interpreted_intent": None,
        "interpreted_currency": None,
        "interpreted_requested_limit": None,
        "last_intent_source": None,
        "interview_stage": "awaiting_income",
        "monthly_income": None,
        "employment_type": None,
        "fixed_expenses": None,
        "dependents": None,
        "has_active_debts": None,
        "exchange_stage": "awaiting_currency",
        "end_reason": None,
    }
