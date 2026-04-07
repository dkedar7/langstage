"""Tests for session management with persistence across reconnects."""

import asyncio
from cowork_dash.stream.session_manager import SessionManager, AgentSession


def test_create_new_session():
    """get_or_create with no session_id creates a fresh session."""
    mgr = SessionManager()
    session = mgr.get_or_create()
    assert isinstance(session, AgentSession)
    assert session.thread_id  # non-empty UUID
    assert mgr.active_count == 0  # no SSE connected yet


def test_get_session_by_id():
    """get_session_by_id returns session by its thread_id."""
    mgr = SessionManager()
    session = mgr.get_or_create()
    assert mgr.get_session_by_id(session.thread_id) is session


def test_get_session_by_id_not_found():
    """get_session_by_id returns None for unknown ID."""
    mgr = SessionManager()
    assert mgr.get_session_by_id("nonexistent") is None


def test_resume_existing_session():
    """get_or_create with a valid session_id resumes the existing session."""
    mgr = SessionManager()
    session = mgr.get_or_create()
    session_id = session.thread_id

    # Resuming with same ID returns same session
    resumed = mgr.get_or_create(session_id=session_id)
    assert resumed is session
    assert resumed.thread_id == session_id


def test_resume_nonexistent_session_creates_new():
    """get_or_create with an unknown session_id creates a new session."""
    mgr = SessionManager()
    session = mgr.get_or_create(session_id="nonexistent-id")
    assert session.thread_id != "nonexistent-id"


def test_delete_session():
    """delete_session permanently removes a session."""
    mgr = SessionManager()
    session = mgr.get_or_create()
    session_id = session.thread_id

    assert mgr.delete_session(session_id) is True

    # Session is gone — can't resume it
    new_session = mgr.get_or_create(session_id=session_id)
    assert new_session is not session
    assert new_session.thread_id != session_id


def test_delete_session_nonexistent():
    """delete_session returns False for unknown session."""
    mgr = SessionManager()
    assert mgr.delete_session("nonexistent") is False


def test_multiple_sessions():
    """Multiple get_or_create calls create independent sessions."""
    mgr = SessionManager()
    s1 = mgr.get_or_create()
    s2 = mgr.get_or_create()
    assert s1.thread_id != s2.thread_id


def test_session_config_has_thread_id():
    """AgentSession.config contains the thread_id."""
    session = AgentSession()
    assert session.config == {"configurable": {"thread_id": session.thread_id}}


def test_active_count_tracks_sse_connections():
    """active_count reflects sessions with sse_connected=True."""
    mgr = SessionManager()
    s1 = mgr.get_or_create()
    s2 = mgr.get_or_create()
    assert mgr.active_count == 0

    s1.sse_connected = True
    assert mgr.active_count == 1

    s2.sse_connected = True
    assert mgr.active_count == 2

    s1.sse_connected = False
    assert mgr.active_count == 1


def test_list_sessions():
    """list_sessions returns session info with connection status."""
    mgr = SessionManager()
    s1 = mgr.get_or_create()
    s1.sse_connected = True
    s2 = mgr.get_or_create()

    sessions = mgr.list_sessions()
    assert len(sessions) == 2

    by_id = {s["session_id"]: s for s in sessions}
    assert by_id[s1.thread_id]["connected"] is True
    assert by_id[s2.thread_id]["connected"] is False


def test_session_has_event_queue():
    """AgentSession has an asyncio.Queue for SSE events."""
    session = AgentSession()
    assert isinstance(session.event_queue, asyncio.Queue)
