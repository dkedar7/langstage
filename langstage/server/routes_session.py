"""REST endpoints for session management, on the shared SessionAdapter."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from langstage_core.adapters import SessionAdapter

from langstage.server.routes_chat import context_parts


class InjectRequest(BaseModel):
    content: str
    cwd: str | None = None


def create_session_router(adapter: SessionAdapter) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["session"])

    @router.get("/sessions")
    async def list_sessions():
        """List all sessions with connection status."""
        return adapter.list_sessions()

    @router.delete("/session/{session_id}")
    async def delete_session(session_id: str):
        adapter.delete_session(session_id)
        return {"ok": True}

    @router.post("/session/{session_id}/inject", status_code=202)
    async def inject_message(session_id: str, body: InjectRequest):
        """Inject a user message into a running session.

        The message appears in the browser as a user bubble and the agent
        processes it, streaming responses via the SSE connection. Returns 202
        immediately (fire-and-forget).
        """
        session = adapter.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if not session.sse_connected:
            raise HTTPException(
                status_code=409,
                detail="No browser connected to this session",
            )

        # Synthetic user_message event so the browser shows a user bubble,
        # then run the turn (submit_message cancels any in-flight stream).
        adapter.push_event(session_id, {
            "type": "user_message",
            "content": body.content,
        })
        adapter.submit_message(
            session_id, body.content, context_parts=context_parts(body.cwd)
        )
        return {"status": "accepted", "session_id": session_id}

    return router
