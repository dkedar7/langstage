"""Tests for session management."""

from unittest.mock import MagicMock
from cowork_dash.stream.session_manager import SessionManager, AgentSession


def test_create_session():
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.create_session(ws)
    assert isinstance(session, AgentSession)
    assert session.thread_id  # non-empty UUID
    assert mgr.active_count == 1


def test_get_session():
    mgr = SessionManager()
    ws = MagicMock()
    session = mgr.create_session(ws)
    assert mgr.get_session(ws) is session


def test_remove_session():
    mgr = SessionManager()
    ws = MagicMock()
    mgr.create_session(ws)
    mgr.remove(ws)
    assert mgr.active_count == 0
    assert mgr.get_session(ws) is None


def test_multiple_sessions():
    mgr = SessionManager()
    ws1 = MagicMock()
    ws2 = MagicMock()
    s1 = mgr.create_session(ws1)
    s2 = mgr.create_session(ws2)
    assert s1.thread_id != s2.thread_id
    assert mgr.active_count == 2
