"""SSE streaming + REST endpoints for chat.

Backed by ``langstage_core.adapters.SessionAdapter`` — the per-session
queue, cancellation, and SSE plumbing that used to live in cowork's own
``stream/`` package now come from the shared runtime.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from langstage.server.models import ChatComplete, SessionAck
from langstage.oneturn import complete_turn

from langstage_core import workspace_root
from langstage_core.adapters import SessionAdapter

from langstage.workspace.file_manager import FileManager

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    session_id: str
    content: str
    cwd: str | None = None


class ChatCompleteRequest(BaseModel):
    """Body for the buffered one-turn endpoint. ``session_id`` is optional — omit
    it for a stateless call (a fresh session is created and returned); pass one to
    continue an existing thread. No pre-opened SSE stream required."""

    content: str
    session_id: str | None = None
    cwd: str | None = None


class InterruptRequest(BaseModel):
    session_id: str
    decisions: list[dict]


class CancelRequest(BaseModel):
    session_id: str


def context_parts(cwd: str | None = None) -> list[str]:
    """Context lines prepended to each user message (current time + working dir).

    Forwarded to ``SessionAdapter.submit_message(context_parts=...)``, which
    feeds them through ``prepare_agent_input``.

    ``[Working directory: ...]`` is the resolved workspace (``core.workspace_root()``),
    the directory ``run()`` makes the process cwd (ADR 0006), so relative paths the
    agent uses resolve there. Reporting the raw virtual ``/`` told a bring-your-own
    agent its cwd was the filesystem root (dogfood F4).

    ``cwd`` is the file browser's current folder as a *virtual* path (``/`` = the
    workspace root). It used to be folded into the working-directory line, so with a
    subfolder open the agent was told it was in ``<workspace>/reports`` while relative
    writes landed in ``<workspace>`` (gh #172). The process is not chdir'd per turn:
    the cwd is process-global and shared with concurrent tasks and schedules, so ADR
    0006 enters the workspace once. Instead the folder is reported on its own line,
    as what the user is looking at, with a note that relative paths don't follow it.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [f"[Current time: {now}]"]
    root = workspace_root()
    parts.append(f"[Working directory: {root}]")
    sub = (cwd or "").strip("/\\")
    if sub:
        browsed = (root / sub).resolve()
        # Only a folder inside the workspace; a `..` path is not something the file
        # browser can show, so don't pass it on.
        if browsed != root.resolve() and browsed.is_relative_to(root.resolve()):
            parts.append(
                f"[File browser folder: {browsed} - the folder the user has open; "
                f"relative paths still resolve against the working directory]"
            )
    return parts


def create_chat_router(
    adapter: SessionAdapter,
    file_manager: FileManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    # Server-sent events, not JSON — say so in the schema (gh #98).
    @router.get(
        "/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def sse_stream(request: Request, session_id: str | None = None):
        """SSE endpoint: the client opens this as an EventSource.

        Agent events and out-of-band file-change events are multiplexed onto
        one stream via the session's queue.
        """
        session = adapter.get_or_create(session_id)

        async def event_generator():
            # File watcher pushes file_changed events into the same session queue.
            file_watch_task = None
            if file_manager:
                file_watch_task = asyncio.create_task(
                    _push_file_changes(adapter, session.id, file_manager)
                )
            frames = adapter.sse(session.id)
            try:
                async for frame in frames:
                    yield frame
            finally:
                if file_watch_task:
                    file_watch_task.cancel()
                # Close the inner stream now (not at garbage collection) so the
                # session is marked disconnected, then reclaim it once idle (gh #164).
                await frames.aclose()
                _schedule_reap(adapter, session.id)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.post("/chat", response_model=SessionAck, response_model_exclude_unset=True)
    async def send_message(body: ChatRequest):
        """Send a user message and start agent streaming."""
        if adapter.get(body.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        adapter.submit_message(
            body.session_id, body.content, context_parts=context_parts(body.cwd)
        )
        return {"status": "ok", "session_id": body.session_id}

    @router.post(
        "/chat/complete",
        response_model=ChatComplete,
        response_model_exclude_unset=True,
    )
    async def chat_complete(body: ChatCompleteRequest):
        """Run ONE turn to completion and return the whole assistant reply as a
        single JSON response — the synchronous, non-SSE sibling of the streaming
        chat pair.

        Removes all the ordering the SSE path requires: there is **no** persistent
        ``GET /api/stream`` to open first (that's what creates a session for the
        streaming path, so a bare ``POST /api/chat`` 404s without it), no SSE frames
        to parse, and no task row persisted. Creates the session when ``session_id``
        is absent, drives the turn on the same ``SessionAdapter`` the streaming
        routes use, and returns ``{session_id, content, tool_calls}``. A turn that
        errors is surfaced as HTTP 500; one that pauses for human review returns 200
        with the assembled-so-far reply plus ``outcome`` + ``interrupt``.
        """
        result = await complete_turn(
            adapter,
            body.content,
            session_id=body.session_id,
            context_parts=context_parts(body.cwd),
        )
        if result.outcome == "error":
            raise HTTPException(
                status_code=500, detail=result.error or "agent turn failed"
            )
        payload: dict = {
            "session_id": result.session_id,
            "content": result.content,
            "tool_calls": result.tool_calls,
        }
        # A one-shot path can't resume a review gate; surface it (200) so the caller
        # knows the reply is partial rather than silently returning it as complete.
        if result.outcome != "complete":
            payload["outcome"] = result.outcome
            if result.interrupt is not None:
                payload["interrupt"] = result.interrupt
        return payload

    @router.post("/chat/interrupt", response_model=SessionAck, response_model_exclude_unset=True)
    async def respond_to_interrupt(body: InterruptRequest):
        """Resume the agent from an interrupt with user decisions."""
        if adapter.get(body.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        adapter.submit_decisions(body.session_id, body.decisions)
        return {"status": "ok", "session_id": body.session_id}

    @router.post("/chat/cancel", response_model=SessionAck, response_model_exclude_unset=True)
    async def cancel_stream(body: CancelRequest):
        """Cancel the in-flight agent stream for a session."""
        if adapter.get(body.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        adapter.cancel(body.session_id)
        return {"status": "ok", "session_id": body.session_id}

    return router


# How long a session with no stream and no running turn is kept, so a client that
# reconnects (EventSource retry, page reload) finds its session again (gh #164).
SESSION_REAP_GRACE_S = 60.0

_reap_tasks: set[asyncio.Task] = set()


def _schedule_reap(adapter: SessionAdapter, session_id: str) -> None:
    task = asyncio.get_running_loop().create_task(_reap_when_idle(adapter, session_id))
    _reap_tasks.add(task)
    task.add_done_callback(_reap_tasks.discard)


async def _reap_when_idle(adapter: SessionAdapter, session_id: str) -> None:
    """Drop a session once it has no stream and no running turn.

    Every ``GET /api/stream`` with a new or absent ``session_id`` creates a session,
    and nothing removed it after the client left, so the store only grew (gh #164).
    Dropping it loses no history: the thread lives in the checkpointer under the
    session id, and a client that comes back with that id gets a session for it.
    """
    from langstage.tools import release_notebook_state

    while True:
        await asyncio.sleep(SESSION_REAP_GRACE_S)
        session = adapter.get(session_id)
        if session is None or session.sse_connected:
            return
        task = session.current_task
        if task is not None and not task.done():
            # A turn is still running (e.g. a HITL-free long run): wait for it, then
            # give the client the grace period again.
            await asyncio.wait([task])
            continue
        adapter.delete_session(session_id)
        release_notebook_state(session_id)
        return


async def _push_file_changes(
    adapter: SessionAdapter, session_id: str, file_manager: FileManager
) -> None:
    """Watch the workspace and push file-change events into the session stream."""
    try:
        async for change in file_manager.watch():
            adapter.push_event(session_id, {
                "type": "file_changed",
                "event": change.event_type,
                "path": change.path,
            })
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("File watcher error")
