"""Startup recovery against the original registry and real AppService attempt."""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedStopEvidenceV1
from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.appserver.managed_mux_close import ManagedMuxClosePhaseV1
from loushang.appserver.protocol import (
    AppServiceError,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    create_appservice_recovery_attempt,
)
from loushang.appservice.continuity import MANAGED_CONTINUITY_VERSION
from loushang.appservice.managed_mux_close import ManagedMuxCloseUseV1
from tests.apphost.test_managed_lifecycle import _identity
from tests.apphost.test_managed_mux_closure import opened, other_target
from tests.apphost.test_managed_mux_management import _ready
from tests.apphost.test_managed_mux_management import owners as _base_owners
from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver

owners = _base_owners
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux startup recovery")


async def member(service, request, title="one", *, session_id=None):
    return await service.open_member(MuxMemberOpenV1(
        MuxSelectorV1(mux_space_id=request.mux_space_id),
        SessionOpenSpecV1(
            "coding", "continuity-1", SessionScopeV1.CWD, "a" * 64,
            title, session_id=session_id,
        ),
    ))


def successor(owners, *, native=True, attempt="f" * 32):
    registry, journal, namespace, key = owners
    previous = journal.read()
    if previous is not None:
        journal.request_stop(previous.handoff.instance)
        journal.record_stop_evidence(ManagedStopEvidenceV1(previous.handoff.instance, True, True, True))
    state = journal.prepare(attempt, expected=journal.read())
    if native:
        journal.register_native(state.handoff.instance, attempt, _identity())
    return ManagedMuxManagerV1(registry, journal, namespace, key, state.handoff.instance,
                               application_id="coding.default", startup_attempt_id=attempt,
                               startup_native_identity=_identity())


def recovery(manager, lease, resolver=None):
    return create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
        "coding", resolver or _Resolver([]), lease, managed_mux=manager.binding(),
    ))


def test_initial_none_is_admitted_without_writes(owners):
    async def scenario():
        manager = successor(owners)
        lease = _MemoryLease()
        service = await recovery(manager, lease).open()
        try:
            assert manager.binding().closing.recovery is not None
            assert not lease.commits
        finally:
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_real_creation_restores_before_commit_without_rewriting(owners, version):
    async def scenario():
        _, service, lease, _, _, _, _, _ = await opened(owners)
        await service.close()
        if version == "v2":
            lease.record = replace(lease.record, contract_version=MANAGED_CONTINUITY_VERSION)
        original, commits = lease.record, len(lease.commits)
        manager = successor(owners)
        restored = await recovery(manager, lease).open()
        try:
            assert len((await restored.list_muxes()).mux_spaces) == 1
            assert lease.record == original and len(lease.commits) == commits
            assert owners[1].read().handoff.phase.value == "provisional"
        finally:
            await restored.close()
    asyncio.run(scenario())


def test_explicit_close_continues_unaccepted_intent_after_proven_recovery(owners):
    async def scenario():
        _, old_service, lease, _, _, reservation, _, request = await opened(owners)
        await member(old_service, request)
        await old_service.close()
        manager = successor(owners)
        events = []
        resolver = _Resolver(events)
        service = await recovery(manager, lease, resolver).open()
        owners[1].commit(manager._instance, "f" * 32, native_identity=_identity())
        try:
            renewed = manager.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5)
            assert renewed.instance_id != request.instance_id
            assert await service.read_managed_mux_close(renewed) is None
            before = len(lease.commits)
            result = await service.close_managed_mux(renewed)
            assert result.phase is ManagedMuxClosePhaseV1.CLOSED
            assert result.instance_id == request.instance_id != renewed.instance_id
            assert len(lease.commits) == before + 2
            assert [item.managed_closures[0].instance_id for item in lease.commits[before:]] == [request.instance_id] * 2
            assert events.count("close:" + resolver.sessions[0].identity.session_id) == 1
            assert await service.close_managed_mux(renewed) == result
            assert len(lease.commits) == before + 2
            assert manager.record_close(renewed, result, deadline=monotonic() + 5) == result
            assert owners[0].resolve(reservation.name) is None
        finally:
            await service.close()
    asyncio.run(scenario())


