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
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from tests.appservice.test_execution_service import fixture
from tests.appservice.test_runtime import FINGERPRINT

from .test_local import _until


@pytest.mark.parametrize("enabled", [False, True])
def test_authenticated_local_record_negotiates_resume_lookup(tmp_path, enabled):
    async def run():
        service, owner, first, second, selector, control, product = await fixture()
        await first.close()
        calls = []

        async def lookup(query):
            calls.append(query)
            return ResumeInputLookupResultV1(query.input_id, "record-1", "committed")

        product.lookup_resume_input = lookup
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server = LocalAppServerV1(
            directory, "workspace", application_id="application", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, FINGERPRINT),),
            scope_factory=owner.open_client_scope,
            execution_scope_factory=owner.open_client_scope,
            resume_input_lookup=enabled,
            request_stop=lambda _: pytest.fail("lookup must not stop the application"),
        )
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            assert client.resume_input_lookup_client is None
            await server.start()
            record = directory.read("workspace")
            assert record.resume_input_lookup is enabled
            assert decode_connection_record(encode_connection_record(record)) == record
            await client.start()
            borrowed = client.resume_input_lookup_client
            assert (borrowed is not None) is enabled
            if enabled:
                assert borrowed is client.execution_client
                attachment = await client.client.attach_mux(MuxAttachV1(selector))
                selected = replace(control, attachment_id=attachment.attachment_id,
                                   controller_generation=attachment.controller_generation)
                query = ResumeInputLookupQueryV1("input-1", "a" * 64)
                assert (await borrowed.lookup_resume_input(selected, "instance", query)).status == "committed"
                assert calls == [query]
            assert owner.pending_counts == (0, 0)
            assert service._execution_registry.active_count == 0
            assert product.legacy_calls == []
            await client.close()
            assert client.resume_input_lookup_client is None
        finally:
            await client.close()
            await server.close()
            await service.close()
            directory.close()

    asyncio.run(asyncio.wait_for(run(), 10))


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
