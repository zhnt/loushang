"""Explicit close negotiation, strict receipt transport and retained delivery."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from loushang.appserver import managed_mux_wire as wire
from loushang.appserver.framing import AppConnectionClosedError, AppFramedStreamV1
from loushang.appserver.local import LocalAppServerV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
)
from loushang.appserver.managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)
from loushang.appserver.protocol import (
    AppFailureV1,
    AppResponseV1,
    InvalidAppMessageError,
    SessionScopeV1,
)
from loushang.appserver.protocol import encode_response as encode_app_response
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    connection_hello,
)
from loushang.appserver.remote_client import RemoteAppClientV1
from tests.appserver.test_connection import _pair
from tests.appserver.test_local import _until


def request():
    return ManagedMuxCloseV1("a" * 64, "b" * 32, "c" * 32, "d" * 32, "dev", "mux-1", "secret")


def state(*, phase=ManagedMuxClosePhaseV1.CLOSED):
    value = request()
    return ManagedMuxCloseStateV1(value.operation_id, "e" * 32, value.creation_operation_id,
                                  value.name, value.mux_space_id, phase)


@pytest.mark.parametrize("read", [False, True])
def test_close_and_lookup_are_distinct_bounded_calls(read):
    call = wire.ManagedMuxCloseCallV1("1", request(), read_result=read)
    assert wire.decode_close_call(wire.encode_close_call(call)) == call
    assert "secret" not in repr(call)
    assert len(wire.encode_close_call(call)) <= wire.MAX_MANAGED_MUX_FRAME
    with pytest.raises(InvalidAppMessageError):
        wire.decode_call(wire.encode_close_call(call))


@pytest.mark.parametrize("result", [None, state(), state(phase=ManagedMuxClosePhaseV1.CLEANUP_PENDING)])
def test_close_response_preserves_historical_origin_without_authority(result):
    response = wire.ManagedMuxCloseResponseV1("1", result)
    encoded = wire.encode_close_response(response)
    assert wire.decode_close_response(encoded) == response
    assert b"secret" not in encoded and b"authority" not in encoded


@pytest.mark.parametrize("mutation", [
    {"extra": True}, {"protocolVersion": "loushang.managed-mux/v1"},
    {"operation": "mux/create"}, {"requestId": True}, {"request": None},
])
def test_close_wire_rejects_foreign_fields_and_operations(mutation):
    encoded = wire.encode_close_call(wire.ManagedMuxCloseCallV1("1", request()))
    raw = json.loads(encoded)
    with pytest.raises(InvalidAppMessageError):
        wire.decode_close_call(json.dumps(raw | mutation).encode())


def test_close_wire_rejects_duplicate_keys_and_oversize_frames():
    encoded = wire.encode_close_call(wire.ManagedMuxCloseCallV1("1", request()))
    with pytest.raises(InvalidAppMessageError):
        wire.decode_close_call(encoded.replace(b'"requestId":"1"', b'"requestId":"1","requestId":"2"'))
    with pytest.raises(InvalidAppMessageError):
        wire.decode_close_call(encoded + b" " * 4096)


@pytest.mark.parametrize("field,value", [
    ("operation_id", "f" * 32), ("creation_operation_id", "f" * 32),
    ("name", "other"), ("mux_space_id", "other"), ("none", None), ("family", None),
])
def test_cancelled_waiter_does_not_bypass_close_response_validation(field, value):
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        profile = AppConnectionProfileV1.LOCAL_MANAGED_CLOSE
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        hello = connection_hello(profile)
        await frames.send(hello)
        await remote.start()
        assert await frames.receive() == hello
        waiter = asyncio.create_task(remote.close_managed_mux(request()))
        try:
            call = wire.decode_close_call(await frames.receive())
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert len(remote._pending) == 1
            if field == "family":
                from loushang.appserver.protocol import AppErrorCodeV1
                payload = encode_app_response(AppResponseV1(call.request_id, AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE)))
            else:
                result = None if field == "none" else replace(state(), **{field: value})
                payload = wire.encode_close_response(wire.ManagedMuxCloseResponseV1(call.request_id, result))
            await frames.send(payload)
            await _until(lambda: not remote._pending)
            assert remote.managed_mux_close_client is None and remote._counts == {False: 0, True: 0}
        finally:
            await remote.close()
            await frames.close()
    asyncio.run(asyncio.wait_for(run(), 5))


def test_close_capability_without_management_is_rejected_before_io(tmp_path):
    directory = LocalConnectionDirectoryV1(tmp_path / "connection")
    try:
        with pytest.raises(ValueError):
            LocalAppServerV1(directory, "managed", application_id="coding.default", product_id="coding",
                scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),), mux_closure=True,
                scope_factory=lambda: pytest.fail("no scope before validation"), request_stop=lambda _: None)
    finally:
        directory.close()


def test_mixed_ordinary_server_saturation_preserves_close_lookup_capacity():
    from loushang.appserver.connection import AppServerConnectionV1
    from loushang.appserver.managed_mux import ManagedMuxCreatedV1
    from loushang.appserver.protocol import (
        AppOperationV1,
        AppRequestV1,
        MuxListResultV1,
        MuxListV1,
        encode_request,
    )
    from loushang.appserver.protocol.stdio_profile import MAX_ORDINARY_REQUESTS
    from tests.appserver.test_connection import _SemanticClient
    from tests.appservice.test_managed_mux import _request

    async def run():
        release = asyncio.Event()
        entered = 0

        async def hold():
            nonlocal entered
            entered += 1
            await release.wait()

        class Semantic(_SemanticClient):
            async def list_muxes(self):
                await hold()
                return MuxListResultV1(())

            async def create_managed_mux(self, value):
                await hold()
                return ManagedMuxCreatedV1(value.operation_id, value.instance_id, value.name, "created")

            async def close_managed_mux(self, value):
                await hold()
                return state()

            async def read_managed_mux_close(self, value):
                return state(phase=ManagedMuxClosePhaseV1.CLEANUP_PENDING)

        left, right = _pair()
        frames = AppFramedStreamV1(left)
        semantic = Semantic()
        profile = AppConnectionProfileV1.LOCAL_MANAGED_CLOSE
        server = AppServerConnectionV1(semantic, AppFramedStreamV1(right), profile=profile,
                                        managed_mux=semantic, managed_mux_close=semantic)
        serving = asyncio.create_task(server.serve())
        try:
            assert await frames.receive() == connection_hello(profile)
            await frames.send(connection_hello(profile))
            for number in range(1, MAX_ORDINARY_REQUESTS + 1):
                if number % 3 == 0:
                    payload = wire.encode_close_call(wire.ManagedMuxCloseCallV1(str(number), request()))
                elif number % 3 == 1:
                    payload = encode_request(AppRequestV1(str(number), AppOperationV1.MUX_LIST, MuxListV1()))
                else:
                    payload = wire.encode_call(wire.ManagedMuxCallV1(str(number), _request()))
                await frames.send(payload)
            await _until(lambda: entered == MAX_ORDINARY_REQUESTS)
            overflow = str(MAX_ORDINARY_REQUESTS + 1)
            await frames.send(wire.encode_close_call(wire.ManagedMuxCloseCallV1(overflow, request())))
            assert isinstance(wire.decode_close_response(await frames.receive()).result, AppFailureV1)
            lookup = str(MAX_ORDINARY_REQUESTS + 2)
            await frames.send(wire.encode_close_call(wire.ManagedMuxCloseCallV1(lookup, request(), read_result=True)))
            result = wire.decode_close_response(await frames.receive())
            assert result.request_id == lookup and result.result.phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
            assert entered == MAX_ORDINARY_REQUESTS and server._counts[False] == MAX_ORDINARY_REQUESTS
        finally:
            release.set()
            await frames.close()
            await server.close()
            await asyncio.gather(serving, return_exceptions=True)
    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("missing", [False, True])
def test_failed_close_capability_borrow_closes_original_scope(tmp_path, missing):
    from loushang.appserver.local import LocalAppClientConnectionV1
    from loushang.appservice.client_scope import ScopedAppServiceV1
    from tests.appservice.test_continuity_runtime import _MemoryLease
    from tests.appservice.test_managed_mux import _binding, _open

    async def run():
        service = await _open(_MemoryLease(), _binding([]))
        owner = ScopedAppServiceV1(service)
        opened, closed = [], []

        class Scope:
            def __init__(self):
                self.inner = owner.open_client_scope()
                opened.append(self)

            @property
            def managed_mux_client(self):
                return self.inner.managed_mux_client

            @property
            def managed_mux_close_client(self):
                if missing:
                    return None
                raise RuntimeError("private capability failure")

            async def close(self):
                await self.inner.close()
                closed.append(self)

        directory = LocalConnectionDirectoryV1(tmp_path / "connection")
        server = LocalAppServerV1(directory, "managed", application_id="coding.default", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),), scope_factory=lambda: pytest.fail("no fallback"),
            managed_mux_scope_factory=Scope, mux_closure=True, request_stop=lambda _: None)
        client = LocalAppClientConnectionV1(directory, "managed")
        try:
            await server.start()
            with pytest.raises(AppConnectionClosedError):
                await client.start()
            await _until(lambda: bool(closed))
            assert len(opened) == 1 and closed == opened
        finally:
            await client.close()
            await server.close()
            await service.close()
            directory.close()
    asyncio.run(asyncio.wait_for(run(), 5))


def test_remote_close_accepts_historical_origin_and_lookup_none():
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        profile = AppConnectionProfileV1.LOCAL_MANAGED_CLOSE
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        hello = connection_hello(profile)
        await frames.send(hello)
        await remote.start()
        assert await frames.receive() == hello
        waiters = []
        try:
            for read, result in ((True, None), (False, state())):
                waiter = asyncio.create_task(remote.read_managed_mux_close(request()) if read
                                              else remote.close_managed_mux(request()))
                waiters.append(waiter)
                call = wire.decode_close_call(await frames.receive())
                assert call.read_result is read
                await frames.send(wire.encode_close_response(wire.ManagedMuxCloseResponseV1(call.request_id, result)))
                assert await waiter == result
                assert remote.managed_mux_close_client is not None
        finally:
            await remote.close()
            await asyncio.gather(*waiters, return_exceptions=True)
            await frames.close()
    asyncio.run(asyncio.wait_for(run(), 5))
