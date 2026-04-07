"""SSE streaming + REST endpoints for chat, replacing WebSocket."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cowork_dash.stream.session_manager import SessionManager
from cowork_dash.stream.sse_adapter import run_agent_stream, run_interrupt_response
from cowork_dash.workspace.file_manager import FileManager

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


def create_chat_router(
    session_manager: SessionManager,
    agent=None,
    file_manager: FileManager | None = None,
    stream_parser_config: dict | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    @router.get("/stream")
    async def sse_stream(request: Request, session_id: str | None = None):
        """SSE endpoint: streams agent events to the client.

        The client opens this as an EventSource. Events are pushed to the
        session's asyncio.Queue by the agent streaming tasks.
        """
        session = session_manager.get_or_create(session_id)
        session.sse_connected = True

        # Tell the client which session it's connected to
        init_event = {"type": "session_init", "session_id": session.thread_id}

        async def event_generator():
            # Send session init first
            yield f"data: {json.dumps(init_event)}\n\n"

            # Start file watcher task
            file_watch_task = None
            if file_manager:
                file_watch_task = asyncio.create_task(
                    _push_file_changes(session, file_manager)
                )

            try:
                while True:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        break

                    try:
                        # Wait for next event with timeout to check disconnection
                        event = await asyncio.wait_for(
                            session.event_queue.get(), timeout=30.0
                        )
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        # Send keepalive comment to prevent proxy timeouts
                        yield ": keepalive\n\n"
            finally:
                session.sse_connected = False
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
        session = session_manager.get_session_by_id(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Cancel any existing stream before starting a new one
        session.cancel_current_stream()

        # Launch agent stream as background task
        session.current_task = asyncio.create_task(
            run_agent_stream(
                agent=agent,
                session=session,
                content=body.content,
                cwd=body.cwd,
                stream_parser_config=stream_parser_config,
            )
        )

        return {"status": "ok", "session_id": body.session_id}

    @router.post("/chat/interrupt")
    async def respond_to_interrupt(body: InterruptRequest):
        """Resume agent from an interrupt with user decisions."""
        session = session_manager.get_session_by_id(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        session.cancel_current_stream()

        session.current_task = asyncio.create_task(
            run_interrupt_response(
                agent=agent,
                session=session,
                decisions=body.decisions,
                stream_parser_config=stream_parser_config,
            )
        )

        return {"status": "ok", "session_id": body.session_id}

    @router.post("/chat/cancel")
    async def cancel_stream(body: CancelRequest):
        """Cancel the current agent stream."""
        session = session_manager.get_session_by_id(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        session.cancel_current_stream()
        return {"status": "ok", "session_id": body.session_id}

    return router


async def _push_file_changes(session, file_manager: FileManager) -> None:
    """Watch workspace for file changes and push to session queue."""
    try:
        async for change in file_manager.watch():
            await session.push_event({
                "type": "file_changed",
                "event": change.event_type,
                "path": change.path,
            })
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("File watcher error")
