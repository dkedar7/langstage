"""WebSocket endpoint: /ws/chat."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from langgraph_stream_parser import StreamParser, create_resume_input

from cowork_dash.stream.event_serializer import EventSerializer
from cowork_dash.stream.session_manager import SessionManager
from cowork_dash.stream.websocket_adapter import DUAL_STREAM_MODE
from cowork_dash.workspace.file_manager import FileManager

logger = logging.getLogger(__name__)


async def chat_websocket(
    websocket: WebSocket,
    agent,
    session_manager: SessionManager,
    file_manager: FileManager,
    stream_parser_config: dict | None = None,
):
    """Handle a single WebSocket connection for chat streaming."""
    await websocket.accept()

    session = session_manager.create_session(websocket)
    serializer = EventSerializer()
    parser = StreamParser(
        stream_mode=DUAL_STREAM_MODE,
        **(stream_parser_config or {}),
    )

    # Start file watcher task for this connection
    file_watch_task = asyncio.create_task(
        _broadcast_file_changes(websocket, file_manager)
    )

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "message":
                await _handle_message(
                    websocket, agent, session, parser, serializer,
                    raw["content"], raw.get("cwd"),
                )

            elif msg_type == "interrupt_response":
                await _handle_interrupt_response(
                    websocket, agent, session, parser, serializer,
                    raw["decisions"],
                )

            elif msg_type == "cancel":
                session.cancel_current_stream()

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: thread=%s", session.thread_id)
    except Exception:
        logger.exception("WebSocket error: thread=%s", session.thread_id)
    finally:
        file_watch_task.cancel()
        session_manager.remove(websocket)


async def _handle_message(
    websocket: WebSocket,
    agent,
    session,
    parser: StreamParser,
    serializer: EventSerializer,
    content: str,
    cwd: str | None = None,
):
    """Stream agent response for a user message."""
    # Inject current time and working directory context
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    prefix_parts = [f"[Current time: {now}]"]
    if cwd:
        prefix_parts.append(f"[Working directory: {cwd}]")
    enriched = "\n".join(prefix_parts) + "\n\n" + content
    input_data = {"messages": [{"role": "user", "content": enriched}]}

    stream = agent.astream(
        input_data,
        config=session.config,
        stream_mode=DUAL_STREAM_MODE,
    )

    async for event in parser.aparse(stream):
        msg = serializer.serialize(event)
        await websocket.send_json(msg)


async def _handle_interrupt_response(
    websocket: WebSocket,
    agent,
    session,
    parser: StreamParser,
    serializer: EventSerializer,
    decisions: list[dict],
):
    """Resume agent from an interrupt with user decisions."""
    resume_input = create_resume_input(decisions=decisions)

    stream = agent.astream(
        resume_input,
        config=session.config,
        stream_mode=DUAL_STREAM_MODE,
    )

    async for event in parser.aparse(stream):
        msg = serializer.serialize(event)
        await websocket.send_json(msg)


async def _broadcast_file_changes(
    websocket: WebSocket,
    file_manager: FileManager,
):
    """Watch workspace for file changes and notify this connection."""
    try:
        async for change in file_manager.watch():
            await websocket.send_json({
                "type": "file_changed",
                "event": change.event_type,
                "path": change.path,
            })
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("File watcher error")
