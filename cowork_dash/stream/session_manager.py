"""Per-connection session state management with persistence across reconnects."""

import asyncio
import uuid
from datetime import datetime

from fastapi import WebSocket


class AgentSession:
    """Session state. Survives WebSocket disconnects so page refresh can resume."""

    def __init__(self):
        self.thread_id: str = str(uuid.uuid4())
        self.config: dict = {"configurable": {"thread_id": self.thread_id}}
        self.current_task: asyncio.Task | None = None
        self.created_at: datetime = datetime.now()

    def cancel_current_stream(self) -> None:
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()


class SessionManager:
    """Manages chat sessions. Sessions persist across WebSocket reconnects."""

    def __init__(self):
        # session_id (== thread_id) → AgentSession
        self._sessions: dict[str, AgentSession] = {}
        # id(websocket) → session_id
        self._ws_to_session: dict[int, str] = {}

    def get_or_create(
        self, websocket: WebSocket, session_id: str | None = None
    ) -> AgentSession:
        """Resume an existing session or create a new one.

        If session_id is provided and exists, reuse it. Otherwise create fresh.
        Links the websocket to the session for later lookup.
        """
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
        else:
            session = AgentSession()
            self._sessions[session.thread_id] = session

        self._ws_to_session[id(websocket)] = session.thread_id
        return session

    def get_session(self, websocket: WebSocket) -> AgentSession | None:
        session_id = self._ws_to_session.get(id(websocket))
        if session_id:
            return self._sessions.get(session_id)
        return None

    def remove(self, websocket: WebSocket) -> None:
        """Unlink websocket but keep session alive for reconnection."""
        session_id = self._ws_to_session.pop(id(websocket), None)
        if session_id:
            session = self._sessions.get(session_id)
            if session:
                session.cancel_current_stream()

    def delete_session(self, session_id: str) -> bool:
        """Permanently delete a session. Returns True if found."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.cancel_current_stream()
            return True
        return False

    @property
    def active_count(self) -> int:
        """Number of sessions with active websocket connections."""
        return len(self._ws_to_session)
