"""File routes answer an OS refusal with a 4xx and a workspace path, not a 500 (gh #228)."""

import errno
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langstage.server.routes_files import _os_error, create_files_router
from langstage.workspace.file_manager import FileManager

LONG = "a" * 300


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "notes.txt").write_text("hi")
    return tmp_path


@pytest.fixture
async def client(workspace):
    app = FastAPI()
    app.include_router(create_files_router(FileManager(workspace)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _no_server_path(resp, workspace):
    detail = resp.json()["detail"]
    assert str(workspace) not in detail and workspace.as_posix() not in detail, detail
    return detail


async def test_mkdir_under_a_file_is_400_on_every_os(client, workspace):
    for resp in (
        await client.post("/api/files/mkdir", params={"path": "notes.txt/sub"}),
        await client.post("/api/files/mkdir", json={"path": "notes.txt/sub"}),
    ):
        # Linux used to 500 (NotADirectoryError); Windows said "Already exists" (409).
        assert resp.status_code == 400
        assert _no_server_path(resp, workspace) == "Not a directory: /notes.txt"
    assert not (workspace / "notes.txt").is_dir()


async def test_upload_under_a_file_names_the_workspace_path(client, workspace):
    resp = await client.post(
        "/api/files/upload",
        params={"path": "notes.txt/sub.txt"},
        files={"file": ("n.txt", b"x")},
    )
    assert resp.status_code == 400
    assert _no_server_path(resp, workspace) == "Not a directory: /notes.txt"


async def test_mkdir_and_upload_with_a_name_too_long(client, workspace):
    resp = await client.post("/api/files/mkdir", params={"path": LONG})
    assert resp.status_code == 400
    assert _no_server_path(resp, workspace).startswith("Invalid path, name too long: aaa")

    resp = await client.post(
        "/api/files/upload", params={"path": LONG}, files={"file": ("n.txt", b"x")}
    )
    assert resp.status_code == 400
    assert "name too long" in _no_server_path(resp, workspace)


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/api/files/tree"),
        ("get", "/api/files/read"),
        ("get", "/api/files/preview"),
        ("get", "/api/files/download"),
        ("post", "/api/files/delete"),
        ("delete", "/api/files/delete"),
    ],
)
async def test_lookups_with_a_name_too_long_are_not_500(client, workspace, method, url):
    resp = await getattr(client, method)(url, params={"path": LONG})
    # Linux raises ENAMETOOLONG from exists() (400); Windows just says it isn't there.
    assert resp.status_code in (400, 404), resp.text
    detail = _no_server_path(resp, workspace)
    if resp.status_code == 400:
        assert "name too long" in detail


@pytest.mark.skipif(sys.platform != "win32", reason="':' is a valid name character off Windows")
async def test_mkdir_with_an_invalid_windows_name(client, workspace):
    resp = await client.post("/api/files/mkdir", params={"path": "bad:name"})
    assert resp.status_code == 400
    assert _no_server_path(resp, workspace) == "Invalid path, not a valid file name: bad:name"


@pytest.mark.parametrize(
    "exc,status,detail",
    [
        (OSError(errno.ENAMETOOLONG, "File name too long", "/srv/ws/x"), 400, "name too long"),
        (OSError(errno.EINVAL, "Invalid argument", "/srv/ws/x"), 400, "not a valid file name"),
        (NotADirectoryError(errno.ENOTDIR, "Not a directory", "/srv/ws/x"), 400, "Not a directory: x"),
        (IsADirectoryError(errno.EISDIR, "Is a directory", "/srv/ws/x"), 400, "Path is a directory: x"),
        (FileNotFoundError(errno.ENOENT, "No such file", "/srv/ws/x"), 404, "Not found: x"),
        (FileExistsError(errno.EEXIST, "File exists", "/srv/ws/x"), 409, "Already exists: x"),
        (PermissionError(errno.EACCES, "Permission denied", "/srv/ws/x"), 403, "Permission denied: x"),
        (OSError(errno.EROFS, "Read-only file system", "/srv/ws/x"), 403, "Permission denied: x"),
        (OSError(errno.ENOSPC, "No space left", "/srv/ws/x"), 507, "Not enough space"),
        (OSError(errno.EIO, "Input/output error", "/srv/ws/x"), 500, "File system error"),
    ],
)
def test_os_error_mapping(exc, status, detail):
    http = _os_error(exc, "x")
    assert http.status_code == status
    assert detail in http.detail
    assert "/srv/ws" not in http.detail


def test_os_error_keeps_our_own_message_and_shortens_long_paths():
    assert _os_error(NotADirectoryError("Not a directory: /notes.txt"), "notes.txt/a").detail == (
        "Not a directory: /notes.txt"
    )
    shown = _os_error(FileNotFoundError(errno.ENOENT, "x"), LONG).detail
    assert shown.endswith("…") and len(shown) < 120
