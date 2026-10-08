"""Real current-instance close permission and historical-name settlement."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedStopEvidenceV1
from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.appserver.managed_mux_close import ManagedMuxClosePhaseV1
from loushang.appserver.protocol import AppServiceError
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    create_appservice_recovery_attempt,
)
from loushang.appservice.managed_mux_close import ManagedMuxCloseUseV1
from tests.apphost.test_managed_lifecycle import _identity
from tests.apphost.test_managed_mux_management import _ready
from tests.apphost.test_managed_mux_management import owners as _base_owners
from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver

owners = _base_owners
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed Mux closure")


def test_authenticated_close_survives_eof_and_query_reconciles_exact_name(owners, tmp_path, monkeypatch):
    from loushang.appserver.local import LocalAppClientConnectionV1, LocalAppServerV1
    from loushang.appserver.local_record import (
        LocalConnectionDirectoryV1,
        LocalRecordScopeV1,
    )
    from loushang.appserver.protocol import SessionScopeV1
    from loushang.appservice.client_scope import ScopedAppServiceV1
    from tests.appserver.test_local import _until
    from tests.appservice.test_managed_mux_close_runtime import member

    async def run():
        manager, service, lease, resolver, _, reservation, _, request = await opened(owners)
        await member(service, request)
        owner = ScopedAppServiceV1(service)
        entered, release = asyncio.Event(), asyncio.Event()
        original_close, original_cleanup = service.close_managed_mux, resolver.sessions[0].close
        calls = 0

        async def counted(self, value):
            nonlocal calls
            assert self is service
            calls += 1
            return await original_close(value)

        async def held():
            entered.set()
            await release.wait()
            await original_cleanup()

        monkeypatch.setattr(type(service), "close_managed_mux", counted)
        resolver.sessions[0].close = held
        directory = LocalConnectionDirectoryV1(tmp_path / "connection")
        server = LocalAppServerV1(directory, "managed", application_id="coding.default", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),),
            scope_factory=owner.open_client_scope, managed_mux_scope_factory=owner.open_client_scope,
            mux_closure=True, request_stop=lambda _: pytest.fail("EOF must not stop the service"))
        first, second = (LocalAppClientConnectionV1(directory, "managed") for _ in range(2))
        waiter = None
        try:
            await server.start()
            await first.start()
            assert directory.read("managed").mux_closure
            assert await first.managed_mux_close_client.read_managed_mux_close(request) is None
            waiter = asyncio.create_task(first.managed_mux_close_client.close_managed_mux(request))
            await asyncio.wait_for(entered.wait(), 3)
            await first.close()
            await asyncio.gather(waiter, return_exceptions=True)
            assert owner.pending_counts == (1, 0) and calls == 1
            await second.start()
            pending = await second.managed_mux_close_client.read_managed_mux_close(request)
            assert pending.phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
            manager.record_close(request, pending, deadline=monotonic() + 5)
            assert owners[0].resolve("dev") == reservation
            release.set()
            await _until(lambda: owner.pending_counts == (0, 0))
            closed = await second.managed_mux_close_client.read_managed_mux_close(request)
            assert closed.phase is ManagedMuxClosePhaseV1.CLOSED and calls == 1
            manager.record_close(request, closed, deadline=monotonic() + 5)
            reused = ManagedMuxReservationV1("dev", reservation.service, "e" * 32)
            owners[0].reserve_mux(reused)
            create = manager.issue_create(reused, deadline=monotonic() + 5)
            created = await second.managed_mux_client.create_managed_mux(create)
            manager.record_created(create, created, deadline=monotonic() + 5)
            assert await second.managed_mux_close_client.read_managed_mux_close(request) == closed
            manager.record_close(request, closed, deadline=monotonic() + 5)
            assert owners[0].resolve("dev") == reused
            assert (await second.client.list_muxes()).mux_spaces[0].mux_space_id == created.mux_space_id
            owner.fence()
            with pytest.raises(AppServiceError):
                await second.managed_mux_close_client.read_managed_mux_close(request)
        finally:
            release.set()
            if waiter is not None:
                await asyncio.gather(waiter, return_exceptions=True)
            await first.close()
            await second.close()
            await server.close()
            await service.close()
            directory.close()
    asyncio.run(asyncio.wait_for(run(), 15))


async def opened(owners):
    manager, instance, reservation = _ready(owners)
    create = manager.issue_create(reservation, deadline=monotonic() + 5)
    lease, resolver = _MemoryLease(), _Resolver([])
    binding = replace(manager.binding(), closing=manager.closing_binding())
    attempt = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
        "coding", resolver, lease, managed_mux=binding,
    ))
    service = await attempt.open()
    created = await service.create_managed_mux(create)
    manager.record_created(create, created, deadline=monotonic() + 5)
    request = manager.issue_close(reservation, operation_id="d" * 32, deadline=monotonic() + 5)
    return manager, service, lease, resolver, instance, reservation, create, request


async def other_target(owners, manager, service, *, issue=True):
    reservation = ManagedMuxReservationV1("other", owners[3], "e" * 32)
    owners[0].reserve_mux(reservation)
    create = manager.issue_create(reservation, deadline=monotonic() + 5)
    created = await service.create_managed_mux(create)
    manager.record_created(create, created, deadline=monotonic() + 5)
    request = manager.issue_close(reservation, operation_id="f" * 32, deadline=monotonic() + 5) if issue else None
    return reservation, create, request


def test_inspection_freezes_confirmed_target_and_optional_close_without_writes(owners, monkeypatch):
    from contextlib import contextmanager

    async def scenario():
        manager, service, _, _, _, reservation, create, request = await opened(owners)
        try:
            other, other_create, _ = await other_target(owners, manager, service, issue=False)
            original = type(owners[0]._database).transaction

            @contextmanager
            def readonly(database, **kwargs):
                assert not kwargs.get("write", False)
                with original(database, **kwargs) as connection:
                    yield connection

            monkeypatch.setattr(type(owners[0]._database), "transaction", readonly)
            view = manager.inspect_mux(reservation, deadline=monotonic() + 5)
            assert view.creation == manager.read_created(create, deadline=monotonic() + 5)
            assert view.close_request == request and view.close_result is None
            assert request.authority not in repr(view)
            assert manager.inspect_close_operation(request.operation_id, deadline=monotonic() + 5) == view
            fresh = await asyncio.to_thread(manager.inspect_mux, other, deadline=monotonic() + 5, wait_for_lock=True)
            assert fresh.creation == manager.read_created(other_create, deadline=monotonic() + 5)
            assert fresh.close_request is fresh.close_result is None
            with pytest.raises(ManagedStorageError, match="not_found"):
                manager.inspect_close_operation("9" * 32, deadline=monotonic() + 5)
        finally:
            monkeypatch.undo()
            await service.close()
    asyncio.run(scenario())


def test_inspection_rejects_unknown_creation_and_old_active_name_reference(owners):
    async def scenario():
        manager, service, _, _, _, reservation, _, request = await opened(owners)
        try:
            result = await service.close_managed_mux(request)
            manager.record_close(request, result, deadline=monotonic() + 5)
            reused = ManagedMuxReservationV1(reservation.name, reservation.service, "e" * 32)
            owners[0].reserve_mux(reused)
            for target in (reservation, reused):
                with pytest.raises(ManagedStorageError, match="conflict"):
                    manager.inspect_mux(target, deadline=monotonic() + 5)
            create = manager.issue_create(reused, deadline=monotonic() + 5)
            created = await service.create_managed_mux(create)
            manager.record_created(create, created, deadline=monotonic() + 5)
            assert manager.inspect_mux(reused, deadline=monotonic() + 5).creation == created
            with pytest.raises(ManagedStorageError, match="conflict"):
                manager.inspect_mux(reservation, deadline=monotonic() + 5)
            old = manager.inspect_close_operation(request.operation_id, deadline=monotonic() + 5)
            assert old.close_result == result and old.creation.mux_space_id != created.mux_space_id
        finally:
            await service.close()
    asyncio.run(scenario())


def test_historical_close_inspection_survives_recorded_stop_without_renewing(owners):
    async def scenario():
        manager, service, _, _, instance, reservation, _, request = await opened(owners)
        try:
            result = await service.close_managed_mux(request)
            manager.record_close(request, result, deadline=monotonic() + 5)
            owners[1].request_stop(instance)
            assert owners[0].resolve(reservation.name) is None
            view = manager.inspect_close_operation(request.operation_id, deadline=monotonic() + 5)
            assert view.close_request == request and view.close_result == result
        finally:
            await service.close()
    asyncio.run(scenario())


def test_historical_inspection_keeps_old_permit_after_real_journal_replacement(owners, monkeypatch):
    from contextlib import contextmanager

    async def scenario():
        manager, service, _, _, instance, reservation, _, request = await opened(owners)
        original_view = manager.inspect_mux(reservation, deadline=monotonic() + 5)
        await service.close()
        registry, journal, namespace, key = owners
        journal.request_stop(instance)
        journal.record_stop_evidence(ManagedStopEvidenceV1(instance, True, True, True))
        current = journal.prepare("f" * 32, expected=journal.read()).handoff.instance
        journal.register_native(current, "f" * 32, _identity())
        journal.commit(current, "f" * 32, native_identity=_identity())
        replacement = ManagedMuxManagerV1(registry, journal, namespace, key, current, application_id="coding.default")
        original = type(registry._database).transaction

        @contextmanager
        def readonly(database, **kwargs):
            assert not kwargs.get("write", False)
            with original(database, **kwargs) as connection:
                yield connection

        monkeypatch.setattr(type(registry._database), "transaction", readonly)
        for selected in (manager, replacement):
            view = selected.inspect_close_operation(request.operation_id, deadline=monotonic() + 5)
            assert view == original_view
            assert view.close_request.instance_id == instance.instance_id != current.instance_id
            assert view.close_request.authority == request.authority
        with pytest.raises(ManagedStorageError, match="conflict"):
            manager.inspect_mux(reservation, deadline=monotonic() + 5)
        assert replacement.inspect_mux(reservation, deadline=monotonic() + 5) == original_view

    asyncio.run(scenario())


def test_result_verification_is_readonly_and_checks_origin_and_monotonicity(owners, monkeypatch):
    from contextlib import contextmanager

    async def scenario():
        manager, service, _, _, _, _, _, request = await opened(owners)
        try:
            closed = await service.close_managed_mux(request)
            manager.record_close(request, closed, deadline=monotonic() + 5)
            original = type(owners[0]._database).transaction

            @contextmanager
            def readonly(database, **kwargs):
                assert not kwargs.get("write", False)
                with original(database, **kwargs) as connection:
                    yield connection

            monkeypatch.setattr(type(owners[0]._database), "transaction", readonly)
            assert manager.verify_close_result(request, closed, deadline=monotonic() + 5) == closed
            for invalid in (replace(closed, instance_id="9" * 32),
                            replace(closed, phase=ManagedMuxClosePhaseV1.CLEANUP_PENDING)):
                with pytest.raises(ManagedStorageError, match="conflict"):
                    manager.verify_close_result(request, invalid, deadline=monotonic() + 5)
        finally:
            monkeypatch.undo()
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["create", "close"])
@pytest.mark.parametrize("boundary", ["fence", "database"])
def test_live_admission_waits_for_read_busy_without_repeating_business_effects(owners, monkeypatch, kind, boundary):
    from contextlib import contextmanager

    async def scenario():
        manager, service, lease, _, _, reservation, _, close = await opened(owners)
        if kind == "create":
            new = ManagedMuxReservationV1("other", reservation.service, "e" * 32)
            owners[0].reserve_mux(new)
            request = manager.issue_create(new, deadline=monotonic() + 5)
            operation = service.create_managed_mux
        else:
            request, operation = close, service.close_managed_mux
        before = len(lease.commits)
        target, method = (owners[1]._fence, "lock") if boundary == "fence" else (owners[0]._database, "transaction")
        original = getattr(target, method)
        attempts = 0

        @contextmanager
        def busy_twice(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                assert len(lease.commits) == before
                raise ManagedStorageError("busy")
            with original(*args, **kwargs) as value:
                yield value

        try:
            with monkeypatch.context() as patch:
                patch.setattr(target, method, busy_twice)
                result = await operation(request)  # One invocation, never replayed by this test.
                assert attempts == (3 if kind == "create" else 4)
                assert len(lease.commits) == before + (1 if kind == "create" else 2)
                assert result.operation_id == request.operation_id
                assert service._managed_admission is None
        finally:
            await service.close()
    asyncio.run(scenario())


def test_real_close_releases_only_original_name_and_keeps_historical_result(owners):
    async def scenario():
        manager, service, lease, _, _, reservation, create, request = await opened(owners)
        registry = owners[0]
        try:
            assert manager.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5) == request
            assert request.authority != create.authority and request.authority not in repr(request)
            before = len(lease.commits)
            assert manager.read_close(request, deadline=monotonic() + 5) is None
            assert len(lease.commits) == before
            result = await service.close_managed_mux(request)
            assert registry.resolve(reservation.name) == reservation
            assert manager.record_close(request, result, deadline=monotonic() + 5) == result
            assert registry.resolve(reservation.name) is None
            new = ManagedMuxReservationV1(reservation.name, reservation.service, "e" * 32)
            registry.reserve_mux(new)
            assert manager.record_close(request, result, deadline=monotonic() + 5) == result
            assert manager.read_close(request, deadline=monotonic() + 5) == result
            assert registry.resolve(reservation.name) == new
            with pytest.raises(ManagedStorageError):
                manager.issue_create(reservation, deadline=monotonic() + 5)
            with pytest.raises(ManagedStorageError):
                manager.record_close(request, replace(result, phase=ManagedMuxClosePhaseV1.CLEANUP_PENDING), deadline=monotonic() + 5)
        finally:
            await service.close()

    asyncio.run(scenario())


def test_creation_token_and_cross_purpose_operations_are_rejected(owners):
    async def scenario():
        manager, service, lease, _, _, reservation, create, request = await opened(owners)
        try:
            other, _, _ = await other_target(owners, manager, service, issue=False)
            before = len(lease.commits)
            with pytest.raises((ManagedStorageError, AppServiceError)):
                await service.close_managed_mux(replace(request, authority=create.authority))
            assert len(lease.commits) == before
            with pytest.raises(ManagedStorageError):
                manager.issue_close(other, operation_id=create.operation_id, deadline=monotonic() + 5)
            with pytest.raises(ManagedStorageError):
                manager.issue_close(reservation, operation_id="f" * 32, deadline=monotonic() + 5)
            with pytest.raises(ManagedStorageError):
                owners[0].reserve_mux(ManagedMuxReservationV1("fresh", reservation.service, request.operation_id))
            with owners[0]._database.transaction() as connection:
                assert connection.execute("SELECT count(*) FROM mux_close_authorities").fetchone() == (1,)
            assert len(lease.commits) == before
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["UPDATE mux_close_authorities", "DELETE FROM muxes"])
def test_closed_record_and_name_delete_rollback_together(owners, monkeypatch, stage):
    async def scenario():
        manager, service, _, _, _, reservation, _, request = await opened(owners)
        try:
            result = await service.close_managed_mux(request)
            original_connect = sqlite3.connect

            class Failure(sqlite3.Connection):
                def execute(self, sql, parameters=()):
                    result = super().execute(sql, parameters)
                    if sql.startswith(stage):
                        raise sqlite3.OperationalError("delete receipt failed")
                    return result

            def connect(*args, **kwargs):
                return original_connect(*args, factory=Failure, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(sqlite3, "connect", connect)
                with pytest.raises(ManagedStorageError):
                    manager.record_close(request, result, deadline=monotonic() + 5)
            assert owners[0].resolve(reservation.name) == reservation
            assert manager.read_close(request, deadline=monotonic() + 5) is None
            manager.record_close(request, result, deadline=monotonic() + 5)
            assert owners[0].resolve(reservation.name) is None
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("use", [ManagedMuxCloseUseV1.ADMIT, ManagedMuxCloseUseV1.SETTLE])
def test_old_pending_cannot_use_live_permission_after_instance_replacement(owners, use):
    async def scenario():
        manager, service, lease, _, instance, reservation, create, request = await opened(owners)
        creation = manager.read_created(create, deadline=monotonic() + 5)
        result = await service.close_managed_mux(request)
        pending = lease.commits[-2].managed_closures[0]
        assert pending.phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
        await service.close()
        registry, journal, namespace, key = owners
        journal.request_stop(instance)
        journal.record_stop_evidence(ManagedStopEvidenceV1(instance, True, True, True))
        new = journal.prepare("f" * 32, expected=journal.read())
        current = new.handoff.instance
        journal.register_native(current, "f" * 32, _identity())
        journal.commit(current, "f" * 32, native_identity=_identity())
        replacement = ManagedMuxManagerV1(registry, journal, namespace, key, current, application_id="coding.default")
        renewed = replacement.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5)
        assert renewed.authority != request.authority
        admission = replacement.prepare_close(renewed, use)
        try:
            await admission.acquire()
            with pytest.raises(ManagedStorageError):
                admission.check_closure(creation, None)
            with pytest.raises(ManagedStorageError):
                admission.check_closure(creation, pending)
        finally:
            await admission.close()
        observer = replacement.prepare_close(renewed, ManagedMuxCloseUseV1.OBSERVE)
        try:
            await observer.acquire()
            observer.check_closure(creation, pending)
            observer.check_closure(creation, result)
        finally:
            await observer.close()
        with pytest.raises(ManagedStorageError):
            manager.record_close(request, result, deadline=monotonic() + 5)
        assert replacement.record_close(renewed, result, deadline=monotonic() + 5) == result
        assert result.instance_id == instance.instance_id != renewed.instance_id
        assert registry.resolve(reservation.name) is None

    asyncio.run(scenario())


def test_local_pending_settles_after_stop_while_registry_result_is_still_null(owners):
    from tests.appservice.test_managed_mux_close_runtime import member

    async def scenario():
        manager, service, _, resolver, instance, reservation, _, request = await opened(owners)
        _, _, other_request = await other_target(owners, manager, service)
        await member(service, request)
        entered, release = asyncio.Event(), asyncio.Event()
        original = resolver.sessions[0].close

        async def held():
            entered.set()
            await release.wait()
            await original()

        resolver.sessions[0].close = held
        closing = asyncio.create_task(service.close_managed_mux(request))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert manager.read_close(request, deadline=monotonic() + 5) is None
            # A separate process must acquire the actual fence while cleanup
            # is held; same-thread RLock reentry would not prove lock release.
            script = """
