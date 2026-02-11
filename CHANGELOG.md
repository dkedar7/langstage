# Changelog

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
