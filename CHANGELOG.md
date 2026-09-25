# Changelog

## 0.13.40 — 2026-09-25

Adopts langstage-core 1.0.37.

### Fixed
- **`tool_start` and `content` carry the right `node` on multi-node graphs (gh #173).**
  With a tool call and the reply in different nodes, and complete messages instead of
  streamed tokens, `/api/stream` labeled `tool_start` with the run's last node and the
  reply with the node that made the tool call. The label came from the checkpoint,
  and the web app's `AsyncSqliteSaver` could write it after the snapshot was read.
  Core 1.0.37 takes each message's node from the step's own update instead. The web
  app had no workaround to remove. `tests/test_node_attribution_173.py` runs the
  issue's three-node graph under the server's SQLite saver and under a saver whose
  writes land late.

### Changed
- `langstage-core[agui]` floor raised to `>=1.0.37`.

## 0.13.39 — 2026-09-25

Makes several advertised behaviors true, or stops advertising them, and brings the
OpenAPI schema in line with the responses. Caps `deepagents` below 1.0.

### Fixed
- **`check` and `chat` use the configured agent (gh #143).** With no `--agent`, they
  now load the spec resolved from `LANGSTAGE_AGENT_SPEC` or `[agent] spec` in
  `langstage.toml`, the one `run` serves, instead of exiting with `Provide --agent`.
  A relative `file.py:attr` from a TOML file loads relative to that file, as in `run`.
  With nothing configured, the error now names the env var and the TOML key.
- **The chat no longer tells the agent it is in the file browser's subfolder
  (gh #172).** With a subfolder open, `[Working directory: ...]` named
  `<workspace>/<sub>`, but the process cwd is the workspace root, so a relative write
  landed in the root. Changing the cwd per turn isn't safe (it is process-global and
  shared with running tasks and schedules; ADR 0006 enters the workspace once), so
  the working-directory line now reports the workspace root, and the open folder
  comes on its own `[File browser folder: ...]` line that says relative paths don't
  follow it.
- **`POST /api/tasks` rejects a per-task `agent_spec` with 422 (gh #165).** The field
  was stored and echoed but never used, so a task "delegated" to another agent ran
  the host agent, and a spec that doesn't exist reported `done`. Loading a module path
  sent over REST would let any caller import code into the server, so the field is
  rejected instead of honored. Omitting it or sending `null` works as before.
- **`LANGSTAGE_CORS_ORIGINS` is a config field (gh #141).** The middleware read it
  with `os.getenv`, so `config` / `--show-config` / `config --json` never showed the
  setting that widens cross-origin access, and it had no TOML key. It is now
  `cors_origins` (env `LANGSTAGE_CORS_ORIGINS`, TOML `[server] cors_origins`, which
  also takes an array), `init` scaffolds it, and the server enforces the resolved value.
  An `AppConfig` built in Python without `cors_origins` no longer picks up the env var
  behind its back.
- **`init --path cfg/` says when the file won't be read (gh #142).** Project config
  is found by walking up from the cwd, so a file written into a subdirectory, or
  under another name, is never read from where you ran `init`. `init` now prints a
  note saying so and what to do, instead of "then `langstage config` to verify".
- **`init` marks example values (gh #152).** `show_canvas = true` looked like a
  default, but the default is auto, and uncommenting it forced an empty Canvas tab
  on. Keys whose default is unset or auto (`spec`, `show_canvas`, `show_files`) now
  carry `example; default: ...` on the line, and the header says so.
- **`POST /api/files/mkdir` accepts `?path=` (gh #159)**, as the upload docs and the
  README advertise, as well as the JSON body the UI sends. A missing path is 422.
- **OpenAPI `CronJob` includes `last_run_state` (gh #135)**, and **`FilePreview`
  includes `headers`, `rows`, `download_url` and `mime` (gh #162)**, the fields the
  responses already carried. Response bodies are unchanged.
- **The default agent is built once, with an explicit model (gh #169).** An
  unused agent was built at import time, so every start built two and printed the
  `create_deep_agent(model=None)` deprecation warning twice. That build is gone, and
  the model is core's `DEFAULT_MODEL` (the one deepagents picked for `None`), so the
  warning is gone too. The module no longer exports `agent`.

### Dependencies
- **`langstage[deepagents]` now requires `deepagents>=0.3,<1.0` (gh #169)**, since
  deepagents 1.0 removes `model=None` and would break the default agent on a fresh
  install.
- `uv.lock` is refreshed. It pinned a `langchain` too old for `deepagents` 0.7, so
  `uv run pytest` failed locally.

## 0.13.38 — 2026-09-24

Local correctness fixes for the files API, CORS under auth, the canvas list and the
notebook path. No dependency change.

### Fixed
- **`GET /api/files/read` returns the file as it is on disk (gh #144).** It used
  `read_text(errors="replace")`, so a CRLF file lost every `
`, a binary came back as
  lossily decoded `language: "text"`, and `size` was the decoded character count. The
  bytes are now decoded without newline translation, and `size` is the byte size that
  `tree`, `upload` and `download` report. A file that isn't UTF-8 text (or contains a
  NUL byte) gets **415** pointing at `/preview` or `/download`, instead of mangled text.
- **The CSV/TSV preview keeps rows with quoted delimiters (gh #154).** Rows were split
  with `str.split`, so an RFC-4180 cell like `"Smith, John"` produced too many columns
  and the row was silently dropped. The preview now uses the `csv` module: quotes are
  stripped, a quoted newline stays in its cell, and a ragged row is padded or trimmed
  to the header instead of dropped.
- **The preview's `download_url` is URL-encoded (gh #163).** A PDF or binary named
  `Q3 report.pdf` got a link with a raw space, and `&`, `+`, `#` or `%` in a name sent
  the download to a different path.
- **Deleting a symlink removes the link, not its target (gh #175).** `DELETE` resolved
  the path first, so removing `link -> data/` deleted `data/`. A symlink or Windows
  junction is now unlinked itself. #148's containment rule applies to where the link
  lives, so a path reached through a link that points outside the workspace is still
  rejected. A link that points outside, or a dangling link, can now be removed.
- **CORS preflights work with `--auth-password` set (gh #155).** Basic auth was the
  outermost middleware, so it answered every preflight `OPTIONS` (which browsers send
  without credentials) with 401, and the Vite dev server or an origin opted in via
  `LANGSTAGE_CORS_ORIGINS` could not reach an authenticated server. CORS is now outside
  auth and answers preflights itself. The request that follows is still authenticated,
  a bare `OPTIONS` still needs credentials, and the loopback-only default is unchanged.
- **`GET /api/canvas/items` no longer 500s on a real canvas (gh #158).**
  `CanvasItemResponse` required `title` and typed `data` as an object, but sections
  and markdown or HTML items have no title and a string `data`. The model now matches
  what the canvas tools write: `title`, `created_at`, `level`, `file`, `source_cell`
  and `execution_count` are optional, and `data` is any JSON value. The OpenAPI schema
  follows.
- **`app.run()` in a notebook no longer changes the kernel's working directory
  (gh #156).** The chdir into the workspace (ADR 0006) is for a process the server owns.
  In a notebook it moved the kernel's cwd, so later cells' relative paths resolved in
  the workspace. The script and CLI path still enter the workspace.

### Security
- **Basic auth now covers WebSocket upgrades.** The middleware passed every non-HTTP
  scope through, although its docstring said WebSockets were authenticated. No WebSocket
  route ships today, so nothing was exposed. An unauthenticated upgrade is now closed
  with 1008 (HTTP 403) before it reaches a route.

## 0.13.37 — 2026-09-24

Adopts langstage-core 1.0.36, which fixes several of these at the root, and moves the
CLI onto core's config reporting and console helpers. **Requires `langstage-core>=1.0.36`.**

### Fixed
- **`config` / `--show-config` no longer say "no langstage.toml found" when the file is
  there but malformed (gh #170).** The footer now names the file as MALFORMED, with the
  parse error. `config --json` is now core's `config_dict()`: each field also carries its
  env var / TOML key, `toml` gains `found`, `paths`, `malformed` and `malformed_files`, and
  a top-level `issues` list is added. The old `toml_read_from` and `unknown_toml_keys`
  keys are kept.
- **`config --strict` fails on every degraded value, not only unknown keys (gh #138).** It
  exits 1 on a malformed `langstage.toml`, a malformed value (`LANGSTAGE_PORT=notanum`,
  `LANGSTAGE_SHOW_FILES=flase`), an invalid value (port 70000, an unknown theme from env
  or TOML) or an unknown key. It prints one stderr line per issue, and `--json` lists them
  under `issues`.
- **`check --json` / `chat --json` stay pure JSON when the agent prints at import time
  (gh #140).** The agent is loaded with core's `stdout_to_stderr=True`, so a library's
  load banner goes to stderr and the README's `| jq -e ...` gate parses.
- **`config` / `--show-config` no longer crash on a cp1252 console (gh #146)** when a
  value such as the welcome message contains an emoji. All CLI output now goes through
  `langstage_core.console` (`safe_print`, or `console_safe` for the colored `check`
  lines), which replaces the local `_echo_streamsafe`.
- **`langstage run --debug` puts the agent's crash traceback on the SSE error frame
  (gh #134)**, as `LANGSTAGE_DEBUG=1` already did. A resolved `debug=True` from the flag or
  the Python API is published as `LANGSTAGE_DEBUG`, which core reads when it reports an
  error.
- **The chat UI attaches each tool's extraction to its own call.** Core emits
  `extraction` after the call's `tool_end`, but the UI only attached it to a call still
  marked running. The extraction was dropped, or landed on a parallel call to the same
  tool. It is now matched by id: the frame's own, or the `tool_end` right before it. The
  task-detail view had the same bug and gets the same fix.
- **A stopped server no longer leaves its graph holding a closed SQLite checkpointer.**
  The in-memory saver is restored on shutdown, so a graph reused after
  `BackgroundServer.stop()` (or served again in the same process) keeps working.

### Fixed in langstage-core 1.0.36 (regression-tested here)
- A `file.py:attr` agent can import its sibling modules (gh #167).
- A stdlib `typing.TypedDict` state works on every turn on Python 3.11 (gh #166).
- `tool_end` carries a real `duration_ms`, so the tool-call card shows the duration the
  README advertises (gh #160).
- `DEEPAGENTS_CONFIG_HOME` prints the one-time legacy notice (gh #136).

### Changed
- `load_agent_spec` now rejects a spec whose attribute is a `str`, with a clear error.
  `check` reports it as a load failure rather than "not runnable".
- A dotted `pkg.mod:attr` spec from `langstage.toml` resolves from that file's directory.

## 0.13.36 — 2026-09-23

Security and data-loss fixes. No dependency change.

### Security
- **`GET /api/files/tree` no longer follows symlinks out of the workspace (gh #148).**
  The entry path was checked (`tree?path=leak` → 400), but the recursive walk built
  child paths lexically and descended through symlinks. A workspace symlink pointing
  outside it (for example one the agent's own bash tool planted) made `tree?depth=N`
  list the target's names, structure and file sizes. A file symlink leaked its target's
  size even at the default `depth=1`. The walk now applies the same resolved-path
  containment rule as `_resolve_path` to every entry. An entry whose real location is
  outside the workspace (symlink or Windows junction) is left out and never
  descended into. Symlinks that stay inside the workspace are still listed. The sibling
  routes (`read`, `preview`, `download`, `upload`, `mkdir`, `delete`) all go
  through `_resolve_path`, which resolves symlinks first. They already refused
  escaping links, and a new test pins that for each one.

### Fixed
- **Schedules survive a server restart (gh #151).** Cron jobs lived only in memory
  and were lost on any restart, even though the task board they enqueue onto
  persists in `<workspace>/.langstage/tasks.db`. Schedules are now stored in a
  `cron_jobs` table in that same database. They are written through on create,
  delete and each fire (run stats included, so overlap protection still knows the
  previous run's task after a restart) and reloaded on startup. `next_run` is
  recomputed from the cron expression. Fires missed while the server was down are
  not replayed. A stored row whose cron no longer validates is skipped with a
  warning. The `/api/cron` request/response shapes and the OpenAPI schema are
  unchanged. The Schedules tab hint and the `schedule_run` tool description no
  longer say "in-memory".
- **Notebook tools are scoped per session (gh #157).** `create_cell`, `execute_cell`,
  `get_variables`, `reset_notebook` and the rest all shared one process-global
  notebook. A background task or scheduled run could therefore read the chat's
  variables or reset them away. Each run now gets its own cells and namespace,
  keyed by the run's `thread_id`: the chat session id, or `task-<id>` for board and
  scheduled runs, the same id the checkpointer uses. Callers with no session keep
  the shared default notebook. A session's notebook is freed when the session is
  deleted, and idle ones are evicted least-recently-used beyond 64. When IPython is
  installed, its singleton shell is bound to the calling notebook's namespace per
  run, and those runs are serialized.

## 0.13.35 — 2026-08-08

Docs-only. No code or dependency change.

### Fixed
- **README Configuration section now documents the *full* config-precedence chain,
  including the global config layer and `LANGSTAGE_CONFIG_HOME` (gh #128).** The section
  described a single, cwd-local `langstage.toml`, but `langstage-core`'s resolver
  (`HostConfig.resolve()`) actually reads **two** deep-merged TOML layers: the global
  `~/.langstage/config.toml` (directory overridable via `LANGSTAGE_CONFIG_HOME`; legacy
  `~/.deepagents/config.toml` / `DEEPAGENTS_CONFIG_HOME` still honored) and the project
  `langstage.toml` — the latter discovered by walking **up** the directory tree from the
  working directory (not from `--workspace`), and winning key-by-key over the global file.
  The corrected chain is now stated as **Python args > CLI args > environment variables >
  project `langstage.toml` (nearest at or above the working directory) > global
  `~/.langstage/config.toml` > defaults**, with a note that a parent-directory or global
  file can silently set values like `auth.password` / `server.host`, so `langstage
  --show-config` is the way to see the resolved source file. This closes the "Related doc
  gap" flagged when #119 shipped. `tests/test_readme_config_priority.py` is updated to pin
  the new chain and the global-layer docs.

## 0.13.34 — 2026-08-06

Requires **langstage-core >= 1.0.33** (bumped from >=1.0.32): #123 is fixed at the
shared core layer and this release wires it through, adds the `--port` CLI guard, and
ships two langstage-local fixes (#124, #125).

### Fixed
- **An out-of-range port (e.g. `70000`, `99999`) is no longer accepted and silently
  mis-bound (gh #123).** A type-valid but out-of-range integer port sailed through the
  resolver, was advertised by `--show-config` and the startup banner, and then uvicorn
  masked it to 16 bits at bind time (`70000 & 0xFFFF == 4464`) — the server listened on a
  *different* port than everything advertised, with no error. Now: the ambient paths
  (`LANGSTAGE_PORT` env, `server.port` in `langstage.toml`, a Python `port=` override)
  **degrade** an out-of-range value to the default `8050` + a one-line stderr `note:` and
  attribute it to `[default]` (via langstage-core 1.0.33's `resolve()` port-range
  validator — the same treatment a non-int value already got), and the interactive
  `--port` flag **hard-errors** cleanly at parse time (`Invalid value for '--port': 70000
  is not in the range 1<=x<=65535`) via `click.IntRange`, mirroring how `--theme`
  hard-rejects. Either way the silent misbind is gone.
- **`GET /api/files/download?path=<a dir>` now returns a clean `400 "Path is a directory"`
  instead of a misleading `404 "File not found"` (gh #124).** Downloading a directory
  path collapsed "exists but is a directory" into the same 404 as "doesn't exist",
  telling a client an existing path was gone. The route now distinguishes the two —
  `400` for a directory (matching `read`/`preview`, and the #117 `tree`-on-a-file fix),
  `404` only when the path truly doesn't exist. `download` was the last `/api/files/*`
  route to misreport a node type.

### Added
- **`langstage config --strict` — a CI gate on a typo'd/unknown `langstage.toml` key (gh
  #125).** `config` surfaces unknown keys (via core's `unknown_toml_keys()`) but always
  exited `0`, so a deploy/CI step couldn't fail the build on a config typo without
  hand-parsing the JSON. `--strict` exits **1** when the config isn't clean (any unknown
  key), and **0** when clean, so `langstage config --strict` is a one-line CI gate. The
  default (no `--strict`) still exits `0`, keeping the "degrade, don't crash on ambient
  config" contract. Composes with `--json` (same output on stdout, the strict error
  summary on stderr, same exit-code contract).

## 0.13.33 — 2026-08-03

Requires **langstage-core >= 1.0.32** (bumped from >=1.0.9): #119 and #120 are
fixed at the shared core layer and this release wires the fixes through langstage's
config surface.

### Fixed
- **`GET /api/files/tree?path=<a file>` now returns a clean 400 instead of HTTP 500
  (gh #117).** Passing a *file* path where a directory is expected raised an uncaught
  `NotADirectoryError` out of the `/tree` route — the only `/api/files/*` route that
  leaked a 500 for a wrong node type (the boundary always held; it was an
  error-handling gap). The route now catches `NotADirectoryError` and returns
  `400 {"detail": "Not a directory: …"}`, the mirror image of `read`/`preview`'s
  existing `IsADirectoryError` → 400 guard for the inverse case.
- **`langstage config` / `--show-config` now attributes each TOML value to the file it
  actually came from (gh #119).** When both a global `~/.langstage/config.toml` and a
  project `langstage.toml` were present, every TOML-sourced field was labeled
  `[toml (langstage.toml)]` — even a value that existed *only* in the global file —
  because the deep-merged config dict had lost per-key provenance. Values always
  resolved correctly (global < project); only the source column was wrong, silently
  defeating the deploy-time "where did this value come from?" assertion the column
  exists for. Fixed in langstage-core 1.0.32's `resolve()` (each key is attributed to
  the highest-precedence file that actually defines it); langstage inherits it —
  `subtitle` set only in the global file now reads `[toml (config.toml)]`.

### Added
- **`langstage config` / `--show-config` now flags unknown / typo'd / misplaced keys in
  `langstage.toml` (gh #120).** A key that maps to no known field — a typo (`titel`),
  a key in the wrong section (`prot` under `[server]`), or an entirely unknown
  table — was silently dropped, so the "edit it, then `langstage config` to verify"
  workflow couldn't catch the single most common hand-edit mistake (`config` just
  reported the field as `[default]`). `config` and `--show-config` now print
  `unknown TOML keys (ignored - a typo or wrong table?): …` (via langstage-core
  1.0.32's `HostConfig.unknown_toml_keys()`, surfaced by `describe()`), and
  `config --json` reports them under a new `unknown_toml_keys` field so a deploy step
  can assert on them machine-side. Keys under the `[configurable]` passthrough table
  are never flagged. Advisory only (exit 0), matching the legacy-env-var notice.

## 0.13.32 — 2026-07-31

### Security
- **CORS no longer reflects every origin with credentials on the default local server
  (gh #113).** The server attached `CORSMiddleware` with `allow_origins=["*"]` **and**
  `allow_credentials=True`; Starlette turns that combination into "reflect the caller's
  `Origin` back + `Access-Control-Allow-Credentials: true`", so on the default
  `langstage run` (localhost, no password) **any web page the user visited could make
  credentialed cross-origin requests to their local server and read the responses** —
  read/write the workspace file browser, read chat/config, delegate agent runs, create
  cron jobs. CORS is now **loopback-only by default**: credentialed access is granted
  only to `http(s)://localhost`, `127.0.0.1`, or `[::1]` (any port) via
  `allow_origin_regex`, which is everything the same-origin SPA and a local Vite dev
  server need — a drive-by origin (`https://evil.example`, the `null` origin of a
  sandboxed iframe/`file://`) is never reflected, so the browser hands it no grant to
  read the response. A user who genuinely needs to allow specific cross-origin sites can
  opt in with `LANGSTAGE_CORS_ORIGINS` (comma-separated); a literal `*` there is honored
  only with `allow_credentials=False` (the browser forbids `*` + credentials anyway).

### Fixed
- **Invalid `LANGSTAGE_SHOW_FILES` / `LANGSTAGE_SHOW_CANVAS` values now degrade with a
  note instead of being silently swallowed to auto and still credited to the env var in
  `--show-config` (gh #112).** `theme` got this treatment in #104, but the two boolean UI
  fields went through a lenient parser that mapped **any** unrecognized string to `None`
  (auto) with no signal — so `LANGSTAGE_SHOW_FILES=flase` (a typo of `false`, meant to
  **hide** the Files tab) silently **showed** it, and `--show-config` misleadingly
  reported `[env:LANGSTAGE_SHOW_FILES]` as honored. These two fields now resolve through a
  **strict** caster: a non-empty unrecognized value is rejected by the shared resolver's
  malformed-value guard, which emits the one-line `note: ignoring malformed …; using
  default None instead.` and repoints the recorded source to `[default]` — matching the
  #104 / `theme` behavior. Valid values (`on`/`off`/`1`/`0`/…) resolve unchanged.
- **The file-browser preview now renders plain-text `.log` / `.ini` / `.cfg` / `.conf`
  as text instead of `binary` (download-only) (gh #114).** The preview path
  (`GET /api/files/preview`, the only files endpoint the SPA calls to view a file) decided
  "is this text?" from `file_manager.LANGUAGE_MAP`, which omitted those extensions — while
  the read path's `file_utils.is_text_file` / `TEXT_EXTENSIONS` already treated them as
  text, so the two detectors contradicted each other (notably for `server.log`, which
  `--demo`/`run` itself writes). Preview's text set is now the **union** of `LANGUAGE_MAP`
  and `TEXT_EXTENSIONS`, sharing one source of truth so the two can't drift apart again;
  the binary guard is unchanged for genuinely non-text files.
- **`langstage chat` no longer crashes with `UnicodeEncodeError` when the agent reply
  contains a non-cp1252 character (emoji/CJK/arrows) on a non-UTF-8 console (gh #115).**
  The reply was printed via a bare `click.echo`, which on the default Windows cp1252
  console raised as soon as the reply held an emoji/CJK/arrow — **losing the answer** and,
  worse, flipping the exit code to a false `1` even though the agent succeeded, breaking
  `chat`'s documented readiness-gate contract (a CI/cron gate saw a failure purely because
  the correct answer had an emoji in it). The reply is now written with an error-tolerant
  policy (`errors="backslashreplace"`), so an un-encodable char degrades to an ASCII
  `\uXXXX` escape (the same fidelity `--json` already got from `ensure_ascii`), the answer
  is shown, and the exit code reflects the agent's real outcome.

## 0.13.31 — 2026-07-26

### Fixed
- **`langstage chat` now `chdir`s into the resolved workspace before the turn, so the
  agent's process `os.getcwd()` and its relative file ops actually land in the workspace
  — matching a browser turn instead of only *naming* the workspace in the injected
  context (gh #110).** This is the residual gap left after #106. That fix made `chat`
  inject the same `[Working directory: <workspace>]` context line the web chat does, but
  `chat` never entered the workspace the way the web server does: `run()` calls
  `CoworkApp._enter_workspace()` (which does `os.chdir(workspace_root())`, per ADR 0006),
  while `chat` constructed `CoworkApp(...)` and called `run_turn_sync(app.agent, …)`
  directly — never `run()`, never `_enter_workspace()`. So the injected line said the
  working directory was the workspace while the process cwd stayed the **launch** dir, and
  a bring-your-own agent's raw relative write (`Path("out.txt").write_text(...)`) landed
  **outside** the workspace the file browser shows — inconsistently with what the same
  turn does in the browser.
  - `chat` now enters the resolved workspace (via `app._enter_workspace()`) after
    `CoworkApp` has resolved and `apply_workspace`'d it and before `run_turn_sync`, exactly
    mirroring `run()`. The chdir is **unconditional**, so `--no-context` follows the
    workspace too — cwd tracks the resolved workspace whether or not the context line is
    injected.
  - The CLI restores the caller's **prior cwd after the turn**, so a library/embedded
    caller of the chat path isn't left with a changed cwd.
  - The web/`run()` path and `__init__`'s deliberate no-cwd-side-effect contract are
    unchanged (embedding `CoworkApp` still never moves the process cwd).

## 0.13.30 — 2026-07-25

### Fixed
- **`POST /api/cron` (and the `schedule_run` agent tool) now reject any non-5-field
  cron expression with the same clean 400 the 4-field case already got — so a 6- or
  7-field cron pasted from another scheduler can no longer be silently accepted and
  fired at an unintended time (gh #108).** Validation delegated entirely to
  `croniter.is_valid`, which also accepts croniter's **6-field (seconds)** and
  **7-field (seconds + year)** extensions. But both the endpoint's own 400 message and
  the README document **standard 5-field UTC cron only** (*"Cron is interpreted in UTC.
  `0 9 * * *` fires at 09:00 UTC"*). The result was a silent-misinterpretation bug: a
  4-field cron was correctly rejected with *"Expected 5 fields 'min hour day month
  weekday'"*, but a 6-field Quartz/Spring/k8s-style cron such as `30 0 9 * * *` was
  **accepted (201)** and read by croniter as `min=30 hour=0 day=9 month=* weekday=*
  second=*` — a `next_run` on the **9th at 00:30 UTC**, not the ~09:00 the user meant —
  with no error and no warning. That is the exact class of misinterpretation the
  strict-5-field message was written to prevent.
  - `validate_cron` now asserts the field count **before** croniter:
    `len(expr.split()) != 5` raises the existing *"Expected 5 fields …"* `ValueError`,
    so anything but a standard 5-field expression is rejected up front. `str.split()`
    (no argument) splits on runs of whitespace, so `"0  9 * * *"` (double space) is
    still 5 fields; steps and ranges like `*/15 * * * *` and `0 9 * * 1-5` still pass.
  - The guard lives in the **single shared** `validate_cron`, which both the HTTP
    create path (`POST /api/cron` → `CronScheduler.add_job`) and the agent-facing
    `schedule_run` tool call — so both surfaces enforce the identical 5-field contract,
    and the endpoint's 400 message is finally true. The 4-field rejection is unchanged.

## 0.13.29 — 2026-07-25

### Fixed
- **`langstage chat` now injects the same per-message context the web chat does, so
  a headless turn is genuinely identical to a browser turn — matching what it (and
  `oneturn.py`) already advertised (gh #106).** The two "buffered one-turn" siblings
  that share `langstage/oneturn.py:complete_turn` — the CLI `langstage chat` and the
  HTTP `POST /api/chat/complete` — fed the agent **different inputs** for the same
  prompt. Both web paths (`POST /api/chat` SSE **and** `POST /api/chat/complete`)
  prepend a per-message context block — `[Current time: …]` + `[Working directory: …]`
  — via `routes_chat.context_parts()`; `langstage chat` deliberately did not. That
  contradicted the very claim both docstrings made — the `chat` docstring's *"the reply
  is exactly what a browser would render"* and `oneturn.py`'s *"identical to what a
  browser would have rendered"* — and it silently defeated the feature's whole purpose:
  `chat` / `check --live` are sold as a low-ceremony **readiness gate** that mirrors a
  production turn, but for any time-aware or workspace-aware agent — including the
  **built-in default agent, whose entire system prompt is about operating in the
  workspace** — the gate validated a materially different input than what ships. The
  keyless echo demo made the divergence visible: `langstage chat --demo "ping"` replied
  `You said: ping`, while `POST /api/chat/complete {"content":"ping"}` replied
  `You said: [Current time: …]\n[Working directory: …]\n\nping`.
  - `langstage chat` now calls the **same** `routes_chat.context_parts()` the web paths
    use and forwards it through the shared `complete_turn`, so both siblings feed the
    agent the same input and produce the same reply. `CoworkApp` has already resolved
    and `apply_workspace`'d the workspace by the time the context is built, so the
    reported `[Working directory: …]` is the real resolved workspace root (the browser's
    default folder), not the launch cwd. The CLI has no file browser, so no `cwd`
    subfolder is applied.
  - A new **`--no-context`** flag opts back out — the terse `prompt in -> answer out`
    echo, for clean scriptable output — at the explicit cost of no longer being
    browser-identical. This keeps the #101 "clean `--demo` echo" use case one flag away
    without letting the *default* silently misrepresent a browser turn.
  - The overstated equivalence claims in the `chat` command docstring and `oneturn.py`'s
    module docstring are corrected to describe the shipped behavior precisely: identity
    of *output* follows from feeding the *same input*, which both callers now do by
    default; `--no-context` is the documented exception. The historical 0.13.27
    changelog entry is left as-is (it records what shipped then); this release makes its
    "exactly what a browser would render" description true by default.

## 0.13.28 — 2026-07-23

### Fixed
- **The `theme` enum is now enforced on the env / TOML / Python-API paths, not
  just the `--theme` CLI flag (gh #104).** `theme` is documented as a three-value
  enum — `--theme [light|dark|auto]` in the CLI `--help`, `theme = "auto"` in the
  `init` template, `# "light" | "dark" | "auto"` in `config.py` — but that enum was
  enforced on **only** the `--theme` flag (a click `Choice`). `LANGSTAGE_THEME`,
  `ui.theme` in `langstage.toml`, and the Python `AppConfig(theme=…)` constructor
  all resolved any string silently: an invalid value flowed through `AppConfig`,
  was reported by `--show-config` / `config` as a legitimately-resolved setting,
  and shipped to the client via `GET /api/config`, where the bundled UI (which
  only matches `dark`/`light`/`auto`) silently ignored it — the same
  "advertised != honored" gap the Configuration surface exists to rule out, with
  `--show-config` confirming a value the CLI would have rejected.
  - The three ambient paths (env / TOML / the `AppConfig(theme=…)` constructor)
    now **degrade** an invalid value to the default `"auto"` and print a one-line
    stderr `note:` naming the bad value and the accepted set — `note: ignoring
    invalid theme 'purple' (expected one of: light, dark, auto); using default
    'auto' instead.` This follows the "degrade, don't crash on ambient config"
    contract langstage-core adopted for malformed numeric config (>= 1.0.23):
    crashing an entrypoint on an env var or a config file is worse than degrading,
    so an invalid `theme` in `langstage.toml` must not brick the server.
    `--show-config` then reports `theme = auto [default]` — never crediting the
    rejected env var / TOML key as the source — and the client can no longer
    receive an un-honorable theme.
  - The interactive `--theme` flag keeps its immediate hard `Choice` rejection
    (`Error: Invalid value for '--theme': 'purple' is not one of 'light', 'dark',
    'auto'.`, exit 2): rejecting an interactive argument on the spot is fine;
    degrading ambient config is the safer default.
  - The enum is **case-sensitive**, exactly matching the CLI's
    `Choice(["light", "dark", "auto"])`, so the accepted set is identical across
    all four sources. It is enforced in `AppConfig` by a post-resolution
    normalization: `__post_init__` covers the direct Python constructor and,
    through `resolve()`'s `cls(**values)`, the env and TOML paths too; `resolve()`
    then repoints the recorded source to `default` so `--show-config` attributes
    the degraded value correctly. A valid value still resolves normally with its
    real source.

## 0.13.27 — 2026-07-23

### Added
- **A headless one-turn chat: the `langstage chat` CLI and a buffered
  `POST /api/chat/complete` endpoint (gh #101).** There was no low-ceremony
  "prompt in -> answer out" path. The SSE chat pair is stateful (you must open a
  *persistent* `GET /api/stream` first — that's what creates the session — then
  `POST /api/chat`, then parse the event stream; a bare `POST /api/chat` 404s
  without the stream); `check --live` runs exactly one real turn but throws the
  reply away; the task board returns the turn but is async, poll-based, and
  persists a SQLite row. Both new surfaces are the synchronous, chat-shaped
  primitive that was missing — for a CLI smoke test, a cron "ask the agent X and
  email me the answer" script, or a CI assertion on the agent's *actual output*:
  - `langstage chat --agent my_agent.py:graph "…"` drives one turn and prints the
    assistant reply to stdout (`--json` for `{content, tool_calls}`); keyless with
    `--demo`, honors the same `--workspace` / `langstage.toml` / `LANGSTAGE_*`
    resolution as `run`, and exits non-zero if the agent errors (like
    `check --live`) so it doubles as a readiness gate that also *shows* the answer.
  - `POST /api/chat/complete {content, session_id?}` runs one turn to completion
    and returns `{session_id, content, tool_calls}` in a single JSON body — no
    pre-opened stream, no SSE parsing, no persisted task row. It creates the
    session when `session_id` is absent; an errored turn is surfaced as HTTP 500.
    Typed with a `response_model` (`extra="allow"` + `response_model_exclude_unset`)
    like every route since #98, so it shows up in `/openapi.json` and `/docs`.
  - Both share **one** implementation (`langstage/oneturn.py`) that buffers the
    same `SessionAdapter` streaming path the web server drives — the reply is
    exactly what a browser would render, just assembled — so the streaming chat
    path is untouched (a bare `POST /api/chat` still 404s without a stream).

### Fixed
- **`LANGSTAGE_TASK_CONCURRENCY` now resolves through the unified config chain
  instead of a raw `os.getenv` (gh #102).** It is a *documented* `LANGSTAGE_*` env
  var (README → Task board), but unlike every other one it was read directly with
  `int(os.getenv("LANGSTAGE_TASK_CONCURRENCY", "3"))` in `server/main.py`, outside
  the resolver every documented option goes through — with two user-visible
  consequences: it was **invisible to `langstage --show-config` / `config`** (a
  user who set it had no way to confirm what it resolved to, and no
  `langstage.toml` key or legacy alias existed), and **a bad value crashed the
  server at startup with an unhandled `ValueError` traceback**, where the exact
  same misconfiguration of `--port` is caught by `run` and reported as a clean
  one-line `Error:`. It is now a first-class `AppConfig` field wired into the
  `_ENV` / `_TOML` maps like the other keys — so it appears in `--show-config`
  with its value + source, gains a `tasks.concurrency` `langstage.toml` key and
  the deprecated `DEEPAGENT_TASK_CONCURRENCY` alias, and a malformed value is
  caught by the resolver and reported as a clean CLI error. The `TaskRunner`
  still clamps the resolved value to `>= 1`, so the effective bound is unchanged.

### Docs
- **The README "Configuration priority" chain now includes `langstage.toml`
  (gh #100).** The line read *"Python args > CLI args > environment variables >
  defaults"* — dropping the exact `langstage.toml` layer that section teaches the
  reader to create with `langstage init`, and contradicting both the
  `init`-generated file header (*"… > env vars > this file > defaults"*) and the
  `--show-config` help (*"defaults < langstage.toml < env < CLI"*). It now reads
  *"Python args > CLI args > environment variables > `langstage.toml` > defaults"*,
  matching the tool's own output and the resolver's real four-layer behavior; the
  identical statement in the `CoworkApp` docstring was corrected to match.

## 0.13.26 — 2026-07-19

### Fixed
- **`/openapi.json` now actually describes response bodies, so it can be fed to a client
  generator as the README promises (gh #98).** The README sells the served schema as the
  canonical reference for a programmatic client *"instead of reverse-engineering shapes"*, but
  **all 32** `/api/*` routes had `"schema": {}` for their 200 response — no route declared a
  response type, so `openapi-generator` typed every return as untyped `object`/`any` and an
  author still had to reverse-engineer every payload from source or live traffic. Request params
  and bodies were typed; responses, the one thing the README said you could skip, were not.
  Every JSON route now declares a `response_model`, and the four non-JSON routes
  (`/api/files/download`, `/api/canvas/assets/*`, `/api/stream`, `/api/custom-css`) declare their
  real media type — `application/octet-stream`, `text/event-stream`, `text/css` — instead of
  advertising an empty JSON body, which would have led a generator to emit a JSON-decoding
  client for a byte stream. The issue's own metric goes from **32/32 empty to 0/32**.

  Two deliberate safeguards, because attaching a `response_model` to a live route changes
  runtime behavior and not just documentation:
  - **`extra="allow"` on every model.** FastAPI *filters* responses through the response model,
    silently dropping undeclared keys. The pre-existing (and entirely unused) `models.py` had
    already drifted — `AppConfigResponse` declared 7 fields while `GET /api/config` returns 12 —
    so wiring it naively would have quietly deleted `save_workflow_prompt`, `run_workflow_prompt`,
    `create_workflow_prompt`, `show_canvas` and `show_files` from the payload the SPA boots on.
  - **`response_model_exclude_unset=True` on every route.** Typing a route can *add* keys too: an
    optional field with a `None` default renders as an explicit `null` the old wire never sent
    (`FileEntry.children` did exactly this). Excluding unset fields keeps each body
    byte-identical to what the handler produced, so this release is schema-only at the wire.

  Model shapes were captured from a live `--demo` server rather than inferred from source. A
  regression test asserts no `/api/*` route advertises an empty schema, that every `$ref`
  resolves, that non-JSON routes declare their real media type, that `/api/config` still carries
  all 12 fields, and that every model in `models.py` sets `extra="allow"` — so a future model
  added without it can't start silently filtering a live endpoint.

## 0.13.25 — 2026-07-18

### Fixed
- **A missing bundled frontend is now a loud, machine-readable condition instead of a
  browser-only surprise (gh #96).** 0.13.24 stopped frontend-less wheels from being *built*;
  this makes one that already shipped — or a mis-set install — impossible to miss at runtime.
  Previously the one thing this package exists to serve could be entirely absent while every
  signal stayed green: `langstage run` printed a happy URL, uvicorn logged `Application startup
  complete`, `/api/health` returned `{"status":"ok"}`, and `langstage check` passed. The only
  way to find out was to open a browser and get raw JSON where the workspace should be — which
  is precisely how the 0.13.20–0.13.23 cut sat unnoticed on PyPI (gh #94). The absence now
  surfaces at three touch-points, all driven by one shared `frontend_bundled()` predicate so
  they cannot drift apart:
  - **Startup warning** — a `WARNING:` line to **stderr** (like the non-loopback auth warning
    from #89, so it stands out from the banner and survives stdout redirection) naming the
    missing artifact, the consequence, and both fixes.
  - **`/api/health?ready=1`** — a `checks.frontend` field (`"ok"` / `"missing"`), giving uptime
    monitors, k8s, and CI a hook to catch a broken deploy that a plain `200` hides. It is
    **reported, not gating**: the readiness verdict is computed before it is added, because the
    REST/WS surface is fully functional without the SPA and a backend-only install is supported
    (the packaging hook honours `LANGSTAGE_SKIP_FRONTEND_BUILD=1`). Failing readiness would pull
    a working API out of a load balancer.
  - **`langstage check`** — a `[warn] bundled frontend missing …` line and a `checks.frontend`
    object under `--json`, so a preflight can assert the UI actually shipped, not just that the
    agent loads. Warning-level: the exit-code contract is unchanged.

## 0.13.24 — 2026-07-16

### Fixed
- **A clean `pip install langstage` now actually ships the web UI — `GET /` serves the
  React SPA, not the JSON placeholder (gh #94).** Regression in 0.13.20–0.13.23: the
  published wheels contained **no** `langstage/static/` at all, so a fresh install fell
  through to the "no pre-built frontend" placeholder branch in `server/main.py` and the
  entire chat workspace — the whole point of the stage — was missing. Root cause was pure
  packaging: the Vite build output (`langstage/static/`) is git-ignored, and
  `[tool.hatch.build] artifacts = ["langstage/static/**"]` only *re-includes* git-ignored
  files that **already exist** at build time — it never builds them. Nothing in the manual
  `uv build` release path ran `npm run build` first (the old `build_frontend.py` was an
  untracked dev script), so the wheel was assembled with an empty tree and shipped no UI.
  Fixed with a Hatchling wheel build hook (`hatch_build.py`) that builds the SPA
  (`npm ci && npm run build`) into `langstage/static/` before the wheel is packed, with a
  skip-if-already-built guard and a **publish guard that fails the build if
  `langstage/static/index.html` is still missing** — so an empty-UI wheel can never reach
  PyPI again. The hook is a no-op for the sdist and for editable installs (`pip install -e`)
  and honours `LANGSTAGE_SKIP_FRONTEND_BUILD=1`, so Node is only needed to cut a real
  release wheel — the Python test/dev loop and a backend-only `pip install .` don't require
  it. Publishing 0.13.24 replaces the broken 0.13.20–0.13.23 cut.

## 0.13.23 — 2026-07-15

### Fixed
- **`langstage run` / `check` no longer print an EMPTY error when the load exception has no
  message (gh #92).** A follow-on gap from #90: `run` broadened its `except` to surface loader
  failures as `Error: <str(e)>`, but `str()` is empty for a message-less exception — most
  commonly `NotImplementedError()`, which `BaseChatModel.bind_tools()` raises for any model that
  doesn't support tool-calling, so `create_react_agent(model, tools=[...])` produces a bare
  `NotImplementedError('')` at import. The result was `Error: ` / `[fail] failed to load: ` with
  **nothing after the colon** — zero diagnostic signal at exactly the moment `run`/`check` exist
  to help. Both surfaces now fall back to the exception **class name** when the message is empty:
  `run` prints `Error: NotImplementedError`, `check` prints `[fail] failed to load:
  NotImplementedError`, and `check --json` reports `"error": "NotImplementedError"` (the dangling
  `": "` trimmed). The human `check` line and the `--json` error now share one formatter so they
  can't drift, and a non-empty message is unchanged (still `Type: message`). Exit code stays `1`.

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
