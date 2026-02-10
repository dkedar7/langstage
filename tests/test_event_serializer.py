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


def test_interrupt_event_hitl_format():
    """Interrupt with HITL middleware ActionRequest format (name, not tool)."""
    from langgraph_stream_parser.extractors.interrupts import process_interrupt

    # Simulate what LangGraph produces: tuple of Interrupt objects
    # Each Interrupt has .value = HITLRequest dict
    class FakeInterrupt:
        def __init__(self, value):
            self.value = value
            self.id = "test-id"

    hitl_request = {
        "action_requests": [
            {"name": "bash", "args": {"command": "rm -rf /tmp/test"}, "description": "Tool execution requires approval\n\nTool: bash\nArgs: {'command': 'rm -rf /tmp/test'}"},
        ],
        "review_configs": [
            {"action_name": "bash", "allowed_decisions": ["approve", "edit", "reject"]},
        ],
    }
    interrupt_tuple = (FakeInterrupt(hitl_request),)

    # process_interrupt should extract and serialize correctly
    interrupt_data = process_interrupt(interrupt_tuple)
    assert len(interrupt_data["action_requests"]) == 1
    assert interrupt_data["action_requests"][0]["tool"] == "bash"
    assert interrupt_data["action_requests"][0]["args"]["command"] == "rm -rf /tmp/test"
    assert interrupt_data["action_requests"][0]["description"] is not None
    assert len(interrupt_data["review_configs"]) == 1
    assert "approve" in interrupt_data["review_configs"][0]["allowed_decisions"]

    # Verify it serializes correctly through EventSerializer
    ser = EventSerializer()
    event = InterruptEvent(
        action_requests=interrupt_data["action_requests"],
        review_configs=interrupt_data["review_configs"],
    )
    result = ser.serialize(event)
    assert result["type"] == "interrupt"
    assert result["action_requests"][0]["tool"] == "bash"
    assert result["action_requests"][0]["args"]["command"] == "rm -rf /tmp/test"
    assert "approve" in result["allowed_decisions"]


def test_interrupt_event_multi_interrupt():
    """Multiple Interrupt objects in tuple (multiple tool calls needing approval)."""
    from langgraph_stream_parser.extractors.interrupts import process_interrupt

    class FakeInterrupt:
        def __init__(self, value):
            self.value = value
            self.id = "test-id"

    hitl1 = {
        "action_requests": [{"name": "bash", "args": {"command": "ls"}}],
        "review_configs": [{"allowed_decisions": ["approve", "reject"]}],
    }
    hitl2 = {
        "action_requests": [{"name": "write_file", "args": {"path": "/tmp/x"}}],
        "review_configs": [{"allowed_decisions": ["approve", "edit", "reject"]}],
    }
    interrupt_tuple = (FakeInterrupt(hitl1), FakeInterrupt(hitl2))

    interrupt_data = process_interrupt(interrupt_tuple)
    assert len(interrupt_data["action_requests"]) == 2
    assert interrupt_data["action_requests"][0]["tool"] == "bash"
    assert interrupt_data["action_requests"][1]["tool"] == "write_file"
    assert len(interrupt_data["review_configs"]) == 2
