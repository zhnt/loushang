from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from dataclasses import replace

import pytest

from loushang.hosting.contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting.errors import HostingError, HostingFailureCategory
from loushang.hosting.service_process import LinuxServiceProcessV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux service spawn")

_CHILD = r'''
import json, os, socket, sys
endpoint = socket.socket(fileno=int(sys.argv[1]))
endpoint.settimeout(8)
endpoint.set_inheritable(False)
try:
    os.open('/dev/tty', os.O_RDONLY)
    tty = True
except OSError:
    tty = False
facts = dict(pid=os.getpid(), sid=os.getsid(0), pgid=os.getpgrp(), tty=tty, cwd=os.getcwd(),
             stdio=[os.readlink('/proc/self/fd/' + str(i)) for i in range(3)],
             env=dict(os.environ))
endpoint.sendall(json.dumps(facts).encode() + b'\n')
endpoint.recv(1)
endpoint.close()
'''


def _request(tmp_path, fd, *, code=_CHILD, environment=()):
    return ProcessLaunchRequest(
        (sys.executable, "-c", code, str(fd)), str(tmp_path), environment,
        ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD),
    )


@pytest.fixture
def launched(tmp_path):
    parent, child = socket.socketpair()
    parent.settimeout(8)
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno()), child)
    try:
        identity = owner.spawn()
        facts = json.loads(_line(parent))
        yield owner, parent, identity, facts
    finally:
        parent.close()  # The test child handles EOF; no native termination.
        owner.close()
        assert owner.wait_scope(timeout=8)


def test_spawn_is_detached_with_no_stdio_and_complete_environment(launched):
    owner, _, identity, facts = launched
    assert facts["pid"] == facts["sid"] == facts["pgid"] == identity.pid
    assert not facts["tty"]
    assert facts["stdio"] == ["/dev/null"] * 3
    # CPython may coerce the empty C locale, but no parent secrets are inherited.
    assert set(facts["env"]) <= {"LC_CTYPE"}
    assert not owner.creation_uncertain
    assert not owner.leader_exited()
    assert not owner.scope_exited()
    assert not owner.handles_closed
    assert owner._endpoint.fileno() == -1


def test_close_only_releases_parent_handles_and_does_not_signal(launched, monkeypatch):
    owner, parent, _, _ = launched

    def forbidden(*args):
        pytest.fail("close must not send signals")

    with monkeypatch.context() as patch:
        patch.setattr(os, "kill", forbidden)
        patch.setattr(os, "killpg", forbidden)
        owner.close()
        owner.close()
    assert owner.handles_closed
    assert not owner.leader_exited()
    assert not owner.scope_exited()
    parent.sendall(b"Q")
    assert owner.wait_scope(timeout=5)


def test_zero_timeout_never_terminates_running_service(launched):
    owner, _, _, _ = launched
    assert not owner.wait_scope(timeout=0)
    assert not owner.leader_exited()


def test_second_spawn_is_refused(launched):
    with pytest.raises(HostingError) as caught:
        launched[0].spawn()
    assert caught.value.category is HostingFailureCategory.SPAWN_FAILED


def test_endpoint_close_lost_receipt_never_becomes_clean(tmp_path, monkeypatch):
    parent, child = socket.socketpair()
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno()), child)
    native = socket.socket.close
    calls = []

    def lose_receipt(endpoint):
        native(endpoint)
        if endpoint is child:
            calls.append(endpoint)
            raise OSError("lost endpoint close receipt")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket, "close", lose_receipt)
            for _ in range(2):
                with pytest.raises(HostingError):
                    owner.close()
                assert not owner.handles_closed
            assert calls == [child] and child.fileno() == -1
    finally:
        parent.close()
        native(child)


def test_close_before_spawn_fences_native_creation(tmp_path, monkeypatch):
    parent, child = socket.socketpair()
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno()), child)
    try:
        owner.close()
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not create"))
        with pytest.raises(HostingError) as caught:
            owner.spawn()
        assert caught.value.category is HostingFailureCategory.HOST_CLOSED
        assert owner.scope_exited()
        assert owner.handles_closed
        assert not owner.creation_uncertain
    finally:
        parent.close()
        owner.close()


def test_failed_spawn_is_unknown_not_a_retry_or_settlement_receipt(tmp_path):
    parent, child = socket.socketpair()
    request = replace(_request(tmp_path, child.fileno()), argv=(str(tmp_path / "missing-executable"),))
    owner = LinuxServiceProcessV1(request, child)
    try:
        with pytest.raises(HostingError) as caught:
            owner.spawn()
        assert caught.value.category is HostingFailureCategory.SPAWN_FAILED
        assert owner.creation_uncertain
        assert not owner.scope_exited()
        with pytest.raises(HostingError):
            owner.spawn()
        owner.close()
        assert owner.handles_closed
        assert not owner.scope_exited()
    finally:
        parent.close()
        owner.close()


