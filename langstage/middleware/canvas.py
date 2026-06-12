"""CanvasMiddleware — injects canvas tools and report-building guidance.

Downstream users can opt into the canvas report-building feature by passing
`CanvasMiddleware()` to `create_deep_agent(middleware=[...])`. The middleware
appends canvas-specific instructions to the system prompt and extends the
tool list with canvas tools at each model call.
"""

from collections.abc import Awaitable, Callable
from typing import Any


def agent_uses_canvas_middleware(agent: Any) -> bool:
    """Best-effort check for a CanvasMiddleware instance on an agent.

    `CanvasMiddleware` uses `wrap_model_call`, which doesn't add a dedicated
    graph node — so this probes likely attribute paths (`middleware`,
    `_middleware`, `builder.middleware`) looking for an instance. Returns
    False if the middleware list can't be located, which causes the caller
    to fall back to the default (canvas tab off).
    """
    candidates = []
    for attr in ("middleware", "_middleware"):
        v = getattr(agent, attr, None)
        if v is not None:
            candidates.append(v)
    builder = getattr(agent, "builder", None)
    if builder is not None:
        for attr in ("middleware", "_middleware"):
            v = getattr(builder, attr, None)
            if v is not None:
                candidates.append(v)

    for candidate in candidates:
        try:
            iterable = candidate if hasattr(candidate, "__iter__") else [candidate]
            for item in iterable:
                if isinstance(item, CanvasMiddleware):
                    return True
        except TypeError:
            continue
    return False

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
)

from langstage.tools import (
    add_canvas_section,
    add_to_canvas,
    remove_canvas_item,
    reorder_canvas,
    update_canvas_item,
)


CANVAS_PROMPT = """## Canvas (Report Builder)

The canvas is a persistent report surface at `.canvas/canvas.md`. Treat it as a
living document you co-author with the user, not a scratchpad for throwaway
outputs. A finished canvas should read like a short report: sections, narrative,
figures with explanations, and a conclusion.

### Canvas tools
- `add_to_canvas(content, title=None, item_id=None)` — append an item. Pass a
  DataFrame, matplotlib/Plotly figure, PIL image, markdown string, or HTML.
  Provide `item_id` when you expect to refine the item later.
- `update_canvas_item(item_id, content, title=None)` — replace an existing
  item in-place. Use this instead of appending a new item when iterating.
- `add_canvas_section(title, level=1, item_id=None)` — structural heading.
  Use to group related items (Overview, Methodology, Findings, etc.).
- `reorder_canvas(item_ids)` — rewrite the canvas in a new order. Pass the
  full list of IDs in the order you want them to appear.
- `remove_canvas_item(item_id)` — delete an item entirely.

### How to build a report

1. **Open with a section + overview.** Before any charts, call
   `add_canvas_section("Overview")` and an `add_to_canvas(markdown_text)`
   that states the question, the approach, and what to expect.
2. **Interleave narrative and figures.** Every chart/table should be preceded
   by a short markdown item explaining what the figure shows and why it
   matters. Don't dump figures back-to-back without prose.
3. **Use sections to group.** Break the report into 2–5 sections
   (e.g., Data, Analysis, Findings, Next Steps). Add a section header
   before the items that belong to it.
4. **Refine, don't duplicate.** When the user says "make the chart blue" or
   "tighten the summary," call `update_canvas_item(id, ...)` with the same
   `item_id` — never add a second version.
5. **Close with a conclusion.** End with a `## Conclusion` section and a
   markdown item summarizing findings and recommended next steps.
6. **Reorder when structure changes.** If the user says "move the summary
   to the top" or the narrative shifts, call `reorder_canvas(...)` with the
   new order rather than deleting and re-adding items.

### Stable IDs

Always provide meaningful `item_id` values (`summary`, `revenue_chart`,
`conclusion`) when you create an item you may refine. Auto-generated IDs
are opaque and make refinement harder.
"""


class CanvasMiddleware(AgentMiddleware):
    """Injects canvas tools and report-building guidance into the agent.

    Append `CanvasMiddleware()` to `create_deep_agent(middleware=[...])` to
    enable the canvas report feature. The middleware extends the agent's
    tool list with the canvas toolkit and appends canvas instructions to
    the system prompt on every model call.
    """

    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self.enabled = enabled
        self._canvas_tools: list[Any] = [
            add_to_canvas,
            update_canvas_item,
            remove_canvas_item,
            add_canvas_section,
            reorder_canvas,
        ]

    def _apply(self, request: ModelRequest) -> None:
        """Mutate the request in place: append canvas prompt + inject tools."""
        existing_prompt = request.system_prompt or ""
        if CANVAS_PROMPT not in existing_prompt:
            request.system_prompt = (
                f"{existing_prompt}\n\n{CANVAS_PROMPT}" if existing_prompt else CANVAS_PROMPT
            )

        existing_tools = list(request.tools or [])
        existing_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in existing_tools}
        for tool in self._canvas_tools:
            tool_name = getattr(tool, "name", getattr(tool, "__name__", ""))
            if tool_name not in existing_names:
                existing_tools.append(tool)
        request.tools = existing_tools

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> Any:
        if not self.enabled:
            return handler(request)
        self._apply(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[Any]],
    ) -> Any:
        if not self.enabled:
            return await handler(request)
        self._apply(request)
        return await handler(request)
