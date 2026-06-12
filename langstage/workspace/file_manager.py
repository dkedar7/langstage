"""File tree building, file reading, and filesystem watching."""

import base64
import mimetypes
import shutil
from pathlib import Path
from typing import AsyncGenerator

from watchfiles import awatch, Change


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
    _TEXT_EXTS = set(LANGUAGE_MAP.keys())  # all mapped extensions are text

    def read_file(self, path: str) -> dict:
        """Read file content with language detection."""
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if target.is_dir():
            raise IsADirectoryError(f"Path is a directory: {path}")

        content = target.read_text(errors="replace")
        lang = LANGUAGE_MAP.get(target.suffix.lower(), "text")
        return {
            "content": content,
            "language": lang,
            "size": len(content),
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
            text = target.read_text(errors="replace")
            sep = "\t" if ext == ".tsv" else ","
            rows = []
            lines = text.split("\n")
            if lines:
                headers = lines[0].split(sep)
                for line in lines[1:51]:  # max 50 rows for preview
                    vals = line.split(sep)
                    if len(vals) == len(headers):
                        rows.append(dict(zip(headers, vals)))
            return {
                **base,
                "preview_type": "csv",
                "language": "csv",
                "headers": headers if lines else [],
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
                "download_url": f"/api/files/download?path={path}",
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
            "download_url": f"/api/files/download?path={path}",
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
        """Delete a file or directory (recursively)."""
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

        # Ensure path is within workspace (prevent directory traversal)
        if not str(resolved).startswith(str(self.workspace)):
            raise ValueError(f"Path escapes workspace: {path}")
        return resolved
