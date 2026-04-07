"""Per-session state management with SSE event queues."""

import asyncio
import uuid
from datetime import datetime


class AgentSession:
    """Session state. Survives browser disconnects so page refresh can resume."""

    def __init__(self):
        self.thread_id: str = str(uuid.uuid4())
        self.config: dict = {"configurable": {"thread_id": self.thread_id}}
        self.current_task: asyncio.Task | None = None
        self.created_at: datetime = datetime.now()
        # SSE event queue — server pushes events here, SSE endpoint reads them
        self.event_queue: asyncio.Queue = asyncio.Queue()
        # Track whether an SSE client is connected
        self.sse_connected: bool = False

    def cancel_current_stream(self) -> None:
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()

    async def push_event(self, event: dict) -> None:
        """Push a serialized event to the SSE queue."""
        await self.event_queue.put(event)


class SessionManager:
    """Manages chat sessions. Sessions persist across SSE reconnects."""

    def __init__(self):
        # session_id (== thread_id) → AgentSession
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create(self, session_id: str | None = None) -> AgentSession:
        """Resume an existing session or create a new one.

        If session_id is provided and exists, reuse it. Otherwise create fresh.
        """
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        session = AgentSession()
        self._sessions[session.thread_id] = session
        return session

    def get_session_by_id(self, session_id: str) -> AgentSession | None:
        """Look up a session directly by its ID."""
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Permanently delete a session. Returns True if found."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.cancel_current_stream()
            return True
        return False

    def list_sessions(self) -> list[dict]:
        """Return summary info for all sessions."""
        return [
            {
                "session_id": sid,
                "created_at": session.created_at.isoformat(),
                "connected": session.sse_connected,
            }
            for sid, session in self._sessions.items()
        ]

    @property
    def active_count(self) -> int:
        """Number of sessions with active SSE connections."""
        return sum(1 for s in self._sessions.values() if s.sse_connected)
