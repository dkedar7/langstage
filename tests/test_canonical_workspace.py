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