def test_cross_origin_pending_requires_original_live_admission_and_allows_stop(owners):
    from loushang.appserver.managed_mux_close import ManagedMuxCloseStateV1

    async def scenario():
        _, old_service, lease, _, _, reservation, _, request = await opened(owners)
        await member(old_service, request)
        await old_service.close()
        manager = successor(owners)
        resolver = _Resolver([])
        service = await recovery(manager, lease, resolver).open()
        owners[1].commit(manager._instance, "f" * 32, native_identity=_identity())
        renewed = manager.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5)
        creation = manager.inspect_mux(reservation, deadline=monotonic() + 5).creation
        expected = ManagedMuxCloseStateV1(request.operation_id, request.instance_id,
            creation.operation_id, creation.name, creation.mux_space_id, ManagedMuxClosePhaseV1.CLEANUP_PENDING)
        admission = manager.prepare_close(renewed, ManagedMuxCloseUseV1.SETTLE)
        try:
            await admission.acquire()
            with pytest.raises(ManagedStorageError):
                admission.check_closure(creation, expected)
        finally:
            await admission.close()
        entered, release = asyncio.Event(), asyncio.Event()
        original = resolver.sessions[0].close

        async def held():
            entered.set()
            await release.wait()
            await original()

        resolver.sessions[0].close = held
        task = asyncio.create_task(service.close_managed_mux(renewed))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert await service.read_managed_mux_close(renewed) == expected
            other_manager = ManagedMuxManagerV1(*owners[:2], owners[2], owners[3], manager._instance,
                                                application_id="coding.default")
            for use in (ManagedMuxCloseUseV1.ADMIT, ManagedMuxCloseUseV1.SETTLE):
                other = other_manager.prepare_close(renewed, use)
                try:
                    await other.acquire()
                    with pytest.raises(ManagedStorageError):
                        other.check_closure(creation, expected)
                finally:
                    await other.close()
            owners[1].request_stop(manager._instance)
            release.set()
            result = await task
            assert result.phase is ManagedMuxClosePhaseV1.CLOSED
            assert manager.record_close(renewed, result, deadline=monotonic() + 5) == result
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["not_admitted", "missing_record", "missing_creation", "missing_mux",
                                    "old_pending", "old_closed", "recorded_pending", "capacity"])
def test_cross_origin_continuation_rejects_missing_proof_before_pending_commit(owners, monkeypatch, fault):
    from loushang.apphost.managed import mux_management
    from loushang.appserver.managed_mux_close import ManagedMuxCloseStateV1

    async def scenario():
        _, old_service, lease, _, _, reservation, _, request = await opened(owners)
        await old_service.close()
        manager = successor(owners)
        service = await recovery(manager, lease).open()
        owners[1].commit(manager._instance, "f" * 32, native_identity=_identity())
        renewed = manager.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5)
        record = manager._recovery_record
        pending = ManagedMuxCloseStateV1(request.operation_id, request.instance_id,
            request.creation_operation_id, request.name, request.mux_space_id, ManagedMuxClosePhaseV1.CLEANUP_PENDING)
        if fault == "not_admitted":
            manager._recovery_admitted = False
        elif fault == "missing_record":
            manager._recovery_record = None
        elif fault == "missing_creation":
            manager._recovery_record = replace(record, managed_creations=(), mux_spaces=())
        elif fault == "missing_mux":
            manager._recovery_record = replace(record, mux_spaces=())
        elif fault == "old_pending":
            manager._recovery_record = replace(record, managed_closures=(pending,))
        elif fault == "old_closed":
            manager._recovery_record = replace(record, mux_spaces=(),
                managed_closures=(replace(pending, phase=ManagedMuxClosePhaseV1.CLOSED),))
        elif fault == "recorded_pending":
            manager.record_close(renewed, pending, deadline=monotonic() + 5)
        else:
            monkeypatch.setattr(mux_management, "MAX_MUXES", 0)
        before = len(lease.commits)
        try:
            with pytest.raises(AppServiceError):
                await service.close_managed_mux(renewed)
            assert len(lease.commits) == before
            assert not manager._continued_closures
            assert len((await service.list_muxes()).mux_spaces) == 1
            assert owners[0].resolve(reservation.name) == reservation
        finally:
            await service.close()
    asyncio.run(scenario())


