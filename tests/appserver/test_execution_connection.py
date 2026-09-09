from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.execution.model import (
    ExecutionServiceErrorV1,
    ExecutionStatusV1,
)
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from tests.appservice.test_execution_guard import scenario
from tests.appservice.test_execution_service import fixture

from .test_connection import _pair


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
