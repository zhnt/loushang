from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.execution.model import ExecutionStatusV1
from loushang.appserver.local import LocalAppClientConnectionV1, LocalAppServerV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
    decode_connection_record,
    encode_connection_record,
)
from loushang.appserver.protocol import MuxAttachV1, SessionScopeV1
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from tests.appservice.test_execution_service import fixture
from tests.appservice.test_runtime import FINGERPRINT

from .test_local import _until


def test_authenticated_local_execution_reconnect_uses_same_registry_instance(tmp_path):
    async def run():
        service, owner, first, second, selector, control, product = await fixture()
        await first.close()
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server = LocalAppServerV1(
            directory, "workspace", application_id="application", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, FINGERPRINT),),
            scope_factory=owner.open_client_scope,
            execution_scope_factory=owner.open_client_scope,
            request_stop=lambda _: pytest.fail("EOF must not stop the application"),
        )
        old, new = (LocalAppClientConnectionV1(directory, "workspace") for _ in range(2))
        try:
            await server.start()
            record = directory.read("workspace")
            assert record.session_execution
            assert record.semantic_profile is AppConnectionProfileV1.LOCAL_EXECUTION
            assert decode_connection_record(encode_connection_record(record)) == record
            combined = replace(record, session_discovery=True)
            assert decode_connection_record(encode_connection_record(combined)) == combined
            assert combined.semantic_profile is AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION
            await old.start()
            attachment = await old.client.attach_mux(MuxAttachV1(selector))
            selected = replace(control, attachment_id=attachment.attachment_id,
                               controller_generation=attachment.controller_generation)
            accepted = await old.execution_client.submit_execution(selected, "instance", "submission", "silent")
            await product.entered.wait()
            await old.close()
            await _until(lambda: server.connection_counts == (0, 0))
            assert service._execution_registry.active_count == 1
            await new.start()
            attachment = await new.client.attach_mux(MuxAttachV1(selector))
            selected = replace(control, attachment_id=attachment.attachment_id,
                               controller_generation=attachment.controller_generation)
            assert new.execution_client.service_instance_id == "instance"
            recovered = await new.execution_client.find_execution_by_submission(selected, "instance", "submission")
            assert recovered.state.execution_id == accepted.state.execution_id
            assert recovered.state.status is ExecutionStatusV1.RUNNING
            await new.execution_client.interrupt_execution(selected, "instance", accepted.state.execution_id)
            await product.cleaning.wait()
        finally:
            await old.close()
            await new.close()
            await server.close()
            await service.close()
            directory.close()

    asyncio.run(asyncio.wait_for(run(), 10))
