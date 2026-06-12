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
