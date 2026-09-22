from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace

import pytest

from loushang.apphost.managed import mux_probe as module
from loushang.apphost.managed.contracts import ManagedServiceKeyV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError, MuxSpaceV1

from .test_managed_connection import committed
from .test_managed_discovery import discovery as discovery
from .test_managed_discovery import owners as owners
from .test_managed_discovery import pytestmark as pytestmark


@pytest.fixture
def probe(owners, discovery, monkeypatch):
    committed(owners)
    reader, registry = discovery
    registry.reserve_mux(ManagedMuxReservationV1("second", owners[2], "d" * 32))
    leases = []
    behavior = SimpleNamespace(absent=False, failed=False, close_failed=False, gate=None, close_gate=None)

    class Lease:
        def __init__(self, *args, **kwargs):
            self.client = self
            self.application_id = "coding.default"
            self.closed = False
            leases.append(self)

        async def prepare(self, **kwargs):
            if behavior.gate is not None:
                await behavior.gate.wait()
            if behavior.failed:
                raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)

        async def read_mux(self, request):
            name = request.selector.mux_space_id
            if name == "second" and behavior.absent:
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
            return MuxSpaceV1(name, name, 1)

        async def close(self):
            if behavior.close_gate is not None:
                await behavior.close_gate.wait()
            if behavior.close_failed:
                raise RuntimeError("injected close failure")
            self.closed = True

    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        def inspect_mux(self, reservation, **kwargs):
            return SimpleNamespace(creation=SimpleNamespace(mux_space_id=reservation.name))

    monkeypatch.setattr(module, "ManagedConnectionLeaseV1", Lease)
    monkeypatch.setattr(module, "ManagedMuxManagerV1", Manager)
    operation = module.ManagedMuxProbeOperationV1(registry, owners[1], product_id="coding",
        runtime_root=owners[3], endpoint="workspace", expected_application_id="coding.default",
        deadline=monotonic() + 10)
    return operation, leases, behavior


@pytest.mark.parametrize("outcome", ["both", "absent", "failed"])
def test_one_authentication_per_service_and_exact_mux_results(probe, outcome):
    operation, leases, behavior = probe
    behavior.absent = outcome == "absent"
    behavior.failed = outcome == "failed"
    async def run():
        try:
            result = await operation.run()
            assert result.candidates_unchanged
            assert len(result.results) == 2
            if outcome == "failed":
                assert all(row.status == "unknown" for row in result.results)
            elif outcome == "absent":
                assert result.unique_present.observation.name == "main"
            else:
                assert all(row.status == "authenticated_present" for row in result.results)
            if outcome != "absent":
                assert result.unique_present is None
            assert len(leases) == 1 and leases[0].closed
        finally:
            await operation.close()
    asyncio.run(run())
    assert not operation.cleanup_pending


def test_cleanup_failure_prevents_results_and_retains_original_owner(probe):
    operation, leases, behavior = probe
    behavior.close_failed = True
    async def run():
        with pytest.raises(RuntimeError, match="injected close"):
            await operation.run()
        assert operation.cleanup_pending and operation._connection is leases[0]
        assert operation._journal is not None
        behavior.close_failed = False
        await operation.close()
    asyncio.run(run())
    assert not operation.cleanup_pending and leases[0].closed


def test_cancelled_waiter_rejoins_original_probe(probe):
    operation, leases, behavior = probe
    async def run():
        behavior.gate = asyncio.Event()
        waiter = asyncio.create_task(operation.run())
        try:
            async with asyncio.timeout(5):
                while not leases:
                    await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not operation._task.done()
            behavior.gate.set()
            assert (await operation.run()).candidates_unchanged
            assert len(leases) == 1
        finally:
            behavior.gate.set()
            await operation.close()
    asyncio.run(run())


