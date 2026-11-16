"""Deterministic, model-free agent for the History e2e tests (gh #232).

Compiled WITHOUT a checkpointer, so the server attaches its durable SQLite one and a
conversation survives a server restart, which is what the tests check.

Each turn calls a ``lookup`` tool and then replies ``reply <n> to: <what was typed>``,
where ``<n>`` counts the user messages in the thread. A reopened conversation that
really continues on its old thread therefore answers with the next number.

Two words in a message change the turn:

- ``slow``: the reply takes a few seconds, long enough for a second browser to find
  the conversation while its turn is still running;
- ``approval``: the turn pauses on a human approval before it replies.
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

SLOW_SECONDS = 6


def _typed(content) -> str:
    """The user's text without the context lines the web stage puts before it."""
    text = content if isinstance(content, str) else str(content)
    head, sep, rest = text.partition("\n\n")
    return rest if sep and head.startswith("[") else text


async def _respond(state: MessagesState) -> dict:
    humans = [m for m in state["messages"] if m.type == "human"]
    n = len(humans)
    typed = _typed(humans[-1].content)
    suffix = ""
    if "approval" in typed:
        answer = interrupt({
            "action_requests": [{"name": "send_email", "args": {"to": "a@example.org"}}],
            "review_configs": [{"allowed_decisions": ["approve", "reject"]}],
        })
        decisions = answer.get("decisions") if isinstance(answer, dict) else None
        suffix = f" ({decisions[0]['type']})" if decisions else " (answered)"
    if "slow" in typed:
        await asyncio.sleep(SLOW_SECONDS)
    call_id = f"call-{n}"
    return {"messages": [
        AIMessage(content="", tool_calls=[{"name": "lookup", "args": {"q": typed}, "id": call_id}]),
        ToolMessage(content=f"ANSWER for {typed}", tool_call_id=call_id, name="lookup"),
        AIMessage(content=f"reply {n}{suffix} to: {typed}"),
    ]}


_builder = StateGraph(MessagesState)
_builder.add_node("respond", _respond)
_builder.add_edge(START, "respond")
_builder.add_edge("respond", END)

graph = _builder.compile()
graph.name = "History Stub"
