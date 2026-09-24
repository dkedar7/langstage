"""Regression tests for the issues langstage-core 1.0.36 fixes at the root (Wave 2).

Each test replays its issue's repro on the web surface (the CLI command, or the
CoworkApp -> SessionAdapter path that feeds ``/api/stream`` / ``/api/chat/complete``).
Some causes were fixed in core and are only pinned here (#167, #166, #160, #136); the
rest also needed langstage changes (#170, #146, #140, #138, #134).
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langstage_core.adapters import SessionAdapter

from langstage import cli as cli_mod
from langstage.app import CoworkApp
from langstage.server.routes_chat import create_chat_router


def _write(path, body):
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _isolate_config(tmp_path, monkeypatch):
    """Empty global config dir, cwd = tmp_path, and no ambient LANGSTAGE_* / legacy env."""
    empty = tmp_path / "no-global"
    empty.mkdir(exist_ok=True)
    for var in list(os.environ):
        if var.startswith(("LANGSTAGE_", "DEEPAGENT_", "DEEPAGENTS_")):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(empty))
    monkeypatch.chdir(tmp_path)


def _client(agent):
    app = FastAPI()
    app.include_router(create_chat_router(SessionAdapter(graph=agent)))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _frames(agent, prompt="go"):
    """Drive one turn through the SessionAdapter that feeds /api/stream; return its frames."""
    adapter = SessionAdapter(graph=agent)
    session = adapter.submit_message("s1", prompt)
    await session.current_task
    out = []
    while not session.event_queue.empty():
        out.append(session.event_queue.get_nowait())
    return out


def _run_cli(args, env_extra, cwd):
    # PYTEST_CURRENT_TEST is dropped too: core silences the legacy notice under pytest.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGSTAGE_", "DEEPAGENT_", "DEEPAGENTS_", "PYTEST_"))}
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "langstage", *args],
        cwd=cwd, env=env, capture_output=True, timeout=120,
    )


# ── #167: a file.py:attr agent can import its sibling modules (fixed in core) ──────────


def _split_agent(tmp_path):
    proj = tmp_path / "myproj"
    proj.mkdir()
    _write(proj / "ls167_helpers.py", """
        from langchain_core.messages import AIMessage
        def reply(state):
            return {"messages": [AIMessage(content="hi from split agent")]}
    """)
    return _write(proj / "my_agent.py", """
        from langgraph.graph import StateGraph, START, END, MessagesState
        from ls167_helpers import reply
        _b = StateGraph(MessagesState)
        _b.add_node("reply", reply)
        _b.add_edge(START, "reply")
        _b.add_edge("reply", END)
        graph = _b.compile()
    """)


def test_167_check_loads_an_agent_with_a_sibling_import(tmp_path, monkeypatch):
    agent = _split_agent(tmp_path)
    monkeypatch.chdir(tmp_path)  # a different dir from the agent's
    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph"])
    assert result.exit_code == 0, result.output
    assert "No module named" not in result.output


async def test_167_web_turn_runs_an_agent_with_a_sibling_import(tmp_path):
    agent = _split_agent(tmp_path)
    app = CoworkApp(agent_spec=f"{agent}:graph", workspace=tmp_path / "ws")
    async with _client(app.agent) as c:
        r = await c.post("/api/chat/complete", json={"content": "hi"})
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "hi from split agent"


# ── #166: stdlib typing.TypedDict state works on every turn (fixed in core) ───────────
# Only meaningful on Python 3.11 (pydantic refuses typing.TypedDict below 3.12); CI's
# 3.11 job is the one that would fail without the fix.


async def test_166_stdlib_typeddict_state_answers_on_the_web_path(tmp_path):
    agent = _write(tmp_path / "td_agent.py", """
        from typing import Annotated, TypedDict
        from langgraph.graph import StateGraph, START, END
        from langgraph.graph.message import add_messages
        from langchain_core.messages import AIMessage

        class State(TypedDict):
            messages: Annotated[list, add_messages]

        def respond(state: State):
            return {"messages": [AIMessage(content="echo: " + state["messages"][-1].content)]}

        _b = StateGraph(State)
        _b.add_node("respond", respond); _b.add_edge(START, "respond"); _b.add_edge("respond", END)
        graph = _b.compile()
    """)
    app = CoworkApp(agent_spec=f"{agent}:graph", workspace=tmp_path / "ws")
    async with _client(app.agent) as c:
        r = await c.post("/api/chat/complete", json={"content": "hi"})
    assert r.status_code == 200, r.text
    assert "PydanticUserError" not in r.text
    assert r.json()["content"].startswith("echo: ")


# ── #160: tool_end carries a real duration_ms (fixed in core) ─────────────────────────


async def test_160_tool_end_frame_carries_a_real_duration(tmp_path):
    agent = _write(tmp_path / "toolagent.py", """
        from typing import Annotated
        from typing_extensions import TypedDict
        from langgraph.graph import StateGraph, START, END
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode
        from langchain_core.messages import AIMessage
        from langchain_core.tools import tool

        @tool
        def lookup(city: str) -> str:
            \"\"\"Look up the weather for a city.\"\"\"
            return f"The weather in {city} is sunny, 25C."

        class State(TypedDict):
            messages: Annotated[list, add_messages]

        def planner(state: State):
            if not any(getattr(m, "type", "") == "tool" for m in state["messages"]):
                return {"messages": [AIMessage(content="", tool_calls=[
                    {"name": "lookup", "args": {"city": "Paris"}, "id": "call_1"}])]}
            return {"messages": [AIMessage(content="Based on the tool: it's sunny in Paris.")]}

        def route(state: State):
            return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

        g = StateGraph(State)
        g.add_node("planner", planner)
        g.add_node("tools", ToolNode([lookup]))
        g.add_edge(START, "planner")
        g.add_conditional_edges("planner", route, {"tools": "tools", END: END})
        g.add_edge("tools", "planner")
        graph = g.compile()
    """)
    app = CoworkApp(agent_spec=f"{agent}:graph", workspace=tmp_path / "ws")
    ends = [f for f in await _frames(app.agent, "weather in Paris") if f.get("type") == "tool_end"]
    assert ends, "no tool_end frame"
    assert ends[0]["id"] == "call_1"
    duration = ends[0]["duration_ms"]
    assert isinstance(duration, (int, float)) and duration >= 0, ends[0]


# ── #140: --json stdout stays pure JSON under a noisy agent import ────────────────────

_NOISY = """
    print("[my-llm-lib] loaded weights v2.1")
    from langgraph.graph import StateGraph, START, END, MessagesState
    from langchain_core.messages import AIMessage
    def respond(state): return {"messages": [AIMessage(content="hi")]}
    _b = StateGraph(MessagesState)
    _b.add_node("respond", respond); _b.add_edge(START, "respond"); _b.add_edge("respond", END)
    graph = _b.compile(name="MyBot")
