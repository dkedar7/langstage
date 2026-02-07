"""File tree and file operations utilities.

Supports both physical filesystem (Path) and virtual filesystem (VirtualFilesystem)
for session isolation in multi-user deployments.
"""

import base64
from pathlib import Path, PurePosixPath
from typing import Tuple, Union, Optional

from .virtual_fs import VirtualFilesystem, VirtualPath


TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".md", ".txt",
    ".yaml", ".yml", ".toml", ".xml", ".csv", ".sh", ".bash", ".sql", ".env",
    ".gitignore", ".dockerignore", ".cfg", ".ini", ".conf", ".log"
}

# Type alias for paths that work with both physical and virtual filesystems
AnyPath = Union[Path, VirtualPath]
AnyRoot = Union[Path, VirtualFilesystem]


def is_text_file(filename: str) -> bool:
    """Check if a file can be viewed as text."""
    ext = Path(filename).suffix.lower()
    return ext in TEXT_EXTENSIONS or ext == ""


def _get_path(root: AnyRoot, path: str = "") -> AnyPath:
    """Get a path object from root, handling both Path and VirtualFilesystem."""
    if isinstance(root, VirtualFilesystem):
        return root.path(path) if path else root.root
    else:
        return root / path if path else root


def read_file_content(
    workspace_root: AnyRoot,
    path: str
) -> Tuple[Optional[str], bool, Optional[str]]:
    """Read file content. Returns (content, is_text, error)."""
    full_path = _get_path(workspace_root, path)

    if not full_path.exists() or not full_path.is_file():
        return None, False, "File not found"

    if is_text_file(path):
        try:
            content = full_path.read_text(encoding="utf-8")
            return content, True, None
        except UnicodeDecodeError:
            return None, False, "Binary file - cannot display"
        except Exception as e:
            return None, False, str(e)
    else:
        return None, False, "Binary file - download to view"


def get_file_download_data(
    workspace_root: AnyRoot,
    path: str
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Get file data for download. Returns (base64_content, filename, mime_type)."""
    full_path = _get_path(workspace_root, path)

    if not full_path.exists():
        return None, None, None

    try:
        content = full_path.read_bytes()
        b64 = base64.b64encode(content).decode('utf-8')

        # Determine MIME type
        ext = PurePosixPath(path).suffix.lower()
        mime_types = {
            # Text
            ".txt": "text/plain", ".py": "text/x-python", ".js": "text/javascript",
            ".json": "application/json", ".html": "text/html", ".htm": "text/html",
            ".css": "text/css", ".md": "text/markdown", ".csv": "text/csv",
            ".xml": "text/xml", ".yaml": "text/yaml", ".yml": "text/yaml",
            # Images
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
            ".ico": "image/x-icon", ".bmp": "image/bmp",
            # Video
            ".mp4": "video/mp4", ".webm": "video/webm", ".ogg": "video/ogg",
            ".mov": "video/quicktime",
            # Audio
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            # Documents
            ".pdf": "application/pdf",
            # Archives
            ".zip": "application/zip",
        }
        mime = mime_types.get(ext, "application/octet-stream")

        # Get filename
        if isinstance(full_path, VirtualPath):
            filename = full_path.name
        else:
            filename = full_path.name

        return b64, filename, mime
    except Exception:
        return None, None, None


def write_file(
    workspace_root: AnyRoot,
    path: str,
    content: Union[str, bytes],
    encoding: str = "utf-8"
) -> bool:
    """
    Write content to a file.

    Args:
        workspace_root: Root workspace directory (Path or VirtualFilesystem)
        path: Relative path to the file
        content: Content to write (str or bytes)
        encoding: Encoding for text content

    Returns:
        True if successful, False otherwise
    """
    full_path = _get_path(workspace_root, path)

    try:
        if isinstance(content, str):
            full_path.write_text(content, encoding=encoding)
        else:
            full_path.write_bytes(content)
        return True
    except Exception as e:
        print(f"Error writing file {path}: {e}")
        return False


def create_directory(
    workspace_root: AnyRoot,
    path: str,
    parents: bool = True,
    exist_ok: bool = True
) -> bool:
    """
    Create a directory.

    Args:
        workspace_root: Root workspace directory (Path or VirtualFilesystem)
        path: Relative path to the directory
        parents: Create parent directories if needed
        exist_ok: Don't error if directory exists

    Returns:
        True if successful, False otherwise
    """
    full_path = _get_path(workspace_root, path)

    try:
        full_path.mkdir(parents=parents, exist_ok=exist_ok)
        return True
    except Exception as e:
        print(f"Error creating directory {path}: {e}")
        return False
