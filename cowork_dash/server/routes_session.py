"""REST endpoints for session management."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cowork_dash.stream.session_manager import SessionManager
from cowork_dash.server.websocket import run_injected_message


class InjectRequest(BaseModel):
    content: str
    cwd: str | None = None


def create_session_router(
    session_manager: SessionManager,
    agent=None,
    stream_parser_config: dict | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["session"])

    @router.get("/sessions")
    async def list_sessions():
        """List all sessions with connection status."""
        return session_manager.list_sessions()

    @router.delete("/session/{session_id}")
    async def delete_session(session_id: str):
        session_manager.delete_session(session_id)
        return {"ok": True}

    @router.post("/session/{session_id}/inject", status_code=202)
    async def inject_message(session_id: str, body: InjectRequest):
        """Inject a user message into a running session.

        The message appears in the browser as a user bubble and the agent
        processes it, streaming responses to the connected WebSocket.
        Returns 202 immediately (fire-and-forget).
        """
        session = session_manager.get_session_by_id(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        websocket = session_manager.get_websocket(session_id)
        if websocket is None:
            raise HTTPException(
                status_code=409,
                detail="No browser connected to this session",
            )

        # Cancel any in-flight stream (same as user sending a new message)
        session.cancel_current_stream()

        # Send synthetic user_message event so the browser shows a user bubble
        await websocket.send_json({
            "type": "user_message",
            "content": body.content,
        })

        # Launch agent stream as fire-and-forget task
        session.current_task = asyncio.create_task(
            run_injected_message(
                websocket=websocket,
                agent=agent,
                session=session,
                content=body.content,
                cwd=body.cwd,
                stream_parser_config=stream_parser_config,
            )
        )

        return {"status": "accepted", "session_id": session_id}

    return router
