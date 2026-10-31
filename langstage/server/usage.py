"""Per-turn token usage for the StatusBar counter (gh #223).

Core doesn't emit usage (langstage-core#155: token accounting is LangChain's, read it
with a usage callback around the turn). This stage does exactly that: every model call
inside a turn reports its ``usage_metadata`` to a handler scoped to that turn, and the
turn's totals go out as one ``usage`` frame when it ends.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tracers.context import register_configure_hook
from langstage_core.adapters.session import Session, SessionAdapter


class TurnUsageHandler(BaseCallbackHandler):
    """Collects the ``usage_metadata`` of every model call in one turn.

    Unlike langchain's UsageMetadataCallbackHandler, it doesn't need
    ``response_metadata["model_name"]``, which custom and some provider models leave unset.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.usages: list[dict[str, Any]] = []

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None) if isinstance(generation, ChatGeneration) else None
                if isinstance(message, AIMessage) and message.usage_metadata:
                    with self._lock:
                        self.usages.append(dict(message.usage_metadata))


# Registered once. langchain's get_usage_metadata_callback() registers a new hook on
# every call, which would grow the global hook list by one per turn for the server's life.
_turn_usage: ContextVar[TurnUsageHandler | None] = ContextVar("langstage_turn_usage", default=None)
register_configure_hook(_turn_usage, inheritable=True)


def usage_frame(usages: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Sum a turn's usage records into one ``usage`` frame (None if no tokens)."""
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for usage in usages:
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        totals["input_tokens"] += tokens_in
        totals["output_tokens"] += tokens_out
        totals["total_tokens"] += int(usage.get("total_tokens") or 0) or tokens_in + tokens_out
    if not totals["total_tokens"]:
        return None
    return {"type": "usage", **totals, "node": None}


class UsageSessionAdapter(SessionAdapter):
    """A SessionAdapter that follows each turn with a ``usage`` frame."""

    async def _produce(self, session: Session, **kwargs: Any) -> None:
        handler = TurnUsageHandler()
        token = _turn_usage.set(handler)
        try:
            await super()._produce(session, **kwargs)
        finally:
            _turn_usage.reset(token)
            # Also after an error or a cancel: the tokens were spent either way.
            frame = usage_frame(handler.usages)
            if frame is not None:
                session.push(frame)
