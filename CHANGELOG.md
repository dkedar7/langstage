# Changelog

## 0.4.0 — 2026-06-02

Adopts the shared `langgraph-stream-parser` runtime and config layer.

### Changed
- Streaming + session plumbing now comes from `langgraph_stream_parser.adapters.SessionAdapter`. The in-tree `agent_loader`, `stream/event_serializer`, `stream/sse_adapter`, and `stream/session_manager` modules are **deleted** (superseded by `host.load_agent_spec`, `event_to_dict`, and `SessionAdapter`). Server wires one `SessionAdapter`; chat/session routes are thin shims over it; the file watcher pushes via `push_event`.
- `default_agent` builds on `demo.create_default_agent` (keeps cowork's notebook/canvas tools, `CanvasMiddleware`, and the bash interrupt).
- `AppConfig` now subclasses `HostConfig`: resolves through `defaults < deepagents.toml < DEEPAGENT_* env < overrides`, gaining **`deepagents.toml` support**. The config field `workspace` was renamed to `workspace_root` to match `HostConfig` — the public `CoworkApp(workspace=...)` kwarg is unchanged.
- Pin `langgraph-stream-parser>=0.2,<0.3`.

### Added
- `cowork-dash config` command — prints the resolved config with each value's source + env var / TOML key.

## 0.3.7 — 2026-04-18

### Added

- `CanvasMiddleware` — opt-in LangChain agent middleware that injects canvas tools and report-building guidance into any `create_deep_agent` call. Downstream users enable the canvas feature via `middleware=[CanvasMiddleware()]` without touching tool lists or system prompts.
- Canvas **section** item type (`add_canvas_section(title, level=1)`) — structural headings that render as `h1`–`h6` in the UI for report organization.
- `reorder_canvas(item_ids)` tool — rewrite canvas items in a new order.
- **Provenance**: canvas items now record `source_cell` and `execution_count` from the most recent notebook cell execution; surfaced as a "cell N" pill in the UI.
- **Tab visibility controls**: `show_canvas` / `show_files` on `CoworkApp`, `--show-canvas/--no-show-canvas` and `--show-files/--no-show-files` CLI flags, `DEEPAGENT_SHOW_CANVAS` / `DEEPAGENT_SHOW_FILES` env vars. Canvas tab defaults to auto-detect (on when `CanvasMiddleware` is attached, off otherwise); files tab defaults to on.
- `agent_uses_canvas_middleware(agent)` helper for downstream detection.
- Integration tests for the SSE streaming pipe (`tests/test_sse_adapter.py`) using a conformant fake agent — catches API drift in `langgraph-stream-parser` before it hangs the UI.
- API contract guards for `prepare_agent_input` and `create_resume_input` signatures.
- `demo/plain_agent.py` — minimal example of a custom agent without canvas middleware.

### Fixed

- Agent streaming hung silently when `prepare_agent_input()` was called with an unsupported `context_parts=` kwarg. Context is now prepended to the user message directly.
- `CanvasMiddleware.awrap_model_call` async variant — the sync-only `wrap_model_call` crashed with `NotImplementedError` under `agent.astream()`.
- `run_agent_stream` / `run_interrupt_response` now wrap the full function body in a try/except and emit `error` events for uncaught exceptions instead of dying silently in the background task.

### Changed

- Canvas tools are no longer baked into `AGENT_TOOLS` — they are injected exclusively via `CanvasMiddleware` to avoid double-registration.
- Default-agent system prompt no longer embeds canvas guidance; the prompt is appended at call time by `CanvasMiddleware`.

### Removed

- Dead `NotebookState._canvas_items` list and `get_canvas_items` / `clear_canvas_items` methods (never populated; replaced by file-backed canvas state).
- Dead `create_session_agent` factory that imported a non-existent `cowork_dash.backends` module.

## 0.3.6 — 2026-04-07

### Changed

- Replace WebSocket streaming with Server-Sent Events (SSE) for reliable operation behind reverse proxies and with `host=0.0.0.0`
- Frontend `useAgentStream` hook now uses `EventSource` + `fetch()` instead of `WebSocket`
- Session manager uses async event queues instead of WebSocket references
- Authentication middleware simplified (no more WebSocket-specific handling)

### Added

- `GET /api/stream` SSE endpoint with 30s keepalive and `X-Accel-Buffering: no` header for nginx compatibility
- `POST /api/chat` endpoint to send user messages
- `POST /api/chat/interrupt` endpoint to respond to HITL interrupts
- `POST /api/chat/cancel` endpoint to cancel running streams

### Removed

- `websockets` dependency (no longer needed)
- WebSocket endpoint (`/ws/chat`) replaced by SSE + REST

## 0.3.5 — 2026-02-19

### Added

- Custom CSS theming support via `--custom-css` CLI flag, `custom_css` Python API param, or `DEEPAGENT_CUSTOM_CSS` env var
- `/api/custom-css` endpoint serves theme file at runtime; frontend injects it dynamically
- `POST /api/session/{id}/inject` REST endpoint for fire-and-forget message injection from external apps
- `GET /api/sessions` endpoint to list all sessions with connection status
- `inject.py` convenience script for programmatic message injection
- Theme reference documentation (`docs/CUSTOM_THEME_REFERENCE.md`)

### Fixed

- Dark mode text color in canvas markdown content (`.markdown-content` missing base `color`)
- Interrupt dialog diagnostics for empty `action_requests`

## 0.3.4 — 2026-02-10

### Added

- `/create-workflow` slash command with two-step text input flow for creating workflows from scratch
- `create_workflow_prompt` configurable via Python API, CLI (`--create-workflow-prompt`), and env var (`DEEPAGENT_CREATE_WORKFLOW_PROMPT`)
- README documentation for slash commands, authentication, and workflow prompt configuration

### Changed

- Refactored slash command `hasArg` boolean to `secondStep` union type (`"none"` | `"file-picker"` | `"text"`) for extensibility
- Generalized `tryExecute` and `handleInputChange` to work with any command definition

## 0.3.3 — 2026-02-10

### Added

- Print/export conversation via browser Print dialog with print-optimized CSS
- `/save-workflow` slash command to capture conversations as reusable workflow markdown files
- `/run-workflow` slash command with autocomplete dropdown listing `.md` files from `./workflows/`
- Configurable workflow prompts via Python API (`save_workflow_prompt`, `run_workflow_prompt`), CLI flags, and env vars

## 0.3.2 — 2026-02-10

### Added

- Optional HTTP Basic Auth (Dash-style) — enable with `DEEPAGENT_AUTH_PASSWORD` env var, `--auth-password` CLI flag, or `auth_password` Python kwarg
- Username defaults to `admin` when only password is set; customize via `DEEPAGENT_AUTH_USERNAME`
- Protects all HTTP and WebSocket endpoints with timing-safe credential comparison

## 0.3.1 — 2026-02-09

### Added

- Session persistence across page refresh (messages, todos, token usage saved to localStorage)
- HITL interrupt tests for single and multi-interrupt serialization

### Fixed

- Fix HITL interrupt dialog showing blank (no tool name or args displayed)
- Fix interrupt approval sending empty decisions (`{"decisions": []}`)
- Fix `Decision` type for edit case to use `edited_action` matching backend format
- Fix display_inline crash and blank screen rendering (records vs data format mismatch)
- Add error boundary around inline display to prevent white-screen crashes
- Rename `display_inline` parameter from `content` to `file_path` to clarify filepath-only usage

## 0.3.0 — 2026-02-08

- Fix wheel build to include frontend static assets
- Inline HTML and Plotly chart rendering via sandboxed iframes
- Icon customization, agent name inference, auto theme, favicon
- Streaming improvements: cancel support, tool previews, scroll anchoring, message timing
- Token usage chart with per-turn breakdown
- File browser, canvas, todo panel, and dark mode style polish

## 0.2.0 — 2026-02-06

Initial release of `cowork-dash`.

### Features

- Chat interface with real-time token streaming via WebSocket
- Tool call visualization with inline display of arguments, results, duration, and status
- Rich inline content rendering: HTML, Plotly charts, images, DataFrames, PDFs, JSON
- Canvas panel for persistent visualizations (Plotly, matplotlib, Mermaid diagrams, DataFrames, Markdown, images)
- File browser with syntax-highlighted viewer and live file change detection
- Task tracking sidebar with progress bar, synced with agent `write_todos` calls
- Human-in-the-loop interrupt dialog for reviewing and approving agent actions
- Token usage counter with per-turn breakdown chart
- Light, dark, and system-auto theming
- Customizable title, subtitle, welcome message, agent name, and icon
- CLI (`cowork-dash run`) and Python API (`CoworkApp`, `run_app`)
- Configuration via Python args, CLI flags, or environment variables