@pytest.mark.parametrize("lost_cleanup", [False, True])
def test_failed_identity_capture_keeps_attached_process_owner(tmp_path, monkeypatch, lost_cleanup):
    import loushang.hosting.service as service
    import loushang.hosting.service_process as module

    parent, child = socket.socketpair()
    parent.settimeout(8)
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno()), child)

    def fail(pid):
        raise HostingError(HostingFailureCategory.PREPARATION_FAILED, "injected")

    if lost_cleanup:
        original_set = os.set_inheritable
        original_close = os.close
        captured = []

        def fail_after_allocation(fd, inheritable):
            captured.append(fd)
            original_set(fd, inheritable)
            raise OSError("capture failed after allocation")

        def lose_close(fd):
            original_close(fd)
            if fd in captured:
                raise OSError("temporary pidfd close receipt lost")

        monkeypatch.setattr(service.os, "set_inheritable", fail_after_allocation)
        monkeypatch.setattr(service.os, "close", lose_close)
    else:
        monkeypatch.setattr(module.LinuxServiceObserverV1, "capture", fail)
    try:
        with pytest.raises(HostingError):
            owner.spawn()
        assert json.loads(_line(parent))["pid"] == owner._process.pid
        assert not owner.creation_uncertain
        assert owner.identity is None
        assert not owner.scope_exited()
    finally:
        parent.close()
        with pytest.raises(HostingError):
            owner.close()
        assert child.fileno() == -1 and not owner.handles_closed
        assert owner.wait_scope(timeout=8)


@pytest.mark.parametrize("change", ["executable", "stdin", "stdout", "stderr"])
def test_admission_rejects_ambient_executable_or_stream_downgrade(tmp_path, change):
    parent, child = socket.socketpair()
    request = _request(tmp_path, child.fileno())
    try:
        with pytest.raises(HostingError):
            if change == "executable":
                request = replace(request, argv=("python", "-c", "pass"))
            else:
                value = {"stdin": ProcessStdinMode.PIPE, "stdout": ProcessStdoutMode.PIPE,
                         "stderr": ProcessStderrMode.CAPTURE_TAIL}[change]
                request = replace(request, streams=replace(request.streams, **{change: value}))
            LinuxServiceProcessV1(request, child)
        assert child.fileno() >= 3
    finally:
        parent.close()
        child.close()


@pytest.mark.parametrize("timeout", [True, -1, 31, float("nan"), float("inf"), 10**1000])
def test_invalid_wait_budget_never_reaches_native_io(launched, timeout):
    with pytest.raises(HostingError) as caught:
        launched[0].wait_scope(timeout=timeout)
    assert caught.value.category is HostingFailureCategory.INVALID_REQUEST


def test_only_explicit_startup_socket_survives_exec(tmp_path):
    parent, child = socket.socketpair()
    extra_left, extra_right = socket.socketpair()
    extra_left.set_inheritable(True)
    target = os.readlink(f"/proc/self/fd/{extra_left.fileno()}")
    code = r'''
import os, socket, sys
channel = socket.socket(fileno=int(sys.argv[1]))
try:
    value = os.readlink('/proc/self/fd/' + sys.argv[2])
except OSError:
    value = 'closed'
channel.sendall(value.encode() + b'\n')
channel.recv(1)
'''
    request = _request(tmp_path, child.fileno(), code=code)
    request = replace(request, argv=(*request.argv, str(extra_left.fileno())))
    owner = LinuxServiceProcessV1(request, child)
    parent.settimeout(8)
    try:
        owner.spawn()
        assert _line(parent).strip().decode() != target
    finally:
        parent.close()
        extra_left.close()
        extra_right.close()
        owner.close()
        assert owner.wait_scope(timeout=8)


