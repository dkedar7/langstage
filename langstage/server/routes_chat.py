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

from langstage_core.adapters import SessionAdapter

from langstage.workspace.file_manager import FileManager

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    session_id: str
    content: str
    cwd: str | None = None


class InterruptRequest(BaseModel):
    session_id: str
    decisions: list[dict]


class CancelRequest(BaseModel):
    session_id: str


def context_parts(cwd: str | None = None) -> list[str]:
    """Context lines prepended to each user message (current time + cwd).

    Forwarded to ``SessionAdapter.submit_message(context_parts=...)``, which
    feeds them through ``prepare_agent_input``.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [f"[Current time: {now}]"]
    if cwd:
        parts.append(f"[Working directory: {cwd}]")
    return parts


def create_chat_router(
    adapter: SessionAdapter,
    file_manager: FileManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    @router.get("/stream")
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
            try:
                async for frame in adapter.sse(session.id):
                    yield frame
            finally:
                if file_watch_task:
                    file_watch_task.cancel()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.post("/chat")
    async def send_message(body: ChatRequest):
        """Send a user message and start agent streaming."""
        if adapter.get(body.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        adapter.submit_message(
            body.session_id, body.content, context_parts=context_parts(body.cwd)
        )
        return {"status": "ok", "session_id": body.session_id}

    @router.post("/chat/interrupt")
    async def respond_to_interrupt(body: InterruptRequest):
        """Resume the agent from an interrupt with user decisions."""
        if adapter.get(body.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        adapter.submit_decisions(body.session_id, body.decisions)
        return {"status": "ok", "session_id": body.session_id}

    @router.post("/chat/cancel")
    async def cancel_stream(body: CancelRequest):
        """Cancel the in-flight agent stream for a session."""
        if adapter.get(body.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        adapter.cancel(body.session_id)
        return {"status": "ok", "session_id": body.session_id}

    return router


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
