import asyncio
from threading import Event

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.output_capture import (
    ManagedOutputCapture,
    ManagedOutputCaptureFactory,
)
from loushang.harness.workspace.exec.capture_lease import CapturePreparation
from loushang.harness.workspace.exec.types import ExecOutputChunk

from .test_managed_files import directory as directory
from .test_managed_storage_budget import namespace as namespace
from .test_managed_storage_budget import pytestmark as pytestmark
from .test_managed_storage_budget import registry as registry
from .test_native_output_capture import capture


def test_async_capture_delivers_both_sources_and_releases_storage(registry, directory):
    native = capture(registry, directory)
    lease = ManagedOutputCapture(native)

    async def run():
        assert await lease.prepare() is CapturePreparation.READY
        await lease.append(ExecOutputChunk("stdout", "你好"))
        await lease.append(ExecOutputChunk("stderr", "warning"))
        sources = await lease.seal()
        assert sources is await lease.seal()
        assert await sources.stdout.read_bytes(max_bytes=6) == "你好".encode()
        assert await sources.stderr.read_bytes(max_bytes=7) == b"warning"
        await lease.close()
        assert not lease.cleanup_pending
        with pytest.raises(ManagedStorageError, match="closed"):
            await sources.stdout.read_bytes(max_bytes=6)

    asyncio.run(run())
    assert all(native.budget.lookup(request) is None for request in native.allocations)


@pytest.mark.parametrize("operation", ["prepare", "read"])
def test_cancelled_waiter_keeps_native_work_until_close(registry, directory, monkeypatch, operation):
    native = capture(registry, directory)
    lease = ManagedOutputCapture(native)
    entered, resume, completed = Event(), Event(), Event()
    original = getattr(native, operation)
    original_close = native.close

    def paused(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        try:
            return original(*args, **kwargs)
        finally:
            completed.set()

    def close_after_completion():
        assert completed.is_set()
        original_close()

    async def run():
        if operation == "read":
            await lease.prepare()
            await lease.append(ExecOutputChunk("stdout", "hello"))
            sources = await lease.seal()
        monkeypatch.setattr(native, operation, paused)
        monkeypatch.setattr(native, "close", close_after_completion)
        waiting = asyncio.create_task(lease.prepare() if operation == "prepare" else sources.stdout.read_bytes(max_bytes=5))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert lease.cleanup_pending
            if operation == "read":
                with pytest.raises(ManagedStorageError, match="busy"):
                    await sources.stdout.read_bytes(max_bytes=5)
            closing = asyncio.create_task(lease.close())
            await asyncio.sleep(0)
            assert not closing.done()
        finally:
            resume.set()
            if closing is not None:
                await closing
            else:
                await lease.close()
        assert not lease.cleanup_pending

    asyncio.run(run())
    assert all(native.budget.lookup(request) is None for request in native.allocations)


def test_executor_submission_receipt_loss_never_admits_native(registry, directory, monkeypatch):
    native = capture(registry, directory)
    lease = ManagedOutputCapture(native)
    submitted = []

    async def run():
        loop = asyncio.get_running_loop()
        original = loop.run_in_executor

        def lost_receipt(*args, **kwargs):
            submitted.append(original(*args, **kwargs))
            raise OSError("executor submitted but lost return")

        with monkeypatch.context() as patch:
            patch.setattr(loop, "run_in_executor", lost_receipt)
            with pytest.raises(OSError):
                await lease.prepare()
        await asyncio.gather(*submitted)
        assert not native.started and native.attempt is None
        await lease.close()
        assert not lease.cleanup_pending

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["prepare", "seal"])
def test_late_public_waiter_cannot_deliver_after_close(registry, directory, monkeypatch, operation):
    native = capture(registry, directory)
    lease = ManagedOutputCapture(native)

    async def run():
        if operation == "seal":
            await lease.prepare()
        reached, resume = asyncio.Event(), asyncio.Event()
        original_shield = asyncio.shield
        waiter = None

        def delayed_shield(awaitable):
            if asyncio.current_task() is waiter:
                async def delayed():
                    result = await original_shield(awaitable)
                    reached.set()
                    await resume.wait()
                    return result
                return delayed()
            return original_shield(awaitable)

        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "shield", delayed_shield)
            waiter = asyncio.create_task(getattr(lease, operation)())
            try:
                await asyncio.wait_for(reached.wait(), timeout=5)
                await lease.close()
            finally:
                resume.set()
            with pytest.raises(ManagedStorageError, match="closed"):
                await waiter
        assert lease._sealed is None and not lease.cleanup_pending

    asyncio.run(run())


def test_internal_cancellation_cannot_overlap_or_admit_queued_native(registry, directory, monkeypatch):
    native = capture(registry, directory)
    lease = ManagedOutputCapture(native)
    entered, resume, finished = Event(), Event(), Event()
    original_append = native.append
    calls = []

    def paused(index, content):
        calls.append(content)
        entered.set()
        assert resume.wait(5)
        try:
            original_append(index, content)
        finally:
            finished.set()

    async def run():
        await lease.prepare()
        monkeypatch.setattr(native, "append", paused)
        first = asyncio.create_task(lease.append(ExecOutputChunk("stdout", "first")))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            original_task = next(task for task in lease._pending if not task.done())
            second = asyncio.create_task(lease.append(ExecOutputChunk("stderr", "second")))
            await asyncio.sleep(0)
            original_task.cancel()
            await asyncio.sleep(0)
            assert not original_task.done() and calls == [b"first"]
        finally:
            resume.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(ManagedStorageError, match="unavailable"):
            await second
        assert finished.is_set() and calls == [b"first"]
        with pytest.raises(ManagedStorageError, match="unavailable"):
            await lease.close()
        assert lease.cleanup_pending

    try:
        asyncio.run(run())
    finally:
        resume.set()
        # Test-owned native cleanup only after asyncio.run joined its executor;
        # the deliberately cancelled lease retains its unknown state.
        native.close()


def test_factory_keeps_unstarted_leases_until_explicit_close_without_storage_io(registry, directory, monkeypatch):
    native = capture(registry, directory)
    request = native.allocations[0]
    factory = ManagedOutputCaptureFactory(native.owner, native.budget, service_id=request.service_id,
                                          instance_id=request.instance_id, capacity=4096)

    def unexpected(*args, **kwargs):
        raise AssertionError("lease allocation must not perform storage IO")

    async def run():
        with monkeypatch.context() as patch:
            patch.setattr(native.owner, "_open", unexpected)
            patch.setattr(native.budget._database, "transaction", unexpected)
            leases = [factory.new_capture() for _ in range(8)]
            assert factory.cleanup_pending
            with pytest.raises(ManagedStorageError, match="capacity"):
                factory.new_capture()
            await leases[0].close()
            replacement = factory.new_capture()
            assert replacement is not leases[0] and replacement._native.allocations[0].slot == 0
            await factory.close()
            assert not factory.cleanup_pending
            with pytest.raises(ManagedStorageError, match="closed"):
                factory.new_capture()

    asyncio.run(run())
    assert native.owner._fd is not None  # Factory only borrowed the shared root.
