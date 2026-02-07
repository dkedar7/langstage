"""Tests for event serialization."""

from cowork_dash.stream.event_serializer import EventSerializer
from langgraph_stream_parser.events import (
    ContentEvent,
    ToolCallStartEvent,
    ToolCallEndEvent,
    CompleteEvent,
    ErrorEvent,
    InterruptEvent,
)


def test_content_event():
    ser = EventSerializer()
    result = ser.serialize(ContentEvent(content="hello", node="agent"))
    assert result["type"] == "content"
    assert result["content"] == "hello"
    assert result["node"] == "agent"


def test_tool_start_event():
    ser = EventSerializer()
    result = ser.serialize(
        ToolCallStartEvent(id="tc1", name="write_file", args={"path": "/x"})
    )
    assert result["type"] == "tool_start"
    assert result["id"] == "tc1"
    assert result["name"] == "write_file"


def test_tool_end_event():
    ser = EventSerializer()
    result = ser.serialize(
        ToolCallEndEvent(
            id="tc1",
            name="write_file",
            result="File written.",
            status="success",
        )
    )
    assert result["type"] == "tool_end"
    assert result["status"] == "success"


def test_complete_event():
    ser = EventSerializer()
    result = ser.serialize(CompleteEvent())
    assert result["type"] == "complete"


def test_error_event():
    ser = EventSerializer()
    result = ser.serialize(ErrorEvent(error="something broke"))
    assert result["type"] == "error"
    assert result["error"] == "something broke"


def test_interrupt_event():
    ser = EventSerializer()
    result = ser.serialize(
        InterruptEvent(
            action_requests=[{"tool": "execute", "args": {"command": "ls"}}],
            review_configs=[{"allowed_decisions": ["approve", "reject"]}],
        )
    )
    assert result["type"] == "interrupt"
    assert len(result["action_requests"]) == 1
