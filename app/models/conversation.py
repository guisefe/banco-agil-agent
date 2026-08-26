from decimal import Decimal
from typing import Literal, TypedDict
from uuid import uuid4

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
        "end_reason": None,
    }