def test_cross_origin_pending_commit_ack_loss_keeps_unknown_even_after_admission(owners):
    class LostReceipt(_MemoryLease):
        async def commit(self, *, expected_revision, record):
            await super().commit(expected_revision=expected_revision, record=record)
            raise RuntimeError("test pending receipt lost")

    async def scenario():
        _, old_service, old_lease, _, _, reservation, _, request = await opened(owners)
        await member(old_service, request)
        await old_service.close()
        manager = successor(owners)
        events = []
        lease = LostReceipt(old_lease.record)
        service = await recovery(manager, lease, _Resolver(events)).open()
        owners[1].commit(manager._instance, "f" * 32, native_identity=_identity())
        renewed = manager.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5)
        with pytest.raises(AppServiceError):
            await service.close_managed_mux(renewed)
        assert manager._continued_closures and service._managed_uncertain
        assert lease.record.managed_closures[0].instance_id == request.instance_id
        assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
        assert not any(event.startswith("close:") for event in events)
        for call in (lambda: service.read_managed_mux_close(renewed),
                     lambda: service.close_managed_mux(renewed), service.close):
            with pytest.raises(AppServiceError):
                await call()
        assert owners[0].resolve(reservation.name) == reservation
        # Settle fake ports only; do not clear unknown state or manufacture a
        # successful service close to make teardown look successful.
        await service._close_sessions(tuple(service._sessions.values()))
    asyncio.run(scenario())


def test_cross_origin_cancelled_admission_release_preserves_original_cleanup(owners, monkeypatch):
    from loushang.apphost.managed.mux_management import ManagedMuxCloseAdmission

    async def scenario():
        _, old_service, lease, _, _, reservation, _, request = await opened(owners)
        await member(old_service, request)
        await old_service.close()
        manager = successor(owners)
        events = []
        resolver = _Resolver(events)
        service = await recovery(manager, lease, resolver).open()
        owners[1].commit(manager._instance, "f" * 32, native_identity=_identity())
        renewed = manager.issue_close(reservation, operation_id=request.operation_id, deadline=monotonic() + 5)
        entered, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_release, original_close = ManagedMuxCloseAdmission.close, resolver.sessions[0].close

        async def held(owner):
            if owner._manager is manager and owner._use is ManagedMuxCloseUseV1.ADMIT:
                entered.set()
                await release.wait()
            await original_release(owner)

        async def closed():
            await original_close()
            cleaned.set()

        monkeypatch.setattr(ManagedMuxCloseAdmission, "close", held)
        resolver.sessions[0].close = closed
        task = asyncio.create_task(service.close_managed_mux(renewed))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert manager._continued_closures[request.operation_id] == lease.record.managed_closures[0]
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(cleaned.wait(), 2)
            assert events.count("close:" + resolver.sessions[0].identity.session_id) == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await service.close()
        assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLOSED
    asyncio.run(scenario())


def test_missing_whole_record_cannot_erase_confirmed_history(owners):
    async def scenario():
        _, service, _, _, _, _, _, _ = await opened(owners)
        await service.close()
        manager = successor(owners)
        lease, resolver = _MemoryLease(), _Resolver([])
        attempt = recovery(manager, lease, resolver)
        try:
            with pytest.raises(AppServiceError):
                await attempt.open()
            assert not resolver.requests and not lease.commits
        finally:
            await attempt.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["attempt", "native", "unregistered", "stop", "committed"])
def test_startup_identity_and_phase_are_required_before_restore(owners, fault):
    async def scenario():
        _, service, lease, _, _, _, _, _ = await opened(owners)
        await service.close()
        manager = successor(owners, native=fault != "unregistered")
        if fault == "attempt":
            manager._startup_attempt = "e" * 32
        elif fault == "native":
            manager._startup_native = replace(_identity(), start_ticks=101)
        elif fault == "stop":
            owners[1].request_stop(manager._instance)
        elif fault == "committed":
            owners[1].commit(manager._instance, "f" * 32, native_identity=_identity())
        resolver = _Resolver([])
        before = len(lease.commits)
        attempt = recovery(manager, lease, resolver)
        try:
            with pytest.raises(AppServiceError):
                await attempt.open()
            assert not resolver.requests and len(lease.commits) == before
        finally:
            await attempt.close()
    asyncio.run(scenario())


