"""Workspace file search and no-overwrite uploads, for @-mentions in the chat (gh #238)."""

import inspect
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langstage.server.routes_files import create_files_router
from langstage.workspace.file_manager import FileManager


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    for rel in (
        "data/sales.csv",
        "data/sales_2025.csv",
        "data/raw/salesforce_export.json",
        "reports/q3/draft.md",
        "reports/q3/sales notes.md",
        "README.md",
        "archive/old_sales.csv",
        ".langstage/checkpoints.db",
        ".git/config",
        "node_modules/sales/index.js",
        ".venv/lib/sales.py",
    ):
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return ws


@pytest.fixture
async def client(workspace):
    app = FastAPI()
    app.include_router(create_files_router(FileManager(workspace)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _paths(body):
    return [r["path"] for r in body["results"]]


def _link_or_skip(link: Path, target: Path) -> None:
    """A directory link: a symlink, or on Windows without the privilege, a junction."""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError) as e:
        if sys.platform != "win32" or not target.is_dir():
            pytest.skip(f"cannot create symlinks here: {e}")
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("cannot create a junction here")


# ── ranking and filtering ────────────────────────────────────────────────────


async def test_name_matches_rank_first_and_paths_are_relative(client):
    body = (await client.get("/api/files/search", params={"q": "sal"})).json()
    paths = _paths(body)
    # Names that start with "sal", shortest first; then a name that only contains it.
    assert paths[:2] == ["data/sales.csv", "data/sales_2025.csv"]
    starts = {"reports/q3/sales notes.md", "data/raw/salesforce_export.json"}
    assert set(paths[2:4]) == starts
    assert paths[4] == "archive/old_sales.csv"
    assert all(not p.startswith("/") and "\\" not in p for p in paths)
    assert body["truncated"] is False
    hit = body["results"][0]
    assert hit == {"path": "data/sales.csv", "name": "sales.csv", "is_dir": False}


async def test_hidden_and_skipped_dirs_are_never_listed(client):
    for q in ("sales", "checkpoints", "config", "index", ""):
        paths = _paths((await client.get("/api/files/search", params={"q": q, "limit": 200})).json())
        assert not any(
            p.startswith((".langstage", ".git", "node_modules", ".venv")) for p in paths
        ), (q, paths)


async def test_every_word_must_match_and_case_is_ignored(client):
    paths = _paths((await client.get("/api/files/search", params={"q": "Q3 DRAFT"})).json())
    assert paths == ["reports/q3/draft.md"]
    assert _paths((await client.get("/api/files/search", params={"q": "nope"})).json()) == []


async def test_folders_are_results_too(client):
    body = (await client.get("/api/files/search", params={"q": "reports"})).json()
    assert body["results"][0] == {"path": "reports", "name": "reports", "is_dir": True}


async def test_empty_query_lists_nearest_the_root_first(client):
    paths = _paths((await client.get("/api/files/search", params={"limit": 3})).json())
    assert len(paths) == 3
    assert all("/" not in p for p in paths), paths  # top-level entries before nested ones


async def test_limit_is_bounded(client):
    assert len(_paths((await client.get("/api/files/search", params={"q": "s", "limit": 2})).json())) == 2
    assert (await client.get("/api/files/search", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/files/search", params={"limit": 10_000})).status_code == 422
    assert (await client.get("/api/files/search", params={"q": "x" * 201})).status_code == 422


# ── the workspace boundary ───────────────────────────────────────────────────


async def test_traversal_in_the_query_finds_nothing_outside(client, workspace):
    (workspace.parent / "secret.txt").write_text("s")
    for q in ("..", "../secret", "/etc/passwd", str(workspace.parent), "secret"):
        body = (await client.get("/api/files/search", params={"q": q})).json()
        assert all("secret" not in p and not p.startswith("..") for p in _paths(body)), (q, body)


def test_a_link_out_of_the_workspace_is_not_followed(tmp_path):
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deep" / "leak.txt").write_text("s")
    ws.mkdir()
    (ws / "ok.txt").write_text("x")
    _link_or_skip(ws / "escape", outside)
    paths = _paths(FileManager(ws).search("", limit=200)) + _paths(FileManager(ws).search("leak"))
    assert "ok.txt" in paths
    assert not any(p.startswith("escape") for p in paths), paths


def test_a_link_loop_is_walked_once(tmp_path):
    ws = tmp_path / "ws"
    (ws / "a").mkdir(parents=True)
    (ws / "a" / "file.txt").write_text("x")
    _link_or_skip(ws / "a" / "loop", ws / "a")
    body = FileManager(ws).search("file", limit=200)
    # The real file, and at most one copy reached through the link; never a/loop/loop/...
    assert "a/file.txt" in _paths(body)
    assert all(p.count("loop") <= 1 for p in _paths(body)), _paths(body)


def test_the_walk_stops_at_its_entry_and_time_limits(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(300):
        (ws / f"f{i:03}.txt").write_text("x")
    fm = FileManager(ws)
    body = fm.search("f", limit=200, max_entries=50)
    assert body["truncated"] is True
    assert len(body["results"]) <= 50

    t0 = time.monotonic()
    body = fm.search("f", limit=200, time_budget=-1.0)
    assert body["truncated"] is True
    assert time.monotonic() - t0 < 1.0


# ── uploads that never overwrite ─────────────────────────────────────────────


async def test_unique_upload_numbers_a_copy_instead_of_replacing(client, workspace):
    (workspace / "notes.md").write_text("original")
    paths = []
    for body in (b"one", b"two"):
        resp = await client.post(
            "/api/files/upload",
            params={"path": "/", "unique": "true"},
            files={"file": ("notes.md", body)},
        )
        assert resp.status_code == 200, resp.text
        paths.append(resp.json()["path"])
    assert paths == ["/notes (1).md", "/notes (2).md"]
    assert (workspace / "notes.md").read_text() == "original"
    assert (workspace / "notes (1).md").read_text() == "one"
    assert (workspace / "notes (2).md").read_text() == "two"


async def test_unique_upload_of_a_new_name_keeps_it(client, workspace):
    resp = await client.post(
        "/api/files/upload",
        params={"path": "data/", "unique": "true"},
        files={"file": ("fresh.csv", b"a,b")},
    )
    assert resp.json()["path"] == "/data/fresh.csv"
    assert (workspace / "data" / "fresh.csv").read_bytes() == b"a,b"


async def test_default_upload_still_replaces(client, workspace):
    (workspace / "notes.md").write_text("original")
    resp = await client.post(
        "/api/files/upload", params={"path": "/"}, files={"file": ("notes.md", b"new")}
    )
    assert resp.json()["path"] == "/notes.md"
    assert (workspace / "notes.md").read_text() == "new"


async def test_unique_upload_cannot_escape_the_workspace(client, workspace):
    for path, name in (("../", "evil.txt"), ("/", "../evil.txt"), ("/../x/", "evil.txt")):
        resp = await client.post(
            "/api/files/upload",
            params={"path": path, "unique": "true"},
            files={"file": (name, b"x")},
        )
        assert resp.status_code == 400, (path, name, resp.text)
    assert not (workspace.parent / "evil.txt").exists()


@pytest.mark.parametrize(
    "name,expected",
    [("notes.md", "notes (1).md"), ("Makefile", "Makefile (1)"), (".env", ".env (1)"), ("a.tar.gz", "a.tar (1).gz")],
)
def test_numbered_copy_names(tmp_path, name, expected):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / name).write_text("x")
    assert FileManager(ws).save_upload(name, b"y", unique=True)["name"] == expected


def test_search_route_does_not_block_the_event_loop():
    # A plain `def` route runs in FastAPI's thread pool; an `async def` walk would
    # stall the stream for the whole walk.
    router = create_files_router(FileManager(Path(os.getcwd())))
    route = next(r for r in router.routes if getattr(r, "path", "") == "/api/files/search")
    assert not inspect.iscoroutinefunction(route.endpoint)
