from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from threading import Event
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.appserver.client import AppConnectionClosedError
from loushang.appserver.local_record import LocalRecordError, LocalRecordErrorCodeV1
from tests.apphost.test_managed_connection import committed
from tests.apphost.test_managed_starter import owners as owners

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed coordinator")


def coordinator(owners):
    journal, namespace, service, runtime = owners

    def forbidden(*args):
        raise AssertionError("unit observation must not launch a child")

    return ManagedServiceCoordinatorV1(
        journal, namespace, service, runtime_root=runtime, endpoint="workspace", request_factory=forbidden,
    )


def fake_leases(monkeypatch, hook=None):
    created = []

    class Lease:
        def __init__(self, journal, namespace, service, instance, **kwargs):
            self.instance = instance
            self.closed = False
            self.close_error = False
            created.append(self)

        @property
        def client(self):
            if self.closed:
                raise AppConnectionClosedError()
            return self

        async def prepare(self, **kwargs):
            if hook is not None:
                await hook(self)

        async def close(self):
            if self.close_error:
                raise RuntimeError("injected_close")
            self.closed = True

    monkeypatch.setattr("loushang.apphost.managed.coordinator.ManagedConnectionLeaseV1", Lease)
    return created


def test_reuse_returns_same_operation_without_launch_or_budget_renewal(owners, monkeypatch):
    state = committed(owners)
    created = fake_leases(monkeypatch)
    owner = coordinator(owners)

    async def scenario():
        deadline = monotonic() + 5
        first = await owner.ensure_started(deadline=deadline)
        assert await owner.ensure_started(deadline=deadline) is first
        assert first.instance == owner.instance == state.handoff.instance
        with pytest.raises(ManagedStorageError, match="conflict"):
            await owner.ensure_started(deadline=deadline + 1)
        assert len(created) == 1 and owner._starter._process is None
        await owner.close()
        assert first.closed and not owner.cleanup_pending

    asyncio.run(scenario())
    assert owners[0].read() == state


def test_start_reply_loss_is_observed_not_replayed(owners, monkeypatch):
    owner = coordinator(owners)
    created = fake_leases(monkeypatch)
    calls = []

    def lost(**kwargs):
        calls.append(1)
        committed(owners)  # Pure durable fixture; a competing start won.
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(owner._starter, "start", lost)

    async def scenario():
        try:
            result = await owner.ensure_started(deadline=monotonic() + 5)
            assert result is created[0] and calls == [1]
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_unknown_start_without_durable_result_is_not_replayed(owners, monkeypatch):
    owner = coordinator(owners)
    calls = []

    def lost(**kwargs):
        calls.append(1)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(owner._starter, "start", lost)

    async def scenario():
        deadline = monotonic() + 5
        try:
            for _ in range(2):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    await owner.ensure_started(deadline=deadline)
            assert calls == [1] and owner.instance is None
        finally:
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["not_found", "busy", "corrupt"])
def test_readiness_retries_only_read_failures_after_settlement(owners, monkeypatch, kind):
    committed(owners)
    calls = []

    async def hook(lease):
        calls.append(lease)
        if len(calls) == 1:
            if kind == "busy":
                raise ManagedStorageError("busy")
            raise LocalRecordError(LocalRecordErrorCodeV1.NOT_FOUND if kind == "not_found" else LocalRecordErrorCodeV1.CORRUPT)
        assert calls[0].closed

    created = fake_leases(monkeypatch, hook)
    owner = coordinator(owners)

    async def scenario():
        try:
            if kind == "corrupt":
                with pytest.raises(LocalRecordError):
                    await owner.ensure_started(deadline=monotonic() + 5)
                assert len(created) == 1
            else:
                result = await owner.ensure_started(deadline=monotonic() + 5)
                assert result is created[1] and created[0].closed
        finally:
            await owner.close()
        assert all(item.closed for item in created)

    asyncio.run(scenario())


