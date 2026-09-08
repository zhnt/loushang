from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionDiscoveryCandidateV1,
    SessionIdentityV1,
    SessionListV1,
    SessionScopeV1,
)
from loushang.appservice import AppServiceV1, InProcessAppClientV1
from loushang.appservice.client_scope import ScopedAppServiceV1
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryBindingV1,
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)
from loushang.appservice.ports import (
    HostedSessionResolutionErrorV1,
    HostedSessionResolutionFailureV1,
)
from loushang.appservice.session_discovery import SessionDiscoveryOwnerV1

from .test_runtime import _mux_with_member, _Resolver, _spec

CWD = HostedSessionDiscoveryScopeV1("coding", SessionScopeV1.CWD, "a" * 64)
HOME = HostedSessionDiscoveryScopeV1("coding", SessionScopeV1.USER_HOME, "b" * 64)


def _query(scope=CWD, **kwargs):
    return SessionListV1(scope.product_id, scope.scope, scope.scope_fingerprint, **kwargs)


def _rows(scope=CWD, size=5):
    return tuple(SessionDiscoveryCandidateV1(
        SessionIdentityV1("coding", "continuity", f"s-{i}", scope.scope,
                          scope.scope_fingerprint),
        f"Session {i}", SessionCompatibilityV1.COMPATIBLE,
        SessionAvailabilityV1.AVAILABLE,
    ) for i in range(size))


class _Product:
    def __init__(self):
        self.requests = []
        self.entered = asyncio.Queue()
        self.release = asyncio.Event()
        self.release.set()
        self.stops = []

    async def discover_sessions(self, scope, *, stop):
        self.requests.append(scope)
        self.stops.append(stop)
        self.entered.put_nowait(scope)
        await self.release.wait()
        return HostedSessionDiscoverySnapshotV1(scope, _rows(scope), True)


def _binding(product, generation="generation-1"):
    return HostedSessionDiscoveryBindingV1(generation, (CWD, HOME), product)


def test_G17_DISCOVERY_pages_are_stable_replayable_and_scope_bound():
    async def scenario():
        product = _Product()
        now = [0.0]
        owner = SessionDiscoveryOwnerV1(_binding(product), clock=lambda: now[0])
        first, second = owner.open_view(), owner.open_view()
        page = await first.list_sessions(_query(limit=2))
        assert len(page.candidates) == 2 and page.complete and page.continuation
        continued = _query(limit=1, continuation=page.continuation)
        next_page = await first.list_sessions(continued)
        assert next_page == await first.list_sessions(continued)
        assert next_page.candidates == _rows()[2:3]
        assert len(product.requests) == 1
        for view, request in (
            (second, continued),
            (first, _query(HOME, continuation=page.continuation)),
        ):
            with pytest.raises(AppServiceError) as error:
                await view.list_sessions(request)
            assert error.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
        await first.list_sessions(_query(HOME))
        assert await first.list_sessions(continued) == next_page
        now[0] = 60.0
        with pytest.raises(AppServiceError) as error:
            await first.list_sessions(continued)
        assert error.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
        assert len(product.requests) == 2  # Expiry never restarts a scan.
        await owner.close()
    asyncio.run(scenario())


def test_G17_DISCOVERY_refresh_and_new_generation_invalidate_cursors():
    async def scenario():
        product = _Product()
        owner = SessionDiscoveryOwnerV1(_binding(product))
        view = owner.open_view()
        old = await view.list_sessions(_query(limit=1))
        fresh = await view.list_sessions(_query(limit=1))
        assert fresh.snapshot_id != old.snapshot_id
        replacement = SessionDiscoveryOwnerV1(_binding(product, "generation-2"))
        for target in (view, replacement.open_view()):
            with pytest.raises(AppServiceError) as error:
                await target.list_sessions(_query(continuation=old.continuation))
            assert error.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
        await owner.close()
        await replacement.close()
    asyncio.run(scenario())


def test_G17_DISCOVERY_old_completed_scan_cannot_overwrite_new_refresh(monkeypatch):
    async def scenario():
        owner = SessionDiscoveryOwnerV1(_binding(_Product()))
        view = owner.open_view()
        entered, release = asyncio.Event(), asyncio.Event()
        original = asyncio.wait
        first = None

        async def pause_publication(*args, **kwargs):
            result = await original(*args, **kwargs)
            if asyncio.current_task() is first:
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(asyncio, "wait", pause_publication)
        first = asyncio.create_task(view.list_sessions(_query(limit=1)))
        try:
            await entered.wait()
            assert owner.pending_count == 0
            newer = await view.list_sessions(_query(limit=1))
            release.set()
            with pytest.raises(AppServiceError) as stale:
                await first
            assert stale.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
            next_page = await view.list_sessions(_query(continuation=newer.continuation))
            assert next_page.snapshot_id == newer.snapshot_id
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            await owner.close()
    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize("changes", [{"product_id": "work"},
                                    {"scope_fingerprint": "c" * 64}])
def test_G17_AUTHORITY_rejects_scope_before_product_call(changes):
    async def scenario():
        product = _Product()
        owner = SessionDiscoveryOwnerV1(_binding(product))
        with pytest.raises(AppServiceError) as error:
            await owner.open_view().list_sessions(replace(_query(), **changes))
        assert error.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
        assert not product.requests
        await owner.close()
    asyncio.run(scenario())


