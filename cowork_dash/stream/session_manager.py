"""Per-WebSocket-connection session state management."""

import asyncio
import uuid
from datetime import datetime

from fastapi import WebSocket


class AgentSession:
    """Per-WebSocket-connection state. One per browser tab."""

    def __init__(self):
        self.thread_id: str = str(uuid.uuid4())
        self.config: dict = {"configurable": {"thread_id": self.thread_id}}
        self.current_task: asyncio.Task | None = None
        self.created_at: datetime = datetime.now()

    def cancel_current_stream(self) -> None:
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()


class SessionManager:
    """Manages active chat sessions. Thread-safe for concurrent connections."""

    def __init__(self):
        self._sessions: dict[int, AgentSession] = {}

    def create_session(self, websocket: WebSocket) -> AgentSession:
        """Always creates a new session. Each tab = new thread."""
        session = AgentSession()
        self._sessions[id(websocket)] = session
        return session

    def get_session(self, websocket: WebSocket) -> AgentSession | None:
        return self._sessions.get(id(websocket))

    def remove(self, websocket: WebSocket) -> None:
        session = self._sessions.pop(id(websocket), None)
        if session:
            session.cancel_current_stream()

    @property
    def active_count(self) -> int:
        return len(self._sessions)
