from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.session.output_artifacts import (
    SessionOutputPersistingExecService,
    persist_session_command_outputs,
)
from loushang.harness.workspace.exec import (
    CapturePreparation,
    ExecRequest,
    ExecResult,
    ExecService,
    SealedExecCapture,
)


class Source:
    size_bytes = 4

    async def read_bytes(self, *, max_bytes):
        assert max_bytes >= 4
        return b"data"


class Lease:
    def __init__(self, *, fail_close=False, preparation=CapturePreparation.READY):
        self.cleanup_pending = True
        self.fail_close = fail_close
        self.preparation = preparation
        self.closes = 0

    async def prepare(self):
        return self.preparation

    async def append(self, chunk):
        pass

    def stop_accepting(self):
        pass

    async def seal(self):
        return SealedExecCapture(Source(), Source())

    async def close(self):
        self.closes += 1
        if self.fail_close:
            raise OSError("private path must not escape")
        self.cleanup_pending = False


class Factory:
    def __init__(self, lease):
        self.lease = lease
        self.calls = 0

    def new_capture(self):
        self.calls += 1
        return self.lease


class Backend:
    def __init__(self, result=None):
        self.result = result or ExecResult(exit_code=7, stdout_truncated=True)
        self.calls = 0

    async def __call__(self, request, *, signal=None, on_update=None):
        raise AssertionError("legacy execution must not run")

    async def execute_captured(self, request, *, capture, signal=None, on_update=None):
        self.calls += 1
        assert not request.retain_output_artifacts
        assert not request.capture_full_output
        return self.result


def adapter(tmp_path, lease, backend=None):
    return SessionOutputPersistingExecService(
        ExecService(backend=backend or Backend()), session_dir=tmp_path / "sessions",
        session_id="test", temporary_root=tmp_path / "unused-scratch",
        capture_factory=Factory(lease),
    )


def test_published_refs_survive_cleanup_failure_then_close_retries(tmp_path: Path):
    async def run():
        lease = Lease(fail_close=True)
        service = adapter(tmp_path, lease)
        result = await service.execute(ExecRequest(("unused",)))
        assert result.exit_code == 7
        assert result.stdout_artifact_ref is not None
        assert result.stderr_artifact_ref is not None
        assert result.artifact_retention_error is None
        assert result.artifact_cleanup_error == "temporary_cleanup_pending"
        assert not (tmp_path / "unused-scratch").exists()
        lease.fail_close = False
        await service.close()
        await service.close()
        assert lease.closes == 2
        with pytest.raises(RuntimeError, match="closing"):
            await service.execute(ExecRequest(("unused",)))
    asyncio.run(run())


@pytest.mark.parametrize("result", [
    ExecResult(exit_code=7, cancelled=True),
    ExecResult(exit_code=7, stdio_complete=False, stdio_drain_reason="hard_timeout"),
])
def test_ineligible_output_is_not_published(tmp_path: Path, result):
    async def run():
        service = adapter(tmp_path, Lease(), Backend(result))
        actual = await service.execute(ExecRequest(("unused",)))
        assert actual.stdout_artifact_ref is None
        assert actual.stderr_artifact_ref is None
        assert actual.artifact_retention_error is not None
        assert actual.cancelled == result.cancelled
        await service.close()
    asyncio.run(run())


