"""REST endpoints for session management."""

from fastapi import APIRouter

from cowork_dash.stream.session_manager import SessionManager

try:
    from cowork_dash.browser import cleanup_browser_state
    _HAS_BROWSER = True
except ImportError:
    _HAS_BROWSER = False


def create_session_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["session"])

    @router.delete("/session/{session_id}")
    async def delete_session(session_id: str):
        if _HAS_BROWSER:
            await cleanup_browser_state(session_id)
        session_manager.delete_session(session_id)
        return {"ok": True}

    return router
