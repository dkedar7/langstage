# Changelog

## 0.13.22 — 2026-07-14

### Fixed
- **`langstage run --agent <spec>` reports a bad spec as a clean one-line error, not a raw
  traceback (gh #90).** `run` only caught `RuntimeError` around building the app (the
  missing-`deepagents`-extra case, #46), so every *other* common `--agent` mistake — a path
  that doesn't exist (`FileNotFoundError`), a file with no such attribute (`AttributeError`),
  or a malformed spec missing the required `:attr` suffix (`ValueError`) — escaped as a
  multi-frame Python traceback for what is usually a one-character typo. That contradicted the
  clean-error intent of #46 and was inconsistent with the sibling `check`, which already
  reports the identical failures as `[fail] failed to load: …`. `run` now catches the loader's
  exception classes too (`ValueError` / `FileNotFoundError` / `AttributeError` / `ImportError`,
  alongside `RuntimeError`) and surfaces them as `Error: …` (a `click.ClickException`),
  matching `check`'s error UX. Exit code stays `1`.

## 0.13.21 — 2026-07-14

### Added
- **A startup warning when binding a non-loopback host with no authentication (gh #89).**
  `langstage run --host 0.0.0.0` (the natural choice on a remote box or in a container) with
  no `--auth-password` exposes the **entire** REST surface — chat, the workspace file browser
  (read/write/delete/upload), and the task board — unauthenticated to anyone who can reach the
  port, and nothing signaled it: the startup banner was identical to a safe `localhost` bind.
  `run()` now prints a clear warning to stderr when the resolved host is non-loopback
  (`0.0.0.0`, `::`, or a concrete address — anything but `localhost` / `127.0.0.0/8` / `::1`)
  **and** no auth password is set, naming the host and pointing at the fix (`--auth-password`
  / `LANGSTAGE_AUTH_PASSWORD`, or a `localhost` bind behind an SSH tunnel). It **warns but
  still starts** — the least-surprising behavior, and auth is a one-flag fix. Auth itself was
  already correct (it returns `401`/`200` and keeps `/api/health` exempt when a password is
  set); the gap was purely that the dangerous default was silent. README documents it.

## 0.13.20 — 2026-07-14

### Fixed
- **`langstage init` now emits the FULL workflow-prompt defaults, so uncommenting one is
  always a valid, exact value (gh #88).** The scaffold truncated the three long defaults —
  `workflow.save_prompt`, `workflow.run_prompt`, `workflow.create_prompt` — to ~72 characters
  plus a literal `...`, then quoted the fragment. The generated file's own header invites
  "uncomment and edit only what you need" and the README promises a `config -> init -> config`
  round-trip is **exact**, but uncommenting one of these lines silently wrote a **corrupted**
  prompt: the trailing `...` became part of the value and the real instruction (e.g. `Execute
  each step as described in the workflow file.`) was gone — a data bug, not just cosmetic
  display truncation, which `config --json` (which does not truncate) faithfully resolved.
  `_render_value()` now emits every default in full as a valid single-line TOML basic string
  (TOML imposes no length limit; quotes/backslashes/newlines are already escaped), so the
  advertised round-trip is exact for all fields and no line is ever a
  syntactically-valid-but-semantically-broken preview. The `init` tests assert the three
  prompts round-trip to their built-in defaults and that no `...` truncation leaks in.

## 0.13.19 — 2026-07-13

### Fixed
- **`app.run()` now just works in a Jupyter notebook — no extra code (gh #87).** The documented
  Python API (`CoworkApp(...).run()` / `run_app(...)`) was **unusable from a notebook**: `run()`
  calls `uvicorn.run()`, which wraps `asyncio.run()`, and a Jupyter kernel already has a running
  event loop — so it died with `RuntimeError: Cannot run the event loop while another loop is
  running`, *after* printing the `LangStage: http://…` banner, so it looked like it was starting.
  Notebook users are squarely in the audience (the family ships **langstage-jupyter**), yet the
  README's "From Python" example was exactly what failed there; the only way out was a manual
  `threading.Thread(...)` wrapper. `run()` now detects an already-running event loop and serves
  on a **background thread**, returning a `BackgroundServer` handle immediately — the cell doesn't
  block, the kernel stays interactive, and `handle.stop()` shuts it down. Scripts and the CLI are
  unchanged (no running loop → `run()` blocks exactly as before). A failed bind (port in use) now
  raises a clean, actionable error instead of silently killing the server thread — and no longer
  risks taking the whole kernel down via uvicorn's `sys.exit(STARTUP_FAILURE)`.

## 0.13.18 — 2026-07-12

### Fixed
- **`/api/files/delete` now accepts `path` as a query parameter and a `DELETE` verb, so the
  documented `delete?path=P` round-trip actually works (gh #81).** The README advertises delete
  as symmetric with `read` / `download` / `upload` (all query-param `path`) and promises
  `upload?path=P` round-trips with `delete?path=P` — but delete only accepted `POST` + a JSON
  body `{"path": ...}`, so `DELETE …?path=P` returned 405 and `POST …?path=P` returned 422, and a
  client written straight from the docs silently left files behind. `delete` now takes `path` as
  a query parameter via **either `POST` or `DELETE`**, matching the other files routes; the
  `POST` + JSON body form still works (the file-browser UI uses it). `/openapi.json` reflects
  both methods + the `path` parameter.

## 0.13.17 — 2026-07-12

### Fixed
- **Schedules now show times in UTC, so the "9am" presets mean what they say (gh #83).** The
  scheduler interprets cron in UTC (a `0 9 * * *` schedule fires at 09:00 UTC, stable across host
  timezones and DST), but the Schedules tab rendered `next_run` / `last_run` in the browser's
  **local** timezone — so on a non-UTC host the "Daily 9am" preset displayed a mismatched time
  (e.g. `5:00 AM`), and the shown next-run contradicted the entered cron. The tab now renders
  those times in **UTC** with a `UTC` label, the hour-specific presets are labeled `9am UTC`, and
  the cron field notes "times are UTC". Interpretation is unchanged (still UTC — the right default
  for an unattended, possibly-containerized scheduler); `GET /api/cron` already returned explicit
  `…+00:00` timestamps. README documents the UTC behavior.

## 0.13.16 — 2026-07-12

### Fixed
- **Agent-created schedules actually work now — `schedule_run` no longer fails with "no running
  event loop" and leaves a zombie schedule (gh #82).** `schedule_run` is a **sync** tool, so
  LangGraph runs it in a **worker thread**; on a started server `add_job()` called
  `asyncio.create_task()` from that thread, which raised `RuntimeError: no running event loop`.
  The tool reported failure — but the job was **already inserted** and never rolled back, so it
  showed up in `GET /api/cron` and the Schedules tab with **no run-loop started** and never
  fired (a zombie). Since the built-in default agent carries `LANGSTAGE_TOOLS`, this was the
  documented path, not an edge case. The scheduler now **captures its event loop at `start()`**
  and starts a job's run-loop **thread-safely** (`call_soon_threadsafe` when called off the
  loop), so `schedule_run` works from the tool thread; and `add_job()` **rolls back** the insert
  if the run-loop can't start, so a failure never leaves a zombie. The REST/UI path was
  unaffected (its handler already runs on the loop).

## 0.13.15 — 2026-07-11

### Added
- **`langstage init` — scaffold a commented `langstage.toml`, the write side of the config
  surface (gh #77).** `config` / `--show-config` already read every resolved value and the exact
  env var **and** `langstage.toml` key that sets it, but there was no *write* side: to create a
  config file you had to reverse-map that flat output into TOML sections yourself (`ui.title` →
  `[ui] title = …`) — the exact "remember the key names" burden the config surface exists to
  remove. `langstage init` now writes a starter file with **every** option present but commented
  out, grouped into its TOML section and annotated with its env-var equivalent. It's generated
  from the *same* field → (env, toml-key, default) metadata `config` reads, so the two stay in
  lockstep by construction and a `config → init → config` round-trip is exact. `langstage init`
  writes `./langstage.toml` (refuses if it exists), `--force` overwrites, and `--path` targets a
  directory or file.

## 0.13.14 — 2026-07-11

### Fixed
- **Scheduled runs no longer overlap their own in-flight run — unattended schedules that hit a
  human-in-the-loop review gate stop piling up stuck tasks (gh #78).** A cron fire enqueues onto
  the same task board as a manual delegation, so if the scheduled agent tripped a review gate its
  task parked at `review_needed` waiting for a human who — for an *unattended* schedule — never
  came, and **every subsequent fire added another stuck task**. This wasn't an edge case: the
  built-in default agent gates `bash` (`interrupt_on=dict(bash=True)`), so scheduling it silently
  stalled at review whenever it used bash. The scheduler now applies cron-style **overlap
  protection**: an automatic fire is **skipped** while the schedule's previous run is still
  unresolved (`queued` / `ongoing` / `review_needed`), and the schedule row surfaces it
  (`last_status = "skipped: previous run still review_needed"`). `GET /api/cron` now also returns
  `last_task_id` and `last_run_state` per schedule so a client can flag a run awaiting review.
  Manual **Run now** (`POST /api/cron/{id}/run`) is an explicit action and still fires regardless.

## 0.13.13 — 2026-07-10

### Changed
- **`/api/files/upload` now treats `path` as the full destination path, symmetric with every
  other files route (gh #75).** `upload` alone interpreted `path` as a *parent directory* and
  appended the multipart filename, while `read`/`preview`/`download`/`delete`/`mkdir` treat
  `path` as the full target. So a `path`-symmetric client doing `POST upload?path=P` then
  `GET read?path=P` didn't get its file back — the upload silently landed at
  `P/<multipart-filename>` (creating a stray directory `P`), returned `200`, and the read of
  `P` then failed. Now `upload?path=P` stores the file **at** `P` and round-trips. The
  directory-drop mode is still available **explicitly** — end `path` with `/`, or point it at
  an existing directory, and the multipart filename is appended (this is what the file-browser
  UI uses, so it's unchanged). The OpenAPI `description` and the README REST section document
  the contract.

## 0.13.12 — 2026-07-09

### Added
- **`langstage check --json` and `langstage config --json` — machine-readable diagnostics
  so the advertised CI readiness gate is actually gateable (gh #73).** `check` produced 6+
  distinct signals that collapsed into a coarse exit code (only a load failure or a `--live`
  runtime error set exit 1; every static finding was a warning that left exit 0), so CI could
  gate on almost nothing the command discovered. `check --json` now emits a stable object —
  `{spec, loads, agent_name, checks:{checkpointer, canvas, write_todos, async_tasks,
  schedules}, live, ok}` — preserving the exit-code contract, so a pipeline can gate on any
  individual check, e.g. `langstage check -a app.py:graph --json | jq -e '.loads and
  .checks.canvas.ok'`. `config --json` emits each field's value + source (and the TOML files
  read) so a deploy step can assert how a container resolved its env / `langstage.toml`. The
  human default output is unchanged.

## 0.13.11 — 2026-07-08

### Added
- **The built-in OpenAPI/Swagger docs are now advertised as the canonical REST reference
  (gh #71).** Because the backend is FastAPI, a complete, always-in-sync schema is already
  served at `/openapi.json`, `/docs` (Swagger UI), and `/redoc` — but it was mentioned
  nowhere, so a client author had to reverse-engineer request shapes. A new README **REST
  API** section points at all three, and `langstage run` prints the docs URL on startup.

### Fixed
- **The OpenAPI schema now reports the real package version (gh #71).** The FastAPI app was
  constructed with a hardcoded `version="2.0.0"`; it now uses the installed `langstage`
  version, with a titled/described schema, so `/openapi.json` and `/docs` are accurate.

## 0.13.10 — 2026-07-07

### Fixed
- **Readiness (`/api/health?ready=1`) now checks the agent is *runnable*, not just
  non-`None` (gh #69).** The `agent` check was `agent is not None` — vacuous (a failed
  load aborts startup, so a serving process always has a non-`None` agent) and blind to
  the common BYO slip of exporting an **uncompiled `StateGraph`**: it loaded, so readiness
  said `200 ok`, yet every turn died with `'StateGraph' object has no attribute
  'aget_state'`. A k8s / ALB probe would mark the pod Ready and route traffic to a server
  that fails every turn. Readiness now gates on runnability (`callable(agent.astream)`) —
  the same check `langstage check` uses (gh #39) — and returns `503 not_runnable` otherwise.

## 0.13.9 — 2026-07-06

### Added
- **A real health/readiness endpoint: `GET /api/health` (gh #67).** `/health` (and every
  non-`/api/*` path) returned the SPA `index.html` — HTTP 200 regardless of backend state,
  and 401 once auth was enabled — so a reverse proxy / k8s / uptime probe had no usable
  liveness signal. The new endpoint is dedicated JSON under `/api/*` (so it can't collide
  with the SPA catch-all) and **exempt from Basic Auth** (a probe can't carry credentials):
  - liveness (default) → `200 {"status": "ok", "version": …}` — the process is up;
  - readiness (`?ready=1`) → `200` only if the agent object loaded **and** the task store
    is reachable, else `503 {"status": "degraded", "checks": {…}}` — reflecting real
    backend state instead of the always-served static shell.

## 0.13.8 — 2026-07-05

### Fixed
- **A relative `--workspace` no longer doubles the agent's working directory (gh #66).**
  With a relative workspace (e.g. the README Quickstart's `--workspace ./workspace`),
  the agent was told — and every bring-your-own file/canvas tool read — a doubled
  `ws/ws` working directory, while the file browser and durable `.langstage` state lived
  at `ws`: the exact split-brain the 0.12.2 note claimed fixed. Root cause was in core
  (`workspace_root()` re-resolving a relative root after `run()` chdir'd into the
  workspace); fixed in **langstage-core 1.0.9**, now the minimum pin. Absolute and
  default workspaces were unaffected.

### Changed
- **Migrated the deprecated `@app.on_event` startup/shutdown handlers to a FastAPI
  `lifespan` context manager (gh #61).** Same behavior (task store + durable checkpointer
  upgrade + scheduler/runner lifecycle); silences the FastAPI deprecation. Thanks
  @AshleyAHuang.

### Internal
- Split semicolon-joined statements in `tasks/sqlite_store.py` for the ruff E702 lint
  (gh #65). Thanks @AshleyAHuang.

## 0.13.7 — 2026-07-04

### Fixed
- **A bare graph's default name "LangGraph" no longer becomes the app title (dogfood
  F3).** A compiled `StateGraph` gets `.name == "LangGraph"` by default, which the app
  used as its header title/agent name for a BYO agent — a confusing brand. Generic
  names (`LangGraph`, `agent`, `graph`) are now ignored, so the `LangStage` default is
  kept; a real agent `.name` still becomes the title.

### Docs
- Refreshed the README header to a `langstage` SVG banner (was a `cover.png` labelled
  "Cowork Dash", the old name).

## 0.13.6 — 2026-07-04

### Fixed
- **A bring-your-own agent's files now land in the workspace, visible in the file
  browser (ADR 0006, dogfood F7).** An agent that writes `Path("out.txt").write_text(…)`
  (a raw cwd-relative path) used to write to the server's *launch* directory — invisible
  in the file browser (rooted at the workspace) — so the agent could say "saved to the
  workspace" while the browser showed it empty. `run()` now `chdir`s to the resolved
  workspace after the agent spec is resolved and the server is wired (both use the
  absolute path, so they're unaffected), matching the cli. Embedding `CoworkApp`
  programmatically has no cwd side effect (the chdir is in `run()`, not `__init__`).

## 0.13.5 — 2026-07-04

### Fixed
- **The `[Working directory: …]` context the chat prepends to each message now
  reports the real filesystem workspace, not the frontend's virtual path (dogfood).**
  It used the file browser's current folder verbatim, so an agent at the browser root
  was told `[Working directory: /]` — misleading, and actively wrong for a
  bring-your-own agent that resolves paths against it. It now reports
  `core.workspace_root()` with the browsed subfolder applied (e.g. `<workspace>/notes`),
  so the agent hears where it actually operates.

## 0.13.4 — 2026-07-03

### Changed
- **The workspace is now one source of truth, not a hand-synced mirror (ADR 0005).**
  `CoworkApp.__init__` used to reconcile the #44 split-brain imperatively — resolving
  the workspace, then assigning `config.WORKSPACE_ROOT` and two env vars so the agent's
  bash/file/canvas tools agreed with the file browser. It now calls
  `core.apply_workspace(self.config.workspace_root)` once, and `config.WORKSPACE_ROOT`
  is a **live view** of `core.workspace_root()` (via module `__getattr__`) — so the
  file browser and the agent tools read the same value by construction, with no mirror
  to drift. Behavior is unchanged (the full #44 regression suite passes); the split-brain
  is now structurally impossible. Requires `langstage-core>=1.0.7`.

## 0.13.3 — 2026-07-03

### Added
- **`langstage check --live`: run one real turn as a true readiness gate (ADR 0004).**
  The static `check` proves the agent is a runnable graph (gh #39) but not that it
  can actually complete a turn — a bad key, a tool that fails at runtime, or a
  broken state schema all pass static and die at first chat. `--live` runs one real
  turn through the shared `langstage-core` preflight (`core.verify()`) and fails the
  check (exit 1) if it errors. Default `check` is unchanged — still fast, static,
  and keyless — so nothing breaks; `--live` is opt-in for when you have a working
  model and want the real gate. Requires `langstage-core>=1.0.6`.

## 0.13.2 — 2026-07-02

### Fixed
- **Canvas auto-detection never fired for a bring-your-own agent (gh #48).**
  `CanvasMiddleware` does its work in `wrap_model_call`, which langchain/deepagents
  fuse into the model node — leaving no `.middleware` attribute or graph node — so an
  agent that attached `CanvasMiddleware()` via `create_deep_agent(middleware=[...])`
  was undetectable: the Canvas tab never auto-appeared and `langstage check` reported
  "no CanvasMiddleware". `CanvasMiddleware` now defines a no-op `before_agent` hook, so
  langchain compiles a named `CanvasMiddleware.before_agent` graph node, and
  `agent_uses_canvas_middleware` detects it by node name (covering `CanvasMiddleware`
  and any subclass) in addition to the stashed-attribute path the bundled default uses.

## 0.13.1 — 2026-07-02

### Fixed
- **`langstage run` crashed on a clean `pip install langstage` (gh #46).** The
  built-in default agent was built at module-import time, so on an install without
  the `deepagents` extra it dumped a traceback — and the remediation named the wrong
  package (`langstage-core[demo]` instead of `langstage[deepagents]`). The import is
  now defensive (falls back to `agent = None`), and `create_default_agent` raises a
  clean, correctly-packaged error that `langstage run` shows as a one-line message
  (`pip install "langstage[deepagents]"`, or use `--demo`, or pass `--agent`) instead
  of a traceback.

## 0.13.0 — 2026-07-02

### Changed
- **AG-UI is now the chat/board's only streaming path (ADR 0003).** The
  `SessionAdapter` streams every turn through `langstage-core`'s in-process AG-UI
  adapter, emitting the **same** SSE frames the React frontend already consumes —
  so the UI is unchanged. Removed the `LANGSTAGE_AGUI` opt-in env and the
  `AppConfig.agui` toggle (they gated a path that no longer exists); the adapter is
  constructed without `agui=`/`stream_mode=`.
- **Repointed to `langstage-core` 1.0** (the rename of `langgraph-stream-parser`;
  ADR 0003). The AG-UI runtime (`ag-ui-langgraph[fastapi]`, via core's `[agui]`
  extra) moved into **base dependencies** — since AG-UI is the only path, a bare
  `pip install langstage` must run a turn. (`fastapi` + `uvicorn` were already base
  deps.) The `[agui]` extra is now a redundant no-op alias.

### Removed
- The `experimental.agui` TOML key / `LANGSTAGE_AGUI` env / `AppConfig.agui` field.
  The frontend's content-delta accumulation was already AG-UI-native, so chat
  rendering is unchanged.

## 0.11.8 — 2026-06-27

### Fixed
- **`POST /api/cron` (and the `schedule_run` agent tool) returned `next_run:
  null` on a running server.** `add_job` computed `next_run` synchronously only
  when the scheduler hadn't started yet; on a live server it deferred to the run
  loop, which hadn't fired when the create response / tool message was
  serialized — so the two places a user looks right after creating a schedule
  showed no next fire time (a follow-up `GET` already had it, and the agent
  always said "Next run: pending"). `next_run` is now computed synchronously in
  `add_job` regardless of started state; the run loop keeps refreshing it.
  (Found by the dogfood routine, gh #37.)

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