def test_G17_DISCOVERY_cancel_and_close_do_not_release_unfinished_scan_slots():
    async def scenario():
        product = _Product()
        product.release.clear()
        owner = SessionDiscoveryOwnerV1(_binding(product), close_timeout=0.01)
        first, second, third = (owner.open_view() for _ in range(3))
        tasks = [asyncio.create_task(view.list_sessions(_query()))
                 for view in (first, second)]
        await product.entered.get()
        await product.entered.get()
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        first.fence()
        assert owner.pending_count == 2
        assert product.stops[0]()
        with pytest.raises(AppServiceError) as busy:
            await third.list_sessions(_query())
        assert busy.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        with pytest.raises(AppServiceError) as debt:
            await owner.close()
        assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert owner.pending_count == 2
        product.release.set()
        with pytest.raises(AppServiceError) as closed:
            await tasks[1]
        assert closed.value.code is AppErrorCodeV1.SERVICE_CLOSED
        await owner.close()
        assert owner.pending_count == 0
    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G17_DISCOVERY_timeout_retains_work_and_prevents_late_publication():
    async def scenario():
        product = _Product()
        product.release.clear()
        owner = SessionDiscoveryOwnerV1(_binding(product), scan_timeout=0.01)
        view = owner.open_view()
        with pytest.raises(AppServiceError) as expired:
            await view.list_sessions(_query())
        assert expired.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert owner.pending_count == 1 and product.stops[0]()
        with pytest.raises(AppServiceError):
            await view.list_sessions(_query())
        product.release.set()
        await owner.close()
        assert owner.pending_count == 0
    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G17_DISCOVERY_scope_clients_do_not_share_paging_or_stop_application():
    async def scenario():
        product = _Product()
        service = AppServiceV1(product_id="coding", resolver=_Resolver(),
                               discovery=_binding(product))
        legacy = InProcessAppClientV1(service)
        assert legacy.discovery_client is not None
        await legacy.discovery_client.list_sessions(_query())
        scopes = ScopedAppServiceV1(service)
        assert legacy.discovery_client is None
        first, second = scopes.open_client_scope(), scopes.open_client_scope()
        assert first.discovery_client is not None and second.discovery_client is not None
        page = await first.discovery_client.list_sessions(_query(limit=1))
        with pytest.raises(AppServiceError):
            await second.discovery_client.list_sessions(_query(continuation=page.continuation))
        borrowed = first.discovery_client
        await first.close()
        with pytest.raises(AppServiceError) as closed:
            await borrowed.list_sessions(_query())
        assert closed.value.code is AppErrorCodeV1.SERVICE_CLOSED
        assert await second.discovery_client.list_sessions(_query())
        await service.close()
    asyncio.run(scenario())


def test_G17_DISCOVERY_absent_port_is_an_unchanged_legacy_configuration():
    async def scenario():
        service = AppServiceV1(product_id="coding", resolver=_Resolver())
        assert InProcessAppClientV1(service).discovery_client is None
        scopes = ScopedAppServiceV1(service)
        assert scopes.open_client_scope().discovery_client is None
        await service.close()
    asyncio.run(scenario())


def test_G17_DISCOVERY_scoped_application_fence_revokes_borrowed_discovery():
    async def scenario():
        product = _Product()
        service = AppServiceV1(product_id="coding", resolver=_Resolver(), discovery=_binding(product))
        scoped = ScopedAppServiceV1(service)
        client = scoped.open_client_scope()
        borrowed = client.discovery_client
        scoped.fence()
        assert borrowed is not None
        with pytest.raises(AppServiceError):
            await borrowed.list_sessions(_query())
        assert not product.requests
        await service.close()
    asyncio.run(scenario())


def test_G17_DISCOVERY_pending_scan_settles_before_product_sessions_close():
    async def scenario():
        product, resolver = _Product(), _Resolver()
        product.release.clear()
        # Verify release/close ordering, not a sub-tick scheduling deadline.
        service = AppServiceV1(product_id="coding", resolver=resolver,
                               discovery=_binding(product), close_timeout_seconds=0.1)
        await _mux_with_member(InProcessAppClientV1(service))
        view = service.discovery_client
        assert view is not None
        query = asyncio.create_task(view.list_sessions(_query()))
        await product.entered.get()
        try:
            with pytest.raises(AppServiceError) as pending:
                await service.close()
            assert pending.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert resolver.sessions[0].closed == 0
            assert service._cleanup_debt
            product.release.set()
            with pytest.raises(AppServiceError):
                await query
            await service.close()
            assert resolver.sessions[0].closed == 1
        finally:
            product.release.set()
            await asyncio.gather(query, return_exceptions=True)
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure,expected", [
    (HostedSessionResolutionErrorV1(HostedSessionResolutionFailureV1.MISSING), AppErrorCodeV1.NOT_FOUND),
    (HostedSessionResolutionErrorV1(HostedSessionResolutionFailureV1.UNAVAILABLE), AppErrorCodeV1.SESSION_UNAVAILABLE),
    (ValueError("private-sentinel"), AppErrorCodeV1.SESSION_UNAVAILABLE),
])
def test_G17_AUTHORITY_maps_only_exact_typed_missing(failure, expected):
    class Resolver:
        async def open_session(self, _request):
            raise failure
    async def scenario():
        service = AppServiceV1(product_id="coding", resolver=Resolver())
        await service.create_mux(MuxCreateV1("dev"))
        try:
            with pytest.raises(AppServiceError) as error:
                await service.open_member(MuxMemberOpenV1(MuxSelectorV1(name="dev"), _spec()))
            assert error.value.code is expected
            assert "sentinel" not in str(error.value)
        finally:
            await service.close()
    asyncio.run(scenario())
