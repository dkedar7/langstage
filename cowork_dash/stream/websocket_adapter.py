"""Standalone async WebSocket adapter for streaming LangGraph events.

Does NOT extend BaseAdapter (which is sync/blocking).
Uses StreamParser.aparse() directly for async streaming over WebSocket.
"""

from fastapi import WebSocket
from langgraph_stream_parser import StreamParser
from langgraph_stream_parser.events import InterruptEvent

from .event_serializer import EventSerializer


DUAL_STREAM_MODE = ["updates", "messages"]


class WebSocketAdapter:
    """Streams agent events as JSON over a WebSocket connection.

    Uses dual stream mode ["updates", "messages"] to get both
    node-level events (tool lifecycle, interrupts) and token-level
    content streaming simultaneously.
    """

    def __init__(
        self,
        websocket: WebSocket,
        serializer: EventSerializer | None = None,
        **parser_kwargs,
    ):
        self.websocket = websocket
        self.serializer = serializer or EventSerializer()
        self.parser = StreamParser(
            stream_mode=DUAL_STREAM_MODE,
            **parser_kwargs,
        )

    async def stream_to_client(
        self,
        agent,
        input_data: dict,
        config: dict,
    ) -> InterruptEvent | None:
        """Run agent.astream() with dual stream mode, parse events,
        and send each as JSON over WebSocket.

        Returns InterruptEvent if the stream paused for HITL, else None.
        """
        stream = agent.astream(
            input_data,
            config=config,
            stream_mode=DUAL_STREAM_MODE,
        )
        last_interrupt = None

        async for event in self.parser.aparse(stream):
            msg = self.serializer.serialize(event)
            await self.websocket.send_json(msg)

            if isinstance(event, InterruptEvent):
                last_interrupt = event

        return last_interrupt
