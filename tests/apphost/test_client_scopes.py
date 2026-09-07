from __future__ import annotations

from itertools import count

import pytest

from loushang.apphost.application import HostedApplicationError
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxSelectorV1,
)

from .test_application import _async_test, _runtime
from .test_continuity import _attempt, _Lease, _record


@_async_test
async def test_scoped_mode_requires_explicit_activation() -> None:
    runtime = _runtime([])
    try:
        with pytest.raises(HostedApplicationError, match="client_scopes_not_enabled"):
            runtime.open_client_scope()
        assert (await runtime.client.list_muxes()).mux_spaces == ()
    finally:
        await runtime.close()


@_async_test
async def test_borrowing_legacy_client_prevents_later_scope_activation() -> None:
    runtime = _runtime([])
    try:
        client = runtime.client
        with pytest.raises(HostedApplicationError, match="client_mode_conflict"):
            runtime.enable_client_scopes()
        assert runtime.client is client
        assert (await client.list_muxes()).mux_spaces == ()
    finally:
        await runtime.close()


@_async_test
async def test_activation_fences_legacy_getter_and_enforces_exclusive_controllers() -> (
    None
):
    ids = count()
    runtime = _runtime([], id_factory=lambda: f"id-{next(ids)}")
    try:
        runtime.enable_client_scopes()
        runtime.enable_client_scopes()  # Same explicit mode, no second owner.
        with pytest.raises(HostedApplicationError, match="client_mode_conflict"):
            _ = runtime.client
        first, second = runtime.open_client_scope(), runtime.open_client_scope()
        mux = await first.create_mux(MuxCreateV1("dev"))
        request = MuxAttachV1(MuxSelectorV1(mux_space_id=mux.mux_space_id))
        attachment = await first.attach_mux(request)
        with pytest.raises(AppServiceError) as raised:
            await second.attach_mux(request)
        assert raised.value.code is AppErrorCodeV1.ALREADY_ATTACHED
        await first.close()
        replacement = await second.attach_mux(request)
        assert replacement.attachment_id != attachment.attachment_id
        assert runtime.accepting
        await second.close()
    finally:
        await runtime.close()


@_async_test
async def test_synchronous_scope_fence_rejects_existing_and_future_clients() -> None:
    events: list[str] = []
    runtime = _runtime(events)
    try:
        runtime.enable_client_scopes()
        client = runtime.open_client_scope()
        runtime.fence_client_scopes()
        assert not runtime.accepting
        assert events == []  # Fence alone does not settle Product owners.
        with pytest.raises(HostedApplicationError, match="not_ready"):
            runtime.open_client_scope()
        with pytest.raises(AppServiceError) as raised:
            await client.create_mux(MuxCreateV1("late"))
        assert raised.value.code is AppErrorCodeV1.SERVICE_CLOSED
        assert events == []
    finally:
        await runtime.close()
    assert events == ["apphost", "product"]


@_async_test
async def test_shutdown_prevents_scope_activation_or_reopening() -> None:
    runtime = _runtime([])
    runtime.enable_client_scopes()
    await runtime.close()
    for operation in (runtime.enable_client_scopes, runtime.open_client_scope):
        with pytest.raises(HostedApplicationError, match="not_ready"):
            operation()


@_async_test
async def test_g13_activates_scopes_only_after_recovery_and_still_releases_lease_last() -> (
    None
):
    events: list[str] = []
    lease = _Lease(events, _record())
    attempt, resolver = _attempt(events, lease)
    runtime = await attempt.open()
    try:
        assert runtime.application_id == lease.application_id
        assert resolver.requests[0].session_id == "session-1"
        runtime.enable_client_scopes()
        scope = runtime.open_client_scope()
        assert (await scope.list_muxes()).mux_spaces[0].name == "dev"
        with pytest.raises(HostedApplicationError, match="client_mode_conflict"):
            _ = runtime.client
        runtime.fence_client_scopes()
        assert not runtime.accepting
        await scope.close()
        assert not lease.closed
        assert events == []
    finally:
        await runtime.close()
    assert events == ["service", "apphost", "product", "lease"]
    assert lease.record is not None
