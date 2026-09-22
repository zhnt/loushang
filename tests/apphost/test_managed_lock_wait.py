from __future__ import annotations

import asyncio
import fcntl
import selectors
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest

from loushang.apphost.managed import _files
from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory

from .test_managed_files import directory as directory

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed flock")


def test_wait_uses_original_fd_until_other_process_releases(directory, monkeypatch):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        pass
    script = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX)
    print('locked', flush=True)
    sys.stdin.readline()
finally:
    os.close(fd)
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(root / "control.lock")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    blocked = Event()
    descriptors = []
    native = fcntl.flock

    def probe(fd, flags):
        descriptors.append(fd)
        try:
            return native(fd, flags)
        except BlockingIOError:
            blocked.set()
            raise

    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=3), "child did not acquire original lock"
        assert child.stdout.readline().strip() == "locked"
        monkeypatch.setattr(fcntl, "flock", probe)

        def release():
            assert blocked.wait(3)
            child.stdin.write("release\n")
            child.stdin.flush()

        with ThreadPoolExecutor(max_workers=1) as pool:
            releasing = pool.submit(release)
            with owner.lock("control.lock", deadline=monotonic() + 5, wait_for_lock=True):
                assert len(descriptors) >= 2 and len(set(descriptors)) == 1
            releasing.result(timeout=3)
        assert child.wait(timeout=3) == 0
    finally:
        child.communicate("release\n" if child.poll() is None else None, timeout=5)


@pytest.mark.parametrize("replacement", [False, True])
def test_wait_timeout_or_replacement_never_enters_body_or_reopens(directory, monkeypatch, replacement):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        pass
    clock = [100.0]
    opens = []
    original = owner._open

    def opened(*args, **kwargs):
        value = original(*args, **kwargs)
        opens.append(value)
        return value

    def busy(*args):
        raise BlockingIOError()

    def pause(delay):
        clock[0] += delay
        if replacement:
            (root / "control.lock").rename(root / "held.lock")
            (root / "control.lock").touch(mode=0o600)

    monkeypatch.setattr(owner, "_open", opened)
    monkeypatch.setattr(_files, "monotonic", lambda: clock[0])
    monkeypatch.setattr(_files, "sleep", pause, raising=False)
    monkeypatch.setattr(fcntl, "flock", busy)
    with pytest.raises(ManagedStorageError, match="conflict" if replacement else "busy"):
        with owner.lock("control.lock", deadline=100.02, wait_for_lock=True):
            pytest.fail("unadmitted body")
    assert len(opens) == 1 and not owner._locks
    assert (root / "control.lock").exists()


def test_wait_is_explicit_and_forbidden_on_event_loop_thread(directory):
    root, owner = directory
    other = PrivateManagedDirectory(root)

    async def scenario():
        with owner.lock("control.lock", create=True):
            for wait in (False, True):
                with pytest.raises(ManagedStorageError, match="busy"):
                    with other.lock("control.lock", deadline=monotonic() + 5, wait_for_lock=wait):
                        pytest.fail("event-loop waiter stole held lock")
                await asyncio.sleep(0)  # Original holder can resume and release.

    try:
        asyncio.run(scenario())
    finally:
        other.close()


@pytest.mark.parametrize("deadline", [None, True, "soon", -1, float("nan"), float("inf")])
def test_wait_requires_valid_deadline_before_open(directory, monkeypatch, deadline):
    _, owner = directory
    monkeypatch.setattr(owner, "_open", lambda *args, **kwargs: pytest.fail("opened invalid wait"))
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        with owner.lock("control.lock", create=True, deadline=deadline, wait_for_lock=True):
            pytest.fail("invalid wait admitted")


def test_event_loop_rejects_explicit_wait_even_without_contention(directory, monkeypatch):
    _, owner = directory
    monkeypatch.setattr(owner, "_open", lambda *args, **kwargs: pytest.fail("opened loop wait"))

    async def scenario():
        with pytest.raises(ManagedStorageError, match="busy"):
            with owner.lock("control.lock", create=True, deadline=monotonic() + 5,
                            wait_for_lock=True):
                pytest.fail("loop wait admitted")

    asyncio.run(scenario())


@pytest.mark.parametrize("bounded", [False, True])
def test_same_owner_local_mutex_never_blocks_event_loop(directory, monkeypatch, bounded):
    root, owner = directory
    other = PrivateManagedDirectory(root)
    blocked = Event()
    native = fcntl.flock
    mutex = owner._mutex

    class CheckedMutex:
        def acquire(self, *args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                assert kwargs.get("blocking") is False, "blocking local mutex on event loop"
            return mutex.acquire(*args, **kwargs)

        def release(self):
            mutex.release()

    def probe(fd, flags):
        try:
            return native(fd, flags)
        except BlockingIOError:
            blocked.set()
            raise

    def waiting():
        with owner.lock("control.lock", deadline=monotonic() + 5, wait_for_lock=True):
            return "settled"

    async def scenario():
        assert await asyncio.to_thread(blocked.wait, 3)
        deadline = monotonic() + 1 if bounded else None
        with pytest.raises(ManagedStorageError, match="busy"):
            with owner.lock("control.lock", deadline=deadline):
                pytest.fail("same-owner loop acquired worker's mutex")
        await asyncio.sleep(0)
        assert not worker.done()

    monkeypatch.setattr(owner, "_mutex", CheckedMutex())
    monkeypatch.setattr(fcntl, "flock", probe)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with other.lock("control.lock", create=True):
                worker = pool.submit(waiting)
                asyncio.run(scenario())
            assert worker.result(timeout=3) == "settled"
    finally:
        monkeypatch.setattr(owner, "_mutex", mutex)
        other.close()
