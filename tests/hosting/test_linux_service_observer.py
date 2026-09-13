from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from loushang.hosting.errors import HostingError, HostingFailureCategory
from loushang.hosting.service import (
    LinuxServiceIdentityV1,
    LinuxServiceObserverV1,
    _parse_start_ticks,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd service observation")


@pytest.fixture
def child():
    process = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        yield process
    finally:
        process.communicate(timeout=5)


def test_capture_reopen_and_exit_with_retained_native_identity(child):
    observer = LinuxServiceObserverV1.capture(child.pid)
    reopened = LinuxServiceObserverV1.reopen(observer.identity)
    try:
        assert type(observer.identity) is LinuxServiceIdentityV1
        assert observer.identity.pid == child.pid
        assert observer.identity.user_id == os.geteuid()
        assert observer.identity == reopened.identity
        assert observer._fd != reopened._fd
        assert not os.get_inheritable(observer._fd)
        assert observer.exited() is False
        child.communicate(b"x", timeout=5)
        assert observer.exited(timeout=1) is True
        assert reopened.exited() is True
    finally:
        reopened.close()
        observer.close()


def test_observer_close_never_stops_or_signals_service(child, monkeypatch):
    observer = LinuxServiceObserverV1.capture(child.pid)

    def forbidden(*args, **kwargs):
        pytest.fail("observer must not send process signals")

    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "killpg", forbidden)
    observer.close()
    observer.close()
    assert child.poll() is None
    with pytest.raises(HostingError) as caught:
        observer.exited()
    assert caught.value.category is HostingFailureCategory.HOST_CLOSED


@pytest.mark.parametrize("field,value", [
    ("start_ticks", 0), ("boot_id", "00000000-0000-0000-0000-000000000000"),
    ("user_id", 2**32 - 1), ("pid_namespace_inode", 1),
])
def test_stale_lookup_facts_do_not_create_observer(child, field, value):
    observer = LinuxServiceObserverV1.capture(child.pid)
    try:
        with pytest.raises(HostingError) as caught:
            LinuxServiceObserverV1.reopen(replace(observer.identity, **{field: value}))
        assert caught.value.category is HostingFailureCategory.PREPARATION_STALE
        assert child.poll() is None
    finally:
        observer.close()


def test_missing_process_is_unknown_not_proof_of_clean_exit(child):
    observer = LinuxServiceObserverV1.capture(child.pid)
    identity = observer.identity
    child.communicate(b"x", timeout=5)
    assert observer.exited(timeout=1)
    observer.close()
    with pytest.raises(HostingError) as caught:
        LinuxServiceObserverV1.reopen(identity)
    assert caught.value.category in {
        HostingFailureCategory.PREPARATION_FAILED, HostingFailureCategory.PREPARATION_STALE,
    }


def test_identity_change_around_pidfd_open_is_rejected_without_fd_leak(child, monkeypatch):
    import loushang.hosting.service as module

    original_observe = module._observe
    calls = 0
    descriptors = len(tuple(Path("/proc/self/fd").iterdir()))

    def changed(pid):
        nonlocal calls
        result = original_observe(pid)
        calls += 1
        return replace(result, start_ticks=result.start_ticks + 1) if calls == 2 else result

    monkeypatch.setattr(module, "_observe", changed)
    with pytest.raises(HostingError) as caught:
        LinuxServiceObserverV1.capture(child.pid)
    assert caught.value.category is HostingFailureCategory.PREPARATION_STALE
    assert len(tuple(Path("/proc/self/fd").iterdir())) == descriptors


@pytest.mark.parametrize("timeout", [
    -1, 31, float("nan"), float("inf"), True, "1",
    pytest.param(10**1000, id="huge-positive"), pytest.param(-(10**1000), id="huge-negative"),
])
def test_observation_wait_is_bounded(child, timeout):
    observer = LinuxServiceObserverV1.capture(child.pid)
    try:
        with pytest.raises(HostingError) as caught:
            observer.exited(timeout=timeout)
        assert caught.value.category is HostingFailureCategory.INVALID_REQUEST
    finally:
        observer.close()


@pytest.mark.parametrize("pid", [0, -1, True, "1", 2**31])
def test_invalid_pid_is_rejected_before_io(pid):
    with pytest.raises(HostingError) as caught:
        LinuxServiceObserverV1.capture(pid)
    assert caught.value.category is HostingFailureCategory.INVALID_REQUEST


def test_proc_stat_comm_delimiters_do_not_change_start_time():
    fields = [b"S"] + [b"0"] * 18 + [b"12345"]
    assert _parse_start_ticks(b"123 (name with ) spaces\n) " + b" ".join(fields), 123) == 12345
    with pytest.raises(HostingError):
        _parse_start_ticks(b"124 (name) " + b" ".join(fields), 123)
    with pytest.raises(HostingError):
        _parse_start_ticks(b"123 broken", 123)