def test_settlement_requires_original_admit_and_allows_same_instance_stop(owners):
    async def scenario():
        _, service, lease, _, _, _, _, _ = await opened(owners)
        await service.close()
        manager = successor(owners)
        async def check(use, allowed):
            admission = manager.prepare_recovery(lease.record, use)
            try:
                if allowed:
                    await admission.acquire()
                    admission.check_record(lease.record)
                else:
                    with pytest.raises(ManagedStorageError):
                        await admission.acquire()
            finally:
                await admission.close()
        await check(ManagedMuxCloseUseV1.SETTLE, False)
        await check(ManagedMuxCloseUseV1.ADMIT, True)
        owners[1].request_stop(manager._instance)
        await check(ManagedMuxCloseUseV1.ADMIT, False)
        await check(ManagedMuxCloseUseV1.SETTLE, True)
        successor(owners, attempt="e" * 32)
        await check(ManagedMuxCloseUseV1.SETTLE, False)
    asyncio.run(scenario())


@pytest.mark.parametrize("known", [False, True])
def test_pending_recovery_settles_before_active_and_retries_original_intent(owners, known):
    async def scenario():
        manager, service, lease, _, _, _, _, request = await opened(owners)
        await member(service, request, session_id="pending-session")
        _, _, active_request = await other_target(owners, manager, service)
        await member(service, active_request, session_id="active-session")
        await service.close_managed_mux(request)
        # Retain the genuine first close CAS, the crash-recovery input, rather
        # than synthesizing a close intent or changing immutable origins.
        pending = lease.commits[-2]
        await service.close()
        if known:
            manager.record_close(request, pending.managed_closures[0], deadline=monotonic() + 5)
        lease = _MemoryLease(pending)
        manager = successor(owners)
        events = []

        class Resolver(_Resolver):
            async def open_session(self, request):
                if request.session_id == "active-session":
                    assert events == ["close:pending-session"]
                    assert len(lease.commits) == 1
                return await super().open_session(request)

        resolver = Resolver(events, fail_session_id="active-session")
        attempt = recovery(manager, lease, resolver)
        with pytest.raises(AppServiceError):
            await attempt.open()
        assert lease.record.managed_closures[0] == replace(
            pending.managed_closures[0], phase=ManagedMuxClosePhaseV1.CLOSED,
        )
        assert manager._recovery_record == pending
        resolver.fail_session_id = None
        restored = await attempt.open()
        try:
            assert len(lease.commits) == 1
            assert [item.session_id for item in resolver.requests].count("pending-session") == 1
            assert [mux.name for mux in (await restored.list_muxes()).mux_spaces] == ["other"]
            assert owners[0].resolve("dev") is not None  # Not silently reconciled/released.
        finally:
            await restored.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["creation_origin", "close_origin", "missing_close", "missing_creation",
                                    "closed_regression", "active_reference"])
def test_registry_history_mismatch_rejects_before_any_session_io(owners, fault):
    async def scenario():
        manager, service, lease, _, _, _, _, request = await opened(owners)
        await member(service, request)
        await service.close_managed_mux(request)
        pending, closed = lease.commits[-2], lease.record
        result = closed.managed_closures[0]
        manager.record_close(request, result if fault == "closed_regression" else pending.managed_closures[0],
                             deadline=monotonic() + 5)
        await service.close()
        record = pending
        if fault == "creation_origin":
            record = replace(record, managed_creations=(replace(record.managed_creations[0], instance_id="a" * 32),))
        elif fault == "close_origin":
            record = replace(record, managed_closures=(replace(record.managed_closures[0], instance_id="a" * 32),))
        elif fault == "missing_close":
            record = replace(record, managed_closures=())
        elif fault == "missing_creation":
            record = replace(record, mux_spaces=(), managed_creations=(), managed_closures=())
        elif fault == "active_reference":
            with owners[0]._database.transaction(write=True) as connection:
                connection.execute("DELETE FROM muxes WHERE name='dev'")
        manager = successor(owners)
        resolver, lease = _Resolver([]), _MemoryLease(record)
        attempt = recovery(manager, lease, resolver)
        try:
            with pytest.raises(AppServiceError):
                await attempt.open()
            assert not resolver.requests and not lease.commits
        finally:
            await attempt.close()
    asyncio.run(scenario())


def test_closed_origin_survives_multiple_generations_and_same_name_reuse(owners):
    async def scenario():
        manager, service, lease, _, _, reservation, _, request = await opened(owners)
        result = await service.close_managed_mux(request)
        manager.record_close(request, result, deadline=monotonic() + 5)
        await service.close()
        reused = ManagedMuxReservationV1(reservation.name, reservation.service, "e" * 32)
        owners[0].reserve_mux(reused)
        for attempt_id in ("f" * 32, "a" * 32):
            manager = successor(owners, attempt=attempt_id)
            before = len(lease.commits)
            restored = await recovery(manager, lease).open()
            try:
                assert lease.record.managed_closures == (result,) and len(lease.commits) == before
                assert owners[0].resolve(reservation.name) == reused
            finally:
                await restored.close()
    asyncio.run(scenario())


