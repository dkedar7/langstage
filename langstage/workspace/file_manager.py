"""File tree building, file reading, and filesystem watching."""

import base64
import csv
import io
import mimetypes
import os
import shutil
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import quote

from watchfiles import awatch, Change

from ..file_utils import TEXT_EXTENSIONS


# Extensions → CodeMirror language modes
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".r": "r",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".csv": "csv",
    ".txt": "text",
}

# Directories to skip in the file tree
SKIP_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".egg-info",
}


class BinaryFileError(ValueError):
    """``read_file`` was asked for a file that isn't UTF-8 text (gh #144).

    ``/api/files/read`` returns text, so a binary is refused rather than lossily
    decoded. ``/api/files/preview`` and ``/api/files/download`` serve binaries.
    """


def _download_url(path: str) -> str:
    """The ``/api/files/download`` link for ``path``, with the query encoded (gh #163).

    Raw interpolation broke on a space and sent ``&``/``+``/``#``/``%`` names to
    the wrong path. ``safe="/"`` keeps separators readable and escapes the rest.
    """
    return f"/api/files/download?path={quote(path, safe='/')}"


class FileChangeEvent:
    """Represents a filesystem change event."""

    def __init__(self, event_type: str, path: str):
        self.event_type = event_type  # "created", "modified", "deleted"
        self.path = path