import os, sys
from pathlib import Path
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
root, fence, platform = sys.argv[1:]
namespace = ManagedNamespaceV1(platform, os.geteuid(), 'a'*32)
key = ManagedServiceKeyV1('coding', '/workspace')
registry = ManagedRegistryV1(Path(root), namespace)
journal = ManagedServiceJournalV1(registry, namespace, key, Path(fence))
try:
    journal.request_stop(journal.read().handoff.instance)
finally:
    journal.close()
    registry.close()
"""
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
            process = await asyncio.to_thread(subprocess.run,
                [sys.executable, "-c", script, str(owners[0]._database._directory._root),
                 str(owners[1]._fence._root), owners[2].platform_home],
                env=env, capture_output=True, timeout=10,
            )
            assert process.returncode == 0, process.stderr
            state = owners[1].read()
            assert state.handoff.instance == instance and state.handoff.stop_requested
            with pytest.raises((ManagedStorageError, AppServiceError)):
                await service.close_managed_mux(other_request)
            assert await service.read_managed_mux_close(other_request) is None
            release.set()
            result = await closing
            assert result.phase is ManagedMuxClosePhaseV1.CLOSED
            manager.record_close(request, result, deadline=monotonic() + 5)
            assert owners[0].resolve(reservation.name) is None
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)
            await service.close()

    asyncio.run(scenario())


def test_observation_never_mutates_pending_or_closed_records(owners):
    async def scenario():
        manager, service, lease, _, _, reservation, create, request = await opened(owners)
        assert manager.binding().closing is None
        created = manager.read_created(create, deadline=monotonic() + 5)
        unset = manager.prepare_close(request, ManagedMuxCloseUseV1.SETTLE)
        try:
            await unset.acquire()
            with pytest.raises(ManagedStorageError):
                unset.check_closure(created, None)
        finally:
            await unset.close()
        result = await service.close_managed_mux(request)
        pending = lease.commits[-2].managed_closures[0]
        path = owners[0]._database._directory._root / "registry.sqlite3"
        try:
            for state in (None, pending, result):
                if state is not None:
                    manager.record_close(request, state, deadline=monotonic() + 5)
                before = (path.read_bytes(), path.stat().st_mtime_ns)
                assert manager.read_close(request, deadline=monotonic() + 5) == state
                assert await service.read_managed_mux_close(request) == result
                assert (path.read_bytes(), path.stat().st_mtime_ns) == before
                assert (owners[0].resolve(reservation.name) is not None) is (state != result)
        finally:
            await service.close()

    asyncio.run(scenario())


def test_commit_success_with_lost_receipt_can_read_original_closed_fact(owners, monkeypatch):
    async def scenario():
        manager, service, _, _, _, reservation, _, request = await opened(owners)
        try:
            result = await service.close_managed_mux(request)
            original_connect = sqlite3.connect

            class Failure(sqlite3.Connection):
                def commit(self):
                    super().commit()
                    raise sqlite3.OperationalError("commit receipt lost")

            def connect(*args, **kwargs):
                return original_connect(*args, factory=Failure, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(sqlite3, "connect", connect)
                with pytest.raises(ManagedStorageError):
                    manager.record_close(request, result, deadline=monotonic() + 5)
            assert manager.read_close(request, deadline=monotonic() + 5) == result
            assert owners[0].resolve(reservation.name) is None
            new = ManagedMuxReservationV1(reservation.name, reservation.service, "e" * 32)
            owners[0].reserve_mux(new)
            assert manager.record_close(request, result, deadline=monotonic() + 5) == result
            assert owners[0].resolve(reservation.name) == new
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["UPDATE mux_close_authorities", "DELETE FROM muxes"])
def test_real_exit_cannot_commit_only_half_of_closed_name_settlement(owners, stage):
    from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
    from loushang.apphost.managed.registry import ManagedRegistryV1

    async def scenario():
        manager, service, _, _, instance, reservation, _, request = await opened(owners)
        result = await service.close_managed_mux(request)
        await service.close()
        registry, journal, namespace, key = owners
        root, fence = registry._database._directory._root, journal._fence._root
        script = """
