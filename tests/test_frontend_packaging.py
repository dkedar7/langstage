"""The bundled frontend must ship in the wheel and be served at ``/`` (gh #94).

Regression guard for the 0.13.20–0.13.23 packaging bug: a clean ``pip install langstage``
shipped **no** ``langstage/static/`` at all, so ``GET /`` served the JSON placeholder
instead of the React SPA. Root cause was that the git-ignored ``langstage/static/`` tree
was never built before packaging and ``artifacts`` only *re-includes* files that already
exist. The fix is the ``hatch_build.py`` wheel build hook.

Most tests here are Node-free and deterministic — they exercise the hook's decision logic
and the server's static-vs-placeholder branch directly. One end-to-end test actually builds
a wheel and asserts the SPA is inside it; it skips unless the build tooling + a pre-built
frontend are present (as they are on a release machine / the CI e2e job).
"""

import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import hatch_build
import langstage.server.main as main_mod
from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATIC_INDEX = _PROJECT_ROOT / "langstage" / "static" / "index.html"


# ── pyproject wiring ─────────────────────────────────────────────────────────


def test_build_hook_registered_for_the_wheel_target():
    """pyproject must wire hatch_build.py as the wheel build hook — the mechanism that
    puts the SPA in the wheel. Before the fix there was no hook, only the (insufficient)
    artifacts glob."""
    with open(_PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        cfg = tomllib.load(fh)
    hook = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["hooks"]["custom"]
    assert hook["path"] == "hatch_build.py"
    assert (_PROJECT_ROOT / hook["path"]).is_file()
    # The artifacts glob that re-includes the built (git-ignored) tree is still present.
    assert "langstage/static/**" in cfg["tool"]["hatch"]["build"]["artifacts"]


# ── hook decision logic (Node-free) ──────────────────────────────────────────


def _no_npm(*_a, **_k):  # pragma: no cover - only hit if the guard is broken
    raise AssertionError("npm must not run on this path")


def test_hook_skips_when_frontend_already_built(tmp_path, monkeypatch):
    """skip-if-exists: a pre-built static/ tree is used as-is, no Node invoked."""
    (tmp_path / "langstage" / "static").mkdir(parents=True)
    (tmp_path / "langstage" / "static" / "index.html").write_text("<!doctype html>")
    monkeypatch.setattr(hatch_build.subprocess, "run", _no_npm)
    assert hatch_build.build_frontend_into_wheel(tmp_path, "wheel", "standard") == "skip:prebuilt"


def test_hook_skips_for_editable_installs(tmp_path, monkeypatch):
    """`pip install -e` (editable wheel) must never require Node — the dev/test loop
    doesn't need the compiled SPA."""
    monkeypatch.delenv("LANGSTAGE_SKIP_FRONTEND_BUILD", raising=False)
    monkeypatch.setattr(hatch_build.subprocess, "run", _no_npm)
    assert hatch_build.build_frontend_into_wheel(tmp_path, "wheel", "editable") == "skip:editable"


def test_hook_skips_for_sdist(tmp_path, monkeypatch):
    monkeypatch.setattr(hatch_build.subprocess, "run", _no_npm)
    assert hatch_build.build_frontend_into_wheel(tmp_path, "sdist", "standard") == "skip:not-wheel"


def test_hook_honours_skip_env(tmp_path, monkeypatch):
    """The escape hatch used by the CI minimal-install job: build a backend-only wheel
    without Node."""
    monkeypatch.setenv("LANGSTAGE_SKIP_FRONTEND_BUILD", "1")
    monkeypatch.setattr(hatch_build.subprocess, "run", _no_npm)
    assert hatch_build.build_frontend_into_wheel(tmp_path, "wheel", "standard") == "skip:env"


def test_hook_publish_guard_fails_when_it_cannot_build(tmp_path, monkeypatch):
    """The publish guard: a real wheel build with no pre-built SPA and nothing to build it
    from must FAIL loudly, so an empty-UI wheel can never reach PyPI again."""
    monkeypatch.delenv("LANGSTAGE_SKIP_FRONTEND_BUILD", raising=False)
    # Empty root: no langstage/static and no frontend/ source -> hard error.
    with pytest.raises(RuntimeError, match="frontend"):
        hatch_build.build_frontend_into_wheel(tmp_path, "wheel", "standard")


def test_hook_errors_when_npm_missing(tmp_path, monkeypatch):
    """A real wheel build that needs to compile the SPA but has no npm fails with an
    actionable message (rather than silently shipping no UI)."""
    monkeypatch.delenv("LANGSTAGE_SKIP_FRONTEND_BUILD", raising=False)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}")
    monkeypatch.setattr(hatch_build.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="npm"):
        hatch_build.build_frontend_into_wheel(tmp_path, "wheel", "standard")


# ── server: SPA vs placeholder branch (Node-free) ────────────────────────────


def _app_with_static(tmp_path, static_dir, monkeypatch):
    monkeypatch.setattr(main_mod, "_static_dir", lambda: static_dir)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    agent = MagicMock()
    agent.checkpointer = MagicMock()
    config = AppConfig(workspace_root=ws, title="T")
    return create_fastapi_app(agent=agent, workspace=ws, config=config)


def test_get_root_serves_the_spa_when_static_present(tmp_path, monkeypatch):
    """The behaviour a correctly-packaged wheel must deliver: GET / returns the real SPA
    HTML (not the JSON placeholder) and /assets/* serves the hashed bundle."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>'
    )
    (static / "assets" / "index-abc123.js").write_text("console.log('spa')")
    (static / "favicon.ico").write_bytes(b"\x00")

    client = TestClient(_app_with_static(tmp_path, static, monkeypatch))

    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert '<div id="root">' in r.text
    assert "LangStage backend is running" not in r.text  # NOT the placeholder

    asset = client.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert "spa" in asset.text


def test_get_root_is_the_json_placeholder_when_static_absent(tmp_path, monkeypatch):
    """Documents the broken-wheel symptom (#94): with no bundled static/, GET / falls back
    to the JSON placeholder. This is exactly what the packaging fix prevents in a release."""
    client = TestClient(_app_with_static(tmp_path, tmp_path / "nope", monkeypatch))
    r = client.get("/")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    assert r.json()["message"] == "LangStage backend is running."


# ── end-to-end: the built wheel actually contains the SPA ────────────────────


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs `uv` to build a wheel")
@pytest.mark.skipif(
    not _STATIC_INDEX.is_file(),
    reason="frontend not pre-built in this tree (run: cd frontend && npm ci && npm run build)",
)
def test_uv_build_wheel_bundles_the_spa(tmp_path):
    """The real thing the issue's RECORD check measured, inverted: a wheel built from this
    tree contains langstage/static/index.html + the hashed JS/CSS assets. Skips in the
    Node-less unit-test job; runs on a release machine / any tree with a built frontend."""
    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=str(_PROJECT_ROOT),
        check=True,
    )
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert "langstage/static/index.html" in names
    assert any(
        n.startswith("langstage/static/assets/") and n.endswith(".js") for n in names
    ), [n for n in names if "static" in n]
