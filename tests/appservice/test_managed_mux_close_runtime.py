from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
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
from loushang.appservice.managed_mux_close import (
    ManagedMuxCloseBindingV1,
    ManagedMuxCloseUseV1,
)
from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver
from tests.appservice.test_managed_mux import INSTANCE, SERVICE, _binding, _request


class Admission:
    def __init__(self, request, use, events, stopped):
        self.request, self.use, self.events, self.stopped = request, use, events, stopped
        self.acquired = False

    async def acquire(self):
        if self.request.authority != "close-secret" or (
            self.use is ManagedMuxCloseUseV1.ADMIT and self.stopped[0]
        ):
            raise RuntimeError("denied")
        self.acquired = True
        self.events.append(("acquire", self.use))

    def check_closure(self, creation, previous):
        assert self.acquired and creation.operation_id == self.request.creation_operation_id
        if self.use is ManagedMuxCloseUseV1.SETTLE:
            assert previous is not None
        return self.request.instance_id if previous is None else previous.instance_id

    async def close(self):
        self.acquired = False
        self.events.append(("release", self.use))


async def opened(lease=None, *, timeout=1, discovery=None):
    lease = lease or _MemoryLease()
    events, admissions, stopped = [], [], [False]
    resolver = _Resolver(events)

    def prepare(request, use):
        owner = Admission(request, use, events, stopped)
        admissions.append(owner)
        return owner

    binding = replace(_binding([]), closing=ManagedMuxCloseBindingV1(prepare))
    attempt = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
        "coding", resolver, lease, managed_mux=binding, close_timeout_seconds=timeout, discovery=discovery,
    ))
    service = await attempt.open()
    created = await service.create_managed_mux(_request())
    request = ManagedMuxCloseV1(SERVICE, INSTANCE, "d" * 32, created.operation_id,
                                created.name, created.mux_space_id, "close-secret")
    return service, lease, resolver, events, admissions, stopped, request


async def member(service, request, title="one", *, session_id=None):
    return await service.open_member(MuxMemberOpenV1(
        MuxSelectorV1(mux_space_id=request.mux_space_id),
        SessionOpenSpecV1("coding", "continuity-1", SessionScopeV1.CWD, "a" * 64, title, session_id=session_id),
    ))


def test_close_empty_mux_commits_pending_then_closed_and_queries_are_readonly():
    async def scenario():
        service, lease, resolver, events, admissions, _, request = await opened()
        try:
            assert await service.read_managed_mux_close(request) is None
            before = len(lease.commits)
            result = await service.close_managed_mux(request)
            assert result.phase is ManagedMuxClosePhaseV1.CLOSED
            assert [item.managed_closures[0].phase for item in lease.commits[before:]] == [
                ManagedMuxClosePhaseV1.CLEANUP_PENDING, ManagedMuxClosePhaseV1.CLOSED,
            ]
            assert not lease.record.mux_spaces and not (await service.list_muxes()).mux_spaces
            for _ in range(2):
                assert await service.read_managed_mux_close(request) == result
            assert len(lease.commits) == before + 2 and not resolver.sessions
            assert all(not owner.acquired for owner in admissions)
            assert await service.close_managed_mux(request) == result
            assert len(lease.commits) == before + 2
        finally:
            await service.close()

    asyncio.run(scenario())


def test_pending_hidden_but_retained_across_unrelated_commit_and_cancelled_waiter():
    async def scenario():
        service, lease, resolver, events, admissions, _, request = await opened()
        await member(service, request)
        entered, release = asyncio.Event(), asyncio.Event()
        original = resolver.sessions[0].close

        async def held():
            assert not service._state_lock.locked()
            assert all(not owner.acquired for owner in admissions)
            entered.set()
            await release.wait()
            await original()

        resolver.sessions[0].close = held
        closing = asyncio.create_task(service.close_managed_mux(request))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert not (await service.list_muxes()).mux_spaces
            snapshot = lease.record.mux_spaces[0]
            pending = await service.read_managed_mux_close(request)
            assert pending.phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
            commits = len(lease.commits)
            assert await service.read_managed_mux_close(request) == pending
            assert len(lease.commits) == commits
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            other = await service.create_managed_mux(_request(name="other", operation_id="e" * 32))
            assert snapshot in lease.record.mux_spaces
            assert lease.record.managed_closures == (pending,)
            assert [mux.mux_space_id for mux in (await service.list_muxes()).mux_spaces] == [other.mux_space_id]
        finally:
            release.set()
            await service.close()
            await asyncio.gather(closing, return_exceptions=True)
        assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLOSED
        assert events.count("close:session-1") == 1

    asyncio.run(scenario())


