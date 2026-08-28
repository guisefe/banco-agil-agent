from typing import Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.credit import CreditAgent
from app.agents.exchange import ExchangeAgent
from app.agents.interview import CreditInterviewAgent
from app.agents.triage import TriageAgent
from app.audit.events import AuditEvent
from app.audit.privacy import pseudonymize_subject
from app.audit.writer import AuditWriteError, AuditWriter
from app.models.conversation import ConversationState, initial_state
from app.tools.conversation import USER_REQUESTED_END_MESSAGE, end_conversation, is_end_request

GraphRoute = Literal["triage", "credit", "interview", "exchange"]
InterviewRoute = Literal["credit_reanalysis", "end"]
TriageRoute = Literal["credit", "interview", "exchange", "end"]


class ConversationWorkflow:
    def __init__(
        self,
        *,
        triage_agent: TriageAgent,
        credit_agent: CreditAgent,
        interview_agent: CreditInterviewAgent,
        exchange_agent: ExchangeAgent,
        audit_writer: AuditWriter,
        pseudonymization_key: bytes,
    ) -> None:
        self._triage_agent = triage_agent
        self._credit_agent = credit_agent
        self._interview_agent = interview_agent
        self._exchange_agent = exchange_agent
        self._audit_writer = audit_writer
        self._pseudonymization_key = pseudonymization_key
        builder: StateGraph[
            ConversationState,
            None,
            ConversationState,
            ConversationState,
        ] = StateGraph(
            ConversationState,
            input_schema=ConversationState,
            output_schema=ConversationState,
        )
        builder.add_node("triage", self._run_triage)
        builder.add_node("credit", self._run_credit)
        builder.add_node("interview", self._run_interview)
        builder.add_node("exchange", self._run_exchange)
        builder.add_node("credit_reanalysis", self._run_credit_reanalysis)
        builder.add_conditional_edges(
            START,
            self._route,
            {
                "triage": "triage",
                "credit": "credit",
                "interview": "interview",
                "exchange": "exchange",
            },
        )
        builder.add_conditional_edges(
            "triage",
            self._route_after_triage,
            {
                "credit": "credit",
                "interview": "interview",
                "exchange": "exchange",
                "end": END,
            },
        )
        builder.add_edge("credit", END)
        builder.add_edge("exchange", END)
        builder.add_conditional_edges(
            "interview",
            self._route_after_interview,
            {"credit_reanalysis": "credit_reanalysis", "end": END},
        )
        builder.add_edge("credit_reanalysis", END)
        self._graph: CompiledStateGraph[
            ConversationState,
            None,
            ConversationState,
            ConversationState,
        ] = builder.compile()

    def start(self) -> ConversationState:
        return initial_state()

    def respond(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        if state["end_reason"] is not None:
            raise ValueError("conversation has already ended")
        if state["triage_stage"] != "greeting" and is_end_request(user_message):
            return self._end_by_user_request(state, user_message)
        graph_input = state.copy()
        graph_input["user_message"] = user_message
        result = self._invoke(graph_input)
        if not state["authenticated"] and result["authenticated"]:
            customer_name = result["customer_name"]
            if customer_name is None:
                raise ValueError("authenticated conversation requires customer name")
            first_name = customer_name.split(maxsplit=1)[0]
            personalized_result = result.copy()
            personalized_result["assistant_message"] = (
                f"Olá, {first_name}! {result['assistant_message']}"
            )
            return personalized_result
        return result

    def _run_triage(self, state: ConversationState) -> ConversationState:
        if state["triage_stage"] == "greeting":
            return self._triage_agent.activate(state, state["user_message"])
        return self._triage_agent.respond(state, state["user_message"])

    def _run_credit(self, state: ConversationState) -> ConversationState:
        return self._credit_agent.respond(
            state,
            state["user_message"],
            advance_turn=not state["handoff_pending"],
        )

    def _run_interview(self, state: ConversationState) -> ConversationState:
        if state["handoff_pending"]:
            return self._interview_agent.begin(state)
        return self._interview_agent.respond(state, state["user_message"])

    def _run_exchange(self, state: ConversationState) -> ConversationState:
        return self._exchange_agent.respond(
            state,
            state["user_message"],
            advance_turn=not state["handoff_pending"],
        )

    def _run_credit_reanalysis(self, state: ConversationState) -> ConversationState:
        return self._credit_agent.reanalyze_pending_request(state)

    @staticmethod
    def _route(state: ConversationState) -> GraphRoute:
        if state["active_agent"] == "credit":
            return "credit"
        if state["active_agent"] == "interview":
            return "interview"
        if state["active_agent"] == "exchange":
            return "exchange"
        return "triage"

    @staticmethod
    def _route_after_interview(state: ConversationState) -> InterviewRoute:
        if state["active_agent"] == "credit" and state["requested_credit_limit"] is not None:
            return "credit_reanalysis"
        return "end"

    @staticmethod
    def _route_after_triage(state: ConversationState) -> TriageRoute:
        if not state["handoff_pending"]:
            return "end"
        if state["active_agent"] == "credit":
            return "credit"
        if state["active_agent"] == "interview":
            return "interview"
        if state["active_agent"] == "exchange":
            return "exchange"
        return "end"

    def _end_by_user_request(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        next_state = state.copy()
        next_state["turn_number"] += 1
        next_state["user_message"] = user_message
        cpf = next_state["cpf"]
        subject_ref = (
            pseudonymize_subject(cpf, key=self._pseudonymization_key) if cpf is not None else None
        )
        ended_state = end_conversation(
            next_state,
            reason="user_requested",
            assistant_message=USER_REQUESTED_END_MESSAGE,
        )
        try:
            self._audit_writer.append(
                AuditEvent(
                    event_type="conversation_ended",
                    conversation_id=state["conversation_id"],
                    turn_number=next_state["turn_number"],
                    agent=state["active_agent"],
                    outcome="success",
                    reason_code="USER_REQUESTED",
                    subject_ref=subject_ref,
                )
            )
        except AuditWriteError:
            pass
        return ended_state

    def _invoke(self, state: ConversationState) -> ConversationState:
        result = self._graph.invoke(state)
        return cast(ConversationState, result)