def test_journal_close_failure_retains_journal_without_reopening_connection(probe, monkeypatch):
    operation, leases, _ = probe
    original_close = module.ManagedServiceJournalV1.close
    failed_journals = []
    fail = [True]

    def close(journal):
        if fail[0]:
            failed_journals.append(journal)
            raise RuntimeError("injected journal close failure")
        return original_close(journal)

    monkeypatch.setattr(module.ManagedServiceJournalV1, "close", close)

    async def run():
        try:
            with pytest.raises(RuntimeError, match="injected journal close"):
                await operation.run()
            retained = operation._journal
            assert retained is failed_journals[0]
            assert operation._connection is None
            assert len(leases) == 1 and leases[0].closed
            assert operation.cleanup_pending
            # Rejoining the failed original task cannot authenticate again or
            # turn its discarded observations into a successful result.
            with pytest.raises(RuntimeError, match="injected journal close"):
                await operation.run()
            assert len(leases) == 1 and operation._journal is retained
        finally:
            fail[0] = False
            await operation.close()
        assert operation._journal is None and not operation.cleanup_pending
        assert len(leases) == 1

    asyncio.run(run())


def test_changed_candidate_set_prevents_automatic_choice(probe, monkeypatch):
    operation, _, behavior = probe
    behavior.absent = True
    original = operation._snapshot
    calls = []
    def snapshot():
        calls.append(1)
        if len(calls) == 2:
            service = original()[0].service
            operation._registry.reserve_mux(ManagedMuxReservationV1("late", service, "e" * 32))
        return original()
    monkeypatch.setattr(operation, "_snapshot", snapshot)
    async def run():
        try:
            result = await operation.run()
            assert not result.candidates_unchanged
            assert result.unique_present is None
            assert [row.observation.name for row in result.results] == ["main", "second"]
        finally:
            await operation.close()
    asyncio.run(run())


def test_exhausted_first_service_budget_never_admits_second(probe, monkeypatch):
    operation, _, _ = probe
    first = operation._snapshot()[0]
    service = ManagedServiceKeyV1("coding", "/another-probe-workspace")
    second = replace(first, reservation=ManagedMuxReservationV1("other", service, "e" * 32),
                     instance=replace(first.instance, service_id=service.service_id))
    monkeypatch.setattr(operation, "_snapshot", lambda: (first, second))
    clock = [monotonic()]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    admitted = []
    async def group(items, results):
        admitted.append(items[0].service)
        clock[0] = operation._deadline + 1
    monkeypatch.setattr(operation, "_probe_group", group)
    async def run():
        try:
            result = await operation.run()
            assert admitted == [first.service]
            assert not result.candidates_unchanged and result.unique_present is None
            assert all(row.status == "unknown" for row in result.results)
        finally:
            await operation.close()
    asyncio.run(run())


def test_close_timeout_retains_task_and_journal_until_original_cleanup_finishes(probe):
    operation, leases, behavior = probe
    async def run():
        behavior.close_gate = asyncio.Event()
        waiter = asyncio.create_task(operation.run())
        try:
            async with asyncio.timeout(5):
                while operation._connection is None or operation._journal is None:
                    await asyncio.sleep(0)
            operation._close_deadline = monotonic() + 0.02
            with pytest.raises(TimeoutError):
                await operation.close()
            closing = operation._close_task
            assert not closing.done() and operation._journal is not None
            assert operation.cleanup_pending and not leases[0].closed
            behavior.close_gate.set()
            with pytest.raises(module.ManagedStorageError, match="closed"):
                await waiter
            await asyncio.shield(closing)
            await operation.close()
            assert operation._close_task is closing
            assert operation._journal is None and not operation.cleanup_pending
        finally:
            behavior.close_gate.set()
            await asyncio.gather(waiter, return_exceptions=True)
            await operation.close()
    asyncio.run(run())


@pytest.mark.parametrize("late_delivery", [False, True])
def test_expired_result_never_authorizes_automatic_selection(probe, monkeypatch, late_delivery):
    operation, _, behavior = probe
    behavior.absent = True
    original = operation._run_once
    async def complete():
        result = await original()
        if late_delivery:
            operation._deadline = monotonic() - 1
        return result
    monkeypatch.setattr(operation, "_run_once", complete)
    async def run():
        try:
            first = await operation.run()
            if not late_delivery:
                assert first.unique_present is not None
                operation._deadline = monotonic() - 1
                first = await operation.run()
            assert not first.candidates_unchanged and first.unique_present is None
        finally:
            await operation.close()
    asyncio.run(run())
