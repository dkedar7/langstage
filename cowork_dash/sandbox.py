"""Sandbox execution for bash commands in virtual filesystem mode.

Provides secure command execution using bubblewrap (Linux) or Docker as fallback.
This module is only used when VIRTUAL_FS mode is enabled.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .virtual_fs import VirtualFilesystem


class SandboxError(Exception):
    """Error during sandbox execution."""
    pass


class SandboxUnavailableError(SandboxError):
    """No sandbox backend available."""
    pass


def check_bubblewrap_available() -> bool:
    """Check if bubblewrap (bwrap) is available on the system."""
    return shutil.which("bwrap") is not None


def check_docker_available() -> bool:
    """Check if Docker is available and running."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_available_sandbox() -> Optional[str]:
    """Get the best available sandbox backend.

    Returns:
        "bubblewrap", "docker", or None if no sandbox available
    """
    if check_bubblewrap_available():
        return "bubblewrap"
    if check_docker_available():
        return "docker"
    return None


class SandboxedBashExecutor:
    """Execute bash commands in a sandboxed environment.

    Syncs files between VirtualFilesystem and a temp directory,
    runs commands in a sandbox, and syncs results back.
    """

    def __init__(self, fs: VirtualFilesystem, session_id: str):
        """Initialize executor with a virtual filesystem.

        Args:
            fs: The VirtualFilesystem to sync with
            session_id: Unique session identifier for temp dir naming
        """
        self.fs = fs
        self.session_id = session_id
        self._temp_dir: Optional[Path] = None
        self._sandbox_backend = get_available_sandbox()

    @property
    def temp_dir(self) -> Path:
        """Get or create the persistent temp directory for this session."""
        if self._temp_dir is None or not self._temp_dir.exists():
            # Create session-specific temp directory
            base_temp = Path(tempfile.gettempdir()) / "cowork-sandbox"
            base_temp.mkdir(exist_ok=True)
            self._temp_dir = base_temp / f"session-{self.session_id}"
            self._temp_dir.mkdir(exist_ok=True)
            # Initial sync from virtual FS to temp dir
            self._sync_to_disk()
        return self._temp_dir

    def _sync_to_disk(self) -> None:
        """Sync virtual filesystem contents to the temp directory."""
        # Clear existing files in temp dir (but keep the dir)
        for item in self.temp_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

        # Copy all files from virtual FS
        for path_str, content in self.fs._files.items():
            # Convert virtual path to relative path
            rel_path = path_str.lstrip("/")
            if rel_path.startswith("workspace/"):
                rel_path = rel_path[len("workspace/"):]

            target = self.temp_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def _sync_from_disk(self) -> None:
        """Sync temp directory contents back to virtual filesystem."""
        # Walk the temp directory and update virtual FS
        for root, dirs, files in os.walk(self.temp_dir):
            rel_root = Path(root).relative_to(self.temp_dir)

            # Create directories in virtual FS
            for d in dirs:
                vpath = f"/workspace/{rel_root / d}" if str(rel_root) != "." else f"/workspace/{d}"
                vpath = vpath.replace("//", "/")
                try:
                    self.fs.mkdir(vpath, parents=True, exist_ok=True)
                except Exception:
                    pass

            # Copy files to virtual FS
            for f in files:
                file_path = Path(root) / f
                vpath = f"/workspace/{rel_root / f}" if str(rel_root) != "." else f"/workspace/{f}"
                vpath = vpath.replace("//", "/")

                try:
                    content = file_path.read_bytes()
                    # Ensure parent exists
                    parent = "/".join(vpath.split("/")[:-1])
                    if parent:
                        self.fs.mkdir(parent, parents=True, exist_ok=True)
                    self.fs.write_bytes(vpath, content)
                except Exception:
                    pass

        # Remove files from virtual FS that no longer exist on disk
        existing_files = set()
        for root, _, files in os.walk(self.temp_dir):
            rel_root = Path(root).relative_to(self.temp_dir)
            for f in files:
                vpath = f"/workspace/{rel_root / f}" if str(rel_root) != "." else f"/workspace/{f}"
                existing_files.add(vpath.replace("//", "/"))

        # Get list of files to remove (avoid modifying dict during iteration)
        to_remove = []
        for vpath in list(self.fs._files.keys()):
            if vpath.startswith("/workspace/") and vpath not in existing_files:
                # Skip .canvas directory
                if not vpath.startswith("/workspace/.canvas"):
                    to_remove.append(vpath)

        for vpath in to_remove:
            try:
                self.fs.unlink(vpath, missing_ok=True)
            except Exception:
                pass

    def execute(
        self,
        command: str,
        timeout: int = 60,
        env: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute a bash command in the sandbox.

        Args:
            command: The bash command to execute
            timeout: Maximum execution time in seconds
            env: Additional environment variables

        Returns:
            Dict with stdout, stderr, return_code, status
        """
        if self._sandbox_backend is None:
            return {
                "stdout": "",
                "stderr": "No sandbox available. Install bubblewrap (bwrap) or Docker.",
                "return_code": 1,
                "status": "error"
            }

        # Sync virtual FS to disk before execution
        self._sync_to_disk()

        try:
            if self._sandbox_backend == "bubblewrap":
                result = self._execute_bubblewrap(command, timeout, env)
            else:
                result = self._execute_docker(command, timeout, env)

            # Sync changes back to virtual FS after execution
            self._sync_from_disk()

            return result

        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
                "return_code": 124,
                "status": "error"
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "return_code": 1,
                "status": "error"
            }

    def _execute_bubblewrap(
        self,
        command: str,
        timeout: int,
        env: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute command using bubblewrap sandbox."""
        # Build bubblewrap command
        bwrap_cmd = [
            "bwrap",
        ]

        # Mount system directories read-only (only if they exist)
        # Different distros have different layouts (e.g., Debian doesn't have /lib64)
        system_dirs = ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc"]
        for sysdir in system_dirs:
            if Path(sysdir).exists():
                bwrap_cmd.extend(["--ro-bind", sysdir, sysdir])

        # Mount workspace read-write
        bwrap_cmd.extend([
            "--bind", str(self.temp_dir), "/workspace",
            # Create minimal /tmp
            "--tmpfs", "/tmp",
            # Create /dev with minimal devices
            "--dev", "/dev",
            # Create /proc (needed by some tools)
            "--proc", "/proc",
            # Isolate network
            "--unshare-net",
            # Isolate PID namespace
            "--unshare-pid",
            # Set working directory
            "--chdir", "/workspace",
            # Clear environment and set minimal
            "--clearenv",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "HOME", "/workspace",
            "--setenv", "TERM", "xterm-256color",
        ])

        # Add custom environment variables
        if env:
            for key, value in env.items():
                bwrap_cmd.extend(["--setenv", key, value])

        # Add the actual command
        bwrap_cmd.extend(["--", "/bin/bash", "-c", command])

        # Execute
        result = subprocess.run(
            bwrap_cmd,
            capture_output=True,
            timeout=timeout,
            text=True
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "status": "success" if result.returncode == 0 else "error"
        }

    def _execute_docker(
        self,
        command: str,
        timeout: int,
        env: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute command using Docker container."""
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--network", "none",  # No network access
            "--memory", "512m",  # Memory limit
            "--cpus", "1",  # CPU limit
            "-v", f"{self.temp_dir}:/workspace",
            "-w", "/workspace",
        ]

        # Add environment variables
        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])

        # Use a minimal Python image (widely available)
        docker_cmd.extend([
            "python:3.11-slim",
            "/bin/bash", "-c", command
        ])

        # Execute
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            timeout=timeout,
            text=True
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "status": "success" if result.returncode == 0 else "error"
        }

    def cleanup(self) -> None:
        """Clean up the temp directory for this session."""
        if self._temp_dir and self._temp_dir.exists():
            try:
                shutil.rmtree(self._temp_dir)
            except Exception:
                pass
            self._temp_dir = None


# Session executor cache
_session_executors: Dict[str, SandboxedBashExecutor] = {}


def get_executor_for_session(
    session_id: str,
    fs: VirtualFilesystem
) -> SandboxedBashExecutor:
    """Get or create a sandboxed executor for a session.

    Args:
        session_id: The session identifier
        fs: The VirtualFilesystem for this session

    Returns:
        SandboxedBashExecutor instance
    """
    if session_id not in _session_executors:
        _session_executors[session_id] = SandboxedBashExecutor(fs, session_id)
    return _session_executors[session_id]


def cleanup_session_executor(session_id: str) -> None:
    """Clean up executor for a session."""
    if session_id in _session_executors:
        _session_executors[session_id].cleanup()
        del _session_executors[session_id]
