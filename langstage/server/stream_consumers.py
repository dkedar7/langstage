"""One reader per session's event stream (gh #236).

A session has one event queue, and every frame in it is handed to whoever asks next.
Two ``GET /api/stream`` connections on the same session therefore split a turn between
them, frame by frame: neither window gets the whole reply. This registry is the one
place that decides who may read a session's queue.

The rules:

- **A second reader is refused.** While one connection reads a session, another gets
  HTTP 409, and the first is left alone. The web UI shows the conversation read-only
  in that window.
- **The same window coming back takes its own place.** The UI sends a ``client`` id
  with its stream. A connection with the id of the current reader is that window
  coming back (a page reload, or a reconnect after its connection dropped) before the
  server has noticed the old connection die. The old reader is stopped and the new
  one carries on, so nobody is locked out of their own conversation.
- **A window can be told to let go.** "Continue here" in a read-only window takes the
  conversation over once no turn is running: the reader it replaces gets a
  ``superseded`` frame and its stream ends. This is also the way past a reader whose
  connection died without the server seeing it.

A handover never loses or repeats a frame on the server side. The outgoing reader
stops *before* the incoming one starts; a frame it had already taken off the queue but
not yet written is passed to its successor. (A frame already written to a connection
that then died is gone. The UI re-reads the transcript when a turn ends after its
stream was re-attached, which covers that.)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: How long a new reader waits for the one it replaces to stop reading. A reader
#: reacts within a turn or two of the event loop, so this only guards against a bug.
HANDOVER_TIMEOUT_S = 10.0

#: ``reason`` values of the ``superseded`` frame.
RECONNECTED = "reconnected"  # the same window attached again
TAKEN_OVER = "taken_over"  # another window continued the conversation


class StreamConsumer:
    """One ``GET /api/stream`` connection reading a session's queue."""

    def __init__(self, session_id: str, client: str | None) -> None:
        self.session_id = session_id
        self.client = client
        #: Set to make this reader stop. It reads no further frame once this is set.
        self.evicted = asyncio.Event()
        self.reason: str | None = None
        #: Set whenever no read of the queue is in flight.
        self.parked = asyncio.Event()
        self.parked.set()
        #: Frames the reader before this one left behind, still to be written.
        self.inherited: list[str] = []
        #: Frames this reader took off the queue but never wrote.
        self.unsent: list[str] = []
        self.done = False

    def evict(self, reason: str) -> None:
        if not self.evicted.is_set():
            self.reason = reason
            self.evicted.set()


class StreamConsumers:
    """Who is reading each session's event queue: at most one reader per session."""

    def __init__(self) -> None:
        self._current: dict[str, StreamConsumer] = {}
        self._unsent: dict[str, list[str]] = {}

    def current(self, session_id: str) -> StreamConsumer | None:
        return self._current.get(session_id)

    def attached(self, session_id: str) -> bool:
        """Whether a connection is reading this session's stream."""
        return session_id in self._current

    def refuses(self, session_id: str, client: str | None) -> bool:
        """Whether ``client`` would be refused the session's stream right now."""
        current = self._current.get(session_id)
        return current is not None and not (client and current.client == client)

    async def claim(self, session_id: str, client: str | None) -> StreamConsumer | None:
        """Become the session's reader, or None when another window holds it.

        The check and the registration happen with no ``await`` between them, so two
        connections arriving together can't both win.
        """
        while True:
            current = self._current.get(session_id)
            if current is None:
                break
            if not client or current.client != client:
                return None
            # The same window, attaching again: its earlier connection gives way.
            if not await self._stop(current, RECONNECTED):
                return None
        consumer = StreamConsumer(session_id, client)
        consumer.inherited = self._unsent.pop(session_id, [])
        self._current[session_id] = consumer
        return consumer

    def hold(self, session_id: str) -> StreamConsumer | None:
        """Reserve the session's queue for a reader that is not a stream (the buffered
        one-turn endpoint), or None when something is already reading it. Release it
        afterwards."""
        if session_id in self._current:
            return None
        consumer = StreamConsumer(session_id, None)
        self._current[session_id] = consumer
        return consumer

    async def take_over(self, session_id: str) -> bool:
        """Stop the session's reader so another window can attach. Frames it had not
        written are dropped: the caller re-reads the transcript, which has them."""
        current = self._current.get(session_id)
        if current is not None and not await self._stop(current, TAKEN_OVER):
            return False
        self._unsent.pop(session_id, None)
        return True

    def release(self, consumer: StreamConsumer) -> None:
        """The reader is gone (its connection closed, or it was stopped)."""
        if consumer.done:
            return
        consumer.done = True
        consumer.parked.set()
        self._retire(consumer)

    def forget(self, session_id: str) -> None:
        """The session is gone: nothing is left to hand on."""
        self._unsent.pop(session_id, None)

    def _retire(self, consumer: StreamConsumer) -> None:
        if self._current.get(consumer.session_id) is consumer:
            del self._current[consumer.session_id]
        # Oldest first: what it inherited and never got to, then what it read itself.
        left = [*consumer.inherited, *consumer.unsent]
        consumer.inherited.clear()
        consumer.unsent.clear()
        if left:
            self._unsent.setdefault(consumer.session_id, []).extend(left)

    async def _stop(self, consumer: StreamConsumer, reason: str) -> bool:
        consumer.evict(reason)
        try:
            async with asyncio.timeout(HANDOVER_TIMEOUT_S):
                await consumer.parked.wait()
        except TimeoutError:
            logger.warning(
                "The stream reading session %s did not stop; refusing to share it",
                consumer.session_id,
            )
            return False
        # It reads nothing more. A connection stuck writing to a dead socket may take a
        # while to finish, but the stream is no longer its to read.
        self._retire(consumer)
        return True


def superseded_frame(reason: str | None) -> dict[str, Any]:
    """The last frame a replaced reader gets, so its window stops reconnecting."""
    return {"type": "superseded", "reason": reason or TAKEN_OVER}
