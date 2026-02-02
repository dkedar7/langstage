"""Tests for sandbox module."""

import platform
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Skip all tests if not on Linux (sandbox is Linux-only)
pytestmark = pytest.mark.skipif(
    platform.system() != "Linux",
    reason="Sandbox tests only run on Linux"
)


class TestSandboxAvailability:
    """Test sandbox backend detection."""

    def test_check_bubblewrap_available_true(self):
        """Test bubblewrap detection when available."""
        from cowork_dash.sandbox import check_bubblewrap_available

        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/bwrap"
            assert check_bubblewrap_available() is True

    def test_check_bubblewrap_available_false(self):
        """Test bubblewrap detection when not available."""
        from cowork_dash.sandbox import check_bubblewrap_available

        with patch("shutil.which") as mock_which:
            mock_which.return_value = None
            assert check_bubblewrap_available() is False

    def test_check_docker_available_true(self):
        """Test Docker detection when available."""
        from cowork_dash.sandbox import check_docker_available

        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/docker"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                assert check_docker_available() is True

    def test_check_docker_available_no_binary(self):
        """Test Docker detection when binary not found."""
        from cowork_dash.sandbox import check_docker_available

        with patch("shutil.which") as mock_which:
            mock_which.return_value = None
            assert check_docker_available() is False

    def test_check_docker_available_not_running(self):
        """Test Docker detection when daemon not running."""
        from cowork_dash.sandbox import check_docker_available

        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/docker"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                assert check_docker_available() is False

    def test_get_available_sandbox_bubblewrap(self):
        """Test sandbox selection prefers bubblewrap."""
        from cowork_dash.sandbox import get_available_sandbox

        with patch("cowork_dash.sandbox.check_bubblewrap_available") as mock_bwrap:
            with patch("cowork_dash.sandbox.check_docker_available") as mock_docker:
                mock_bwrap.return_value = True
                mock_docker.return_value = True
                assert get_available_sandbox() == "bubblewrap"

    def test_get_available_sandbox_docker_fallback(self):
        """Test sandbox falls back to Docker when no bubblewrap."""
        from cowork_dash.sandbox import get_available_sandbox

        with patch("cowork_dash.sandbox.check_bubblewrap_available") as mock_bwrap:
            with patch("cowork_dash.sandbox.check_docker_available") as mock_docker:
                mock_bwrap.return_value = False
                mock_docker.return_value = True
                assert get_available_sandbox() == "docker"

    def test_get_available_sandbox_none(self):
        """Test sandbox returns None when nothing available."""
        from cowork_dash.sandbox import get_available_sandbox

        with patch("cowork_dash.sandbox.check_bubblewrap_available") as mock_bwrap:
            with patch("cowork_dash.sandbox.check_docker_available") as mock_docker:
                mock_bwrap.return_value = False
                mock_docker.return_value = False
                assert get_available_sandbox() is None


class TestSandboxedBashExecutor:
    """Test SandboxedBashExecutor class."""

    @pytest.fixture
    def virtual_fs(self):
        """Create a virtual filesystem for testing."""
        from cowork_dash.virtual_fs import VirtualFilesystem
        fs = VirtualFilesystem(root="/workspace")
        fs.mkdir("/workspace", exist_ok=True)
        return fs

    @pytest.fixture
    def executor(self, virtual_fs):
        """Create executor with mocked sandbox."""
        from cowork_dash.sandbox import SandboxedBashExecutor

        with patch("cowork_dash.sandbox.get_available_sandbox") as mock:
            mock.return_value = "bubblewrap"
            executor = SandboxedBashExecutor(virtual_fs, "test-session")
            yield executor
            executor.cleanup()

    def test_executor_creates_temp_dir(self, executor):
        """Test executor creates session temp directory."""
        temp_dir = executor.temp_dir
        assert temp_dir.exists()
        assert "test-session" in str(temp_dir)

    def test_sync_to_disk(self, executor, virtual_fs):
        """Test syncing virtual FS to disk."""
        # Add a file to virtual FS
        virtual_fs.write_text("/workspace/test.txt", "hello world")

        # Force sync
        executor._sync_to_disk()

        # Check file exists in temp dir
        temp_file = executor.temp_dir / "test.txt"
        assert temp_file.exists()
        assert temp_file.read_text() == "hello world"

    def test_sync_from_disk(self, executor, virtual_fs):
        """Test syncing disk to virtual FS."""
        # Create temp dir
        temp_dir = executor.temp_dir

        # Add a file to temp dir
        (temp_dir / "new_file.txt").write_text("from disk")

        # Sync back
        executor._sync_from_disk()

        # Check file in virtual FS
        assert virtual_fs.exists("/workspace/new_file.txt")
        assert virtual_fs.read_text("/workspace/new_file.txt") == "from disk"

    def test_execute_no_sandbox(self, virtual_fs):
        """Test execute fails gracefully when no sandbox."""
        from cowork_dash.sandbox import SandboxedBashExecutor

        with patch("cowork_dash.sandbox.get_available_sandbox") as mock:
            mock.return_value = None
            executor = SandboxedBashExecutor(virtual_fs, "no-sandbox")

            result = executor.execute("echo hello")
            assert result["status"] == "error"
            assert "No sandbox available" in result["stderr"]

    def test_cleanup(self, executor):
        """Test cleanup removes temp directory."""
        temp_dir = executor.temp_dir
        assert temp_dir.exists()

        executor.cleanup()
        assert not temp_dir.exists()


