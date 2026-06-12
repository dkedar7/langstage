"""Session-ephemeral virtual filesystem for multi-user isolation.

Provides an in-memory filesystem that isolates files, canvas, and uploads
between different user sessions. Each session gets its own virtual workspace
that is automatically cleaned up when the session ends.
"""

import threading
import time
import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Dict, Iterator, List, Optional, Union


class VirtualPath:
    """Path-like object for virtual filesystem paths.

    Provides a subset of pathlib.Path interface for compatibility
    with existing code that uses Path objects.
    """

    def __init__(self, path: str, fs: "VirtualFilesystem"):
        self._path = PurePosixPath(path)
        self._fs = fs

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"VirtualPath({str(self._path)!r})"

    def __truediv__(self, other: Union[str, "VirtualPath"]) -> "VirtualPath":
        if isinstance(other, VirtualPath):
            other = str(other._path)
        return VirtualPath(str(self._path / other), self._fs)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, VirtualPath):
            return str(self._path) == str(other._path)
        if isinstance(other, str):
            return str(self._path) == other
        return False

    def __hash__(self) -> int:
        return hash(str(self._path))

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def stem(self) -> str:
        return self._path.stem

    @property
    def suffix(self) -> str:
        return self._path.suffix

    @property
    def parent(self) -> "VirtualPath":
        return VirtualPath(str(self._path.parent), self._fs)

    @property
    def parts(self) -> tuple:
        return self._path.parts

    def resolve(self) -> "VirtualPath":
        """Return the path with no .. or . components."""
        # Normalize the path
        parts = []
        for part in self._path.parts:
            if part == "..":
                if parts and parts[-1] != "/":
                    parts.pop()
            elif part != ".":
                parts.append(part)
        if not parts:
            parts = ["/"]
        return VirtualPath("/".join(parts) if parts[0] != "/" else "/" + "/".join(parts[1:]), self._fs)

    def exists(self) -> bool:
        return self._fs.exists(str(self._path))

    def is_file(self) -> bool:
        return self._fs.is_file(str(self._path))

    def is_dir(self) -> bool:
        return self._fs.is_dir(str(self._path))

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self._fs.mkdir(str(self._path), parents=parents, exist_ok=exist_ok)

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._fs.read_text(str(self._path), encoding=encoding)

    def read_bytes(self) -> bytes:
        return self._fs.read_bytes(str(self._path))

    def write_text(self, data: str, encoding: str = "utf-8") -> int:
        return self._fs.write_text(str(self._path), data, encoding=encoding)

    def write_bytes(self, data: bytes) -> int:
        return self._fs.write_bytes(str(self._path), data)

    def unlink(self, missing_ok: bool = False) -> None:
        self._fs.unlink(str(self._path), missing_ok=missing_ok)

    def rmdir(self) -> None:
        self._fs.rmdir(str(self._path))

    def iterdir(self) -> Iterator["VirtualPath"]:
        for name in self._fs.listdir(str(self._path)):
            yield self / name

    def glob(self, pattern: str) -> Iterator["VirtualPath"]:
        """Simple glob implementation for virtual filesystem."""
        for path in self._fs.glob(str(self._path), pattern):
            yield VirtualPath(path, self._fs)

    def relative_to(self, other: Union[str, "VirtualPath"]) -> "VirtualPath":
        if isinstance(other, VirtualPath):
            other = str(other._path)
        return VirtualPath(str(self._path.relative_to(other)), self._fs)


