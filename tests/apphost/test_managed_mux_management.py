"""Real registry/fence consumer of AppService's managed creation capability."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedStopEvidenceV1
from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.appserver.protocol import AppServiceError
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    create_appservice_recovery_attempt,
)
from tests.apphost.test_managed_lifecycle import _identity
from tests.apphost.test_managed_lifecycle import owners as _base_owners
from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver

owners = _base_owners


def test_real_permit_crosses_authenticated_local_wire_and_settles_registry_receipt(owners, tmp_path):
    from loushang.appserver.local import LocalAppClientConnectionV1, LocalAppServerV1
    from loushang.appserver.local_record import (
        LocalConnectionDirectoryV1,
        LocalRecordScopeV1,
    )
    from loushang.appserver.protocol import SessionScopeV1
    from loushang.appservice.client_scope import ScopedAppServiceV1

    async def scenario():
        manager, _, reservation = _ready(owners)
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        owner = ScopedAppServiceV1(service)
        directory = LocalConnectionDirectoryV1(tmp_path / "connection")
        server = LocalAppServerV1(
            directory, "managed", application_id="coding.default", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),),
            scope_factory=owner.open_client_scope, managed_mux_scope_factory=owner.open_client_scope,
            request_stop=lambda _: pytest.fail("connection close must not stop service"),
        )
        client = LocalAppClientConnectionV1(directory, "managed")
        try:
            await server.start()
            await client.start()
            capability = client.managed_mux_client
            assert capability is not None
            with pytest.raises(AppServiceError):
                await capability.create_managed_mux(replace(request, authority="forged"))
            assert not lease.commits
            assert manager.read_created(request, deadline=monotonic() + 5) is None
            result = await capability.create_managed_mux(request)
            assert manager.record_created(request, result, deadline=monotonic() + 5) == result
            assert await capability.create_managed_mux(request) == result
            assert manager.read_created(request, deadline=monotonic() + 5) == result
            assert len(lease.commits) == 1
            assert request.authority.encode() not in repr(directory.read("managed")).encode()
        finally:
            await client.close()
            await server.close()
            await service.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 15))


def _ready(owners):
    registry, journal, namespace, service = owners
    state = journal.prepare("c" * 32, expected=None)
    instance = state.handoff.instance
    journal.register_native(instance, "c" * 32, _identity())
    journal.commit(instance, "c" * 32, native_identity=_identity())
    manager = ManagedMuxManagerV1(registry, journal, namespace, service, instance,
                                  application_id="coding.default")
    return manager, instance, ManagedMuxReservationV1("dev", service, "b" * 32)


async def _service(manager, lease):
    attempt = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
        "coding", _Resolver([]), lease, managed_mux=manager.binding(),
    ))
    return await attempt.open()


def test_real_management_issues_exact_idempotent_permit_and_records_result(owners):
    async def scenario():
        manager, instance, reservation = _ready(owners)
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        assert manager.issue_create(reservation, deadline=monotonic() + 5) == request
        assert request.instance_id == instance.instance_id
        assert request.authority not in repr(request)
        assert manager.read_created(request, deadline=monotonic() + 5) is None
        lease = _MemoryLease()
        service = await _service(manager, lease)
        try:
            result = await service.create_managed_mux(request)
            assert manager.record_created(request, result, deadline=monotonic() + 5) == result
            assert manager.record_created(request, result, deadline=monotonic() + 5) == result
            assert manager.read_created(request, deadline=monotonic() + 5) == result
            with pytest.raises(ManagedStorageError):
                manager.record_created(request, replace(result, mux_space_id="another"),
                                       deadline=monotonic() + 5)
            assert len(lease.commits) == 1
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("field,value", (
    ("name", "unreserved"), ("operation_id", "d" * 32),
    ("authority", "forged"), ("instance_id", "e" * 32), ("service_id", "f" * 64),
))
def test_real_management_rejects_forged_or_mismatched_create_without_commit(owners, field, value):
    async def scenario():
        manager, _, reservation = _ready(owners)
        permit = manager.issue_create(reservation, deadline=monotonic() + 5)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        try:
            with pytest.raises(AppServiceError):
                await service.create_managed_mux(replace(permit, **{field: value}))
            assert not lease.commits
            assert owners[1].read() is not None
        finally:
            await service.close()

    asyncio.run(scenario())


def test_real_management_creation_holds_only_service_fence_until_commit_settles(owners):
    async def scenario():
        manager, instance, reservation = _ready(owners)
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        entered, release = asyncio.Event(), asyncio.Event()

        class PausedLease(_MemoryLease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = PausedLease()
        service = await _service(manager, lease)
        creation = asyncio.create_task(service.create_managed_mux(request))
        await entered.wait()
        try:
            # Same service cannot pass the admission's original native lock.
            with pytest.raises(ManagedStorageError, match="busy"):
                owners[1].request_stop(instance)
            # The global registry transaction has already been released.
            other = ManagedMuxReservationV1("other", reservation.service, "d" * 32)
            assert owners[0].reserve_mux(other) == other
            release.set()
            result = await creation
            owners[1].request_stop(instance)
            assert manager.record_created(request, result, deadline=monotonic() + 5) == result
            with pytest.raises(AppServiceError):
                await service.create_managed_mux(request)
            with pytest.raises(ManagedStorageError):
                manager.issue_create(other, deadline=monotonic() + 5)
            assert len(lease.commits) == 1
        finally:
            release.set()
            await asyncio.gather(creation, return_exceptions=True)
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("already_recorded", (False, True))
def test_real_management_reauthorization_keeps_historical_receipt_and_rejects_old_permit(owners, already_recorded, monkeypatch):
    async def scenario():
        manager, first_instance, reservation = _ready(owners)
        first_request = manager.issue_create(reservation, deadline=monotonic() + 5)
        lease = _MemoryLease()
        service = await _service(manager, lease)
        result = await service.create_managed_mux(first_request)
        if already_recorded:
            manager.record_created(first_request, result, deadline=monotonic() + 5)
        await service.close()
        # Simulate the trusted three-fact clean retirement; no native process
        # is launched/killed by this fixture.
        registry, journal, namespace, key = owners
        journal.request_stop(first_instance)
        journal.record_stop_evidence(ManagedStopEvidenceV1(first_instance, True, True, True))
        state = journal.prepare("d" * 32, expected=journal.read())
        second_instance = state.handoff.instance
        journal.register_native(second_instance, "d" * 32, _identity())
        journal.commit(second_instance, "d" * 32, native_identity=_identity())
        second = ManagedMuxManagerV1(registry, journal, namespace, key, second_instance,
                                     application_id="coding.default")
        def no_normal_growth(_connection):
            raise ManagedStorageError("capacity")

        monkeypatch.setattr(registry._database, "admit_growth", no_normal_growth)
        request = second.issue_create(reservation, deadline=monotonic() + 5)
        assert request.authority != first_request.authority
        assert second.read_created(request, deadline=monotonic() + 5) == (result if already_recorded else None)
        recovered = await _service(second, _MemoryLease(lease.record))
        try:
            assert await recovered.create_managed_mux(request) == result
            assert second.record_created(request, result, deadline=monotonic() + 5) == result
            assert result.instance_id == first_instance.instance_id
            for selected in (manager, second):
                with pytest.raises(ManagedStorageError):
                    selected.record_created(first_request, result, deadline=monotonic() + 5)
        finally:
            await recovered.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("history", ("missing", "conflicting", "unrecorded"))
def test_real_management_reauthorization_cannot_recreate_missing_or_conflicting_history(owners, history):
    async def scenario():
        manager, instance, reservation = _ready(owners)
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        lease = _MemoryLease()
        original = await _service(manager, lease)
        result = await original.create_managed_mux(request)
        if history != "unrecorded":
            manager.record_created(request, result, deadline=monotonic() + 5)
        await original.close()
        registry, journal, namespace, key = owners
        journal.request_stop(instance)
        journal.record_stop_evidence(ManagedStopEvidenceV1(instance, True, True, True))
        state = journal.prepare("d" * 32, expected=journal.read())
        replacement = state.handoff.instance
        journal.register_native(replacement, "d" * 32, _identity())
        journal.commit(replacement, "d" * 32, native_identity=_identity())
        second = ManagedMuxManagerV1(registry, journal, namespace, key, replacement,
                                     application_id="coding.default")
        permit = second.issue_create(reservation, deadline=monotonic() + 5)
        record = None
        if history == "conflicting":
            # Keep this malformed-history fixture internally coherent, so the
            # consumer's stronger known-result comparison must reject it.
            record = replace(lease.record,
                mux_spaces=(replace(lease.record.mux_spaces[0], mux_space_id="different"),),
                managed_creations=(replace(result, mux_space_id="different"),))
        fresh_lease = _MemoryLease(record)
        recovered = await _service(second, fresh_lease)
        try:
            with pytest.raises(AppServiceError):
                await recovered.create_managed_mux(permit)
            assert not fresh_lease.commits
        finally:
            await recovered.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("closed_before_error", (False, True))
def test_real_management_acquire_unwind_keeps_unknown_close_debt(tmp_path, monkeypatch, closed_before_error):
    from loushang.apphost.managed.contracts import (
        ManagedNamespaceV1,
        ManagedServiceKeyV1,
    )
    from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
    from loushang.apphost.managed.registry import ManagedRegistryV1

    async def scenario():
        namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
        key = ManagedServiceKeyV1("coding", "/workspace")
        registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
        registry.reserve_mux(ManagedMuxReservationV1("dev", key, "b" * 32))
        journal = ManagedServiceJournalV1(registry, namespace, key, tmp_path / "fence", create=True)
        manager, _, reservation = _ready((registry, journal, namespace, key))
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        service = await _service(manager, _MemoryLease())
        fence = journal._fence
        original_open, original_check, original_close = fence._open, fence._check_named, os.close
        target: int | None = None
        replacement: int | None = None
        close_calls = 0

        def capture(name, *args, **kwargs):
            nonlocal target
            value = original_open(name, *args, **kwargs)
            if name == "lifecycle.lock":
                target = value
            return value

        def reject(name, identity):
            if name == "lifecycle.lock" and target is not None:
                raise ManagedStorageError("conflict")
            return original_check(name, identity)

        def interrupted_close(fd):
            nonlocal replacement, close_calls
            if fd != target:
                return original_close(fd)
            close_calls += 1
            if closed_before_error:
                original_close(fd)
                replacement = os.open("/dev/null", os.O_RDONLY)
                assert replacement == fd
            raise KeyboardInterrupt("injected close receipt loss")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(fence, "_open", capture)
                patch.setattr(fence, "_check_named", reject)
                patch.setattr(os, "close", interrupted_close)
                with pytest.raises(AppServiceError):
                    await service.create_managed_mux(request)
                assert close_calls == 1
                assert target in fence._uncertain_closes
                assert service._managed_admission is not None
                for _ in range(2):
                    with pytest.raises(AppServiceError):
                        await service.close()
                assert close_calls == 1
                assert target is not None
                os.fstat(target)
            with pytest.raises(ManagedStorageError):
                journal.close()
            assert target in fence._uncertain_closes
            os.fstat(target)
        finally:
            # Test instrumentation alone knows whether this exact descriptor
            # is the original still-open lock or our /dev/null replacement.
            # Production owners never clear the unknown-close ledger or retry.
            if target is not None:
                original_close(target)
            registry.close()

    asyncio.run(scenario())


def test_real_management_native_competing_stop_waits_for_cancelled_create(owners, tmp_path):
    script = """
