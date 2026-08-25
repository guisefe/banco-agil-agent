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
    customer_name: str | None
    authentication_attempts: int

    active_agent: AgentName
    triage_stage: TriageStage

    end_reason: EndReason | None


def initial_state() -> ConversationState:
    return {
        "conversation_id": str(uuid4()),
        "turn_number": 0,
        "user_message": "",
        "assistant_message": "",
        "authenticated": False,
        "cpf": None,
        "customer_name": None,
        "authentication_attempts": 0,
        "active_agent": "triage",
        "triage_stage": "greeting",
        "end_reason": None,
    }