"""


def test_140_check_json_stdout_is_pure_json_for_a_noisy_agent(tmp_path):
    agent = _write(tmp_path / "noisy_check.py", _NOISY)
    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)  # the README's `| jq -e ...` gate
    assert report["loads"] and report["checks"]["canvas"] is not None
    assert "loaded weights" in result.stderr  # not lost, just off stdout


def test_140_chat_json_stdout_is_pure_json_for_a_noisy_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = _write(tmp_path / "noisy_chat.py", _NOISY)
    result = CliRunner().invoke(
        cli_mod.main,
        ["chat", "--agent", f"{agent}:graph", "--workspace", str(tmp_path / "ws"), "--json", "hi"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["content"] == "hi"
    assert "loaded weights" in result.stderr


# ── #170: a present-but-malformed langstage.toml is reported as such ──────────────────


def test_170_config_footer_names_a_malformed_toml(tmp_path, monkeypatch):
    _isolate_config(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text("[ui]\ntitle = MyAgent\n")  # unquoted value
    for args in (["config"], ["--show-config"]):
        result = CliRunner().invoke(cli_mod.main, args)
        assert result.exit_code == 0, result.output
        assert "no langstage.toml" not in result.stdout, args
        assert "MALFORMED" in result.stdout, args
        assert "langstage.toml" in result.stdout


def test_170_config_json_uses_core_config_dict(tmp_path, monkeypatch):
    _isolate_config(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text("[ui]\ntitle = MyAgent\n")
    result = CliRunner().invoke(cli_mod.main, ["config", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    toml = payload["toml"]
    assert toml["found"] is True and toml["malformed"] is True
    assert toml["malformed_files"][0]["path"].endswith("langstage.toml")
    assert any(i["kind"] == "malformed_toml" for i in payload["issues"])
    # Pre-1.0.36 keys kept for existing consumers.
    assert payload["toml_read_from"] == [] and payload["unknown_toml_keys"] == []


# ── #138: config --strict fails on every degraded / invalid value ─────────────────────


@pytest.mark.parametrize(
    "env,toml,kind",
    [
        ({"LANGSTAGE_PORT": "notanum"}, None, "malformed_value"),
        ({"LANGSTAGE_PORT": "70000"}, None, "invalid_value"),
        ({"LANGSTAGE_THEME": "chartreuse"}, None, "invalid_value"),
        ({"LANGSTAGE_SHOW_FILES": "flase"}, None, "malformed_value"),
        ({}, '[server]\nhost = localhost\nport = 8123\n', "malformed_toml"),
        ({}, '[ui]\ntheme = "chartreuse"\n', "invalid_value"),
        ({}, '[server]\nprt = 9000\n', "unknown_toml_key"),
    ],
    ids=["bad-port", "range-port", "bad-theme", "bad-bool", "malformed-toml",
         "toml-theme", "unknown-key"],
)
def test_138_config_strict_fails_on_each_issue(tmp_path, monkeypatch, env, toml, kind):
    _isolate_config(tmp_path, monkeypatch)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if toml:
        (tmp_path / "langstage.toml").write_text(toml)

    result = CliRunner().invoke(cli_mod.main, ["config", "--strict"])
    assert result.exit_code == 1, result.output
    assert "not clean" in result.stderr

    result = CliRunner().invoke(cli_mod.main, ["config", "--json", "--strict"])
    assert result.exit_code == 1, result.output
    assert kind in [i["kind"] for i in json.loads(result.stdout)["issues"]]


def test_138_config_strict_passes_a_clean_config(tmp_path, monkeypatch):
    _isolate_config(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text('[server]\nport = 9000\n[ui]\ntheme = "dark"\n')
    result = CliRunner().invoke(cli_mod.main, ["config", "--strict"])
    assert result.exit_code == 0, result.output
    assert json.loads(
        CliRunner().invoke(cli_mod.main, ["config", "--json"]).stdout
    )["issues"] == []


# ── #146 / #136: real subprocess, so the console encoding and the once-per-process
#    legacy notice behave as they do for a user ──────────────────────────────────────


@pytest.mark.parametrize("args", [["config"], ["--show-config"]])
def test_146_config_survives_a_cp1252_console(tmp_path, args):
    r = _run_cli(
        args,
        {"PYTHONIOENCODING": "cp1252", "LANGSTAGE_WELCOME_MESSAGE": "Welcome \U0001f44b",
         "LANGSTAGE_CONFIG_HOME": str(tmp_path)},
        tmp_path,
    )
    assert r.returncode == 0, r.stderr.decode("cp1252", "replace")
    out = r.stdout.decode("cp1252")
    assert "UnicodeEncodeError" not in r.stderr.decode("cp1252", "replace")
    assert "Welcome \\U0001f44b" in out  # escaped, not crashed


def test_136_deepagents_config_home_emits_the_legacy_notice(tmp_path):
    home = tmp_path / "gh"
    home.mkdir()
    (home / "config.toml").write_text('[ui]\ntitle = "FromLegacyHome"\n')
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_cli(["config"], {"DEEPAGENTS_CONFIG_HOME": str(home)}, proj)
    assert r.returncode == 0, r.stderr
    assert "FromLegacyHome" in r.stdout.decode()
    err = r.stderr.decode()
    assert "DEEPAGENTS_CONFIG_HOME" in err and "deprecated" in err.lower()
    assert err.count("DEEPAGENTS_CONFIG_HOME") == 1  # exactly one notice


# ── #134: `run --debug` puts the agent's crash traceback on the SSE error frame ──────

_ERR_AGENT = """
    from typing import Annotated
    from typing_extensions import TypedDict
    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.message import add_messages

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def boom(state):
        raise RuntimeError("intentional agent failure for dogfood test")

    g = StateGraph(State); g.add_node("boom", boom)
    g.add_edge(START, "boom"); g.add_edge("boom", END)
    graph = g.compile(); graph.name = "ErrAgent"
