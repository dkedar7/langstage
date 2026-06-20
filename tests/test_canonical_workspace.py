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
