# Changelog

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
