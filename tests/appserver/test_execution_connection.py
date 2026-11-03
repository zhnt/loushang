from __future__ import annotations

import asyncio
from unittest.mock import create_autospec

import pytest

from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.execution.model import (
    ExecutionCallV1,
    ExecutionOperationV1,
    ExecutionServiceErrorV1,
    ExecutionStatusV1,
)
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.managed_mux import ManagedMuxCreationClientV1
from loushang.appserver.managed_mux_close import ManagedMuxCloseClientV1
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    supports_managed_mux,
    supports_managed_mux_close,
)
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from tests.appservice.test_execution_guard import scenario
from tests.appservice.test_execution_service import fixture

from .test_connection import _pair


@pytest.mark.parametrize("profile", [
    AppConnectionProfileV1.LOCAL_EXECUTION,
    AppConnectionProfileV1.LOCAL_RESUME_EXECUTION,
    AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION,
    AppConnectionProfileV1.LOCAL_RESUME_EXECUTION_MANAGED,
    AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED,
    AppConnectionProfileV1.LOCAL_RESUME_EXECUTION_MANAGED_CLOSE,
    AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED_CLOSE,
])
def test_resume_lookup_is_negotiated_and_reaches_the_existing_scoped_owner(profile):
    async def run():
        service, owner, first, second, selector, control, product = await fixture()
        calls = []

        async def lookup(query):
            calls.append(query)
            return ResumeInputLookupResultV1(query.input_id, "record-1", "committed")

        product.lookup_resume_input = lookup
        enabled = profile is not AppConnectionProfileV1.LOCAL_EXECUTION
        left, right = _pair()
        server = AppServerConnectionV1(
            first, AppFramedStreamV1(right), profile=profile, execution=first.execution_client,
            managed_mux=(create_autospec(ManagedMuxCreationClientV1, instance=True)
                         if supports_managed_mux(profile) else None),
            managed_mux_close=(create_autospec(ManagedMuxCloseClientV1, instance=True)
                               if supports_managed_mux_close(profile) else None),
        )
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        query = ResumeInputLookupQueryV1("input-1", "a" * 64)
        try:
            await remote.start()
            client = remote.execution_client
            assert client.resume_input_lookup_available is enabled
            assert remote.resume_input_lookup_client is (client if enabled else None)
            if enabled:
                assert (await client.lookup_resume_input(control, "instance", query)).status == "committed"
                assert calls == [query]
                with pytest.raises(ExecutionServiceErrorV1):
                    await client.lookup_resume_input(control, "different-instance", query)
            else:
                with pytest.raises(AppServiceError) as unsupported:
                    await client.lookup_resume_input(control, "instance", query)
                assert unsupported.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
                # A peer manually encoding the new operation cannot bypass the
                # negotiated profile or reach the Product on an old profile.
                with pytest.raises(AppServiceError) as unsupported_wire:
                    await remote._send_execution(
                        lambda request_id: ExecutionCallV1(
                            request_id, ExecutionOperationV1.RESUME_INPUT_LOOKUP,
                            control, "instance", resume_query=query,
                        ), ResumeInputLookupResultV1, True, False,
                    )
                assert unsupported_wire.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
                assert calls == []
            assert owner.pending_counts == (0, 0)
            assert product.legacy_calls == []
            assert (await remote.list_muxes()).mux_spaces
        finally:
            await remote.close()
            await serving
            await service.close()

    asyncio.run(run())


@scenario
async def test_optional_execution_connection_submit_snapshot_interrupt_and_old_operations():
    service, owner, first, second, selector, control, product = await fixture()
    left, right = _pair()
    server = AppServerConnectionV1(
        first, AppFramedStreamV1(right), profile=AppConnectionProfileV1.LOCAL_EXECUTION,
        execution=first.execution_client,
    )
    remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=AppConnectionProfileV1.LOCAL_EXECUTION)
    serving = asyncio.create_task(server.serve())
    try:
        assert remote.execution_client is None
        await remote.start()
        client = remote.execution_client
        assert client.service_instance_id == "instance"
        assert (await remote.list_muxes()).mux_spaces
        record = await client.submit_execution(control, "instance", "submission", "silent")
        await product.entered.wait()
        found = await client.find_execution_by_submission(control, "instance", "submission")
        assert found.state.execution_id == record.state.execution_id
        snapshot = await client.snapshot_execution_session(control, "instance")
        assert snapshot.executions.active.status is ExecutionStatusV1.RUNNING
        result = await client.interrupt_execution(control, "instance", record.state.execution_id)
        assert result.record.state.interrupt_requested or result.record.state.status.terminal
        await service._execution_registry.wait(service._sessions[product.identity.session_id]._execution, record)
        finished = await client.get_execution(control, "instance", record.state.execution_id)
        assert finished.state.status is ExecutionStatusV1.INTERRUPTED
        assert await client.read_execution_events(control, "instance")
        with pytest.raises(ExecutionServiceErrorV1) as stale:
            await client.submit_execution(control, "other-instance", "submission", "different")
        assert str(stale.value) == "service_instance_changed"
    finally:
        await remote.close()
        await serving
        await service.close()


@scenario
async def test_execution_requires_explicit_profile_and_injected_capability():
    service, owner, first, second, selector, control, product = await fixture()
    left, right = _pair()
    with pytest.raises(ValueError):
        AppServerConnectionV1(first, AppFramedStreamV1(right), profile=AppConnectionProfileV1.LOCAL_EXECUTION)
    with pytest.raises(ValueError):
        AppServerConnectionV1(first, AppFramedStreamV1(right), execution=first.execution_client)
    await service.close()
