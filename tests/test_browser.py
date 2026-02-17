"""Tests for browser state management and stream manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cowork_dash.browser import (
    BrowserFrame,
    BrowserState,
    BrowserStreamManager,
    get_browser_state,
    cleanup_browser_state,
    _session_browser_states,
    _browser_state,
)


# ---------------------------------------------------------------------------
# BrowserFrame
# ---------------------------------------------------------------------------

def test_browser_frame_fields():
    frame = BrowserFrame(
        data="base64data", session_id=1, width=1280, height=720, timestamp=1.0
    )
    assert frame.data == "base64data"
    assert frame.width == 1280
    assert frame.height == 720


# ---------------------------------------------------------------------------
# BrowserState lifecycle
# ---------------------------------------------------------------------------

def test_browser_state_init():
    state = BrowserState()
    assert state.is_running is False
    assert state.current_url == ""


def test_browser_state_with_session_id():
    state = BrowserState(ws_session_id="test-session")
    assert state._ws_session_id == "test-session"
    assert state.is_running is False


async def test_browser_state_close_when_not_running():
    state = BrowserState()
    result = await state.close()
    assert result == {"status": "closed"}
    assert state.is_running is False


async def test_browser_state_reset():
    state = BrowserState()
    await state.reset()
    assert state.is_running is False
    assert state.current_url == ""


async def test_browser_state_frame_callback():
    state = BrowserState()
    callback = AsyncMock()
    state.set_frame_callback(callback)
    assert state._frame_callback is callback

    # Clear callback
    state.set_frame_callback(None)
    assert state._frame_callback is None


# ---------------------------------------------------------------------------
# BrowserStreamManager
# ---------------------------------------------------------------------------

def test_stream_manager_singleton():
    # Reset singleton for test isolation
    BrowserStreamManager._instance = None
    mgr1 = BrowserStreamManager.get_instance()
    mgr2 = BrowserStreamManager.get_instance()
    assert mgr1 is mgr2
    BrowserStreamManager._instance = None


def test_stream_manager_register_unregister():
    mgr = BrowserStreamManager()
    ws = MagicMock()
    mgr.register("session-1", ws)
    assert "session-1" in mgr._connections

    mgr.unregister("session-1")
    assert "session-1" not in mgr._connections


def test_stream_manager_unregister_nonexistent():
    mgr = BrowserStreamManager()
    # Should not raise
    mgr.unregister("nonexistent")


async def test_stream_manager_send_frame():
    mgr = BrowserStreamManager()
    ws = AsyncMock()
    mgr.register("session-1", ws)

    frame = BrowserFrame(
        data="abc123", session_id=1, width=1280, height=720, timestamp=1.0
    )
    await mgr.send_frame("session-1", frame)

    ws.send_json.assert_called_once_with({
        "type": "browser_frame",
        "data": "abc123",
        "width": 1280,
        "height": 720,
    })


async def test_stream_manager_send_frame_no_connection():
    mgr = BrowserStreamManager()
    frame = BrowserFrame(
        data="abc123", session_id=1, width=1280, height=720, timestamp=1.0
    )
    # Should not raise when no connection
    await mgr.send_frame("nonexistent", frame)


async def test_stream_manager_send_status():
    mgr = BrowserStreamManager()
    ws = AsyncMock()
    mgr.register("session-1", ws)

    await mgr.send_status("session-1", "running")
    ws.send_json.assert_called_once_with({
        "type": "browser_status",
        "status": "running",
    })


async def test_stream_manager_send_url():
    mgr = BrowserStreamManager()
    ws = AsyncMock()
    mgr.register("session-1", ws)

    await mgr.send_url("session-1", "https://example.com")
    ws.send_json.assert_called_once_with({
        "type": "browser_url",
        "url": "https://example.com",
    })


async def test_stream_manager_send_frame_handles_error():
    mgr = BrowserStreamManager()
    ws = AsyncMock()
    ws.send_json.side_effect = Exception("connection closed")
    mgr.register("session-1", ws)

    frame = BrowserFrame(
        data="abc", session_id=1, width=1280, height=720, timestamp=1.0
    )
    # Should not raise
    await mgr.send_frame("session-1", frame)


# ---------------------------------------------------------------------------
# Module-level state: get_browser_state / cleanup_browser_state
# ---------------------------------------------------------------------------

def test_get_browser_state_global():
    import cowork_dash.browser as mod
    old = mod._browser_state
    mod._browser_state = None

    state = get_browser_state()
    assert isinstance(state, BrowserState)
    # Calling again returns the same instance
    assert get_browser_state() is state

    mod._browser_state = old


def test_get_browser_state_session():
    _session_browser_states.clear()

    state = get_browser_state("test-session")
    assert isinstance(state, BrowserState)
    assert state._ws_session_id == "test-session"

    # Same session returns same instance
    assert get_browser_state("test-session") is state

    # Different session returns different instance
    state2 = get_browser_state("other-session")
    assert state2 is not state

    _session_browser_states.clear()


async def test_cleanup_browser_state():
    _session_browser_states.clear()

    state = get_browser_state("cleanup-test")
    assert "cleanup-test" in _session_browser_states

    await cleanup_browser_state("cleanup-test")
    assert "cleanup-test" not in _session_browser_states


async def test_cleanup_nonexistent_session():
    _session_browser_states.clear()
    # Should not raise
    await cleanup_browser_state("nonexistent")
