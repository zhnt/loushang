"""Checks of one retained owner coordinate without serializing its operations."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading

import pytest

from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_runtime_profile import _runtime
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_runtime import prepare

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux retained writer")


class ObservedRLock:
    """Expose real contention so tests never depend on a scheduling delay."""

    def __init__(self):
        self.lock = threading.RLock()
        self.contended = threading.Event()

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contended.set()
            self.lock.acquire()
        return self

    def __exit__(self, *_):
        self.lock.release()


@pytest.mark.parametrize("lease_kind", ["transcript", "blob"])
@pytest.mark.parametrize("second_kind", ["async", "sync"])
def test_overlapping_checks_share_one_healthy_owner(
    tmp_path, monkeypatch, lease_kind, second_kind
):
    async def scenario():
        runtime = _runtime("coding")
        owner, writer = prepare(
            tmp_path, runtime, runtime.bind_lifecycle_owned, manage_blobs=True
        )
        session = await owner.create()
        selected = writer if lease_kind == "transcript" else owner._blob_writer
        original = selected._validate_binding
        entered, release = threading.Event(), threading.Event()
        coordinator = ObservedRLock()
        monkeypatch.setattr(owner, "_writer_check_lock", coordinator, raising=False)

        def validation():
            if not entered.is_set():
                entered.set()
                assert release.wait(10), "first native check was never released"
            original()

        monkeypatch.setattr(selected, "_validate_binding", validation)

        async def operation():
            async with session.operation_scope():
                return "admitted"

        first = asyncio.create_task(operation())
        second = None
        waiter = None
        helper = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            if second_kind == "async":
                second = asyncio.create_task(operation())
                waiter = asyncio.create_task(
                    asyncio.to_thread(coordinator.contended.wait, 5)
                )
                # Old code finishes with busy; fixed code waits at the coordinator.
                await asyncio.wait(
                    (second, waiter), return_when=asyncio.FIRST_COMPLETED
                )
                release.set()
                results = await asyncio.gather(first, second, return_exceptions=True)
            else:

                def unblock():
                    if coordinator.contended.wait(5):
                        release.set()

                helper = threading.Thread(target=unblock)
                helper.start()
                try:
                    with session.sync_operation_scope():
                        result = "admitted"
                except Exception as error:
                    result = error
                finally:
                    release.set()
                results = [await first, result]
            assert results == ["admitted", "admitted"]
            assert writer._held and not writer._closing
        finally:
            release.set()
            coordinator.contended.set()
            await asyncio.gather(
                *[task for task in (first, second, waiter) if task is not None],
                return_exceptions=True,
            )
            if helper is not None:
                helper.join(5)
                assert not helper.is_alive()
            monkeypatch.undo()
            await owner.dispose()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_check_coordination_allows_overlapping_and_nested_operations(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        first_inside, second_inside = asyncio.Event(), asyncio.Event()

        async def first():
            async with session.operation_scope():
                first_inside.set()
                await second_inside.wait()
                async with session.operation_scope():
                    pass
                with session.sync_operation_scope():
                    pass

        async def second():
            await first_inside.wait()
            async with session.operation_scope():
                second_inside.set()

        try:
            async with asyncio.timeout(10):  # Failure-only deadlock watchdog.
                await asyncio.gather(first(), second())
        finally:
            await owner.dispose()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_check_coordination_is_local_to_one_owner(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        roots = [tmp_path / "first", tmp_path / "second"]
        for root in roots:
            root.mkdir(mode=0o700)
        owners = [
            prepare(root, runtime, runtime.bind_lifecycle_owned)[0] for root in roots
        ]
        sessions = [await owner.create() for owner in owners]
        entered, release = threading.Event(), threading.Event()
        original = owners[0]._writer._validate_binding

        def validation():
            entered.set()
            assert release.wait(10)
            original()

        monkeypatch.setattr(owners[0]._writer, "_validate_binding", validation)

        async def operation():
            async with sessions[0].operation_scope():
                pass

        first = asyncio.create_task(operation())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            async with asyncio.timeout(5):
                async with sessions[1].operation_scope():
                    assert not first.done()
        finally:
            release.set()
            await first
            monkeypatch.undo()
            for owner in owners:
                await owner.dispose()
        assert all(not owner.cleanup_pending for owner in owners)

    asyncio.run(scenario())


def test_cancelled_queued_check_settles_before_writer_disposal(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        owner, writer = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        entered, release = threading.Event(), threading.Event()
        closing_waited = asyncio.Event()
        original = writer._validate_binding
        original_wait = owner._io_drained.wait
        coordinator = ObservedRLock()
        monkeypatch.setattr(owner, "_writer_check_lock", coordinator)

        def validation():
            if not entered.is_set():
                entered.set()
                assert release.wait(10)
            original()

        async def wait_for_drain():
            closing_waited.set()
            await original_wait()

        monkeypatch.setattr(writer, "_validate_binding", validation)
        monkeypatch.setattr(owner._io_drained, "wait", wait_for_drain)
        admitted = []

        async def operation(number):
            async with session.operation_scope():
                admitted.append(number)

        tasks = []
        try:
            first = asyncio.create_task(operation(1))
            tasks.append(first)
            assert await asyncio.to_thread(entered.wait, 5)
            second = asyncio.create_task(operation(2))
            tasks.append(second)
            assert await asyncio.to_thread(coordinator.contended.wait, 5)
            second.cancel()
            closing = asyncio.create_task(owner.dispose())
            tasks.append(closing)
            async with asyncio.timeout(5):
                await closing_waited.wait()
            assert owner.closing and owner._active_io == 2
            assert not second.done() and not closing.done()
            assert_busy(tmp_path)
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert results[0] is None
            assert isinstance(results[1], asyncio.CancelledError)
            assert results[2] is None
            assert admitted == [1]
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            monkeypatch.undo()
            await owner.dispose()
        assert not owner.cleanup_pending
        assert_available(tmp_path)

    asyncio.run(scenario())


def test_fork_rejects_before_waiting_for_inherited_check_coordinator(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        await owner.create()
        entered, release = threading.Event(), threading.Event()

        def hold():
            with owner._writer_check_lock:
                entered.set()
                release.wait(10)

        helper = threading.Thread(target=hold)
        helper.start()
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pid = os.fork()
            if pid == 0:
                signal.alarm(3)  # An inherited mutex must never strand the child.
                try:
                    owner._check_writers()
                except TranscriptWriterError as error:
                    os._exit(0 if error.code == "unsupported" else 2)
                except BaseException:
                    os._exit(3)
                os._exit(4)
            _, status = await asyncio.to_thread(os.waitpid, pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        finally:
            release.set()
            helper.join(5)
            assert not helper.is_alive()
            await owner.dispose()
        assert not owner.cleanup_pending

    asyncio.run(scenario())