class VirtualFilesystem:
    """In-memory filesystem for session isolation.

    Stores files as a flat dictionary mapping paths to content.
    Directories are tracked implicitly by path prefixes.
    """

    def __init__(self, root: str = "/"):
        self._root = root.rstrip("/") or "/"
        self._files: Dict[str, bytes] = {}
        self._directories: set = {self._root}
        self._lock = threading.Lock()
        self._created_at = datetime.now()
        self._last_accessed = datetime.now()

    def _normalize_path(self, path: str) -> str:
        """Normalize path to absolute form within the virtual filesystem."""
        if not path.startswith("/"):
            path = f"{self._root}/{path}"
        # Remove trailing slashes except for root
        path = path.rstrip("/") or "/"
        # Resolve . and ..
        parts = []
        for part in path.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part and part != ".":
                parts.append(part)
        return "/" + "/".join(parts)

    def _touch_access(self) -> None:
        """Update last accessed time."""
        self._last_accessed = datetime.now()

    @property
    def root(self) -> VirtualPath:
        """Get the root path as a VirtualPath object."""
        return VirtualPath(self._root, self)

    def path(self, p: str) -> VirtualPath:
        """Create a VirtualPath for the given path string."""
        return VirtualPath(p, self)

    def exists(self, path: str) -> bool:
        """Check if path exists (file or directory)."""
        self._touch_access()
        norm_path = self._normalize_path(path)
        with self._lock:
            if norm_path in self._files:
                return True
            if norm_path in self._directories:
                return True
            return False

    def is_file(self, path: str) -> bool:
        """Check if path is a file."""
        self._touch_access()
        norm_path = self._normalize_path(path)
        with self._lock:
            return norm_path in self._files

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory."""
        self._touch_access()
        norm_path = self._normalize_path(path)
        with self._lock:
            return norm_path in self._directories

    def mkdir(self, path: str, parents: bool = False, exist_ok: bool = False) -> None:
        """Create a directory."""
        self._touch_access()
        norm_path = self._normalize_path(path)

        with self._lock:
            if norm_path in self._files:
                raise FileExistsError(f"File exists: {path}")

            if norm_path in self._directories:
                if exist_ok:
                    return
                raise FileExistsError(f"Directory exists: {path}")

            # Check parent exists
            parent = "/".join(norm_path.split("/")[:-1]) or "/"
            if parent not in self._directories:
                if parents:
                    # Create parent directories recursively
                    parts = norm_path.split("/")[1:]  # Skip leading empty string
                    current = ""
                    for part in parts:
                        current = f"{current}/{part}"
                        self._directories.add(current)
                else:
                    raise FileNotFoundError(f"Parent directory does not exist: {parent}")
            else:
                self._directories.add(norm_path)

    def read_bytes(self, path: str) -> bytes:
        """Read file as bytes."""
        self._touch_access()
        norm_path = self._normalize_path(path)
        with self._lock:
            if norm_path not in self._files:
                raise FileNotFoundError(f"File not found: {path}")
            return self._files[norm_path]

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read file as text."""
        return self.read_bytes(path).decode(encoding)

    def write_bytes(self, path: str, data: bytes) -> int:
        """Write bytes to file."""
        self._touch_access()
        norm_path = self._normalize_path(path)

        with self._lock:
            # Check parent directory exists
            parent = "/".join(norm_path.split("/")[:-1]) or "/"
            if parent not in self._directories:
                raise FileNotFoundError(f"Parent directory does not exist: {parent}")

            self._files[norm_path] = data
            return len(data)

    def write_text(self, path: str, data: str, encoding: str = "utf-8") -> int:
        """Write text to file."""
        return self.write_bytes(path, data.encode(encoding))

    def unlink(self, path: str, missing_ok: bool = False) -> None:
        """Delete a file."""
        self._touch_access()
        norm_path = self._normalize_path(path)

        with self._lock:
            if norm_path not in self._files:
                if missing_ok:
                    return
                raise FileNotFoundError(f"File not found: {path}")
            del self._files[norm_path]

    def rmdir(self, path: str) -> None:
        """Remove a directory (must be empty)."""
        self._touch_access()
        norm_path = self._normalize_path(path)

        with self._lock:
            if norm_path not in self._directories:
                raise FileNotFoundError(f"Directory not found: {path}")

            # Check if directory is empty
            prefix = norm_path + "/"
            for p in self._files:
                if p.startswith(prefix):
                    raise OSError(f"Directory not empty: {path}")
            for p in self._directories:
                if p.startswith(prefix):
                    raise OSError(f"Directory not empty: {path}")

            self._directories.remove(norm_path)

    def listdir(self, path: str) -> List[str]:
        """List contents of a directory."""
        self._touch_access()
        norm_path = self._normalize_path(path)

        with self._lock:
            if norm_path not in self._directories:
                raise FileNotFoundError(f"Directory not found: {path}")

            prefix = norm_path + "/" if norm_path != "/" else "/"
            prefix_len = len(prefix)

            items = set()

            # Find files in this directory
            for p in self._files:
                if p.startswith(prefix):
                    remainder = p[prefix_len:]
                    if "/" not in remainder:
                        items.add(remainder)

            # Find subdirectories
            for p in self._directories:
                if p.startswith(prefix) and p != norm_path:
                    remainder = p[prefix_len:]
                    if "/" not in remainder:
                        items.add(remainder)

            return sorted(items)

    def glob(self, path: str, pattern: str) -> List[str]:
        """Simple glob matching within a directory."""
        import fnmatch

        self._touch_access()
        norm_path = self._normalize_path(path)

        results = []

        with self._lock:
            prefix = norm_path + "/" if norm_path != "/" else "/"
            prefix_len = len(prefix)

            # Check all files
            for p in self._files:
                if p.startswith(prefix):
                    remainder = p[prefix_len:]
                    if fnmatch.fnmatch(remainder, pattern):
                        results.append(p)

            # Check directories
            for p in self._directories:
                if p.startswith(prefix) and p != norm_path:
                    remainder = p[prefix_len:]
                    if fnmatch.fnmatch(remainder, pattern):
                        results.append(p)

        return sorted(results)