def test_late_prepare_does_not_launch_after_close(tmp_path: Path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        class SlowLease(Lease):
            async def prepare(self):
                started.set()
                await release.wait()
                return CapturePreparation.READY
        backend = Backend()
        service = adapter(tmp_path, SlowLease(), backend)
        execution = asyncio.create_task(service.execute(ExecRequest(("unused",))))
        await started.wait()
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(RuntimeError, match="closing"):
            await execution
        await closing
        assert backend.calls == 0
    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_existing_adapter_cannot_change_capture_authority(tmp_path: Path, managed):
    factory = Factory(Lease())
    service = SessionOutputPersistingExecService(
        ExecService(backend=Backend()), session_dir=tmp_path / "sessions",
        session_id="test", temporary_root=tmp_path / "scratch",
        capture_factory=factory if managed else None,
    )
    with pytest.raises(ValueError, match="capture authority"):
        persist_session_command_outputs(
            service, session_dir=tmp_path / "sessions", session_id="test", persist=True,
            capture_factory=Factory(Lease()),
        )
    if managed:
        assert persist_session_command_outputs(
            service, session_dir=tmp_path / "sessions", session_id="test", persist=True,
            capture_factory=factory,
        ) is service


def test_nonpersistent_capture_is_not_silently_ignored(tmp_path: Path):
    with pytest.raises(ValueError, match="durable Session"):
        persist_session_command_outputs(
            ExecService(), session_dir=tmp_path / "sessions", session_id="test",
            persist=False, capture_factory=Factory(Lease()),
        )


def test_capture_rejects_another_loop_before_factory(tmp_path: Path):
    service = adapter(tmp_path, Lease())
    asyncio.run(service.execute(ExecRequest(("unused",))))
    with pytest.raises(RuntimeError, match="another event loop"):
        asyncio.run(service.execute(ExecRequest(("unused",))))
    with pytest.raises(RuntimeError, match="another event loop"):
        asyncio.run(service.close())


def test_cleanup_debt_occupies_all_eight_slots(tmp_path: Path):
    async def run():
        class FreshFactory:
            calls = 0

            def new_capture(self):
                self.calls += 1
                return Lease(fail_close=True)
        factory = FreshFactory()
        service = SessionOutputPersistingExecService(
            ExecService(backend=Backend()), session_dir=tmp_path / "sessions",
            session_id="test", capture_factory=factory,
        )
        for _ in range(8):
            result = await service.execute(ExecRequest(("unused",)))
            assert result.artifact_cleanup_error == "temporary_cleanup_pending"
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await service.execute(ExecRequest(("unused",)))
        assert factory.calls == 8
    asyncio.run(run())


@pytest.mark.parametrize("unknown", [False, True])
def test_preparation_refusal_and_unknown_have_distinct_execution_effects(tmp_path: Path, unknown):
    async def run():
        class PreparedLease(Lease):
            async def prepare(self):
                if unknown:
                    raise OSError("unknown original commit")
                return CapturePreparation.RETENTION_UNAVAILABLE
        backend = Backend()
        service = adapter(tmp_path, PreparedLease(), backend)
        if unknown:
            with pytest.raises(OSError, match="unknown original commit"):
                await service.execute(ExecRequest(("unused",)))
            assert backend.calls == 0
        else:
            result = await service.execute(ExecRequest(("unused",)))
            assert backend.calls == 1
            assert result.stdout_artifact_ref is None
            assert result.artifact_retention_error is not None
        await service.close()
    asyncio.run(run())


@pytest.mark.parametrize("receipt_fails", [False, True])
def test_late_cleanup_waiter_cannot_erase_next_phase(tmp_path: Path, monkeypatch, receipt_fails):
    from loushang.harness.session import _output_capture as capture_module

    async def run():
        lease = Lease(fail_close=True)
        service = adapter(tmp_path, lease)
        await service.execute(ExecRequest(("unused",)))
        owner = service._capture
        assert owner is not None
        pending = owner._pending[0]
        lease.fail_close = False
        first_release, second_release = asyncio.Event(), asyncio.Event()
        second_started = asyncio.Event()
        late_joined, late_release = asyncio.Event(), asyncio.Event()
        original_join = capture_module._await_cancellation_atomic
        late = None

        async def phased_close():
            lease.closes += 1
            if lease.closes == 2:
                await first_release.wait()
                # First successful phase still has native debt.
            else:
                lease.cleanup_pending = False
                second_started.set()
                await second_release.wait()
                if receipt_fails:
                    raise OSError("cleanup receipt unknown")

        async def delayed_join(task):
            result = await original_join(task)
            if asyncio.current_task() is late:
                late_joined.set()
                await late_release.wait()
            return result

        monkeypatch.setattr(lease, "close", phased_close)
        monkeypatch.setattr(capture_module, "_await_cancellation_atomic", delayed_join)
        first = asyncio.create_task(owner.close())
        late = asyncio.create_task(owner.close())
        await asyncio.sleep(0)
        first_release.set()
        await late_joined.wait()
        with pytest.raises(RuntimeError, match="cleanup remains pending"):
            await first
        next_phase = asyncio.create_task(owner.close())
        await second_started.wait()
        original_next = pending.cleanup
        assert original_next is not None and not original_next.done()
        late_release.set()
        with pytest.raises(RuntimeError, match="cleanup remains pending"):
            await late
        assert pending.cleanup is original_next
        assert pending in owner._pending
        final_waiter = asyncio.create_task(owner.close())
        await asyncio.sleep(0)
        assert pending.cleanup is original_next
        second_release.set()
        outcomes = await asyncio.gather(next_phase, final_waiter, return_exceptions=True)
        if receipt_fails:
            assert all(isinstance(value, OSError) for value in outcomes)
            assert pending in owner._pending
        else:
            assert outcomes == [None, None]
            assert pending not in owner._pending
        assert lease.closes == 3
    asyncio.run(run())


@pytest.mark.parametrize("fault", ["aggregate_limit", "changed_length", "publication"])
def test_publication_failure_and_cleanup_failure_remain_independent(tmp_path: Path, monkeypatch, fault):
    from loushang.harness.session import _output_capture as capture_module

    async def run():
        class FaultySource(Source):
            async def read_bytes(self, *, max_bytes):
                if fault == "aggregate_limit":
                    raise AssertionError("limit must be checked before reads")
                return b"changed" if fault == "changed_length" else b"data"

        class FaultyLease(Lease):
            async def seal(self):
                return SealedExecCapture(FaultySource(), FaultySource())

        service = adapter(tmp_path, FaultyLease(fail_close=True))
        imports = []

        def failed_import(values):
            imports.append(values)
            raise OSError("publication outcome unknown")

        monkeypatch.setattr(service._store, "import_blobs", failed_import)
        if fault == "aggregate_limit":
            monkeypatch.setattr(capture_module, "MAX_PUBLICATION_BYTES", 7)
        result = await service.execute(ExecRequest(("unused",)))
        assert result.exit_code == 7
        assert result.stdout_artifact_ref is None
        assert result.stderr_artifact_ref is None
        assert result.artifact_retention_error == "command output was not retained"
        assert result.artifact_cleanup_error == "temporary_cleanup_pending"
        assert len(imports) == (1 if fault == "publication" else 0)
        assert len(service._capture._pending) == 1
    asyncio.run(run())


def test_complete_timeout_keeps_real_status_and_publishes(tmp_path: Path):
    async def run():
        service = adapter(tmp_path, Lease(), Backend(ExecResult(exit_code=-15, timed_out=True)))
        result = await service.execute(ExecRequest(("unused",)))
        assert result.timed_out
        assert result.exit_code == -15
        assert result.stdout_artifact_ref is not None
        await service.close()
    asyncio.run(run())


def test_repeated_cancel_joins_original_cleanup_without_publication(tmp_path: Path, monkeypatch):
    async def run():
        reading, cleanup_started, cleanup_release = (asyncio.Event() for _ in range(3))

        class WaitingSource(Source):
            async def read_bytes(self, *, max_bytes):
                reading.set()
                await asyncio.Event().wait()

        class WaitingLease(Lease):
            async def seal(self):
                return SealedExecCapture(WaitingSource(), Source())

            async def close(self):
                self.closes += 1
                cleanup_started.set()
                await cleanup_release.wait()
                self.cleanup_pending = False

        lease = WaitingLease()
        service = adapter(tmp_path, lease)

        def no_import(values):
            raise AssertionError("cancelled read must not publish")

        monkeypatch.setattr(service._store, "import_blobs", no_import)
        execution = asyncio.create_task(service.execute(ExecRequest(("unused",))))
        await reading.wait()
        execution.cancel()
        await cleanup_started.wait()
        execution.cancel()
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not execution.done()
        assert not closing.done()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await execution
        await closing
        assert lease.closes == 1
        assert not service._capture._pending
    asyncio.run(run())