def test_independent_client_reopens_same_running_service(child):
    observer = LinuxServiceObserverV1.capture(child.pid)
    identity = observer.identity
    observer.close()
    script = """
import json, sys
from loushang.hosting.service import LinuxServiceIdentityV1, LinuxServiceObserverV1
observer = LinuxServiceObserverV1.reopen(LinuxServiceIdentityV1(**json.loads(sys.argv[1])))
try:
    print('exited' if observer.exited() else 'running')
finally:
    observer.close()
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    result = subprocess.run([sys.executable, "-c", script, json.dumps(asdict(identity))], env=env,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "running"
    assert child.poll() is None


def test_exit_of_leader_does_not_assert_descendant_settlement():
    # The explicit pipe remains owned by a known descendant after the leader
    # exits; a readable pidfd still only proves the leader's exit.
    # Use two inherited pipes so each explicitly owned process has one release.
    leader_read, leader_write = os.pipe()
    descendant_read, descendant_write = os.pipe()
    script = """
import os, subprocess, sys
child = subprocess.Popen([sys.executable, '-c', 'import os,sys; os.read(int(sys.argv[1]),1)', sys.argv[2]],
                         pass_fds=(int(sys.argv[2]),), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid, flush=True)
os.read(int(sys.argv[1]),1)
"""
    leader = subprocess.Popen([sys.executable, "-c", script, str(leader_read), str(descendant_read)],
                              pass_fds=(leader_read, descendant_read), stdout=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    os.close(leader_read)
    os.close(descendant_read)
    parent_observer = descendant_observer = None
    try:
        import select

        assert select.select([leader.stdout], [], [], 5)[0]
        descendant_pid = int(leader.stdout.readline())
        parent_observer = LinuxServiceObserverV1.capture(leader.pid)
        descendant_observer = LinuxServiceObserverV1.capture(descendant_pid)
        os.write(leader_write, b"x")
        leader.wait(timeout=5)
        assert parent_observer.exited(timeout=1)
        assert not descendant_observer.exited()
        assert not hasattr(parent_observer, "process_scope_settled")
    finally:
        os.close(leader_write)
        os.close(descendant_write)
        leader.communicate(timeout=5)
        if descendant_observer is not None:
            assert descendant_observer.exited(timeout=5)
            descendant_observer.close()
        if parent_observer is not None:
            parent_observer.close()


def test_proc_directory_owner_does_not_substitute_for_actual_uid(child, monkeypatch):
    import loushang.hosting.service as module

    original_read = module._read_file

    def different_uid(path, **kwargs):
        if path == "status":
            uid = str(os.geteuid() + 1).encode()
            return b"Uid:\t" + b"\t".join([uid] * 4) + b"\n"
        return original_read(path, **kwargs)

    monkeypatch.setattr(module, "_read_file", different_uid)
    with pytest.raises(HostingError) as caught:
        LinuxServiceObserverV1.capture(child.pid)
    assert caught.value.category is HostingFailureCategory.PREPARATION_REJECTED


def test_contended_observe_is_bounded_and_close_fences_new_waits(child, monkeypatch):
    import loushang.hosting.service as module

    observer = LinuxServiceObserverV1.capture(child.pid)
    entered = threading.Event()
    release = threading.Event()
    short_finished = threading.Event()
    results = []
    failures = []

    class BlockedPoll:
        def register(self, fd, mask):
            pass

        def poll(self, timeout):
            entered.set()
            assert release.wait(5)
            return []

    def wait():
        try:
            results.append(observer.exited(timeout=5))
        except BaseException as error:
            failures.append(error)

    def immediate():
        try:
            observer.exited(timeout=0)
        except HostingError as error:
            results.append(error.category)
        finally:
            short_finished.set()

    def close():
        try:
            observer.close()
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(module.select, "poll", BlockedPoll)
    waiting = threading.Thread(target=wait)
    short = threading.Thread(target=immediate)
    closing = threading.Thread(target=close)
    waiting.start()
    try:
        assert entered.wait(5)
        short.start()
        assert short_finished.wait(1)
        assert HostingFailureCategory.CAPACITY_EXHAUSTED in results
        closing.start()
        assert observer._closing.wait(5)
        with pytest.raises(HostingError) as caught:
            observer.exited(timeout=0)
        assert caught.value.category is HostingFailureCategory.HOST_CLOSED
    finally:
        release.set()
        for worker in (waiting, short, closing):
            if worker.ident is not None:
                worker.join(5)
                assert not worker.is_alive()
        observer.close()
    assert not failures
    assert results.count(False) == 1
    assert child.poll() is None
