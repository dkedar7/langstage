"""Deterministic, model-free agent for the cowork-dash e2e tests.

Launch the app against it with::

    cowork-dash run --agent <abs path>/stub_agent.py:graph --no-browser

It's a real compiled LangGraph graph with a MemorySaver checkpointer, so it
streams through the exact same ``langgraph_stream_parser`` path as the
production agent — including token-by-token ``messages``-mode streaming, which
the cowork-dash adapter relies on. But the "model" is a local echo that just
replays the user's last message, so there's no API key and it's fully
deterministic.
"""
from __future__ import annotations

from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END, MessagesState, StateGraph


def _last_human(messages: List[BaseMessage]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


class EchoChatModel(BaseChatModel):
    """A no-API chat model that echoes the user's last message, with streaming.

    Implements ``_stream`` so that under LangGraph's ``messages`` stream mode the
    reply is emitted token-by-token (matching how a real chat model behaves).
    """

    @property
    def _llm_type(self) -> str:
        return "echo-stub"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = f"stub reply: {_last_human(messages)}"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = f"stub reply: {_last_human(messages)}"
        tokens = text.split(" ")
        for i, token in enumerate(tokens):
            piece = token if i == len(tokens) - 1 else token + " "
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager is not None:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk


_model = EchoChatModel()


def _respond(state: MessagesState) -> dict:
    return {"messages": [_model.invoke(state["messages"])]}


_builder = StateGraph(MessagesState)
_builder.add_node("respond", _respond)
_builder.add_edge(START, "respond")
_builder.add_edge("respond", END)

graph = _builder.compile(checkpointer=MemorySaver())
graph.name = "Stub Agent"