def test_issued_only_missing_result_stays_unknown_and_reserved(owners):
    async def scenario():
        manager, _, reservation = _ready(owners)
        manager.issue_create(reservation, deadline=monotonic() + 5)
        manager = successor(owners)
        lease = _MemoryLease()
        restored = await recovery(manager, lease).open()
        try:
            assert not lease.commits and owners[0].resolve(reservation.name) == reservation
            assert not (await restored.list_muxes()).mux_spaces
        finally:
            await restored.close()
    asyncio.run(scenario())


def test_creation_without_issued_permit_cannot_restore(owners):
    async def scenario():
        manager, service, lease, _, _, _, _, _ = await opened(owners)
        reservation, create, _ = await other_target(owners, manager, service, issue=False)
        await service.close()
        # Independent creation-only target: no close FK masks the actual
        # recovery check, and the malformed record remains structurally valid.
        with owners[0]._database.transaction(write=True) as connection:
            connection.execute("DELETE FROM mux_authorities WHERE operation_id=?", (create.operation_id,))
        manager = successor(owners)
        resolver = _Resolver([])
        before = len(lease.commits)
        attempt = recovery(manager, lease, resolver)
        try:
            with pytest.raises(AppServiceError):
                await attempt.open()
            assert not resolver.requests and len(lease.commits) == before
            assert owners[0].resolve(reservation.name) == reservation
        finally:
            await attempt.close()
    asyncio.run(scenario())


def test_real_file_absence_after_clean_restart_is_not_a_fresh_application(owners, tmp_path):
    from loushang.appservice import JsonFileApplicationContinuityStoreV1

    async def scenario():
        _, service, memory, _, _, _, _, _ = await opened(owners)
        await service.close()
        root = tmp_path / "continuity"
        store = JsonFileApplicationContinuityStoreV1(root)
        lease = await store.acquire(application_id="coding.default", owner_epoch="before")
        await lease.commit(expected_revision=None, record=memory.record)
        await lease.close()
        paths = tuple(root.glob("*.json"))
        assert len(paths) == 1
        original = paths[0].read_bytes()
        backup = tmp_path / "retained-test-continuity.json"
        paths[0].rename(backup)  # Preserve the fixture; never remove user state.
        manager = successor(owners)
        lease = await store.acquire(application_id="coding.default", owner_epoch="after")
        resolver = _Resolver([])
        attempt = recovery(manager, lease, resolver)
        try:
            assert await lease.load() is None
            with pytest.raises(AppServiceError):
                await attempt.open()
            assert not resolver.requests and not paths[0].exists()
            assert backup.read_bytes() == original
        finally:
            await attempt.close()
            await lease.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["fence", "database"])
