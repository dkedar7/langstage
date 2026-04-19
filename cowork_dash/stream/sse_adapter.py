"""SSE adapter for streaming LangGraph events to the client.

Replaces the WebSocket adapter with Server-Sent Events over plain HTTP.
Events are pushed to a per-session asyncio.Queue, and the SSE endpoint
reads from that queue.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from langgraph_stream_parser import StreamParser, create_resume_input, prepare_agent_input

from .event_serializer import EventSerializer
from .session_manager import AgentSession

logger = logging.getLogger(__name__)

DUAL_STREAM_MODE = ["updates", "messages"]


async def run_agent_stream(
    agent,
    session: AgentSession,
    content: str,
    cwd: str | None = None,
    stream_parser_config: dict | None = None,
) -> None:
    """Stream agent response for a user message, pushing events to the session queue."""
    try:
        serializer = EventSerializer()
        parser = StreamParser(
            stream_mode=DUAL_STREAM_MODE,
            **(stream_parser_config or {}),
        )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        context_lines = [f"[Current time: {now}]"]
        if cwd:
            context_lines.append(f"[Working directory: {cwd}]")
        annotated_message = "\n".join(context_lines) + "\n\n" + content
        input_data = prepare_agent_input(message=annotated_message)

        stream = agent.astream(
            input_data,
            config=session.config,
            stream_mode=DUAL_STREAM_MODE,
        )

        async for event in parser.aparse(stream):
            msg = serializer.serialize(event)
            if msg.get("type") == "interrupt":
                logger.info(
                    "Interrupt event: action_requests=%s, review_configs=%s, allowed=%s",
                    msg.get("action_requests"),
                    msg.get("review_configs"),
                    msg.get("allowed_decisions"),
                )
            await session.push_event(msg)
    except asyncio.CancelledError:
        logger.info("Stream cancelled for session %s", session.thread_id)
        await session.push_event({"type": "cancelled"})
    except Exception as exc:
        logger.exception("Agent stream failed for session %s", session.thread_id)
        await session.push_event({
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
        })


async def run_interrupt_response(
    agent,
    session: AgentSession,
    decisions: list[dict],
    stream_parser_config: dict | None = None,
) -> None:
    """Resume agent from an interrupt with user decisions."""
    serializer = EventSerializer()
    parser = StreamParser(
        stream_mode=DUAL_STREAM_MODE,
        **(stream_parser_config or {}),
    )

    resume_input = create_resume_input(decisions=decisions)

    stream = agent.astream(
        resume_input,
        config=session.config,
        stream_mode=DUAL_STREAM_MODE,
    )

    try:
        async for event in parser.aparse(stream):
            msg = serializer.serialize(event)
            await session.push_event(msg)
    except asyncio.CancelledError:
        logger.info("Interrupt stream cancelled for session %s", session.thread_id)
        await session.push_event({"type": "cancelled"})
    except Exception as exc:
        logger.exception("Interrupt stream failed for session %s", session.thread_id)
        await session.push_event({
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
        })
