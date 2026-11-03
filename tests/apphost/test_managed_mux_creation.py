from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.appserver.client import AppConnectionClosedError
from loushang.appservice.client_scope import ScopedAppServiceV1
from tests.apphost.test_managed_mux_management import _ready, _service
from tests.apphost.test_managed_mux_management import owners as owners
from tests.appservice.test_continuity_runtime import _MemoryLease


def operation(owners, monkeypatch, service, *, create=None):
    registry, journal, namespace, key = owners
    state = journal.read()
    coordinators = []

    class Lease:
        instance = state.handoff.instance
        managed_mux_client = service
        application_id = "coding.default"

        @property
        def client(self):
            return service

    class Coordinator:
        def __init__(self, *args, **kwargs):
            self.starts = self.closes = 0
            self.fenced = self.fail_close = False
            self.lease = Lease()
            coordinators.append(self)

        async def ensure_started(self, *, deadline):
            self.starts += 1
            if create is not None:
                await create()
            return self.lease

        def fence(self):
            self.fenced = True

        async def close(self):
            self.closes += 1
            if self.fail_close:
                raise ManagedStorageError("unavailable")

    monkeypatch.setattr("loushang.apphost.managed.mux_creation.ManagedServiceCoordinatorV1", Coordinator)
    owner = ManagedMuxCreateOperationV1(
        registry, journal, namespace, ManagedMuxReservationV1("dev", key, "b" * 32),
        runtime_root=namespace.platform_home + "-runtime", endpoint="workspace", application_id="coding.default",
        request_factory=lambda *_: pytest.fail("fixture must not launch process"),
    )
    return owner, coordinators


def test_creation_operation_joins_once_and_closes_only_its_connection_owner(owners, monkeypatch):
    async def scenario():
        manager, _, _ = _ready(owners)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        owner, coordinators = operation(owners, monkeypatch, service)
        deadline = monotonic() + 5
        try:
            one, two = await asyncio.gather(owner.run(deadline=deadline), owner.run(deadline=deadline))
            assert one == two == owner.result
            assert len(lease.commits) == 1 and coordinators[0].starts == 1
            assert owner.connection is coordinators[0].lease
            with pytest.raises(ManagedStorageError, match="conflict"):
                await owner.run(deadline=deadline + 1)
            assert owners[0].resolve("dev").operation_id == "b" * 32
        finally:
            await owner.close()
            await service.close()
        assert not owner.cleanup_pending
        assert coordinators[0].closes == 1
        assert owners[1].read().handoff.stop_requested is False
        assert owners[0].resolve("dev") is not None

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_conflicting_name_intent_never_starts_service(owners, monkeypatch):
    async def scenario():
        manager, _, _ = _ready(owners)
        service = await _service(manager, _MemoryLease())
        owner, coordinators = operation(owners, monkeypatch, service)
        owner._reservation = replace(owner._reservation, operation_id="e" * 32)
        try:
            with pytest.raises(ManagedStorageError, match="conflict"):
                await owner.run(deadline=monotonic() + 5)
            assert coordinators[0].starts == 0
            assert owner.result is None
        finally:
            await owner.close()
            await service.close()

    asyncio.run(scenario())


def test_cancelled_waiter_and_close_join_accepted_creation_before_releasing_connection(owners, monkeypatch):
    async def scenario():
        manager, _, reservation = _ready(owners)
        entered, release = asyncio.Event(), asyncio.Event()

        class Lease(_MemoryLease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = Lease()
        service = await _service(manager, lease)
        owner, coordinators = operation(owners, monkeypatch, service)
        deadline = monotonic() + 5
        waiter = asyncio.create_task(owner.run(deadline=deadline))
        closing = None
        try:
            await entered.wait()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0)
            assert coordinators[0].fenced and coordinators[0].closes == 0
            assert not closing.done()
            release.set()
            await closing
            assert owner.created == owner.result == lease.record.managed_creations[0]
            permit = manager.issue_create(reservation, deadline=deadline)
            assert manager.read_created(permit, deadline=deadline) == owner.result
            assert coordinators[0].closes == 1
            with pytest.raises(ManagedStorageError, match="closed"):
                _ = owner.connection
        finally:
            release.set()
            await asyncio.gather(waiter, *(() if closing is None else (closing,)), return_exceptions=True)
            await owner.close()
            await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("failure", ("rpc", "reconciliation", "reconciliation_after_commit"))