import os, sys
from pathlib import Path
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1, ManagedInstanceRefV1
from loushang.apphost.managed._files import ManagedStorageError
namespace = ManagedNamespaceV1(sys.argv[2], os.geteuid(), 'a'*32)
service = ManagedServiceKeyV1('coding', '/workspace')
registry = ManagedRegistryV1(Path(sys.argv[1])/'registry', namespace)
journal = ManagedServiceJournalV1(registry, namespace, service, Path(sys.argv[1])/'fence')
try:
    journal.request_stop(ManagedInstanceRefV1(namespace.namespace_key, service.service_id, sys.argv[3]))
    print('stopped')
except ManagedStorageError as error:
    print(error.code)
finally:
    journal.close()
    registry.close()
"""

    async def scenario():
        manager, instance, reservation = _ready(owners)
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        entered, release = asyncio.Event(), asyncio.Event()

        class PausedLease(_MemoryLease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = PausedLease()
        service = await _service(manager, lease)
        task = asyncio.create_task(service.create_managed_mux(request))
        await entered.wait()

        def external_stop():
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
            result = subprocess.run(
                [sys.executable, "-c", script, str(tmp_path), owners[2].platform_home, instance.instance_id],
                env=env, capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        try:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert external_stop() == "busy"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(lease.commits) == 1
            assert external_stop() == "stopped"
            with pytest.raises(AppServiceError):
                await service.create_managed_mux(request)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await service.close()

    asyncio.run(scenario())


def test_real_management_expired_and_unreserved_issuance_never_creates_authority(owners):
    manager, _, reservation = _ready(owners)
    for selected, deadline in (
        (reservation, monotonic() - 1),
        (replace(reservation, operation_id="f" * 32), monotonic() + 5),
        (replace(reservation, name="unreserved"), monotonic() + 5),
    ):
        with pytest.raises(ManagedStorageError):
            manager.issue_create(selected, deadline=deadline)
    with owners[0]._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM mux_authorities").fetchone()[0] == 0


def test_real_management_lost_registry_replies_do_not_rotate_permit_or_result(owners, monkeypatch):
    from contextlib import contextmanager

    async def scenario():
        manager, _, reservation = _ready(owners)
        database = owners[0]._database
        original = database.transaction
        lose_reply = False

        @contextmanager
        def transaction(*args, **kwargs):
            nonlocal lose_reply
            with original(*args, **kwargs) as connection:
                yield connection
            if lose_reply and kwargs.get("write"):
                lose_reply = False
                raise ManagedStorageError("unavailable")

        monkeypatch.setattr(database, "transaction", transaction)
        lose_reply = True
        with pytest.raises(ManagedStorageError):
            manager.issue_create(reservation, deadline=monotonic() + 5)
        with original() as connection:
            authority = connection.execute("SELECT authority FROM mux_authorities").fetchone()[0]
        request = manager.issue_create(reservation, deadline=monotonic() + 5)
        assert request.authority == authority
        lease = _MemoryLease()
        service = await _service(manager, lease)
        try:
            result = await service.create_managed_mux(request)
            lose_reply = True
            with pytest.raises(ManagedStorageError):
                manager.record_created(request, result, deadline=monotonic() + 5)
            assert manager.read_created(request, deadline=monotonic() + 5) == result
            assert manager.record_created(request, result, deadline=monotonic() + 5) == result
            assert len(lease.commits) == 1
        finally:
            await service.close()

    asyncio.run(scenario())
