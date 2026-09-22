"""Recovery settles hidden close debt before publishing unrelated active Muxes."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.managed_mux import ManagedMuxCreatedV1
from loushang.appserver.managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    create_appservice_recovery_attempt,
)
from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver
from tests.appservice.test_managed_mux import INSTANCE, SERVICE, _binding, _request
from tests.appservice.test_managed_mux_close_continuity import record
from tests.appservice.test_managed_mux_close_runtime import Admission


def mixed_record(*, closed=False):
    original = record(closed=closed)
    active = record().mux_spaces[0]
    member = active.members[0]
    active = replace(active, mux_space_id="mux-active", name="active", members=(
        replace(member, member_id="member-active", session=replace(member.session, session_id="session-active")),
    ))
    creation = ManagedMuxCreatedV1("e" * 32, INSTANCE, active.name, active.mux_space_id)
    return replace(original, mux_spaces=(*original.mux_spaces, active),
                   managed_creations=(*original.managed_creations, creation))


class Permission:
    def __init__(self, value, use, owners):
        self.value, self.use, self.owners = value, use, owners
        self.acquired = False
        self.denied = False
        self.fail_release = False
        self.release_calls = 0

    async def acquire(self):
        if self.denied:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self.acquired = True

    def check_record(self, value):
        assert self.acquired and value == self.value

    async def close(self):
        self.release_calls += 1
        if self.fail_release:
            raise RuntimeError("release unavailable")
        self.acquired = False


def setup(value=None, *, lease=None, resolver=None, factory=None):
    from loushang.appservice.managed_mux_close import (
        ManagedMuxCloseBindingV1,
        ManagedMuxCloseRecoveryBindingV1,
    )

    owners, events = [], []
    lease = lease or _MemoryLease(value or mixed_record())
    resolver = resolver or _Resolver(events)

    def prepare(value, use):
        owner = Permission(value, use, owners)
        owners.append(owner)
        if factory:
            factory(owner)
        return owner

    closing = ManagedMuxCloseBindingV1(
        lambda request, use: Admission(request, use, events, [False]),
        recovery=ManagedMuxCloseRecoveryBindingV1(prepare),
    )
    binding = replace(_binding([]), closing=closing)
    attempt = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
        "coding", resolver, lease, managed_mux=binding,
    ))
    return attempt, lease, resolver, owners


def test_pending_settles_before_active_and_preserves_origin_history():
    async def scenario():
        events = []

        class Resolver(_Resolver):
            async def open_session(self, request):
                assert all(not owner.acquired for owner in owners)
                if request.session_id == "session-active":
                    assert events == ["close:session-1"]
                    assert len(lease.commits) == 1
                return await super().open_session(request)

        attempt, lease, resolver, owners = setup(resolver=Resolver(events))
        original = lease.record
        service = await attempt.open()
        try:
            assert [mux.name for mux in (await service.list_muxes()).mux_spaces] == ["active"]
            result = lease.record.managed_closures[0]
            assert result == replace(original.managed_closures[0], phase=ManagedMuxClosePhaseV1.CLOSED)
            request = ManagedMuxCloseV1(SERVICE, INSTANCE, result.operation_id,
                                       result.creation_operation_id, result.name, result.mux_space_id, "close-secret")
            assert await service.read_managed_mux_close(request) == result
            assert result.instance_id != request.instance_id
            await service.create_managed_mux(_request(operation_id="f" * 32, name="new"))
            assert lease.record.managed_closures == (result,)
            assert [request.session_id for request in resolver.requests] == ["session-1", "session-active"]
        finally:
            await service.close()
        assert events == ["close:session-1", "close:session-active"]
        assert not lease.closed

    asyncio.run(scenario())


def test_closed_history_opens_only_unrelated_active_members_without_writing():
    async def scenario():
        attempt, lease, resolver, _ = setup(mixed_record(closed=True))
        original = lease.record
        service = await attempt.open()
        try:
            assert [request.session_id for request in resolver.requests] == ["session-active"]
            assert lease.record == original and not lease.commits
            assert service._managed_closures == {item.operation_id: item for item in original.managed_closures}
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["admit", "release", "settle"])
def test_permission_failure_never_publishes_active_and_retains_original_release(failure):
    async def scenario():
        from loushang.appservice.managed_mux_close import ManagedMuxCloseUseV1

        def configure(owner):
            owner.denied = (failure == "admit" and owner.use is ManagedMuxCloseUseV1.ADMIT
                            or failure == "settle" and owner.use is ManagedMuxCloseUseV1.SETTLE)
            owner.fail_release = failure == "release"

        attempt, lease, resolver, owners = setup(factory=configure)
        with pytest.raises(AppServiceError):
            await attempt.open()
        assert not lease.commits
        assert not resolver.requests or failure == "settle"
        assert all(request.session_id != "session-active" for request in resolver.requests)
        if failure == "release":
            assert attempt.cleanup_pending and len(owners) == 1
            original = owners[0]
            original.fail_release = False
            await asyncio.gather(attempt.close(), attempt.close())
            assert owners == [original] and not original.acquired
        else:
            await attempt.close()
        assert not lease.closed

    asyncio.run(scenario())


def test_confirmed_commit_then_active_failure_retries_without_pending_reopen_or_commit():
    async def scenario():
        events = []
        resolver = _Resolver(events, fail_session_id="session-active")
        attempt, lease, _, _ = setup(resolver=resolver)
        with pytest.raises(AppServiceError):
            await attempt.open()
        assert len(lease.commits) == 1 and events == ["close:session-1"]
        resolver.fail_session_id = None
        service = await attempt.open()
        try:
            assert len(lease.commits) == 1
            assert [request.session_id for request in resolver.requests].count("session-1") == 1
            assert events == ["close:session-1"]
        finally:
            await service.close()

    asyncio.run(scenario())


def test_unknown_commit_is_not_repaired_by_reading_closed_bytes():
    class LostReceipt(_MemoryLease):
        async def commit(self, *, expected_revision, record):
            await super().commit(expected_revision=expected_revision, record=record)
            raise RuntimeError("lost durable receipt")

    async def scenario():
        attempt, lease, resolver, _ = setup(lease=LostReceipt(mixed_record()))
        for _ in range(2):
            with pytest.raises(AppServiceError):
                await attempt.open()
        assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLOSED
        assert len(lease.commits) == 1
        assert [request.session_id for request in resolver.requests] == ["session-1"]
        assert attempt.cleanup_pending
        with pytest.raises(AppServiceError) as caught:
            await attempt.close()
        assert caught.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert not lease.closed

    asyncio.run(scenario())


def test_partial_cleanup_retries_original_failed_owner_without_reopening_success():
    async def scenario():
        events, allow_close = [], [False]

        class Resolver(_Resolver):
            async def open_session(self, request):
                port = await super().open_session(request)
                if request.session_id == "session-2":
                    original = port.close

                    async def close():
                        if not allow_close[0]:
                            events.append("failed:session-2")
                            raise RuntimeError("cleanup unavailable")
                        await original()

                    port.close = close
                return port

        value = mixed_record()
        pending = value.mux_spaces[0]
        member = pending.members[0]
        pending = replace(pending, members=(*pending.members, replace(
            member, member_id="member-2", position=2,
            session=replace(member.session, session_id="session-2"),
        )))
        value = replace(value, mux_spaces=(pending, value.mux_spaces[1]))
        attempt, lease, resolver, _ = setup(value, resolver=Resolver(events))
        with pytest.raises(AppServiceError):
            await attempt.open()
        original_ports = tuple(resolver.sessions)
        assert events.count("close:session-1") == 1 and "failed:session-2" in events
        assert not lease.commits and attempt.cleanup_pending
        assert [request.session_id for request in resolver.requests] == ["session-1", "session-2"]
        allow_close[0] = True
        service = await attempt.open()
        try:
            assert tuple(resolver.sessions[:2]) == original_ports
            assert [request.session_id for request in resolver.requests] == ["session-1", "session-2", "session-active"]
            assert events.count("close:session-1") == events.count("close:session-2") == 1
            assert len(lease.commits) == 1
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["admit", "settle"])
def test_release_barrier_cancellation_joins_original_recovery_before_active(phase):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        def configure(owner):
            if owner.use.value != phase:
                return
            original = owner.close

            async def held():
                entered.set()
                await release.wait()
                await original()

            owner.close = held

        attempt, lease, resolver, owners = setup(factory=configure)
        opening = asyncio.create_task(attempt.open())
        await asyncio.wait_for(entered.wait(), 2)
        original_task = attempt._open_task
        assert [request.session_id for request in resolver.requests] == ([] if phase == "admit" else ["session-1"])
        assert len(lease.commits) == (0 if phase == "admit" else 1)
        assert owners[-1].acquired
        opening.cancel()
        second = asyncio.create_task(attempt.open())
        await asyncio.sleep(0)
        assert attempt._open_task is original_task and not second.done()
        release.set()
        service = await second
        with pytest.raises(asyncio.CancelledError):
            await opening
        try:
            assert len(lease.commits) == 1
            assert [request.session_id for request in resolver.requests] == ["session-1", "session-active"]
            assert all(not owner.acquired for owner in owners)
        finally:
            await service.close()

    asyncio.run(scenario())


def test_confirmed_commit_release_failure_retries_same_permission_without_cas():
    async def scenario():
        def configure(owner):
            owner.fail_release = owner.use.value == "settle"

        attempt, lease, resolver, owners = setup(factory=configure)
        with pytest.raises(AppServiceError):
            await attempt.open()
        permission = owners[-1]
        assert permission.use.value == "settle" and attempt.cleanup_pending
        assert len(lease.commits) == 1
        assert [request.session_id for request in resolver.requests] == ["session-1"]
        permission.fail_release = False
        service = await attempt.open()
        try:
            assert not permission.acquired and len(lease.commits) == 1
            assert [owner.use.value for owner in owners] == ["admit", "settle", "admit"]
            assert [request.session_id for request in resolver.requests] == ["session-1", "session-active"]
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("replacement", ["absent", "revision"])
def test_retry_rejects_replaced_frozen_record_before_more_session_io(replacement):
    async def scenario():
        def configure(owner):
            owner.denied = owner.use.value == "settle"

        attempt, lease, resolver, _ = setup(factory=configure)
        with pytest.raises(AppServiceError):
            await attempt.open()
        lease.record = None if replacement == "absent" else replace(lease.record, record_revision=2)
        with pytest.raises(AppServiceError) as caught:
            await attempt.open()
        assert caught.value.code is AppErrorCodeV1.REVISION_CONFLICT
        assert [request.session_id for request in resolver.requests] == ["session-1"]
        assert not lease.commits
        await attempt.close()

    asyncio.run(scenario())


def test_task_factory_scheduled_without_receipt_cannot_enter_recovery_effects():
    async def scenario():
        attempt, lease, resolver, owners = setup()
        loop = asyncio.get_running_loop()
        original_factory, orphaned = loop.get_task_factory(), []

        def factory(loop, coroutine, **kwargs):
            task = asyncio.Task(coroutine, loop=loop, **kwargs)
            orphaned.append(task)
            raise RuntimeError("scheduled but no receipt")

        loop.set_task_factory(factory)
        try:
            with pytest.raises(AppServiceError):
                await attempt.open()
        finally:
            loop.set_task_factory(original_factory)
        await asyncio.gather(*orphaned, return_exceptions=True)
        assert not resolver.requests and not owners and not lease.commits
        assert attempt._open_task is None
        service = await attempt.open()
        await service.close()

    asyncio.run(scenario())


def test_real_lease_reopen_settles_pending_and_reopens_only_active_afterward(tmp_path):
    from loushang.appservice import JsonFileApplicationContinuityStoreV1

    async def scenario():
        value = mixed_record()
        store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
        lease = await store.acquire(application_id=value.application_id, owner_epoch="before")
        await lease.commit(expected_revision=None, record=value)
        await lease.close()
        lease = await store.acquire(application_id=value.application_id, owner_epoch="after")
        attempt, _, resolver, _ = setup(lease=lease)
        try:
            service = await attempt.open()
            assert [mux.name for mux in (await service.list_muxes()).mux_spaces] == ["active"]
            assert [request.session_id for request in resolver.requests] == ["session-1", "session-active"]
            await service.close()
        finally:
            await attempt.close()
            await lease.close()
        lease = await store.acquire(application_id=value.application_id, owner_epoch="third")
        attempt, _, resolver, _ = setup(lease=lease)
        try:
            paths = tuple((tmp_path / "continuity").glob("*.json"))
            assert len(paths) == 1
            path = paths[0]
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            recovered = await lease.load()
            assert recovered.record_revision == value.record_revision + 1
            assert recovered.managed_closures == (replace(value.managed_closures[0], phase=ManagedMuxClosePhaseV1.CLOSED),)
            service = await attempt.open()
            assert [request.session_id for request in resolver.requests] == ["session-active"]
            await service.close()
            assert (path.read_bytes(), path.stat().st_mtime_ns) == before
        finally:
            await attempt.close()
            await lease.close()

    asyncio.run(scenario())