class FileManager:
    """Reads the workspace directory for the file browser UI."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def get_tree(self, path: str = "/", depth: int = 1) -> dict:
        """Return directory listing with lazy loading support."""
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        entries = self._list_dir(target, depth=depth, current_depth=0)
        return {
            "entries": entries,
            "root": str(path),
        }

    def _list_dir(self, dir_path: Path, depth: int, current_depth: int) -> list[dict]:
        """Recursively list directory entries."""
        entries = []
        try:
            items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return entries

        for item in items:
            if item.name.startswith("."):
                continue
            if item.is_dir() and item.name in SKIP_DIRS:
                continue
            # Apply _resolve_path's containment rule to every child, not just the entry
            # dir: an entry whose real location is OUTSIDE the workspace (a symlink, or a
            # Windows junction) is omitted entirely, so the walk never lists, stats, or
            # descends into its target. Without this, the lexical relative_to() below
            # accepted workspace/leak/... and is_dir()/iterdir() followed the link,
            # enumerating arbitrary host paths. (gh #148)
            if not self._is_contained(item):
                continue

            rel_path = "/" + str(item.relative_to(self.workspace))
            entry: dict = {
                "name": item.name,
                "path": rel_path,
                "is_dir": item.is_dir(),
            }

            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    entry["size"] = None

            if item.is_dir() and current_depth < depth - 1:
                entry["children"] = self._list_dir(item, depth, current_depth + 1)

            entries.append(entry)

        return entries

    # File type classification
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
    _HTML_EXTS = {".html", ".htm"}
    _CSV_EXTS = {".csv", ".tsv"}
    # Union of the two independent text-file allowlists so preview and read agree on
    # what counts as text: every syntax-highlightable extension (LANGUAGE_MAP) PLUS
    # everything the read path's is_text_file / TEXT_EXTENSIONS treats as text
    # (.log/.ini/.cfg/.conf/.env/...). Sharing TEXT_EXTENSIONS is the single source of
    # truth that keeps the two detectors from drifting apart again (gh #114).
    _TEXT_EXTS = set(LANGUAGE_MAP.keys()) | TEXT_EXTENSIONS

    def read_file(self, path: str) -> dict:
        """Read a UTF-8 text file exactly as it is on disk, with language detection.

        The bytes are decoded as-is, with no newline translation, so CRLF stays CRLF,
        and ``size`` is the byte size that tree/upload/download report. A file that
        isn't UTF-8 text (or contains a NUL byte) raises :class:`BinaryFileError`
        instead of coming back as lossily decoded "text". (gh #144)
        """
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if target.is_dir():
            raise IsADirectoryError(f"Path is a directory: {path}")

        raw = target.read_bytes()
        try:
            if b"\x00" in raw:
                raise UnicodeError
            content = raw.decode("utf-8")
        except UnicodeError:
            raise BinaryFileError(
                f"Not a UTF-8 text file: {path}. Use /api/files/preview or "
                "/api/files/download for binary files."
            ) from None
        lang = LANGUAGE_MAP.get(target.suffix.lower(), "text")
        return {
            "content": content,
            "language": lang,
            "size": len(raw),
            "path": path,
        }

    def preview_file(self, path: str) -> dict:
        """Return a structured preview for any file type.

        Returns dict with:
            preview_type: "text" | "image" | "html" | "csv" | "pdf" | "binary"
            data: type-specific payload
            path, name, size, language
        """
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if target.is_dir():
            raise IsADirectoryError(f"Path is a directory: {path}")

        ext = target.suffix.lower()
        stat = target.stat()
        base = {
            "path": path,
            "name": target.name,
            "size": stat.st_size,
        }

        # Images → base64
        if ext in self._IMAGE_EXTS:
            img_bytes = target.read_bytes()
            mime = mimetypes.guess_type(target.name)[0] or "image/png"
            return {
                **base,
                "preview_type": "image",
                "mime": mime,
                "data": base64.b64encode(img_bytes).decode("utf-8"),
            }

        # HTML → raw HTML string for iframe
        if ext in self._HTML_EXTS:
            return {
                **base,
                "preview_type": "html",
                "language": "html",
                "data": target.read_text(errors="replace"),
            }

        # CSV/TSV → first 50 rows as records + full text
        if ext in self._CSV_EXTS:
            # Decode the bytes as-is (no newline translation) and parse with the csv
            # module, so RFC-4180 quoting works: a quoted cell holding the delimiter
            # or a newline no longer splits into extra columns and drops the row,
            # and the quote characters are stripped. (gh #154)
            text = target.read_bytes().decode("utf-8", errors="replace")
            sep = "\t" if ext == ".tsv" else ","
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=sep)
            headers: list[str] = []
            rows = []
            try:
                headers = next(reader, [])
                for vals in reader:
                    if len(rows) >= 50:  # max 50 rows for preview
                        break
                    if not vals:  # blank line
                        continue
                    # A ragged row is padded / trimmed to the header, not dropped.
                    vals = (vals + [""] * len(headers))[: len(headers)]
                    rows.append(dict(zip(headers, vals)))
            except csv.Error:
                pass  # malformed tail: keep the rows parsed so far
            return {
                **base,
                "preview_type": "csv",
                "language": "csv",
                "headers": headers,
                "rows": rows,
                "data": text,
            }

        # PDF → base64 for browser-native rendering
        if ext == ".pdf":
            pdf_bytes = target.read_bytes()
            return {
                **base,
                "preview_type": "pdf",
                "data": base64.b64encode(pdf_bytes).decode("utf-8"),
                "download_url": _download_url(path),
            }

        # Text files → read as text with language
        if ext in self._TEXT_EXTS or ext == "":
            try:
                content = target.read_text(encoding="utf-8")
                lang = LANGUAGE_MAP.get(ext, "text")
                return {
                    **base,
                    "preview_type": "text",
                    "language": lang,
                    "data": content,
                }
            except UnicodeDecodeError:
                pass  # fall through to binary

        # Binary fallback
        return {
            **base,
            "preview_type": "binary",
            "download_url": _download_url(path),
        }

    def get_absolute_path(self, path: str) -> Path:
        """Resolve and return the absolute path (for file serving)."""
        return self._resolve_path(path)

    def create_directory(self, path: str) -> dict:
        """Create a new directory."""
        target = self._resolve_path(path)
        if target.exists():
            raise FileExistsError(f"Path already exists: {path}")
        target.mkdir(parents=True, exist_ok=False)
        return {"path": path, "name": target.name}

    def save_upload(self, path: str, content: bytes) -> dict:
        """Write uploaded file content to the workspace."""
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {"path": path, "name": target.name, "size": len(content)}

    def delete_path(self, path: str) -> dict:
        """Delete a file or directory (recursively).

        A symlink (or Windows junction) is removed itself, never its target: the old
        code resolved the link first, so deleting ``link -> data/`` deleted ``data/``.
        (gh #175)
        """
        link = self._unresolved_link(path)
        if link is not None:
            _remove_link(link)
            return {"path": path, "name": link.name}

        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        # Prevent deleting the workspace root
        if target == self.workspace:
            raise ValueError("Cannot delete workspace root")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"path": path, "name": target.name}

    async def watch(self) -> AsyncGenerator[FileChangeEvent, None]:
        """Yield file change events using watchfiles.

        Used to push file_changed events over WebSocket when the
        agent modifies files.
        """
        async for changes in awatch(self.workspace):
            for change_type, change_path in changes:
                try:
                    rel_path = "/" + str(Path(change_path).relative_to(self.workspace))
                except ValueError:
                    continue

                # Skip hidden/ignored directories
                parts = Path(change_path).relative_to(self.workspace).parts
                if any(p in SKIP_DIRS or (p.startswith(".") and p != ".canvas") for p in parts):
                    continue

                event_type = {
                    Change.added: "created",
                    Change.modified: "modified",
                    Change.deleted: "deleted",
                }.get(change_type, "modified")

                yield FileChangeEvent(event_type=event_type, path=rel_path)

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path to an absolute path within the workspace."""
        clean = path.lstrip("/")
        if clean:
            resolved = (self.workspace / clean).resolve()
        else:
            resolved = self.workspace

        # Confine to the workspace by path containment, NOT a string prefix. A bare
        # startswith() match has no path-separator boundary, so a *sibling* directory
        # that shares the workspace's name as a prefix (ws-secret, ws.bak, ws2, ...)
        # slips through and becomes readable/writable/deletable via ../-relative
        # paths. is_relative_to() is true only for the workspace itself or a real
        # descendant. (gh #41)
        if not resolved.is_relative_to(self.workspace):
            raise ValueError(f"Path escapes workspace: {path}")
        return resolved

    def _unresolved_link(self, path: str) -> Path | None:
        """The link at ``path`` itself (not followed) if it is a symlink/junction.

        Only the parent is resolved. #148's containment rule applies to where the
        LINK lives: its parent must resolve inside the workspace, so a link reached
        through an escaping directory link returns None (and ``_resolve_path`` then
        rejects the path).
        """
        lexical = self.workspace / path.lstrip("/")
        if lexical == self.workspace or lexical.name in ("", ".", ".."):
            return None
        try:
            parent = lexical.parent.resolve()
        except (OSError, RuntimeError):
            return None
        if not parent.is_relative_to(self.workspace):
            return None
        candidate = parent / lexical.name
        if candidate.is_symlink() or _is_junction(candidate):
            return candidate
        return None

    def _is_contained(self, path: Path) -> bool:
        """True if ``path``'s real (symlink-resolved) location is inside the workspace."""
        try:
            return path.resolve().is_relative_to(self.workspace)
        except (OSError, RuntimeError):  # unresolvable (e.g. a symlink loop)
            return False


def _is_junction(path: Path) -> bool:
    """True for a Windows directory junction (``Path.is_junction`` is 3.12+)."""
    check = getattr(path, "is_junction", None)
    try:
        return bool(check()) if check else False
    except OSError:
        return False


def _remove_link(link: Path) -> None:
    """Remove a symlink or junction without touching its target.

    On Windows a directory symlink or junction is removed with ``rmdir``, which
    drops the link itself and never recurses. Everything else is ``unlink``.
    """
    if os.name == "nt" and (_is_junction(link) or link.is_dir()):
        os.rmdir(link)
    else:
        link.unlink()