def test_startup_retries_clean_read_contention_on_original_owner(owners, monkeypatch, boundary):
    async def scenario():
        manager = successor(owners)
        target = owners[1]._fence if boundary == "fence" else owners[0]._database
        method = "lock" if boundary == "fence" else "transaction"
        original = getattr(target, method)
        calls = 0

        @contextmanager
        def contended(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ManagedStorageError("busy")
            with original(*args, **kwargs) as result:
                yield result

        monkeypatch.setattr(target, method, contended)
        lease = _MemoryLease()
        attempt = recovery(manager, lease)
        service = None
        try:
            service = await attempt.open()
            assert calls == 3 and not lease.commits
            assert manager._recovery_admitted and manager._recovery_record is None
        finally:
            if service is not None:
                await service.close()
            await attempt.close()
    asyncio.run(scenario())


def test_startup_fence_contention_ignores_unrelated_transient_database_close(owners, monkeypatch):
    async def scenario():
        manager = successor(owners)
        fence = owners[1]._fence
        database_directory = owners[0]._database._directory
        original = fence.lock
        calls = 0
        transient_descriptor = -1

        @contextmanager
        def contended(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                database_directory._uncertain_closes.add(transient_descriptor)
                raise ManagedStorageError("busy")
            with original(*args, **kwargs) as result:
                yield result

        async def settle_unrelated_close(_):
            database_directory._uncertain_closes.remove(transient_descriptor)

        monkeypatch.setattr(fence, "lock", contended)
        monkeypatch.setattr(asyncio, "sleep", settle_unrelated_close)
        service = None
        attempt = recovery(manager, _MemoryLease())
        try:
            service = await attempt.open()
            assert calls == 2
            assert manager._recovery_admitted
        finally:
            database_directory._uncertain_closes.discard(transient_descriptor)
            if service is not None:
                await service.close()
            await attempt.close()

    asyncio.run(scenario())


async def _permission_case(owners, mode):
    if mode == "recovery":
        manager = successor(owners)
        return manager, manager.prepare_recovery(None, ManagedMuxCloseUseV1.ADMIT), None
    manager, service, _, _, _, _, create, close = await opened(owners)
    admission = manager.prepare(create) if mode == "create" else manager.prepare_close(close, ManagedMuxCloseUseV1.ADMIT)
    return manager, admission, service


@pytest.mark.parametrize("mode", ["recovery", "create", "close"])
@pytest.mark.parametrize("action", ["close", "stop"])
def test_backoff_rechecks_admission_close_and_durable_stop(owners, monkeypatch, action, mode):
    async def scenario():
        manager, admission, service = await _permission_case(owners, mode)
        target = owners[1]._fence
        original = target.lock
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        @contextmanager
        def contended(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ManagedStorageError("busy")
            with original(*args, **kwargs):
                yield

        async def pause(_):
            entered.set()
            await release.wait()

        monkeypatch.setattr(target, "lock", contended)
        monkeypatch.setattr(asyncio, "sleep", pause)
        task = asyncio.create_task(admission.acquire())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if action == "close":
                await admission.close()
            else:
                owners[1].request_stop(manager._instance)
            release.set()
            with pytest.raises(ManagedStorageError):
                await task
            if action == "close":
                assert calls == 1
            assert not manager._recovery_admitted
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await admission.close()
            if service is not None:
                await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["recovery", "create", "close"])
def test_unknown_fence_release_is_not_retried_as_busy(owners, monkeypatch, mode):
    async def scenario():
        manager, admission, service = await _permission_case(owners, mode)
        original = owners[1]._fence.lock
        entries = exits = 0

        @contextmanager
        def uncertain(*args, **kwargs):
            nonlocal entries, exits
            entries += 1
            with original(*args, **kwargs):
                yield
            exits += 1
            raise ManagedStorageError("busy")  # Release receipt lost, not a retry permit.

        @contextmanager
        def busy(*args, **kwargs):
            raise ManagedStorageError("busy")
            yield  # pragma: no cover

        with monkeypatch.context() as patch:
            patch.setattr(owners[1]._fence, "lock", uncertain)
            patch.setattr(owners[0]._database, "transaction", busy)
            with pytest.raises(ManagedStorageError):
                await admission.acquire()
            with pytest.raises(ManagedStorageError, match="unavailable"):
                await admission.close()
            assert entries == exits == 1 and not manager._recovery_admitted
        if service is not None:
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["recovery", "create", "close"])
def test_persistent_read_busy_exhausts_original_deadline_without_renewal(owners, monkeypatch, mode):
    from loushang.apphost.managed import _files
    from loushang.apphost.managed import mux_management as module

    async def scenario():
        manager, admission, service = await _permission_case(owners, mode)
        now = 100.0
        deadlines = []

        @contextmanager
        def busy(*args, deadline=None, **kwargs):
            deadlines.append(deadline)
            raise ManagedStorageError("busy")
            yield  # pragma: no cover

        async def advance(_):
            nonlocal now
            now += 1.0

        with monkeypatch.context() as patch:
            patch.setattr(module, "monotonic", lambda: now)
            patch.setattr(_files, "monotonic", lambda: now)
            patch.setattr(owners[1]._fence, "lock", busy)
            patch.setattr(asyncio, "sleep", advance)
            with pytest.raises(ManagedStorageError) as error:
                await admission.acquire()
            assert error.value.code == "busy"  # Existing deadline contract, no new error taxonomy.
            assert deadlines == [105.0] * 5 and now == 105.0
            with pytest.raises(ManagedStorageError, match="conflict"):
                await admission.acquire()
            assert len(deadlines) == 5 and not manager._recovery_admitted
            await admission.close()
        if service is not None:
            await service.close()
    asyncio.run(scenario())