def test_close_during_native_creation_retains_the_single_spawn(tmp_path, monkeypatch):
    import loushang.hosting.service_process as module

    parent, child = socket.socketpair()
    parent.settimeout(8)
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno()), child)
    entered, release = threading.Event(), threading.Event()
    original = module.subprocess.Popen
    results = []

    def create(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", create)
    worker = threading.Thread(target=lambda: results.append(owner.spawn()))
    closer = threading.Thread(target=owner.close)
    worker.start()
    try:
        assert entered.wait(5)
        closer.start()
        assert owner._closing.wait(5)
        with pytest.raises(HostingError) as caught:
            owner.spawn()
        assert caught.value.category is HostingFailureCategory.HOST_CLOSED
        release.set()
        worker.join(5)
        closer.join(5)
        assert not worker.is_alive() and not closer.is_alive()
        assert len(results) == 1
        assert json.loads(_line(parent))["pid"] == results[0].pid
        assert owner.handles_closed
        assert not owner.leader_exited()
    finally:
        release.set()
        worker.join(5)
        if closer.ident is not None:
            closer.join(5)
        parent.close()
        owner.close()
        assert owner.wait_scope(timeout=8)


def test_leader_exit_is_not_settlement_of_a_living_descendant(tmp_path):
    from loushang.hosting.service_group import LinuxServiceGroupObservationV1
    parent, child = socket.socketpair()
    parent.settimeout(8)
    code = r'''
import os, socket, sys
channel = socket.socket(fileno=int(sys.argv[1]))
channel.settimeout(8)
channel.sendall(b'R')
if channel.recv(1) != b'G':
    sys.exit(0)
pid = os.fork()
if pid == 0:
    channel.sendall(b'D')
    channel.recv(1)
    channel.close()
    os._exit(0)
channel.close()
os._exit(0)
'''
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno(), code=code), child)
    try:
        owner.spawn()
        assert parent.recv(1) == b"R"
        group = LinuxServiceGroupObservationV1(owner._observer)
        group.admit()
        parent.sendall(b"G")
        assert parent.recv(1) == b"D"
        assert owner._process.wait(timeout=5) == 0
        assert owner.leader_exited()
        assert not group.exited()
        assert not owner.scope_exited()
        owner.close()
        assert owner.handles_closed
        assert not owner.scope_exited()
    finally:
        parent.close()
        owner.close()
        assert owner.wait_scope(timeout=8)


def test_explicit_environment_and_workspace_reach_the_real_child(tmp_path, monkeypatch):
    monkeypatch.setenv("LMUX_AMBIENT_ONLY", "must not inherit")
    monkeypatch.setenv("LMUX_EXPLICIT", "parent value")
    expected = {"LMUX_EXPLICIT": "显式 value with spaces", "LMUX_EMPTY": "",
                "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    parent, child = socket.socketpair()
    parent.settimeout(8)
    owner = LinuxServiceProcessV1(
        _request(workspace, child.fileno(), environment=tuple(expected.items())), child,
    )
    try:
        owner.spawn()
        facts = json.loads(_line(parent))
        assert facts["env"] == expected
        assert facts["cwd"] == str(workspace)
    finally:
        parent.close()
        owner.close()
        assert owner.wait_scope(timeout=8)


def test_cancelled_spawn_and_failed_observer_close_still_release_socket(tmp_path, monkeypatch):
    import loushang.hosting.service_process as module

    parent, child = socket.socketpair()
    parent.settimeout(8)
    owner = LinuxServiceProcessV1(_request(tmp_path, child.fileno()), child)
    original = module.LinuxServiceObserverV1.capture

    class CaptureThenCancel:
        def __init__(self, pid):
            self.observer = original(pid)
            self.fail = True

        @property
        def identity(self):
            raise KeyboardInterrupt()

        def close(self):
            if self.fail:
                self.fail = False
                self.observer.close()
                raise OSError("injected observer close failure")
            self.observer.close()

    monkeypatch.setattr(module.LinuxServiceObserverV1, "capture", CaptureThenCancel)
    try:
        with pytest.raises(KeyboardInterrupt):
            owner.spawn()
        assert json.loads(_line(parent))["pid"] == owner._process.pid
        assert child.fileno() >= 3
        with monkeypatch.context() as patch:
            patch.setattr(os, "kill", lambda *args: pytest.fail("no signals"))
            patch.setattr(os, "killpg", lambda *args: pytest.fail("no signals"))
            with pytest.raises(HostingError) as caught:
                owner.close()
            assert caught.value.category is HostingFailureCategory.CLEANUP_FAILED
            assert child.fileno() == -1
            assert owner._observer is not None
            assert not owner.handles_closed
            with pytest.raises(HostingError):
                owner.close()
        assert owner._observer is not None
        assert not owner.handles_closed
        assert not owner.leader_exited()
    finally:
        parent.close()
        with pytest.raises(HostingError):
            owner.close()
        assert owner.wait_scope(timeout=8)


def _line(endpoint):
    result = bytearray()
    while len(result) < 8192:
        block = endpoint.recv(1)
        if not block:
            break
        result.extend(block)
        if block == b"\n":
            return bytes(result)
    pytest.fail("missing bounded child report")
