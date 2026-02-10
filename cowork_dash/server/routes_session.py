"""REST endpoints for session management."""

from fastapi import APIRouter

from cowork_dash.stream.session_manager import SessionManager


def create_session_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["session"])

    @router.delete("/session/{session_id}")
    async def delete_session(session_id: str):
        session_manager.delete_session(session_id)
        return {"ok": True}

    return router
