# Changelog

## 0.11.7 — 2026-06-26

### Fixed
- **`--show-config` reported `auth_username` as empty when the effective default
  is `admin`.** The `admin` default lived only in the auth middleware
  (`auth_username or "admin"`), not the config layer that `--show-config`
  renders — so a user enabling auth and consulting the documented config
  inspector to find their login username saw a blank, while the server enforced
  `admin`. The default now lives in `config.py` (`auth_username: str = "admin"`),
  so `--show-config`, `--help`, the README table, and the runtime all agree.
  (Auth stays inert unless a password is set, so this has no security effect.)
  (Found by the dogfood routine, gh #35.)

## 0.11.6 — 2026-06-22

### Fixed
- **`/api/files/*` returned 500 on a path that escapes the workspace.** The
  workspace boundary held (no traversal — `_resolve_path` raised
  `ValueError("Path escapes workspace: …")`), but on `read`, `preview`, and
  `tree` that error propagated uncaught into a generic 500, while the sibling
  routes (`download`/`mkdir`/`delete`) already mapped it to a clean 400. Those
  three now return **400** too, matching the rest of the file API. (Found by the
  dogfood routine.)

## 0.11.5 — 2026-06-22

### Fixed
- **Workspace split-brain: the agent's `bash`/file tools ignored
  `LANGSTAGE_WORKSPACE_ROOT`.** 0.11.2 fixed `default_agent.py` to honor the
  canonical var, but `config.py`'s module-level `WORKSPACE_ROOT` / `VIRTUAL_FS`
  still read **only** the legacy `DEEPAGENT_*` names — and `tools.py` uses
  `config.WORKSPACE_ROOT` as the `bash` cwd. So with only `LANGSTAGE_WORKSPACE_ROOT`
  set, the file browser used the canonical workspace while `bash`/file tools ran in
  cwd (the 0.11.2 entry over-claimed the fix). `config.py` is now canonical-first
  (legacy fallback + warning) for both vars, and is the **single source** —
  `default_agent.py` imports `config.WORKSPACE_ROOT` instead of resolving its own
  copy, so the agent and tools can never disagree again. (gh #-dogfood)

## 0.11.4 — 2026-06-21

### Fixed
- **Unknown `/api/*` paths returned 200 + the SPA HTML shell instead of 404.** The
  SPA catch-all route swallowed the whole `/api` (and `/ws`) namespace, so a typo'd
  or missing API path silently returned an HTML page to programmatic clients. The
  catch-all now raises a JSON 404 for `/api/*` and `/ws/*`; other paths still serve
  the SPA. (gh #-dogfood)
- **CLI help / `config` text** still referenced the pre-rename `deepagents.toml`;
  now `langstage.toml`.
- **Default Title** was documented (and the bundled `index.html` `<title>`) as
  `Cowork Dash`; corrected to `LangStage`.

### Added
- **`langstage --version`** flag (it only had `--show-config`/`--help`).

### Docs
- Documented the schedules REST surface (`GET/POST/DELETE /api/cron`,
  `POST /api/cron/{id}/run`) — the path is `/api/cron`, not `/api/schedules`.
- Bumped the `langgraph-stream-parser` floor to `>=0.6.7` (tool_end name + dict
  messages).

## 0.11.3 — 2026-06-21

### Fixed
- **README advertised a `/ws/chat` WebSocket transport that doesn't exist** — the
  Architecture diagram and Features bullet promised WebSocket; connecting to
  `/ws/chat` returns **403** (no such route). The real chat transport is
  Server-Sent Events: `GET /api/stream?session_id=…` + `POST /api/chat`. Corrected
  the diagram, the Features bullet, and the Stack line. (gh #-dogfood)
- Bumped the `langgraph-stream-parser` floor to `>=0.6.6` (base + `[agui]`) so
  dict-form-message agents (`{"role":"assistant","content":…}`) render in chat.

## 0.11.2 — 2026-06-20

### Fixed
- **Custom non-streaming agents replied with nothing in chat (gh #-dogfood).** A
  `CompiledGraph` whose node returns a finished `AIMessage` (rule-based / router /
  retrieval agents, or any LLM call outside a token-streaming node) rendered an
  empty assistant turn. Root cause was in the shared core; bumped
  `langgraph-stream-parser` to `>=0.6.4`, which emits such content as a fallback.
- **Canonical `LANGSTAGE_WORKSPACE_ROOT` was ignored** when computing the default
  agent's workspace — `default_agent.py` read only the deprecated
  `DEEPAGENT_WORKSPACE_ROOT`. It now reads the canonical name first and warns on
  the legacy one.

## 0.11.1 — 2026-06-16

### Fixed
- **Declare `langchain` as a dependency.** `langstage.middleware` (canvas) imports
  `langchain.agents.middleware` and is loaded on hot paths (`app`, the `check` CLI
  command, the default agent), but `langchain` wasn't declared — it only arrived
  transitively via the `[deepagents]` extra. A clean `pip install langstage` therefore
  failed with `ModuleNotFoundError: No module named 'langchain'` on `langstage check`
  / `langstage run`. Now a hard dependency. (Found in production by the daily QA routine.)

### CI
- Added a **minimal-install** job: installs with no extras (`pip install .`) and runs
  an import + CLI smoke — the lane that matches a real `pip install langstage`. The
  other jobs install `[deepagents]`, which masked the missing `langchain` by pulling
  it transitively. This guards against undeclared dependencies going forward.

## 0.11.0 — 2026-06-15

### Changed
- **Durable agent checkpointer.** The auto-attached checkpointer is now upgraded
  to a SQLite-backed `AsyncSqliteSaver` (`<workspace>/.langstage/checkpoints.db`)
  at server startup, so conversation + interrupt state and the task review gate
  **survive restarts**, and orphaned tasks resume from their last checkpoint
  instead of from scratch. Only checkpointers LangStage auto-attached are
  upgraded — a user-supplied checkpointer is never replaced. Falls back to
  in-memory if the SQLite saver can't initialize.
- Picks up `langgraph-stream-parser` 0.6.1 (sharper async-delegation tool
  descriptions, so the agent reaches for the task board for long/background work).

### Added
- Dependency: `langgraph-checkpoint-sqlite`.

## 0.10.0 — 2026-06-15

**Bring-your-own-agent integration** — make pointing `--agent` at any LangGraph graph "just work," and tell users exactly what lights up.

### Added
- **`langstage check --agent <spec>`** — a preflight doctor that loads your agent and reports which features will light up (checkpointer, Canvas, Plan/`write_todos`, async-delegation tools) and which need a convention or tool to unlock.
- **`LANGSTAGE_TOOLS`** — a one-import bundle (`from langstage import LANGSTAGE_TOOLS`) of the host's scheduling + async task-delegation tools, so a BYO agent unlocks agent self-delegation and agent-created schedules in one line.
- README **"Bring your own agent"** section documenting the integration contract.

### Changed
- **Checkpointer is now auto-attached** when a loaded agent has none (was: a console warning, then silently degraded). Conversation memory, human-in-the-loop interrupts, and the task review gate now work for any BYO graph out of the box; supply your own checkpointer for durability. (Matches the AG-UI bridge's behavior.)
- `__version__` now reads from package metadata (was a stale hardcoded constant).

## 0.9.1 — 2026-06-14

### Fixed
- Task board columns now expand to fill the panel width (they were fixed-width, leaving dead space when the right panel was widened).

### Docs
- README: documented the task board (delegate, live-tail detail pop-up, review gate, agent self-delegation, REST API).

## 0.9.0 — 2026-06-14

**Async task board** — delegate tasks to background copies of the agent, track them on a Kanban board, and interact with each run.

### Added
- **Task board** (new **Board** tab): delegate a task from the UI and watch it move `queued → ongoing → review_needed → done` (cancel/retry per card). Backed by the core 0.6 task engine (`TaskRunner` + a durable SQLite store) — non-blocking, single-process, no extra infra.
- **`/api/tasks`** REST: list/get/create/cancel/retry, plus `GET /{id}/events`, `POST /{id}/resume` (HITL approve/reject), `POST /{id}/message` (talk-back).
- **Task detail pop-up**: click a card to replay/live-tail its agent's full event stream, approve/reject a paused task, and send follow-ups.
- **Agent self-delegation**: the default agent now carries `start/check/list/update/cancel_async_task` tools, so it can spawn async sub-tasks (tracked on the board with parent links).
- The cron **scheduler** now enqueues onto the task board (durable) and its timezone handling is fixed (UTC throughout).

### Changed
- Parser pinned `>=0.6,<0.7` (+ `[agui]`); added `aiosqlite`.
- The **"Tasks"** tab (the todo/plan list) is renamed **"Plan"** (the async tasks live on the new Board tab).

### Notes
- Runs on the existing in-memory checkpointer; task rows + transcripts persist in SQLite (the board survives a restart). Durable mid-run checkpoint resume is a later pass.
- Single-process: run one server worker.

## 0.8.0 — 2026-06-14

Adopt AG-UI: widen the langgraph-stream-parser ceiling to <0.5 and add an [agui] extra so this surface's agent can be served over AG-UI via langstage-agui. Additive; no runtime changes.

## 0.7.0 — 2026-06-12

**cowork-dash is now `langstage`** — the web stage (and namesake) of the LangStage family ("every stage for your LangGraph agent"). The rename also clears the collision with Anthropic's Claude Cowork.

### Changed
- Distribution `cowork-dash` → **`langstage`**; module `cowork_dash` → **`langstage`**; command `cowork-dash` → **`langstage`** (the old command remains as a deprecated alias, and a deprecated alias package keeps `import cowork_dash` working with a warning).
- Canonical config vocabulary via langgraph-stream-parser 0.3: `LANGSTAGE_*` env vars, project `langstage.toml`, global `~/.langstage/config.toml`. The full legacy `DEEPAGENT_*` / `deepagents.toml` vocabulary still resolves as a deprecated fallback.
- Parser pinned `>=0.3,<0.4`.

## 0.6.0 — 2026-06-10

### Added
- **`cowork-dash run --demo`** — launches the full UI against a built-in keyless echo agent (`langgraph_stream_parser.demo.stub:graph`): no API key, no agent file. Mutually exclusive with `--agent`.
- **`-a`** short flag for `--agent`, matching `deepagent-code -a`.
- **`cowork-dash --show-config`** — group-level flag printing the resolved configuration (defaults < `deepagents.toml` < `DEEPAGENT_*` env), each value with its source. The `cowork-dash config` subcommand is unchanged.
- **Visual-regression gate** — pinned-Docker Playwright baselines (`frontend/e2e/visual.spec.ts`) run in CI; `frontend/e2e/docker-visual.sh` reproduces the exact CI render locally for baseline updates.
- README: *One agent, every surface* family table.

### Changed
- `langgraph>=1.0` is now a declared dependency (any real use already has it — it is the thing being hosted; declaring it makes `--demo` work on a bare install). `langgraph-stream-parser` pinned `>=0.2.2,<0.3`.

## 0.5.0 — 2026-06-02

### Added
- **Scheduled runs (cron).** Recurring agent runs on a standard 5-field cron expression, kept in memory for the life of the app process. A new **Schedules** tab lists active jobs and lets you add, run-now, and delete them; agents can manage schedules too via the `schedule_run`, `list_scheduled_runs`, and `cancel_scheduled_run` tools. REST API under `/api/cron`. New dependency: `croniter>=2.0`.
- Playwright end-to-end tests (`frontend/e2e/`) driving the built app against a model-free stub agent, plus the first CI workflow (pytest matrix + e2e).

### Fixed
- `import cowork_dash` no longer requires the optional `deepagents`/`langchain` dependency — the default agent and canvas middleware are imported lazily, so the base install works on its own.

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