class SessionManager:
    """Manages per-session virtual filesystems.

    Creates and tracks virtual filesystems for each user session,
    providing automatic cleanup of inactive sessions.
    """

    def __init__(
        self,
        session_timeout_seconds: int = 3600,  # 1 hour default
        cleanup_interval_seconds: int = 300,   # 5 minutes
    ):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._session_timeout = session_timeout_seconds
        self._cleanup_interval = cleanup_interval_seconds
        self._last_cleanup = time.time()

    def create_session(self, session_id: Optional[str] = None) -> str:
        """Create a new session with its own virtual filesystem.

        Returns the session ID (generated if not provided).
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "filesystem": VirtualFilesystem(root="/workspace"),
                    "created_at": datetime.now(),
                    "last_accessed": datetime.now(),
                    "agent_state": None,
                    "thread_id": str(uuid.uuid4()),
                }

                # Initialize default directories
                fs = self._sessions[session_id]["filesystem"]
                fs.mkdir("/workspace", exist_ok=True)
                fs.mkdir("/workspace/.canvas", exist_ok=True)

        self._maybe_cleanup()
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by ID."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["last_accessed"] = datetime.now()
                session["filesystem"]._last_accessed = datetime.now()
            return session

    def get_filesystem(self, session_id: str) -> Optional[VirtualFilesystem]:
        """Get the virtual filesystem for a session."""
        session = self.get_session(session_id)
        return session["filesystem"] if session else None

    def get_thread_id(self, session_id: str) -> Optional[str]:
        """Get the LangGraph thread ID for a session."""
        session = self.get_session(session_id)
        return session["thread_id"] if session else None

    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        """Get existing session or create new one."""
        if session_id and session_id in self._sessions:
            self.get_session(session_id)  # Touch access time
            return session_id
        return self.create_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its virtual filesystem."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def _maybe_cleanup(self) -> None:
        """Clean up expired sessions if enough time has passed."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        self._cleanup_expired_sessions()

    def _cleanup_expired_sessions(self) -> int:
        """Remove sessions that have been inactive too long."""
        now = datetime.now()
        expired = []

        with self._lock:
            for session_id, session in self._sessions.items():
                last_accessed = session["last_accessed"]
                if (now - last_accessed).total_seconds() > self._session_timeout:
                    expired.append(session_id)

            for session_id in expired:
                del self._sessions[session_id]

        if expired:
            print(f"Session cleanup: removed {len(expired)} expired sessions")

        return len(expired)


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def get_virtual_filesystem(session_id: str) -> Optional[VirtualFilesystem]:
    """Convenience function to get a session's virtual filesystem."""
    return get_session_manager().get_filesystem(session_id)
