"""End open SSE streams when the server shuts down (gh #211).

Uvicorn's graceful shutdown waits for every open connection to finish *before* it
runs the app's lifespan shutdown. The UI's ``GET /api/stream`` never finishes on its
own, so with a tab open one Ctrl+C or SIGTERM hung forever, and the lifespan (the
scheduler and task runner shutdown) never ran.

:class:`Server` sets the app's shutdown event the moment shutdown starts, and
:func:`until_shutdown` ends a stream when it fires. The connections then close, and
uvicorn goes on to the lifespan shutdown as usual. The servers also get a short
``timeout_graceful_shutdown`` as a backstop for any other long-lived request.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import uvicorn

STATE_KEY = "langstage_shutdown"

#: Seconds uvicorn waits for open requests before cancelling them.
GRACEFUL_SHUTDOWN_TIMEOUT = 5.0


def shutdown_event(app: Any) -> asyncio.Event:
    """The app's shutdown event, created on first use (a never-set one without an app)."""
    if app is None:
        return asyncio.Event()
    event = getattr(app.state, STATE_KEY, None)
    if event is None:
        event = asyncio.Event()
        setattr(app.state, STATE_KEY, event)
    return event


async def until_shutdown(frames: AsyncIterator[Any], stop: asyncio.Event) -> AsyncIterator[Any]:
    """Yield from ``frames`` until it ends or ``stop`` is set, whichever comes first."""
    stop_wait = asyncio.ensure_future(stop.wait())
    try:
        while True:
            nxt = asyncio.ensure_future(anext(frames))
            done, _ = await asyncio.wait({nxt, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
            if nxt not in done:
                nxt.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await nxt
                return
            try:
                frame = nxt.result()
            except StopAsyncIteration:
                return
            yield frame
    finally:
        stop_wait.cancel()


class Server(uvicorn.Server):
    """A uvicorn server that tells the app it's shutting down before it waits on
    open connections, so SSE streams end instead of holding the shutdown open."""

    async def shutdown(self, sockets: Any = None) -> None:
        app = self.config.app
        state = getattr(app, "state", None)
        event = getattr(state, STATE_KEY, None) if state is not None else None
        if event is not None:
            event.set()
        await super().shutdown(sockets)
