"""Serialize langgraph-stream-parser events to JSON-compatible dicts.

Uses event.to_dict() from the library, so field names match the library's conventions.
"""

from langgraph_stream_parser.events import StreamEvent, ToolCallEndEvent, event_to_dict


class EventSerializer:
    """Serializes StreamEvent instances to JSON-ready dicts for WebSocket transport."""

    MAX_RESULT_LEN = 50_000

    def serialize(self, event: StreamEvent) -> dict:
        """Convert a StreamEvent to a JSON-serializable dict.

        Delegates to event.to_dict() from langgraph-stream-parser,
        which provides canonical field names and serialization.
        Tool results use a larger limit so the UI can show full output.
        """
        if isinstance(event, ToolCallEndEvent):
            return event.to_dict(max_result_len=self.MAX_RESULT_LEN)
        return event_to_dict(event)
