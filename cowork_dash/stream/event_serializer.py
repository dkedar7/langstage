"""Serialize langgraph-stream-parser events to JSON-compatible dicts.

Uses event.to_dict() from the library, so field names match the library's conventions.
"""

from langgraph_stream_parser.events import StreamEvent, event_to_dict


class EventSerializer:
    """Serializes StreamEvent instances to JSON-ready dicts for WebSocket transport."""

    def serialize(self, event: StreamEvent) -> dict:
        """Convert a StreamEvent to a JSON-serializable dict.

        Delegates to event.to_dict() from langgraph-stream-parser,
        which provides canonical field names and serialization.
        """
        return event_to_dict(event)
