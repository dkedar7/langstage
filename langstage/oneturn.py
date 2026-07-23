"""One headless, synchronous turn — the shared core behind ``langstage chat`` and
``POST /api/chat/complete`` (gh #101).

Every existing way to run a single turn makes you do more work than the task
warrants: the SSE chat pair is stateful (open a persistent ``GET /api/stream`` to
create the session, then ``POST /api/chat``, then parse the event stream);
``check --live`` runs one real turn but throws the reply away; the task board is
async + persisted. This module is the low-ceremony "prompt in -> answer out"
primitive that completes the story.

It does **not** reimplement streaming. It drives the same
:class:`~langstage_core.adapters.SessionAdapter` the web server drives — the exact
path ``POST /api/chat`` + ``GET /api/stream`` use — and simply *buffers* the
serialized event frames into one assembled result instead of forwarding them over
SSE. So the reply, tool calls, and terminal outcome are identical to what a browser
would have rendered; the CLI and the HTTP endpoint share this one implementation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langstage_core.adapters import SessionAdapter

# Frame ``type`` values that end a turn's stream. ``iter_event_frames`` emits
# exactly one ``complete`` at the end of every turn (an ``interrupt`` is followed
# by a trailing ``complete``); ``error`` / ``cancelled`` end it early. Mirrors the
# TaskRunner's terminal set so the buffered path stops on the same signals the
# board-backed path does.
_TERMINAL = frozenset({"complete", "error", "cancelled"})


@dataclass
class OneTurnResult:
    """The assembled outcome of one buffered turn.

    ``content`` is the assistant's final text (all ``content`` frames joined);
    ``tool_calls`` is the ordered list of ``{"name", "args"}`` the agent invoked;
    ``outcome`` is the session's typed terminal state
    (``"complete" | "error" | "interrupted" | "cancelled"``). ``ok`` is True only
    when the turn completed cleanly, so ``if result.ok:`` reads naturally and a CLI
    can use it as a readiness gate.
    """

    session_id: str
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    outcome: str | None = None
    error: str | None = None
    interrupt: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "complete"


async def complete_turn(
    adapter: SessionAdapter,
    content: str,
    *,
    session_id: str | None = None,
    context_parts: list[str] | None = None,
) -> OneTurnResult:
    """Run exactly one turn through ``adapter`` and return the assembled reply.

    Starts the turn with :meth:`SessionAdapter.submit_message` (creating the
    session when ``session_id`` is absent/unknown — the same call the SSE
    ``POST /api/chat`` route makes), drains the session's event queue as frames
    arrive, and stops at the first terminal frame. Reads the typed
    ``session.outcome`` / ``session.error`` / ``session.interrupt`` that
    ``SessionAdapter._produce`` records, so a failed turn comes back as
    ``outcome="error"`` rather than raising.

    Draining the queue here is safe precisely because this is the *buffered*
    path: with no SSE consumer attached to the (typically fresh) session, nothing
    else is competing for its frames.
    """
    session = adapter.submit_message(session_id, content, context_parts=context_parts)

    parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    queue = session.event_queue
    while True:
        event = await queue.get()
        etype = event.get("type")
        if etype == "content" and event.get("role", "assistant") == "assistant":
            parts.append(event.get("content", ""))
        elif etype == "tool_start":
            tool_calls.append({"name": event.get("name"), "args": event.get("args")})
        if etype in _TERMINAL:
            break

    # Ensure the producer coroutine has fully finished (it sets session.outcome
    # right after pushing the terminal frame) so we never read a stale outcome,
    # and no background task lingers past this call.
    run_task = session.current_task
    if run_task is not None and not run_task.done():
        try:
            await run_task
        except asyncio.CancelledError:  # pragma: no cover - not triggered on this path
            pass

    return OneTurnResult(
        session_id=session.id,
        content="".join(parts).strip(),
        tool_calls=tool_calls,
        outcome=session.outcome,
        error=session.error,
        interrupt=session.interrupt,
    )


def run_turn_sync(
    agent: Any,
    content: str,
    *,
    context_parts: list[str] | None = None,
    max_result_len: int = 50_000,
) -> OneTurnResult:
    """Synchronous one-shot: wrap ``agent`` in a fresh ``SessionAdapter`` and run
    one buffered turn. The blocking entry point the ``langstage chat`` CLI uses.

    ``agent`` is a compiled LangGraph graph (the same object the server holds).
    A new adapter per call keeps the CLI stateless — one process, one turn, exit.
    """
    adapter = SessionAdapter(graph=agent, max_result_len=max_result_len)
    return asyncio.run(
        complete_turn(adapter, content, context_parts=context_parts)
    )
