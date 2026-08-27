from typing import Literal, TypedDict, cast

import streamlit as st

from app.bootstrap import Application, build_application
from app.models.conversation import ConversationState
from app.ui.privacy import safe_user_message_for_display

_APPLICATION_KEY = "application"
_STATE_KEY = "conversation_state"
_MESSAGES_KEY = "chat_messages"


class ChatMessage(TypedDict):
    role: Literal["assistant", "user"]
    content: str


def render_app() -> None:
    st.set_page_config(
        page_title="Banco Ágil",
        page_icon="🏦",
        layout="centered",
    )
    st.title("🏦 Banco Ágil")
    st.caption("Atendimento bancário inteligente e seguro")

    application = _get_application()
    state, messages = _get_or_start_conversation(application)

    with st.sidebar:
        st.subheader("Sessão")
        st.write("Canal: **Atendimento**")
        st.write(f"Tentativas de autenticação: **{state['authentication_attempts']}/3**")
        if application.uses_ephemeral_audit_key:
            st.warning(
                "Demonstração usando chave de auditoria efêmera. "
                "Configure AUDIT_PSEUDONYMIZATION_KEY para uma referência estável."
            )
        if st.button("Nova conversa", use_container_width=True):
            _reset_conversation(application)
            st.rerun()

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    can_receive_message = state["end_reason"] is None
    if state["end_reason"] is not None:
        st.success("Conversa finalizada. Inicie uma nova conversa para continuar.")

    user_message = st.chat_input(
        "Digite sua mensagem",
        disabled=not can_receive_message,
    )
    if user_message:
        safe_message = safe_user_message_for_display(state, user_message)
        messages.append({"role": "user", "content": safe_message})
        try:
            with st.spinner("Processando sua solicitação..."):
                next_state = application.workflow.respond(state, user_message)
        except Exception:  # noqa: BLE001 - final UI boundary keeps the session recoverable
            messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "Tive uma falha inesperada, mas sua sessão continua ativa. "
                        "Tente novamente; se persistir, inicie uma nova conversa."
                    ),
                }
            )
        else:
            messages.append({"role": "assistant", "content": next_state["assistant_message"]})
            st.session_state[_STATE_KEY] = next_state
        st.session_state[_MESSAGES_KEY] = messages
        st.rerun()


def _get_application() -> Application:
    if _APPLICATION_KEY not in st.session_state:
        st.session_state[_APPLICATION_KEY] = build_application()
    return cast(Application, st.session_state[_APPLICATION_KEY])


def _get_or_start_conversation(
    application: Application,
) -> tuple[ConversationState, list[ChatMessage]]:
    if _STATE_KEY not in st.session_state:
        _reset_conversation(application)

    state = cast(ConversationState, st.session_state[_STATE_KEY])
    messages = cast(list[ChatMessage], st.session_state[_MESSAGES_KEY])
    return state, messages


def _reset_conversation(application: Application) -> None:
    state = application.workflow.start()
    st.session_state[_STATE_KEY] = state
    st.session_state[_MESSAGES_KEY] = [{"role": "assistant", "content": state["assistant_message"]}]
