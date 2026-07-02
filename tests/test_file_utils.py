"""Tests for read_file_content in file_utils."""

import pytest
from langstage.file_utils import read_file_content


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "hello.py").write_text("print('hello')")
    (tmp_path / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "bad_encoding.py").write_bytes(b"\xff\xfe\x00\x01")
    return tmp_path


def test_read_file_content_text_file(workspace):
    content, is_text, error = read_file_content(workspace, "hello.py")
    assert content == "print('hello')"
    assert is_text is True
    assert error is None


def test_read_file_content_not_found(workspace):
    content, is_text, error = read_file_content(workspace, "nonexistent.py")
    assert content is None
    assert is_text is False
    assert error == "File not found"


def test_read_file_content_binary_extension(workspace):
    content, is_text, error = read_file_content(workspace, "cover.png")
    assert content is None
    assert is_text is False
    assert error == "Binary file - download to view"


def test_read_file_content_invalid_utf8(workspace):
    """A text-extension file with bytes that aren't valid UTF-8 should
    report a decode error rather than raising or returning garbage."""
    content, is_text, error = read_file_content(workspace, "bad_encoding.py")
    assert content is None
    assert is_text is False
    assert error == "Binary file - cannot display"
