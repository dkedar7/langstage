"""gh #247: a busy port is one clean line before the banner, for every address the
host resolves to.

``localhost`` resolves to ``::1`` and ``127.0.0.1`` (in that order on Windows and many
Linux boxes). The probe used to bind only the first, so a server holding
``127.0.0.1:8050`` passed it, the banner printed, and uvicorn (which binds every
address) failed with a raw bind error.
"""
import socket
import sys

import pytest
from click.testing import CliRunner

from langstage import cli as cli_mod


def _listener(host, family=socket.AF_INET):
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(1)
    return sock


def _localhost_addrs():
    return {a[4][0] for a in socket.getaddrinfo("localhost", 0, type=socket.SOCK_STREAM)}


def _ipv6_ok():
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


def test_localhost_probe_sees_a_listener_on_127_0_0_1():
    if "127.0.0.1" not in _localhost_addrs():
        pytest.skip("localhost doesn't resolve to 127.0.0.1 here")
    holder = _listener("127.0.0.1")
    port = holder.getsockname()[1]
    try:
        reason = cli_mod._port_bind_error("localhost", port)
    finally:
        holder.close()
    assert reason == f"port {port} is already in use on 127.0.0.1; pass --port or set LANGSTAGE_PORT"


@pytest.mark.skipif(not _ipv6_ok(), reason="no IPv6 loopback")
def test_localhost_probe_sees_a_listener_on_ipv6_loopback():
    if "::1" not in _localhost_addrs():
        pytest.skip("localhost doesn't resolve to ::1 here")
    holder = _listener("::1", socket.AF_INET6)
    port = holder.getsockname()[1]
    try:
        reason = cli_mod._port_bind_error("localhost", port)
    finally:
        holder.close()
    assert reason is not None and "already in use on ::1" in reason


def test_free_port_on_localhost_passes():
    # Find a port free on every localhost address, then probe it.
    holder = _listener("127.0.0.1")
    port = holder.getsockname()[1]
    holder.close()
    assert cli_mod._port_bind_error("localhost", port) is None


def test_wildcard_host_passes_when_free():
    assert cli_mod._port_bind_error("0.0.0.0", 0) is None


def test_unresolvable_host_is_a_clean_reason():
    reason = cli_mod._port_bind_error("no-such-host.invalid", 8050)
    assert reason is not None and reason.startswith("cannot serve at http://no-such-host.invalid:8050: ")


@pytest.mark.parametrize("exc, expected", [
    (OSError(98, "Address already in use"), True),  # Linux errno; also matched via errno module
    (OSError(10048, "Only one usage of each socket address"), True),  # Windows WSAEADDRINUSE
    (OSError(13, "Permission denied"), False),
])
def test_is_addr_in_use(exc, expected):
    import errno

    if exc.errno == 98 and errno.EADDRINUSE != 98:
        exc = OSError(errno.EADDRINUSE, "Address already in use")
    assert cli_mod._is_addr_in_use(exc) is expected


def test_run_on_default_host_fails_before_the_banner(monkeypatch, tmp_path):
    # The reported repro: `langstage run --demo --port P` (host defaults to localhost)
    # with another server already on 127.0.0.1:P.
    if "127.0.0.1" not in _localhost_addrs():
        pytest.skip("localhost doesn't resolve to 127.0.0.1 here")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LANGSTAGE_HOST", raising=False)
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(tmp_path / "no-global"))
    served = []
    monkeypatch.setattr(cli_mod.CoworkApp, "run", lambda self, open_browser=True: served.append(1))
    holder = _listener("127.0.0.1")
    port = holder.getsockname()[1]
    try:
        result = CliRunner().invoke(cli_mod.main, ["run", "--demo", "--no-browser", "--port", str(port)])
    finally:
        holder.close()
    assert result.exit_code == 1, result.output
    assert served == []
    assert "LangStage:" not in result.output
    assert result.output.strip() == (
        f"Error: port {port} is already in use on 127.0.0.1; pass --port or set LANGSTAGE_PORT"
    )