class TestSessionExecutorCache:
    """Test session executor caching."""

    @pytest.fixture
    def virtual_fs(self):
        """Create a virtual filesystem for testing."""
        from cowork_dash.virtual_fs import VirtualFilesystem
        fs = VirtualFilesystem(root="/workspace")
        fs.mkdir("/workspace", exist_ok=True)
        return fs

    def test_get_executor_creates_new(self, virtual_fs):
        """Test getting executor creates new instance."""
        from cowork_dash.sandbox import get_executor_for_session, cleanup_session_executor

        with patch("cowork_dash.sandbox.get_available_sandbox") as mock:
            mock.return_value = "bubblewrap"
            executor = get_executor_for_session("test-1", virtual_fs)
            assert executor is not None
            cleanup_session_executor("test-1")

    def test_get_executor_returns_cached(self, virtual_fs):
        """Test getting executor returns cached instance."""
        from cowork_dash.sandbox import get_executor_for_session, cleanup_session_executor

        with patch("cowork_dash.sandbox.get_available_sandbox") as mock:
            mock.return_value = "bubblewrap"
            executor1 = get_executor_for_session("test-2", virtual_fs)
            executor2 = get_executor_for_session("test-2", virtual_fs)
            assert executor1 is executor2
            cleanup_session_executor("test-2")


# Integration test - only runs if bubblewrap is actually available
@pytest.mark.skipif(
    not shutil.which("bwrap"),
    reason="bubblewrap not installed"
)
class TestBubblewrapIntegration:
    """Integration tests with real bubblewrap (requires bwrap installed)."""

    @pytest.fixture
    def virtual_fs(self):
        """Create a virtual filesystem for testing."""
        from cowork_dash.virtual_fs import VirtualFilesystem
        fs = VirtualFilesystem(root="/workspace")
        fs.mkdir("/workspace", exist_ok=True)
        return fs

    @pytest.fixture
    def executor(self, virtual_fs):
        """Create real executor."""
        from cowork_dash.sandbox import SandboxedBashExecutor
        executor = SandboxedBashExecutor(virtual_fs, "integration-test")
        yield executor
        executor.cleanup()

    def test_execute_simple_command(self, executor):
        """Test executing a simple command."""
        result = executor.execute("echo 'hello world'")
        assert result["status"] == "success"
        assert "hello world" in result["stdout"]

    def test_execute_creates_file(self, executor, virtual_fs):
        """Test command that creates a file."""
        result = executor.execute("echo 'test content' > test_output.txt")
        assert result["status"] == "success"

        # File should be synced back to virtual FS
        assert virtual_fs.exists("/workspace/test_output.txt")

    def test_execute_no_network(self, executor):
        """Test network is disabled in sandbox."""
        result = executor.execute("curl -s https://example.com", timeout=5)
        # Should fail because network is disabled
        assert result["return_code"] != 0

    def test_execute_timeout(self, executor):
        """Test command timeout."""
        result = executor.execute("sleep 10", timeout=1)
        assert result["status"] == "error"
        assert "timed out" in result["stderr"].lower()
