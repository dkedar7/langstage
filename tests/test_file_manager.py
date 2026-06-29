"""Tests for FileManager."""

import pytest
from pathlib import Path
from langstage.workspace.file_manager import FileManager


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "hello.py").write_text("print('hello')")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content")
    return tmp_path


def test_get_tree(workspace):
    fm = FileManager(workspace)
    tree = fm.get_tree("/", depth=1)
    assert "entries" in tree
    names = [e["name"] for e in tree["entries"]]
    assert "hello.py" in names
    assert "subdir" in names


def test_get_tree_depth_2(workspace):
    fm = FileManager(workspace)
    tree = fm.get_tree("/", depth=2)
    subdir = next(e for e in tree["entries"] if e["name"] == "subdir")
    assert subdir["children"] is not None
    child_names = [c["name"] for c in subdir["children"]]
    assert "nested.txt" in child_names


def test_read_file(workspace):
    fm = FileManager(workspace)
    content = fm.read_file("/hello.py")
    assert content["content"] == "print('hello')"
    assert content["language"] == "python"


def test_read_file_not_found(workspace):
    fm = FileManager(workspace)
    with pytest.raises(FileNotFoundError):
        fm.read_file("/nonexistent.txt")


def test_directory_traversal_prevention(workspace):
    fm = FileManager(workspace)
    with pytest.raises(ValueError, match="escapes workspace"):
        fm.read_file("/../../../etc/passwd")


def test_csv_language(workspace):
    fm = FileManager(workspace)
    content = fm.read_file("/data.csv")
    assert content["language"] == "csv"


def test_sibling_prefix_dir_cannot_escape_workspace(tmp_path):
    """A sibling dir sharing the workspace's name prefix must NOT be reachable.

    The old guard used a plain str startswith() with no separator boundary, so
    `ws-secret` passed the check for workspace `ws` and a ../-relative path could
    read/write/delete outside the workspace. (gh #41 — path traversal)
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    sibling = tmp_path / "ws_secret"
    sibling.mkdir()
    (sibling / "passwd.txt").write_text("SECRET outside the workspace")
    (ws / "inside.txt").write_text("ok")

    fm = FileManager(ws)
    # Legitimate in-workspace access still works.
    assert fm._resolve_path("inside.txt").name == "inside.txt"
    assert fm._resolve_path("/").resolve() == ws.resolve()
    # Every traversal into the prefix-sharing sibling is rejected.
    for escape in ("../ws_secret/passwd.txt", "../ws_secret", "/../ws_secret/passwd.txt"):
        with pytest.raises(ValueError, match="escapes workspace"):
            fm._resolve_path(escape)
