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


# ── preview agrees with the read path on what counts as text (gh #114) ────────
# The file browser renders via GET /api/files/preview, which classified plain-text
# .log/.ini/.cfg/.conf as "binary" (download-only) because preview's LANGUAGE_MAP
# and the read path's is_text_file / TEXT_EXTENSIONS disagreed. They now share
# TEXT_EXTENSIONS as one source of truth, so both detectors agree.


@pytest.mark.parametrize(
    "name,body",
    [
        ("server.log", "INFO server started\nWARN low disk\n"),
        ("settings.ini", "[server]\nhost = localhost\n"),
        ("app.cfg", "key = value\n"),
        ("nginx.conf", "server { listen 80; }\n"),
    ],
)
def test_plain_text_configs_and_logs_preview_as_text_not_binary(tmp_path, name, body):
    (tmp_path / name).write_text(body)
    preview = FileManager(tmp_path).preview_file(name)
    assert preview["preview_type"] == "text", preview
    assert preview["data"] == body  # content is inlined, not a download-only stub
    assert "download_url" not in preview


def test_preview_and_is_text_file_agree_for_the_regressed_extensions(tmp_path):
    # The core invariant of gh #114: is_text_file(f) True ⇒ preview shows text.
    from langstage.file_utils import is_text_file

    for name in ("a.log", "b.ini", "c.cfg", "d.conf"):
        (tmp_path / name).write_text("plain text\n")
        assert is_text_file(name) is True
        assert FileManager(tmp_path).preview_file(name)["preview_type"] == "text"


def test_genuinely_binary_file_still_previews_as_binary(tmp_path):
    # The text-detector union must not loosen the guard for real binaries.
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
    preview = FileManager(tmp_path).preview_file("blob.bin")
    assert preview["preview_type"] == "binary"
    assert "download_url" in preview


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


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as e:  # e.g. Windows without symlink privilege
        pytest.skip(f"cannot create symlinks here: {e}")


@pytest.fixture
def escaping_symlinks(tmp_path):
    """A workspace holding one dir symlink and one file symlink that point OUTSIDE it,
    plus one symlink that stays inside (gh #148 repro)."""
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    (ws / "sub" / "normal.txt").write_text("inside")
    outside = tmp_path / "SECRET_OUTSIDE"
    (outside / "private").mkdir(parents=True)
    (outside / "private" / "secret.txt").write_text("TOP SECRET")
    (outside / "passwords.txt").write_text("creds")
    _symlink_or_skip(ws / "leak", outside)
    _symlink_or_skip(ws / "leaked_file", outside / "passwords.txt")
    _symlink_or_skip(ws / "inner_link", ws / "sub")
    return ws


def _all_names(entries):
    for e in entries:
        yield e["name"]
        yield from _all_names(e.get("children") or [])


def test_tree_does_not_follow_symlinks_out_of_the_workspace(escaping_symlinks):
    """The recursive tree walk must honor the same containment rule as every
    single-path route: a symlink resolving outside the workspace is neither listed
    nor descended into, so no out-of-workspace name/structure/size leaks. (gh #148)"""
    fm = FileManager(escaping_symlinks)
    for depth in (1, 3):
        entries = fm.get_tree("/", depth=depth)["entries"]
        names = set(_all_names(entries))
        assert "leak" not in names
        assert "leaked_file" not in names
        assert not names & {"private", "secret.txt", "passwords.txt"}
        # In-workspace entries (incl. a symlink that stays inside) are still listed.
        assert {"sub", "inner_link"} <= names
    deep = fm.get_tree("/", depth=2)["entries"]
    inner = next(e for e in deep if e["name"] == "inner_link")
    assert [c["name"] for c in inner["children"]] == ["normal.txt"]


def test_single_path_routes_reject_escaping_symlinks(escaping_symlinks):
    """Every sibling files operation resolves symlinks before the containment check
    (gh #148 audit): none can read, stat, write through, or delete an escaping link."""
    fm = FileManager(escaping_symlinks)
    ops = [
        lambda: fm.get_tree("leak"),
        lambda: fm.read_file("leak/passwords.txt"),
        lambda: fm.read_file("leaked_file"),
        lambda: fm.preview_file("leaked_file"),
        lambda: fm.get_absolute_path("leak/passwords.txt"),
        lambda: fm.create_directory("leak/newdir"),
        lambda: fm.save_upload("leak/planted.txt", b"x"),
        lambda: fm.save_upload("leaked_file", b"overwrite"),
        lambda: fm.delete_path("leak/passwords.txt"),
    ]
    for op in ops:
        with pytest.raises(ValueError, match="escapes workspace"):
            op()
    outside = escaping_symlinks.parent / "SECRET_OUTSIDE"
    assert (outside / "passwords.txt").read_text() == "creds"
    assert not (outside / "newdir").exists()
    assert not (outside / "planted.txt").exists()