def test_failed_readiness_cleanup_blocks_replacement(owners, monkeypatch):
    committed(owners)

    async def hook(lease):
        lease.close_error = True
        raise LocalRecordError(LocalRecordErrorCodeV1.NOT_FOUND)

    created = fake_leases(monkeypatch, hook)
    owner = coordinator(owners)

    async def scenario():
        try:
            with pytest.raises(RuntimeError, match="injected_close"):
                await owner.ensure_started(deadline=monotonic() + 5)
            assert len(created) == 1 and owner._connection is created[0] and owner.cleanup_pending
        finally:
            created[0].close_error = False
            await owner.close()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_generation_change_during_wait_does_not_retarget(owners, monkeypatch):
    journal = owners[0]
    state = journal.prepare("c" * 32, expected=None)
    owner = coordinator(owners)
    calls = []

    async def change(deadline):
        calls.append(1)
        changed = replace(state, handoff=replace(state.handoff, instance=replace(state.handoff.instance, instance_id="d" * 32)),
                          evidence=replace(state.evidence, instance=replace(state.handoff.instance, instance_id="d" * 32)))
        monkeypatch.setattr(journal, "read", lambda **kwargs: changed)

    monkeypatch.setattr(owner, "_pause", change)
    created = fake_leases(monkeypatch)

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError, match="conflict"):
                await owner.ensure_started(deadline=monotonic() + 5)
            assert calls == [1] and owner.instance == state.handoff.instance and not created
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_stopping_instance_does_not_start_or_connect(owners, monkeypatch):
    state = committed(owners)
    owners[0].request_stop(state.handoff.instance)
    owner = coordinator(owners)
    created = fake_leases(monkeypatch)

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError, match="conflict"):
                await owner.ensure_started(deadline=monotonic() + 5)
            assert not owner._starter._started and not created
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_close_fences_start_and_joins_cancelled_native_waiter(owners, monkeypatch):
    owner = coordinator(owners)
    entered, release = Event(), Event()
    original = owners[0].read

    def held(**kwargs):
        entered.set()
        assert release.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(owners[0], "read", held)

    async def scenario():
        work = asyncio.create_task(owner.ensure_started(deadline=monotonic() + 10))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            work.cancel()
            with pytest.raises(asyncio.CancelledError):
                await work
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0)
            assert owner._starter._closing.is_set() and not closing.done()
        finally:
            release.set()
            await owner.close()
            await asyncio.gather(work, *([closing] if closing else []), return_exceptions=True)
        assert not owner._starter._started and not owner.cleanup_pending

    asyncio.run(scenario())


def test_cancelled_waiter_can_rejoin_same_operation_without_renewal(owners, monkeypatch):
    committed(owners)
    owner = coordinator(owners)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def held(lease):
            entered.set()
            await release.wait()

        created = fake_leases(monkeypatch, held)
        deadline = monotonic() + 5
        work = asyncio.create_task(owner.ensure_started(deadline=deadline))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            original_task = owner._task
            work.cancel()
            with pytest.raises(asyncio.CancelledError):
                await work
            assert not original_task.done()
            release.set()
            result = await owner.ensure_started(deadline=deadline)
            assert result is created[0] and len(created) == 1
            assert owner._task is original_task and owner._deadline == deadline
            await result.close()
            with pytest.raises(AppConnectionClosedError):
                await owner.ensure_started(deadline=deadline)
            assert len(created) == 1
        finally:
            release.set()
            await owner.close()
            await asyncio.gather(work, return_exceptions=True)

    asyncio.run(scenario())


def test_failed_connection_close_still_closes_starter_and_retains_original(owners, monkeypatch):
    committed(owners)
    owner = coordinator(owners)
    created = fake_leases(monkeypatch)
    original = owner._starter.close
    closes = []

    def close():
        closes.append(1)
        original()

    monkeypatch.setattr(owner._starter, "close", close)

    async def scenario():
        result = await owner.ensure_started(deadline=monotonic() + 5)
        result.close_error = True
        try:
            with pytest.raises(RuntimeError, match="injected_close"):
                await owner.close()
            assert closes == [1] and owner._connection is result and owner.cleanup_pending
        finally:
            result.close_error = False
            await owner.close()
        assert len(created) == 1 and result.closed and not owner.cleanup_pending

    asyncio.run(scenario())