import json, os, sqlite3, sys
from pathlib import Path
from time import monotonic
from loushang.apphost.managed.registry import ManagedRegistryV1, ManagedMuxReservationV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.appserver.managed_mux_close import ManagedMuxCloseStateV1, ManagedMuxClosePhaseV1
root, fence, platform, stage, raw = sys.argv[1:]
namespace = ManagedNamespaceV1(platform, os.geteuid(), 'a'*32)
key = ManagedServiceKeyV1('coding', '/workspace')
registry = ManagedRegistryV1(Path(root), namespace)
journal = ManagedServiceJournalV1(registry, namespace, key, Path(fence))
manager = ManagedMuxManagerV1(registry, journal, namespace, key, journal.read().handoff.instance, application_id='coding.default')
request = manager.issue_close(ManagedMuxReservationV1('dev', key, 'b'*32), operation_id='d'*32, deadline=monotonic()+5)
value = json.loads(raw)
value['phase'] = ManagedMuxClosePhaseV1(value['phase'])
result = ManagedMuxCloseStateV1(**value)
original = sqlite3.connect
class Crash(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if sql.startswith(stage):
            os._exit(23)
        return result
def connect(*args, **kwargs):
    return original(*args, factory=Crash, **kwargs)
sqlite3.connect = connect
manager.record_close(request, result, deadline=monotonic()+5)
os._exit(24)
"""
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
        process = await asyncio.to_thread(subprocess.run,
            [sys.executable, "-c", script, str(root), str(fence), namespace.platform_home, stage, json.dumps(asdict(result))],
            env=env, capture_output=True, timeout=10,
        )
        assert process.returncode == 23, process.stderr
        journal.close()
        registry.close()
        restored = ManagedRegistryV1(root, namespace, create=True)
        recovered_journal = ManagedServiceJournalV1(restored, namespace, key, fence)
        try:
            recovered = ManagedMuxManagerV1(restored, recovered_journal, namespace, key, instance, application_id="coding.default")
            assert restored.resolve(reservation.name) == reservation
            assert recovered.read_close(request, deadline=monotonic() + 5) is None
            recovered.record_close(request, result, deadline=monotonic() + 5)
            assert restored.resolve(reservation.name) is None
        finally:
            recovered_journal.close()
            restored.close()

    asyncio.run(scenario())
