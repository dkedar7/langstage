"""Headless one-turn chat: `POST /api/chat/complete` + the shared helper (gh #101).

The buffered endpoint is the synchronous, non-SSE sibling of the streaming chat
pair: one HTTP call, prompt in -> full reply out, with none of the SSE ceremony
(no persistent ``GET /api/stream`` to open first, no event parsing, no task row).
It drives the same ``SessionAdapter`` the streaming routes drive, so the reply is
identical — just buffered. These tests also pin that the streaming path is not
regressed.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, MessagesState, StateGraph

from langstage_core import load_agent_spec
from langstage_core.adapters import SessionAdapter

from langstage.oneturn import OneTurnResult, complete_turn, run_turn_sync
from langstage.server.routes_chat import create_chat_router


def _stub():
    return load_agent_spec("langstage_core.demo.stub:graph")


def _boom_graph():
    def boom(state):
        raise RuntimeError("synthetic model failure")

    b = StateGraph(MessagesState)
    b.add_node("boom", boom)
    b.add_edge(START, "boom")
    b.add_edge("boom", END)
    return b.compile()


def _client(graph):
    app = FastAPI()
    app.include_router(create_chat_router(SessionAdapter(graph=graph)))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ── the endpoint ─────────────────────────────────────────────────────────────


async def test_complete_returns_reply_with_no_pre_opened_stream():
    """The whole point: a single POST returns the full reply, cold — no persistent
    GET /api/stream to create the session first (the SSE path's hidden ordering)."""
    async with _client(_stub()) as c:
        r = await c.post("/api/chat/complete", json={"content": "hello buffered"})
    assert r.status_code == 200
    body = r.json()
    assert "hello buffered" in body["content"]  # the demo echoes the user message
    assert body["session_id"]  # a session was created and returned
    assert body["tool_calls"] == []  # shape present (demo has no tools)


async def test_complete_reuses_a_provided_session_id():
    async with _client(_stub()) as c:
        r = await c.post(
            "/api/chat/complete", json={"content": "hi", "session_id": "sess-xyz"}
        )
    assert r.status_code == 200
    assert r.json()["session_id"] == "sess-xyz"


async def test_complete_surfaces_agent_error_as_500():
    async with _client(_boom_graph()) as c:
        r = await c.post("/api/chat/complete", json={"content": "hi"})
    assert r.status_code == 500
    assert "synthetic model failure" in r.json()["detail"]


async def test_streaming_chat_path_is_unchanged():
    """The SSE contract must not regress: a bare POST /api/chat still 404s without a
    session (which only the persistent stream creates) — the buffered path is
    additive, it doesn't loosen the streaming ordering."""
    async with _client(_stub()) as c:
        r = await c.post("/api/chat", json={"session_id": "never-opened", "content": "x"})
    assert r.status_code == 404


# ── the shared helper (one implementation behind CLI + endpoint) ─────────────


async def test_complete_turn_assembles_content_and_outcome():
    adapter = SessionAdapter(graph=_stub())
    result = await complete_turn(adapter, "ping the agent")
    assert isinstance(result, OneTurnResult)
    assert result.ok and result.outcome == "complete"
    assert "ping the agent" in result.content


async def test_complete_turn_reports_agent_error_without_raising():
    adapter = SessionAdapter(graph=_boom_graph())
    result = await complete_turn(adapter, "hi")
    assert not result.ok
    assert result.outcome == "error"
    assert "synthetic model failure" in (result.error or "")


def test_run_turn_sync_drives_one_turn_end_to_end():
    """The blocking entry point the CLI uses: wrap a graph, run one turn, return."""
    result = run_turn_sync(_stub(), "sync smoke")
    assert result.ok
    assert "sync smoke" in result.content


# ── the two siblings feed the agent the SAME input (gh #106) ─────────────────


def test_cli_and_endpoint_feed_the_agent_the_same_input(monkeypatch, raw_demo_echo):
    """gh #106: `langstage chat` and `POST /api/chat/complete` share `complete_turn`
    and are documented as producing an identical, browser-faithful reply — so they must
    feed the agent the *same input* for the same prompt. Previously the CLI withheld the
    per-message `[Current time]` / `[Working directory]` context the web paths inject, so
    the demo echo agent (which reflects its input) returned different replies.

    Drive the endpoint via `httpx.ASGITransport` and the CLI via `CliRunner`, both keyless
    with `--demo` and the same prompt, and assert the replies match. `context_parts` is
    pinned to a fixed value so the assertion is deterministic (no per-second timestamp /
    workspace drift) and targets the real invariant: the CLI now injects the SAME context
    the endpoint does. Fails before the fix (CLI fed no context), passes after.

    This test is synchronous (not the module's default async): the CLI's `run_turn_sync`
    calls `asyncio.run`, which can't be nested inside a running loop, so the endpoint leg
    runs in its own `asyncio.run` and the CLI leg runs after it.
    """
    import asyncio
    import json

    from click.testing import CliRunner

    from langstage import cli as cli_mod
    from langstage.server import routes_chat

    fixed = ["[Current time: 2026-07-25 00:00:00 UTC]", "[Working directory: /ws]"]
    # Both siblings resolve `context_parts` from routes_chat at call time (the endpoint
    # via its module global, the CLI via `routes_chat.context_parts()`), so one patch
    # covers both. The demo echoes its full input, exposing any divergence.
    monkeypatch.setattr(routes_chat, "context_parts", lambda cwd=None: list(fixed))

    async def _endpoint_reply() -> str:
        async with _client(_stub()) as c:
            r = await c.post("/api/chat/complete", json={"content": "ping"})
        assert r.status_code == 200
        return r.json()["content"]

    endpoint_content = asyncio.run(_endpoint_reply())

    cli_result = CliRunner().invoke(cli_mod.main, ["chat", "--demo", "--json", "ping"])
    assert cli_result.exit_code == 0, cli_result.output
    cli_content = json.loads(cli_result.output)["content"]

    # Same shared complete_turn + same demo agent + same injected context => same reply.
    assert cli_content == endpoint_content
    # And the context really is injected (guards against a both-empty false pass).
    assert "[Working directory: /ws]" in cli_content
    assert "ping" in cli_content


def test_cli_no_context_flag_restores_the_terse_echo(raw_demo_echo):
    """gh #106: `--no-context` opts back out of the browser-identical context injection
    for a clean scriptable echo — so the CLI's default (context injected) and its escape
    hatch (context withheld) are demonstrably different, and the flag exists at all
    (before the fix it did not, and the default omitted the context)."""
    import json

    from click.testing import CliRunner

    from langstage import cli as cli_mod

    default = CliRunner().invoke(cli_mod.main, ["chat", "--demo", "--json", "ping"])
    raw = CliRunner().invoke(
        cli_mod.main, ["chat", "--demo", "--no-context", "--json", "ping"]
    )
    assert default.exit_code == 0, default.output
    assert raw.exit_code == 0, raw.output

    default_content = json.loads(default.output)["content"]
    raw_content = json.loads(raw.output)["content"]

    # Default injects the real per-message context; --no-context strips it.
    assert "[Working directory:" in default_content
    assert "[Current time:" in default_content
    assert "[Working directory:" not in raw_content
    assert "[Current time:" not in raw_content
    assert default_content != raw_content


# ── chat enters the resolved workspace before the turn (gh #110) ──────────────

# A bring-your-own agent whose single node reports its process cwd and does a RAW
# relative write (`Path("probe_out.txt").write_text(cwd)`) — the file lands wherever
# the process cwd is, so where it appears is a direct probe of whether `chat` chdir'd
# into the workspace. Mirrors the issue's probe_agent.py pattern.
_PROBE_AGENT_SRC = '''
import os
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph


def _probe(state):
    cwd = os.getcwd()
    Path("probe_out.txt").write_text(cwd, encoding="utf-8")
    return {"messages": [AIMessage(content=f"cwd={cwd}")]}


builder = StateGraph(MessagesState)
builder.add_node("probe", _probe)
builder.add_edge(START, "probe")
builder.add_edge("probe", END)
graph = builder.compile()
'''


# ── chat survives a non-cp1252 reply on a cp1252 console (gh #115) ────────────


@pytest.mark.parametrize(
    "prompt,escape",
    [("\U0001f389", "1f389"), ("A→B", "2192"), ("日本語", "65e5")],
    ids=["emoji", "arrow", "cjk"],
)
def test_chat_does_not_crash_on_cp1252_stdout(prompt, escape):
    """gh #115: `langstage chat` printed the reply via a bare click.echo, which on a
    non-UTF-8 console (the default Windows cp1252) raised UnicodeEncodeError as soon as
    the reply held an emoji/CJK/arrow — losing the answer AND flipping the exit code to
    a false 1, breaking the documented readiness-gate contract (the agent succeeded).

    CliRunner(charset="cp1252") wraps stdout in a strict cp1252 encoder, faithfully
    reproducing that console. The reply must now be shown (lossily, backslash-escaped)
    and the exit code must reflect the agent's real, successful outcome (0)."""
    from click.testing import CliRunner

    from langstage import cli as cli_mod

    result = CliRunner(charset="cp1252").invoke(
        cli_mod.main, ["chat", "--demo", "--no-context", prompt]
    )
    assert result.exception is None, result.output  # no unhandled UnicodeEncodeError
    assert result.exit_code == 0  # agent succeeded => exit 0, not a false failure
    assert result.output.strip()  # the answer reached stdout, not just a traceback
    assert result.output.isascii()  # degraded to ASCII escapes, printable on cp1252
    assert escape in result.output.lower()  # the char is shown escaped, not dropped


def test_chat_json_path_still_survives_cp1252(monkeypatch):
    """Control: the --json path was already safe (json.dumps escapes to ASCII); keep it
    green so the plain-path fix didn't regress it."""
    import json

    from click.testing import CliRunner

    from langstage import cli as cli_mod

    result = CliRunner(charset="cp1252").invoke(
        cli_mod.main, ["chat", "--demo", "--no-context", "--json", "\U0001f389"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["content"]  # parseable, content present


@pytest.mark.parametrize("extra", [[], ["--no-context"]], ids=["default", "no-context"])
def test_chat_enters_workspace_so_relative_writes_land_there(tmp_path, monkeypatch, extra):
    """gh #110: `langstage chat` must `chdir` into the resolved workspace before the turn,
    the way `run()` does via `_enter_workspace()` — not merely inject a
    `[Working directory: <workspace>]` line while the process cwd stays the launch dir
    (the residual gap after #106). Otherwise a BYO agent's `os.getcwd()` and its raw
    relative file ops disagree with a browser turn: they land in the LAUNCH dir, outside
    the workspace the file browser shows.

    Drive the real CLI with a probe agent that reports its cwd and writes a relative file,
    from a launch cwd that is deliberately NOT the workspace, and assert the write landed
    in the workspace (and the reported cwd equals it). `--no-context` is covered too: the
    chdir is unconditional, so cwd follows the workspace whether or not the context line is
    injected. Before the fix, the relative file landed in the launch dir and this fails.
    """
    import os
    from pathlib import Path

    from click.testing import CliRunner

    from langstage.cli import main

    workspace = tmp_path / "ws"
    launch = tmp_path / "launch"
    workspace.mkdir()
    launch.mkdir()
    probe = tmp_path / "probe_agent.py"
    probe.write_text(_PROBE_AGENT_SRC, encoding="utf-8")

    # Launch from a clean dir distinct from the workspace, so "landed in the workspace"
    # is distinguishable from "landed in the launch dir" (the bug).
    monkeypatch.chdir(launch)
    result = CliRunner().invoke(
        main,
        ["chat", "--agent", f"{probe}:graph", "--workspace", str(workspace), *extra, "go"],
    )
    assert result.exit_code == 0, result.output

    # The raw relative write landed IN the workspace, not the launch dir.
    assert (workspace / "probe_out.txt").exists(), "relative write did not land in the workspace"
    assert not (launch / "probe_out.txt").exists(), "relative write leaked into the launch dir"

    # And the agent's actual os.getcwd() during the turn WAS the resolved workspace —
    # the file's contents are that cwd.
    reported = Path((workspace / "probe_out.txt").read_text(encoding="utf-8"))
    assert reported.resolve() == workspace.resolve()

    # Nice-to-have (gh #110): the CLI restores the caller's prior cwd after the turn, so a
    # library/embedded caller of the chat path isn't left with a changed cwd.
    assert Path(os.getcwd()).resolve() == launch.resolve()
