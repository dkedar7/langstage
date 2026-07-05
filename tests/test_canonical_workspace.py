"""Regression: the default agent's workspace honors canonical
LANGSTAGE_WORKSPACE_ROOT, not only the deprecated DEEPAGENT_WORKSPACE_ROOT
(dogfood cluster 2).

``default_agent.workspace_root`` is resolved at import time, so each case runs a
subprocess with the env set first.
"""
import os
import subprocess
import sys


def _workspace_root(env_overrides: dict) -> str:
    env = dict(os.environ)
    for k in list(env):
        if k.endswith("WORKSPACE_ROOT"):
            del env[k]
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", "import langstage.default_agent as d; print(d.workspace_root)"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_canonical_workspace_root_is_honored(tmp_path):
    target = str(tmp_path / "canon")
    assert _workspace_root({"LANGSTAGE_WORKSPACE_ROOT": target}) == target


def test_canonical_beats_legacy(tmp_path):
    canon = str(tmp_path / "canon")
    legacy = str(tmp_path / "legacy")
    got = _workspace_root(
        {"LANGSTAGE_WORKSPACE_ROOT": canon, "DEEPAGENT_WORKSPACE_ROOT": legacy}
    )
    assert got == canon


def test_legacy_still_works(tmp_path):
    legacy = str(tmp_path / "legacy")
    assert _workspace_root({"DEEPAGENT_WORKSPACE_ROOT": legacy}) == legacy


def _config_and_tools_and_agent_roots(env_overrides: dict) -> tuple[str, str, str]:
    """Return (config.WORKSPACE_ROOT, tools.WORKSPACE_ROOT, agent.workspace_root)
    — all resolved at import, so run a subprocess with the env set first."""
    env = dict(os.environ)
    for k in list(env):
        if k.endswith("WORKSPACE_ROOT"):
            del env[k]
    env.update(env_overrides)
    code = (
        "import langstage.config as c, langstage.tools as t, langstage.default_agent as d;"
        "print(c.WORKSPACE_ROOT); print(t.WORKSPACE_ROOT); print(d.workspace_root)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    cfg, tools, agent = out.stdout.strip().splitlines()[-3:]
    return cfg, tools, agent


def test_config_tools_agent_agree_on_canonical_workspace(tmp_path):
    """No split-brain: config.WORKSPACE_ROOT (the bash cwd via tools) and the
    agent's workspace must both honor canonical LANGSTAGE_WORKSPACE_ROOT and
    agree — config.py used to read only the legacy name (gh #-dogfood)."""
    from pathlib import Path

    target = str(tmp_path / "canon")
    cfg, tools, agent = _config_and_tools_and_agent_roots(
        {"LANGSTAGE_WORKSPACE_ROOT": target}
    )
    assert Path(cfg) == Path(target), f"config.WORKSPACE_ROOT ignored canonical: {cfg}"
    assert Path(tools) == Path(target), f"bash cwd ignored canonical: {tools}"
    assert Path(agent) == Path(target)
    assert Path(cfg) == Path(tools) == Path(agent)  # no split-brain


def test_config_workspace_root_is_live_view_of_source_of_truth(tmp_path):
    """ADR 0005: config.WORKSPACE_ROOT is a *live view* of core.workspace_root(),
    not a separate mutable mirror — so the file browser and the agent tools can't
    drift apart (the #44 split-brain is structurally impossible). Run in a
    subprocess so the process-global workspace can't leak.
    """
    import os as _os

    ws = tmp_path / "applied"
    code = (
        "from langstage_core import apply_workspace, workspace_root;"
        "import langstage.config as c;"
        f"apply_workspace(r'{ws}');"
        # After apply, the module attribute reflects the source of truth with no
        # separate assignment — reading it again tracks a re-apply.
        "print('CFG=' + str(c.WORKSPACE_ROOT));"
        "print('SRC=' + str(workspace_root()))"
    )
    env = {k: v for k, v in _os.environ.items() if not k.endswith("WORKSPACE_ROOT")}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    cfg = next(line[4:] for line in out.stdout.splitlines() if line.startswith("CFG="))
    src = next(line[4:] for line in out.stdout.splitlines() if line.startswith("SRC="))
    assert cfg == src == str(ws.resolve())


def test_cli_workspace_reaches_agent_bash(tmp_path):
    """--workspace / CoworkApp(workspace=) must reach the agent's bash tool, not
    just the file browser. Previously only the env var (lowest documented
    priority) reached the agent; CLI/TOML/Python were dropped. (gh #44)

    Run in a subprocess so the global config.WORKSPACE_ROOT mutation can't leak.
    """
    launch = tmp_path / "launch"
    project = launch / "project"
    project.mkdir(parents=True)
    agent = launch / "bashpwd.py"
    agent.write_text(
        "from langgraph.graph import StateGraph, MessagesState, START, END\n"
        "from langchain_core.messages import AIMessage\n"
        "from langstage.tools import bash\n"
        "def respond(s):\n"
        "    return {'messages': [AIMessage(content=bash('pwd')['stdout'].strip())]}\n"
        "b = StateGraph(MessagesState); b.add_node('respond', respond)\n"
        "b.add_edge(START, 'respond'); b.add_edge('respond', END)\n"
        "graph = b.compile()\n"
    )
    code = (
        f"from langstage import CoworkApp; "
        f"CoworkApp(agent_spec=r'{agent}:graph', workspace='./project', port=8190); "
        "import langstage.config as cfg; from langstage.tools import bash; "
        "print('WS=' + str(cfg.WORKSPACE_ROOT)); "
        "print('BASH=' + bash('pwd')['stdout'].strip())"
    )
    env = {k: v for k, v in os.environ.items() if not k.endswith("WORKSPACE_ROOT")}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(launch), env=env, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    ws = next(line[3:] for line in out.stdout.splitlines() if line.startswith("WS="))
    bashpwd = next(line[5:] for line in out.stdout.splitlines() if line.startswith("BASH="))
    # Both the tools' workspace and the agent's bash cwd resolve to ./project,
    # not the launch cwd.
    assert os.path.basename(ws.rstrip("/\\")) == "project", ws
    assert os.path.basename(bashpwd.rstrip("/")) == "project", bashpwd


def test_run_enters_workspace_cwd(tmp_path):
    """ADR 0006: run() chdirs to the resolved workspace so a bring-your-own agent's
    raw relative file writes land in the workspace (visible in the file browser), not
    the server's launch cwd. Construction itself must NOT chdir (embedding side effect)."""
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langstage import CoworkApp

    def _n(s):
        return {"messages": []}

    b = StateGraph(MessagesState)
    b.add_node("n", _n)
    b.add_edge(START, "n")
    b.add_edge("n", END)

    ws = tmp_path / "ws"
    origin = os.getcwd()
    try:
        app = CoworkApp(agent=b.compile(), workspace=str(ws))
        # Constructing does not move cwd...
        assert os.getcwd() == origin
        # ...run()'s enter-workspace step does.
        app._enter_workspace()
        from pathlib import Path
        assert Path(os.getcwd()).resolve() == ws.resolve()
    finally:
        os.chdir(origin)
