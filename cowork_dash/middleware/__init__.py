"""Middleware for injecting optional agent capabilities."""

from cowork_dash.middleware.canvas import (
    CANVAS_PROMPT,
    CanvasMiddleware,
    agent_uses_canvas_middleware,
)

__all__ = [
    "CanvasMiddleware",
    "CANVAS_PROMPT",
    "agent_uses_canvas_middleware",
]