def test_partial_cleanup_retries_only_original_unsettled_member():
    async def scenario():
        service, lease, resolver, events, _, _, request = await opened()
        await member(service, request, "one")
        await member(service, request, "two")
        resolver.sessions[1]._fail_close_once = True
        try:
            with pytest.raises(AppServiceError) as error:
                await service.close_managed_mux(request)
            assert error.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert (await service.read_managed_mux_close(request)).phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
            assert lease.record.mux_spaces[0].members
            assert (await service.close_managed_mux(request)).phase is ManagedMuxClosePhaseV1.CLOSED
            assert events.count("close:session-1") == 1
            assert events.count("close:session-2") == 2
        finally:
            await service.close()

    asyncio.run(scenario())


def test_stop_fences_new_close_but_joins_original_settlement_without_double_cleanup():
    async def scenario():
        service, lease, resolver, events, _, stopped, request = await opened()
        await member(service, request)
        other = await service.create_managed_mux(_request(name="other", operation_id="e" * 32))
        other_request = replace(request, name=other.name, mux_space_id=other.mux_space_id,
                                creation_operation_id=other.operation_id, operation_id="f" * 32)
        entered, release = asyncio.Event(), asyncio.Event()
        original = resolver.sessions[0].close

        async def held():
            entered.set()
            await release.wait()
            await original()

        resolver.sessions[0].close = held
        closing = asyncio.create_task(service.close_managed_mux(request))
        stopping = None
        try:
            await asyncio.wait_for(entered.wait(), 2)
            stopped[0] = True
            stopping = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            assert service._managed_shutdown and not stopping.done()
            commits = len(lease.commits)
            with pytest.raises(AppServiceError):
                await service.close_managed_mux(other_request)
            assert len(lease.commits) == commits
            assert [item.operation_id for item in lease.record.managed_closures] == [request.operation_id]
            release.set()
            assert (await closing).phase is ManagedMuxClosePhaseV1.CLOSED
            await asyncio.wait_for(stopping, 2)
            assert events.count("close:session-1") == 1
        finally:
            release.set()
            await service.close()
            await asyncio.gather(closing, *([stopping] if stopping else []), return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", [ManagedMuxClosePhaseV1.CLEANUP_PENDING, ManagedMuxClosePhaseV1.CLOSED])
def test_unknown_commit_never_reports_closed_or_discards_original_owners(phase):
    class LostReceipt(_MemoryLease):
        async def commit(self, *, expected_revision, record):
            await super().commit(expected_revision=expected_revision, record=record)
            if record.managed_closures and record.managed_closures[0].phase is phase:
                raise RuntimeError("private write acknowledgement lost")

    async def scenario():
        service, lease, resolver, events, admissions, _, request = await opened(LostReceipt())
        await member(service, request)
        with pytest.raises(AppServiceError):
            await service.close_managed_mux(request)
        assert service._managed_uncertain
        assert lease.record.managed_closures[0].phase is phase
        assert events.count("close:session-1") == (1 if phase is ManagedMuxClosePhaseV1.CLOSED else 0)
        for call in (lambda: service.read_managed_mux_close(request),
                     lambda: service.close_managed_mux(request), service.close):
            with pytest.raises(AppServiceError):
                await call()
        assert all(not owner.acquired for owner in admissions)
        assert service._managed_closing_muxes or service._sessions
        # The application deliberately retains unresolved durable debt. Settle
        # only fake member resources for test teardown, without clearing it.
        await service._close_sessions(tuple(service._sessions.values()))

    asyncio.run(scenario())


def test_task_factory_failure_after_pending_retains_members_for_explicit_retry():
    async def scenario():
        service, lease, resolver, events, _, _, request = await opened()
        await member(service, request)
        loop = asyncio.get_running_loop()
        original_factory = loop.get_task_factory()

        def factory(loop, coroutine, **kwargs):
            operation = coroutine.cr_frame.f_locals.get("operation")
            code = getattr(operation, "__code__", None)
            if code is not None and "_settle_managed_close" in code.co_names:
                raise RuntimeError("injected publication failure")
            return asyncio.Task(coroutine, loop=loop, **kwargs)

        try:
            loop.set_task_factory(factory)
            with pytest.raises(AppServiceError):
                await service.close_managed_mux(request)
            assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
            assert not (await service.list_muxes()).mux_spaces
            pending = service._managed_closing_muxes[request.operation_id]
            assert pending.task is None and len(pending.sessions) == 1
            assert not events.count("close:session-1")
            loop.set_task_factory(original_factory)
            assert (await service.close_managed_mux(request)).phase is ManagedMuxClosePhaseV1.CLOSED
            assert events.count("close:session-1") == 1
        finally:
            loop.set_task_factory(original_factory)
            await service.close()

    asyncio.run(scenario())


def test_cancellation_during_pending_commit_still_publishes_retained_cleanup():
    class PausedLease(_MemoryLease):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def commit(self, *, expected_revision, record):
            await super().commit(expected_revision=expected_revision, record=record)
            if record.managed_closures and record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING:
                self.entered.set()
                await self.release.wait()

    async def scenario():
        lease = PausedLease()
        service, _, resolver, events, _, _, request = await opened(lease)
        await member(service, request)
        closing = asyncio.create_task(service.close_managed_mux(request))
        try:
            await asyncio.wait_for(lease.entered.wait(), 2)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
            lease.release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            await service.close()
            assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLOSED
            assert events.count("close:session-1") == 1
        finally:
            lease.release.set()
            await service.close()
            await asyncio.gather(closing, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["name", "mux_space_id", "creation_operation_id", "instance_id", "authority"])
def test_close_requires_exact_target_and_purpose_specific_permission(mutation):
    async def scenario():
        service, lease, _, events, _, _, request = await opened()
        before = len(lease.commits)
        value = "e" * 32 if mutation.endswith("_id") and mutation != "mux_space_id" else "wrong"
        try:
            with pytest.raises(AppServiceError):
                await service.close_managed_mux(replace(request, **{mutation: value}))
            assert len(lease.commits) == before and (await service.list_muxes()).mux_spaces
        finally:
            await service.close()

    asyncio.run(scenario())


def test_cancelled_admission_release_cannot_strand_durable_close(monkeypatch):
    async def scenario():
        service, lease, resolver, events, _, _, request = await opened()
        await member(service, request)
        entered, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_release, original_close = Admission.close, resolver.sessions[0].close

        async def held(owner):
            if owner.use is ManagedMuxCloseUseV1.ADMIT:
                entered.set()
                await release.wait()
            await original_release(owner)

        async def closed():
            await original_close()
            cleaned.set()

        monkeypatch.setattr(Admission, "close", held)
        resolver.sessions[0].close = closed
        closing = asyncio.create_task(service.close_managed_mux(request))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
            closing.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            # No second close request/service shutdown may start this cleanup.
            await asyncio.wait_for(cleaned.wait(), 2)
            assert events.count("close:session-1") == 1
        finally:
            release.set()
            await service.close()
            await asyncio.gather(closing, return_exceptions=True)

    asyncio.run(scenario())


def test_pending_snapshot_reserves_even_already_cleaned_member_identity():
    async def scenario():
        service, lease, resolver, events, _, _, request = await opened()
        await member(service, request, "one")
        await member(service, request, "two")
        resolver.sessions[1]._fail_close_once = True
        other = await service.create_managed_mux(_request(name="other", operation_id="e" * 32))
        other_request = replace(request, mux_space_id=other.mux_space_id,
                                creation_operation_id=other.operation_id, operation_id="f" * 32, name=other.name)
        try:
            with pytest.raises(AppServiceError):
                await service.close_managed_mux(request)
            with pytest.raises(AppServiceError) as error:
                await member(service, other_request, session_id="session-1")
            assert error.value.code is AppErrorCodeV1.ALREADY_EXISTS
            assert (await service.close_managed_mux(request)).phase is ManagedMuxClosePhaseV1.CLOSED
            opened_mux = await member(service, other_request, session_id="session-1")
            assert opened_mux.members[0].session.session_id == "session-1"
        finally:
            await service.close()

    asyncio.run(scenario())


def test_shutdown_fences_borrowed_discovery_before_waiting_for_close():
    from loushang.appservice.client_scope import ScopedAppServiceV1
    from tests.appservice.test_session_discovery import _binding as discovery_binding
    from tests.appservice.test_session_discovery import _Product, _query

    async def scenario():
        product = _Product()
        service, _, resolver, _, _, _, request = await opened(discovery=discovery_binding(product))
        scoped = ScopedAppServiceV1(service)
        scope = scoped.open_client_scope()
        view = scope.discovery_client
        await view.list_sessions(_query())
        await member(service, request)
        entered, release = asyncio.Event(), asyncio.Event()
        original = resolver.sessions[0].close

        async def held():
            entered.set()
            await release.wait()
            await original()

        resolver.sessions[0].close = held
        closing = asyncio.create_task(service.close_managed_mux(request))
        stopping = None
        try:
            await asyncio.wait_for(entered.wait(), 2)
            stopping = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            assert service._managed_shutdown and not stopping.done()
            before = len(product.requests)
            with pytest.raises(AppServiceError):
                await view.list_sessions(_query())
            with pytest.raises(AppServiceError):
                _ = scope.managed_mux_client
            assert len(product.requests) == before
        finally:
            release.set()
            await service.close()
            await asyncio.gather(closing, *([stopping] if stopping else []), return_exceptions=True)

    asyncio.run(scenario())


def test_concurrent_targets_preserve_each_other_and_duplicate_waiter_joins_original(monkeypatch):
    async def scenario():
        service, lease, resolver, events, _, _, first = await opened()
        await member(service, first)
        created = await service.create_managed_mux(_request(name="other", operation_id="e" * 32))
        second = replace(first, name=created.name, mux_space_id=created.mux_space_id,
                         creation_operation_id=created.operation_id, operation_id="f" * 32)
        await member(service, second)
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        replay_admitted = asyncio.Event()
        original_check = Admission.check_closure

        def checked(owner, creation, previous):
            origin = original_check(owner, creation, previous)
            if owner.use is ManagedMuxCloseUseV1.ADMIT and previous is not None:
                replay_admitted.set()
            return origin

        monkeypatch.setattr(Admission, "check_closure", checked)
        for index, session in enumerate(resolver.sessions):
            original = session.close

            async def held(index=index, original=original):
                entered[index].set()
                await release[index].wait()
                await original()

            session.close = held
        tasks = [asyncio.create_task(service.close_managed_mux(request)) for request in (first, second)]
        duplicate = None
        try:
            await asyncio.wait_for(asyncio.gather(*(item.wait() for item in entered)), 2)
            assert len(lease.record.managed_closures) == 2 and len(lease.record.mux_spaces) == 2
            second_snapshot = next(item for item in lease.record.mux_spaces if item.mux_space_id == second.mux_space_id)
            original_task = service._managed_closing_muxes[first.operation_id].task
            duplicate = asyncio.create_task(service.close_managed_mux(first))
            await asyncio.wait_for(replay_admitted.wait(), 2)
            assert service._managed_closing_muxes[first.operation_id].task is original_task
            release[0].set()
            results = await asyncio.wait_for(asyncio.gather(tasks[0], duplicate), 2)
            assert results[0] == results[1] and results[0].phase is ManagedMuxClosePhaseV1.CLOSED
            phases = {item.operation_id: item.phase for item in lease.record.managed_closures}
            assert phases == {first.operation_id: ManagedMuxClosePhaseV1.CLOSED,
                              second.operation_id: ManagedMuxClosePhaseV1.CLEANUP_PENDING}
            assert lease.record.mux_spaces == (second_snapshot,)
            release[1].set()
            assert (await tasks[1]).phase is ManagedMuxClosePhaseV1.CLOSED
            assert events.count("close:session-1") == events.count("close:session-2") == 1
        finally:
            for gate in release:
                gate.set()
            await service.close()
            await asyncio.gather(*tasks, *([duplicate] if duplicate else []), return_exceptions=True)

    asyncio.run(scenario())


def test_failed_admission_release_keeps_original_and_does_not_start_cleanup(monkeypatch):
    async def scenario():
        service, lease, resolver, events, admissions, _, request = await opened()
        await member(service, request)
        original = Admission.close
        attempts = []

        async def fail_once(owner):
            attempts.append(owner)
            if len(attempts) == 1:
                raise RuntimeError("original permission release failed")
            await original(owner)

        monkeypatch.setattr(Admission, "close", fail_once)
        with pytest.raises(AppServiceError) as error:
            await service.close_managed_mux(request)
        assert error.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        original_owner = admissions[0]
        assert service._managed_admission is original_owner and original_owner.acquired
        assert service._managed_closing_muxes[request.operation_id].task is None
        assert events.count("close:session-1") == 0
        await service.close()
        assert attempts[0] is attempts[1] is original_owner
        assert events.count("close:session-1") == 1
        assert lease.record.managed_closures[0].phase is ManagedMuxClosePhaseV1.CLOSED

    asyncio.run(scenario())
