"""Tests for session management with persistence across reconnects."""

import asyncio
from unittest.mock import MagicMock
from cowork_dash.stream.session_manager import SessionManager, AgentSession


def test_create_new_session():
    """get_or_create with no session_id creates a fresh session."""
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.get_or_create(ws)
    assert isinstance(session, AgentSession)
    assert session.thread_id  # non-empty UUID
    assert mgr.active_count == 1


def test_get_session():
    """get_session returns the session linked to a websocket."""
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.get_or_create(ws)
    assert mgr.get_session(ws) is session


def test_get_session_unknown_ws():
    """get_session returns None for an unknown websocket."""
    mgr = SessionManager()
    ws = MagicMock()
    assert mgr.get_session(ws) is None


def test_remove_unlinks_but_preserves_session():
    """remove() unlinks websocket but keeps the session alive."""
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.get_or_create(ws)
    session_id = session.thread_id

    mgr.remove(ws)

    # WebSocket is unlinked
    assert mgr.active_count == 0
    assert mgr.get_session(ws) is None

    # But session still exists and can be resumed
    ws2 = MagicMock()
    resumed = mgr.get_or_create(ws2, session_id=session_id)
    assert resumed is session
    assert resumed.thread_id == session_id
    assert mgr.active_count == 1


def test_resume_existing_session():
    """get_or_create with a valid session_id resumes the existing session."""
    mgr = SessionManager()
    ws1 = MagicMock()
    session = mgr.get_or_create(ws1)
    session_id = session.thread_id

    # Simulate disconnect
    mgr.remove(ws1)

    # Reconnect with the same session_id
    ws2 = MagicMock()
    resumed = mgr.get_or_create(ws2, session_id=session_id)
    assert resumed is session
    assert resumed.thread_id == session_id
    assert mgr.get_session(ws2) is session


def test_resume_nonexistent_session_creates_new():
    """get_or_create with an unknown session_id creates a new session."""
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.get_or_create(ws, session_id="nonexistent-id")
    assert session.thread_id != "nonexistent-id"
    assert mgr.active_count == 1


def test_delete_session():
    """delete_session permanently removes a session."""
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.get_or_create(ws)
    session_id = session.thread_id

    mgr.remove(ws)
    assert mgr.delete_session(session_id) is True

    # Session is gone — can't resume it
    ws2 = MagicMock()
    new_session = mgr.get_or_create(ws2, session_id=session_id)
    assert new_session is not session
    assert new_session.thread_id != session_id


def test_delete_session_nonexistent():
    """delete_session returns False for unknown session."""
    mgr = SessionManager()
    assert mgr.delete_session("nonexistent") is False


def test_multiple_sessions():
    """Multiple websockets create independent sessions."""
    mgr = SessionManager()
    ws1 = MagicMock()
    ws2 = MagicMock()
    s1 = mgr.get_or_create(ws1)
    s2 = mgr.get_or_create(ws2)
    assert s1.thread_id != s2.thread_id
    assert mgr.active_count == 2


def test_session_config_has_thread_id():
    """AgentSession.config contains the thread_id."""
    session = AgentSession()
    assert session.config == {"configurable": {"thread_id": session.thread_id}}


def test_active_count_tracks_websockets_not_sessions():
    """active_count reflects connected websockets, not total sessions."""
    mgr = SessionManager()
    ws1 = MagicMock()
    ws2 = MagicMock()

    mgr.get_or_create(ws1)
    mgr.get_or_create(ws2)
    assert mgr.active_count == 2

    mgr.remove(ws1)
    assert mgr.active_count == 1  # 1 websocket, but 2 sessions exist

    mgr.remove(ws2)
    assert mgr.active_count == 0  # 0 websockets, 2 sessions still in memory
