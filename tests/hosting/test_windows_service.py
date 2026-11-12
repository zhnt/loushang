"""Exercise retained Windows service observation in a native process."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace

import pytest

from loushang.hosting.errors import HostingError, HostingFailureCategory

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process handles")


def test_windows_service_reopens_exact_live_process_and_observes_exit():
    from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
    from loushang.hosting.service_windows import WindowsServiceObserverV1

    with subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ) as child:
        assert child.stdin is not None
        observed = WindowsServiceObserverV1.capture(child.pid)
        reopened = None
        try:
            assert observed.identity.pid == child.pid
            with WindowsPrivateDirectoryAcl() as acl:
                assert observed.identity.user_id == acl.user_sid
            reopened = WindowsServiceObserverV1.reopen(observed.identity)
            assert not reopened.exited()
            stale = replace(observed.identity, creation_filetime=observed.identity.creation_filetime + 1)
            with pytest.raises(HostingError) as caught:
                WindowsServiceObserverV1.reopen(stale)
            assert caught.value.category is HostingFailureCategory.PREPARATION_STALE
            observed.close()
            assert child.poll() is None
            child.stdin.close()
            assert reopened.exited(timeout=5)
            assert child.wait(timeout=5) == 0
        finally:
            child.stdin.close()
            observed.close()
            if reopened is not None:
                reopened.close()


def test_windows_service_close_releases_only_its_native_handle():
    from loushang.hosting.service_windows import WindowsServiceObserverV1

    observed = WindowsServiceObserverV1.capture(os.getpid())
    assert not observed.exited()
    observed.close()
    observed.close()
    with pytest.raises(HostingError) as caught:
        observed.exited()
    assert caught.value.category is HostingFailureCategory.HOST_CLOSED


def test_windows_service_survives_launch_handle_close_and_settles_scope(tmp_path):
    import socket
    from time import monotonic, sleep

    from loushang.hosting.contracts import (
        ProcessLaunchRequest,
        ProcessStderrMode,
        ProcessStdinMode,
        ProcessStdoutMode,
        ProcessStreamSpec,
    )
    from loushang.hosting.service_windows import (
        WindowsServiceLaunchRequestV1,
        WindowsServiceObserverV1,
        WindowsServiceProcessV1,
    )

    code = (
        "import socket, sys\n"
        "from loushang.hosting.service_windows import read_windows_service_startup\n"
        "with socket.socket(fileno=int(sys.argv[1])) as endpoint:\n"
        "    payload = read_windows_service_startup(endpoint, int(sys.argv[2]))\n"
        "    endpoint.sendall(bytes([int(payload == b'launch' * 18000)]))\n"
        "    endpoint.recv(1)\n"
    )
    parent, child = socket.socketpair()
    request = ProcessLaunchRequest(
        (sys.executable, "-c", code, str(child.fileno())), str(tmp_path),
        tuple(os.environ.items()),
        ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD),
    )
    attempt = "3" * 32
    process = WindowsServiceProcessV1(WindowsServiceLaunchRequestV1(request, b"launch" * 18000), child, attempt)
    with parent:
        try:
            identity = process.spawn(parent, deadline=monotonic() + 10)
            process.close()
            observer = WindowsServiceObserverV1.reopen(identity)
            try:
                scope = observer.open_scope(attempt)
                try:
                    parent.settimeout(10)
                    assert parent.recv(1) == b"\x01"
                    assert not observer.exited()
                    assert not scope.exited()
                    parent.sendall(b"q")
                    assert observer.exited(timeout=10)
                    deadline = monotonic() + 5
                    while not scope.exited() and monotonic() < deadline:
                        sleep(0.01)
                    assert scope.exited()
                finally:
                    scope.close()
            finally:
                observer.close()
        finally:
            process.close()