def test_unknown_reply_or_result_registration_never_replays_rpc_or_releases_name(owners, monkeypatch, failure):
    async def scenario():
        manager, _, _ = _ready(owners)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        calls = []

        class Capability:
            async def create_managed_mux(self, request):
                calls.append(request)
                result = await service.create_managed_mux(request)
                if failure == "rpc":
                    raise AppConnectionClosedError()
                return result

        if failure.startswith("reconciliation"):
            original = type(manager).record_created
            def failed(*args, **kwargs):
                if failure == "reconciliation_after_commit":
                    original(*args, **kwargs)
                raise ManagedStorageError("unavailable")
            monkeypatch.setattr(type(manager), "record_created", failed)
        owner, coordinators = operation(owners, monkeypatch, Capability())
        deadline = monotonic() + 5
        try:
            for _ in range(2):
                with pytest.raises((ManagedStorageError, AppConnectionClosedError)):
                    await owner.run(deadline=deadline)
            assert len(calls) == len(lease.commits) == 1
            assert coordinators[0].starts == 1
            assert owner.result is None
            assert owner.created == (None if failure == "rpc" else lease.record.managed_creations[0])
            assert owners[0].resolve("dev") is not None
            assert not owners[1].read().handoff.stop_requested
            if failure == "reconciliation_after_commit":
                assert manager.read_created(calls[0], deadline=deadline) == owner.created
        finally:
            await owner.close()
            await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_rpc_deadline_does_not_cancel_scoped_accepted_work_or_renew_budget(owners, monkeypatch):
    async def scenario():
        manager, _, _ = _ready(owners)
        entered, release = asyncio.Event(), asyncio.Event()

        class Lease(_MemoryLease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = Lease()
        service = await _service(manager, lease)
        scopes = ScopedAppServiceV1(service)
        scope = scopes.open_client_scope()
        owner, _ = operation(owners, monkeypatch, scope)
        deadline = monotonic() + 0.3
        waiter = asyncio.create_task(owner.run(deadline=deadline))
        try:
            await entered.wait()
            with pytest.raises(ManagedStorageError, match="unavailable"):
                await waiter
            assert scopes.pending_counts == (1, 0)
            assert not lease.commits
            assert owner.created is owner.result is None
            with pytest.raises(ManagedStorageError):
                await owner.run(deadline=deadline + 5)
            await owner.close()
            assert owners[0].resolve("dev") is not None
            release.set()
        finally:
            release.set()
            await asyncio.gather(waiter, return_exceptions=True)
            await owner.close()
            await scope.close()
            await service.close()
        assert len(lease.commits) == 1

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_creation_cleanup_failure_retains_original_coordinator_for_retry(owners, monkeypatch):
    async def scenario():
        manager, _, _ = _ready(owners)
        service = await _service(manager, _MemoryLease())
        owner, coordinators = operation(owners, monkeypatch, service)
        await owner.run(deadline=monotonic() + 5)
        coordinators[0].fail_close = True
        try:
            with pytest.raises(ManagedStorageError):
                await owner.close()
            assert owner.cleanup_pending and len(coordinators) == 1
            assert owners[0].resolve("dev") is not None
            coordinators[0].fail_close = False
            await owner.close()
            assert not owner.cleanup_pending and coordinators[0].closes == 2
        finally:
            coordinators[0].fail_close = False
            await owner.close()
            await service.close()

    asyncio.run(scenario())


def test_result_registration_lost_busy_reply_retries_only_same_control_fact(owners, monkeypatch):
    async def scenario():
        manager, _, _ = _ready(owners)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        original = type(manager).record_created
        registrations, requests = [], []

        def lost(self, request, result, **kwargs):
            registrations.append((request, result))
            confirmed = original(self, request, result, **kwargs)
            if len(registrations) == 1:
                raise ManagedStorageError("busy")
            return confirmed

        class Capability:
            async def create_managed_mux(self, request):
                requests.append(request)
                return await service.create_managed_mux(request)

        monkeypatch.setattr(type(manager), "record_created", lost)
        owner, _ = operation(owners, monkeypatch, Capability())
        try:
            result = await owner.run(deadline=monotonic() + 5)
            assert owner.created == owner.result == result
            assert len(requests) == len(lease.commits) == 1
            assert len(registrations) == 2 and registrations[0] == registrations[1]
        finally:
            await owner.close()
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("deadline", (None, True, float("nan"), float("inf"), 10**30))
def test_invalid_creation_deadline_has_no_task_or_storage_effects(owners, monkeypatch, deadline):
    async def scenario():
        manager, _, _ = _ready(owners)
        service = await _service(manager, _MemoryLease())
        owner, coordinators = operation(owners, monkeypatch, service)
        try:
            with pytest.raises(ManagedStorageError):
                await owner.run(deadline=deadline)
            assert owner._task is None and owner._deadline is None
            assert coordinators[0].starts == 0
        finally:
            await owner.close()
            await service.close()

    asyncio.run(scenario())


def test_wrong_authenticated_application_identity_never_issues_permit_or_rpc(owners, monkeypatch):
    async def scenario():
        manager, _, _ = _ready(owners)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        owner, _ = operation(owners, monkeypatch, service)
        owner._application_id = "coding.other"
        try:
            with pytest.raises(ManagedStorageError, match="conflict"):
                await owner.run(deadline=monotonic() + 5)
            assert not lease.commits
            with owners[0]._database.transaction() as connection:
                assert connection.execute("SELECT count(*) FROM mux_authorities").fetchone() == (0,)
            assert owner.created is owner.result is None
        finally:
            await owner.close()
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ("run", "close"))
def test_task_publication_failure_has_no_unowned_creation_or_cleanup(owners, monkeypatch, phase):
    async def scenario():
        manager, _, _ = _ready(owners)
        service = await _service(manager, _MemoryLease())
        owner, coordinators = operation(owners, monkeypatch, service)
        loop = asyncio.get_running_loop()
        factory = loop.get_task_factory()
        abandoned = []

        def spawn_then_fail(loop, coroutine, **kwargs):
            task = asyncio.Task(coroutine, loop=loop, **kwargs)
            abandoned.append(task)
            raise RuntimeError("task publication failed")

        try:
            loop.set_task_factory(spawn_then_fail)
            with pytest.raises(RuntimeError, match="publication failed"):
                if phase == "run":
                    await owner.run(deadline=monotonic() + 5)
                else:
                    await owner.close()
        finally:
            loop.set_task_factory(factory)
            await asyncio.gather(*abandoned, return_exceptions=True)
        try:
            assert coordinators[0].starts == coordinators[0].closes == 0
            assert owner.created is owner.result is None
            assert owner.cleanup_pending
        finally:
            await owner.close()
            await service.close()
        assert coordinators[0].closes == 1 and not owner.cleanup_pending

    asyncio.run(scenario())
