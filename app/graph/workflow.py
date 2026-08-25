from typing import cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.triage import TriageAgent
from app.models.conversation import ConversationState, initial_state


class AgentUnavailableError(RuntimeError):
    """Raised when the active agent has not been implemented yet."""


class ConversationWorkflow:
    def __init__(self, *, triage_agent: TriageAgent) -> None:
        self._triage_agent = triage_agent
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
        builder.add_edge(START, "triage")
        builder.add_edge("triage", END)
        self._graph: CompiledStateGraph[
            ConversationState,
            None,
            ConversationState,
            ConversationState,
        ] = builder.compile()

    def start(self) -> ConversationState:
        return self._invoke(initial_state())

    def respond(
        self,
        state: ConversationState,
        user_message: str,
    ) -> ConversationState:
        if state["end_reason"] is not None:
            raise ValueError("conversation has already ended")
        if state["active_agent"] != "triage":
            raise AgentUnavailableError(
                f"agent '{state['active_agent']}' is not available in this sprint"
            )

        graph_input = state.copy()
        graph_input["user_message"] = user_message
        return self._invoke(graph_input)

    def _run_triage(self, state: ConversationState) -> ConversationState:
        if state["triage_stage"] == "greeting":
            return self._triage_agent.start(state)
        return self._triage_agent.respond(state, state["user_message"])

    def _invoke(self, state: ConversationState) -> ConversationState:
        result = self._graph.invoke(state)
        return cast(ConversationState, result)