"""


async def _error_frame_from_run(tmp_path, monkeypatch, *flags):
    """`langstage run --agent erragent.py:graph [flags]`, with the server swapped for one
    turn through the app's agent on the SSE producer; returns the error frame."""
    monkeypatch.delenv("LANGSTAGE_DEBUG", raising=False)  # restored at teardown
    monkeypatch.delenv("DEEPAGENT_DEBUG", raising=False)
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    agent = _write(tmp_path / f"erragent{len(flags)}.py", _ERR_AGENT)
    apps = []
    monkeypatch.setattr(CoworkApp, "run", lambda self, open_browser=True: apps.append(self))
    result = CliRunner().invoke(
        cli_mod.main,
        ["run", "--agent", f"{agent}:graph", "--no-browser",
         "--workspace", str(tmp_path / "ws"), *flags],
    )
    assert result.exit_code == 0, result.output
    frames = await _frames(apps[0].agent)
    return next(f for f in frames if f.get("type") == "error")


async def test_134_run_debug_flag_surfaces_the_traceback(tmp_path, monkeypatch):
    err = await _error_frame_from_run(tmp_path, monkeypatch, "--debug")
    assert "intentional agent failure" in err["error"]
    assert "traceback" in err, err
    assert "erragent1.py" in err["traceback"] and "in boom" in err["traceback"]


async def test_134_without_debug_the_error_frame_has_no_traceback(tmp_path, monkeypatch):
    err = await _error_frame_from_run(tmp_path, monkeypatch)
    assert "intentional agent failure" in err["error"]
    assert "traceback" not in err
