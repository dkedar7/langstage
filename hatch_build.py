"""Hatchling wheel build hook: bundle the built React SPA into the wheel (gh #94).

Why this exists
---------------
The web UI is a Vite/React app under ``frontend/``. Its build output lands in
``langstage/static/`` (see ``frontend/vite.config.ts``), which is git-ignored — so that
directory is empty in a fresh clone and in the unpacked sdist. The
``[tool.hatch.build] artifacts = ["langstage/static/**"]`` line in ``pyproject.toml`` only
*re-includes* git-ignored files that already exist at build time; it never creates them.
So a plain ``uv build`` (the manual release path) produced a wheel with no
``langstage/static/`` at all — ``pip install langstage`` shipped no frontend and ``GET /``
served the JSON placeholder instead of the SPA (regression in 0.13.20–0.13.23).

What it does
------------
For a real (non-editable) wheel build, it guarantees ``langstage/static/index.html`` exists
before the archive is assembled (``artifacts`` then bundles the tree):

* **skip-if-exists** — if the SPA is already built (a CI tree that ran ``npm run build``, or
  a prior local build), do nothing. No Node needed.
* otherwise run ``npm ci && npm run build`` in ``frontend/`` to produce it.
* **publish guard** — if ``index.html`` still isn't present afterwards, fail the build so an
  empty-UI wheel can never reach PyPI again.

Skipped for the ``sdist`` target and for ``editable`` installs (``pip install -e``): the
Python test suite and the dev loop don't need the compiled SPA, so those paths never
require Node. Set ``LANGSTAGE_SKIP_FRONTEND_BUILD=1`` to force-skip the build (e.g. a
Node-less ``pip install .`` that only exercises the backend, as the CI minimal-install job
does).

The core is factored into :func:`build_frontend_into_wheel` so it is unit-testable without
constructing a Hatchling interface (see ``tests/test_frontend_packaging.py``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ModuleNotFoundError:  # hatchling lives in the build env, not the runtime/test venv
    BuildHookInterface = object  # type: ignore[assignment,misc]

_TRUTHY = {"1", "true", "yes", "on"}


def _skip_env_set() -> bool:
    return os.environ.get("LANGSTAGE_SKIP_FRONTEND_BUILD", "").strip().lower() in _TRUTHY


def build_frontend_into_wheel(
    root: str | os.PathLike[str],
    target_name: str,
    version: str,
    *,
    display: Callable[[str], None] | None = None,
) -> str:
    """Ensure the built SPA exists at ``<root>/langstage/static`` for a wheel build.

    Returns a short status token describing what happened:
    ``"skip:not-wheel"``, ``"skip:editable"``, ``"skip:prebuilt"``, ``"skip:env"``, or
    ``"built"``. Raises ``RuntimeError`` if it must build but can't, or if the build
    produced no ``index.html`` (the publish guard).
    """
    log = display or (lambda _msg: None)

    # Only the wheel carries runtime assets; the sdist just ships source.
    if target_name != "wheel":
        return "skip:not-wheel"
    # Editable installs (`pip install -e`) build an "editable" wheel — the dev loop and the
    # Python test suite don't need the compiled SPA, so never require Node.
    if version == "editable":
        return "skip:editable"

    root = Path(root)
    static_dir = root / "langstage" / "static"
    index_html = static_dir / "index.html"

    if index_html.is_file():
        log(f"langstage: using pre-built frontend at {static_dir}")
        return "skip:prebuilt"

    if _skip_env_set():
        log(
            "langstage: LANGSTAGE_SKIP_FRONTEND_BUILD set — building a backend-only wheel "
            "with NO frontend (GET / will serve the JSON placeholder)."
        )
        return "skip:env"

    _run_npm_build(root, log)

    if not index_html.is_file():
        raise RuntimeError(
            "langstage build hook: the frontend build finished but "
            f"{index_html} is missing — refusing to build a no-UI wheel (gh #94)."
        )
    log(f"langstage: bundled built frontend from {static_dir}")
    return "built"


def _run_npm_build(root: Path, log: Callable[[str], None]) -> None:
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        raise RuntimeError(
            "langstage build hook: no frontend/ source to build and no pre-built "
            f"langstage/static/index.html present (looked in {frontend}). Build the SPA first "
            "(cd frontend && npm ci && npm run build), or set LANGSTAGE_SKIP_FRONTEND_BUILD=1 "
            "for a backend-only wheel."
        )

    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "langstage build hook: `npm` not found on PATH — Node.js is required to build the "
            "bundled frontend. Install Node, or pre-build the SPA (cd frontend && npm run "
            "build), or set LANGSTAGE_SKIP_FRONTEND_BUILD=1 for a backend-only wheel."
        )

    install = "ci" if (frontend / "package-lock.json").is_file() else "install"
    log(f"langstage: building frontend (npm {install} && npm run build) in {frontend}…")
    subprocess.run([npm, install], cwd=str(frontend), check=True)
    subprocess.run([npm, "run", "build"], cwd=str(frontend), check=True)


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        build_frontend_into_wheel(
            self.root,
            self.target_name,
            version,
            display=self.app.display_info,
        )
