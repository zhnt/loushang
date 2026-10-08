from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.execution.codec import (
    encode_response as encode_execution_response,
)
from loushang.appserver.execution.model import ExecutionResponseV1
from loushang.appserver.framing import AppConnectionClosedError, AppFramedStreamV1
from loushang.appserver.local import LocalAppClientConnectionV1, LocalAppServerV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
    decode_connection_record,
    encode_connection_record,
)
from loushang.appserver.managed_mux import ManagedMuxCreatedV1
from loushang.appserver.managed_mux_wire import (
    ManagedMuxCallV1,
    ManagedMuxResponseV1,
    decode_call,
    decode_response,
    encode_call,
    encode_response,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppOperationV1,
    AppRequestV1,
    AppResponseV1,
    AppServiceError,
    InvalidAppMessageError,
    MuxCreateV1,
    MuxListV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    encode_request,
)
from loushang.appserver.protocol import (
    encode_response as encode_app_response,
)
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    connection_hello,
)
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.appservice.client_scope import ScopedAppServiceV1
from tests.appservice.test_continuity_runtime import _MemoryLease
from tests.appservice.test_managed_mux import _binding, _open, _request

from .test_connection import _pair, _SemanticClient
from .test_local import _until


def test_managed_wire_closed_roundtrip_and_credential_safe_repr():
    call = ManagedMuxCallV1("1", _request())
    result = ManagedMuxCreatedV1(call.request.operation_id, call.request.instance_id, "dev", "mux-1")
    response = ManagedMuxResponseV1("1", result)
    assert decode_call(encode_call(call)) == call
    assert decode_response(encode_response(response)) == response
    assert "secret" not in repr(call)
    assert b"secret" not in encode_response(response)


@pytest.mark.parametrize("mutation", (
    {"extra": True}, {"protocolVersion": "loushang.app/v1"},
    {"requestId": True}, {"operation": "mux/close"}, {"request": None},
))
def test_managed_wire_rejects_unknown_or_cross_protocol_fields(mutation):
    raw = json.loads(encode_call(ManagedMuxCallV1("1", _request())))
    with pytest.raises(InvalidAppMessageError):
        decode_call(json.dumps(raw | mutation).encode())


def test_managed_wire_rejects_duplicate_keys_and_oversized_authority():
    encoded = encode_call(ManagedMuxCallV1("1", _request()))
    with pytest.raises(InvalidAppMessageError):
        decode_call(encoded.replace(b'"requestId":"1"', b'"requestId":"1","requestId":"2"'))
    raw = json.loads(encoded)
    raw["request"]["authority"] = "x" * 1025
    with pytest.raises(InvalidAppMessageError):
        decode_call(json.dumps(raw).encode())


def test_authenticated_managed_creation_survives_client_eof_without_replay(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class PausedLease(_MemoryLease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = PausedLease()
        service = await _open(lease, _binding([]))
        owner = ScopedAppServiceV1(service)
        directory = LocalConnectionDirectoryV1(tmp_path / "connection")
        server = LocalAppServerV1(
            directory, "managed", application_id="coding.default", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),),
            scope_factory=owner.open_client_scope,
            managed_mux_scope_factory=owner.open_client_scope,
            request_stop=lambda _: pytest.fail("client EOF must not stop service"),
        )
        first, second = (LocalAppClientConnectionV1(directory, "managed") for _ in range(2))
        waiter = None
        try:
            await server.start()
            record = directory.read("managed")
            assert record.mux_management
            await first.start()
            assert first.managed_mux_client is not None
            with pytest.raises(AppServiceError):
                await first.client.create_mux(MuxCreateV1("legacy"))
            waiter = asyncio.create_task(first.managed_mux_client.create_managed_mux(_request()))
            await entered.wait()
            await first.close()
            assert not lease.commits
            assert owner.pending_counts == (1, 0)
            release.set()
            await second.start()
            result = await second.managed_mux_client.create_managed_mux(_request())
            assert result == lease.record.managed_creations[0]
            assert len(lease.commits) == 1
            assert len((await second.client.list_muxes()).mux_spaces) == 1
            with pytest.raises(AppServiceError):
                await second.managed_mux_client.create_managed_mux(replace(_request(), authority="wrong"))
        finally:
            release.set()
            if waiter is not None:
                await asyncio.gather(waiter, return_exceptions=True)
            await first.close()
            await second.close()
            await server.close()
            await service.close()
            directory.close()

    asyncio.run(asyncio.wait_for(run(), 15))


@pytest.mark.parametrize("request_family,reply_family", (
    ("app", "execution"), ("app", "managed"),
    ("execution", "app"), ("execution", "managed"),
    ("managed", "app"), ("managed", "execution"),
    ("close", "app"), ("close", "execution"), ("close", "managed"),
    ("app", "close"), ("execution", "close"), ("managed", "close"),
))
def test_matching_request_id_cannot_accept_failure_from_another_protocol(request_family, reply_family):
    from loushang.appserver.managed_mux_wire import (
        ManagedMuxCloseResponseV1,
        encode_close_response,
    )
    from tests.appserver.test_managed_mux_close_wire import request as close_request

    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        profile = (AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED_CLOSE if "close" in (request_family, reply_family)
                   else AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED)
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)

        async def peer():
            hello = connection_hello(profile, service_instance_id="instance")
            await frames.send(hello)
            assert await frames.receive() == hello
            call = json.loads(await frames.receive())
            request_id = call["requestId"]
            failure = AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            payload = {
                "app": lambda: encode_app_response(AppResponseV1(request_id, failure)),
                "execution": lambda: encode_execution_response(ExecutionResponseV1(request_id, failure)),
                "managed": lambda: encode_response(ManagedMuxResponseV1(request_id, failure)),
                "close": lambda: encode_close_response(ManagedMuxCloseResponseV1(request_id, failure)),
            }[reply_family]()
            await frames.send(payload)

        serving = asyncio.create_task(peer())
        try:
            await remote.start()
            with pytest.raises(AppConnectionClosedError):
                if request_family == "app":
                    await remote.list_muxes()
                elif request_family == "execution":
                    await remote.execution_client.get_execution(
                        SessionSnapshotRequestV1("attachment", 1, "member"), "instance", "execution",
                    )
                elif request_family == "close":
                    await remote.managed_mux_close_client.close_managed_mux(close_request())
                else:
                    await remote.managed_mux_client.create_managed_mux(_request())
            assert remote.managed_mux_client is None
            assert not remote._pending
            assert remote._counts == {False: 0, True: 0}
        finally:
            await remote.close()
            await serving
            await frames.close()

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("discovery,execution,expected_profile", (
    (False, False, AppConnectionProfileV1.LOCAL_MANAGED),
    (True, False, AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED),
    (False, True, AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED),
    (True, True, AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED),
))
@pytest.mark.parametrize("closure", [False, True])
def test_local_managed_profiles_borrow_all_capabilities_from_one_scope(
    tmp_path, discovery, execution, expected_profile, closure,
):
    if closure:
        expected_profile = AppConnectionProfileV1(expected_profile.value.removesuffix("/v1") + "/v2")
    async def run():
        service = await _open(_MemoryLease(), _binding([]))
        owner = ScopedAppServiceV1(service)
        opened, closed = [], []

        class Scope:
            def __init__(self):
                self.inner = owner.open_client_scope()
                self.managed_mux_client = self.inner.managed_mux_client
                self.managed_mux_close_client = object() if closure else None
                self.discovery_client = object() if discovery else None
                self.execution_client = SimpleNamespace(service_instance_id="instance") if execution else None
                opened.append(self)

            def __getattr__(self, name):
                return getattr(self.inner, name)

            async def close(self):
                await self.inner.close()
                closed.append(self)

        def fallback():
            pytest.fail("optional capabilities must not acquire separate scopes")

        directory = LocalConnectionDirectoryV1(tmp_path / "connection")
        server = LocalAppServerV1(
            directory, "managed", application_id="coding.default", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),),
            scope_factory=fallback, managed_mux_scope_factory=Scope,
            mux_closure=closure,
            discovery_scope_factory=fallback if discovery else None,
            execution_scope_factory=fallback if execution else None,
            request_stop=lambda _: pytest.fail("client EOF must not stop service"),
        )
        client = LocalAppClientConnectionV1(directory, "managed")
        try:
            assert client.managed_mux_client is None
            await server.start()
            record = directory.read("managed")
            assert record.semantic_profile is expected_profile
            assert decode_connection_record(encode_connection_record(record)) == record
            assert "mux_management" in json.loads(encode_connection_record(record))["capabilities"]
            await client.start()
            assert (client.discovery_client is not None) is discovery
            assert (client.execution_client is not None) is execution
            assert client.managed_mux_client is not None
            assert (client.managed_mux_close_client is not None) is closure
            result = await client.managed_mux_client.create_managed_mux(_request())
            assert result.name == "dev"
            assert len(opened) == 1
            await client.close()
            await _until(lambda: server.connection_counts == (0, 0))
            assert closed == opened
            assert client.managed_mux_client is None
        finally:
            await client.close()
            await server.close()
            await service.close()
            directory.close()

    asyncio.run(asyncio.wait_for(run(), 10))


def _failure_frame(family, request_id):
    failure = AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    if family == "loushang.managed-mux/v1":
        return encode_response(ManagedMuxResponseV1(request_id, failure))
    if family == "loushang.execution/v1":
        return encode_execution_response(ExecutionResponseV1(request_id, failure))
    return encode_app_response(AppResponseV1(request_id, failure))


@pytest.mark.parametrize("field,value", (("operation_id", "e" * 32), ("name", "other")))
def test_cancelled_waiter_cannot_bypass_managed_receipt_intent_validation(field, value):
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=AppConnectionProfileV1.LOCAL_MANAGED)
        hello = connection_hello(AppConnectionProfileV1.LOCAL_MANAGED)
        await frames.send(hello)
        await remote.start()
        assert await frames.receive() == hello
        request = _request()
        waiter = asyncio.create_task(remote.create_managed_mux(request))
        try:
            call = decode_call(await frames.receive())
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert len(remote._pending) == 1
            result = ManagedMuxCreatedV1(request.operation_id, request.instance_id, request.name, "mux")
            await frames.send(encode_response(ManagedMuxResponseV1(call.request_id, replace(result, **{field: value}))))
            await _until(lambda: not remote._pending)
            assert remote.managed_mux_client is None
            assert remote._closed
            assert remote._counts == {False: 0, True: 0}
        finally:
            await remote.close()
            await frames.close()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(asyncio.wait_for(run(), 5))


def test_historical_managed_receipt_instance_is_not_rewritten_or_rejected():
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=AppConnectionProfileV1.LOCAL_MANAGED)
        hello = connection_hello(AppConnectionProfileV1.LOCAL_MANAGED)
        await frames.send(hello)
        await remote.start()
        assert await frames.receive() == hello
        request = _request()
        waiter = asyncio.create_task(remote.create_managed_mux(request))
        try:
            call = decode_call(await frames.receive())
            historical = ManagedMuxCreatedV1(request.operation_id, "e" * 32, request.name, "mux")
            await frames.send(encode_response(ManagedMuxResponseV1(call.request_id, historical)))
            assert await waiter == historical
            assert remote.managed_mux_client is not None
        finally:
            await remote.close()
            await frames.close()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(asyncio.wait_for(run(), 5))


def test_mixed_protocols_share_client_request_numbers_and_ordinary_capacity():
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        profile = AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        full, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def peer():
            hello = connection_hello(profile, service_instance_id="instance")
            await frames.send(hello)
            assert await frames.receive() == hello
            for _ in range(16):
                calls.append(json.loads(await frames.receive()))
            full.set()
            # The independent control allowance still uses the SAME ID sequence.
            control = json.loads(await frames.receive())
            assert control["requestId"] == "17"
            await frames.send(_failure_frame(control["protocolVersion"], "17"))
            await release.wait()
            for call in calls:
                await frames.send(_failure_frame(call["protocolVersion"], call["requestId"]))

        serving = asyncio.create_task(peer())
        pending = []
        try:
            await remote.start()
            for index in range(16):
                if index % 3 == 0:
                    work = remote.list_muxes()
                elif index % 3 == 1:
                    work = remote.managed_mux_client.create_managed_mux(_request())
                else:
                    work = remote.execution_client.submit_execution(
                        SessionSnapshotRequestV1("attachment", 1, "member"), "instance", f"s{index}", "text",
                    )
                pending.append(asyncio.create_task(work))
            await full.wait()
            assert [call["requestId"] for call in calls] == [str(n) for n in range(1, 17)]
            assert len({call["protocolVersion"] for call in calls}) == 3
            assert remote._counts == {False: 16, True: 0}
            with pytest.raises(AppServiceError) as error:
                await remote.managed_mux_client.create_managed_mux(_request())
            assert error.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            assert remote._next_id == 16
            with pytest.raises(AppServiceError):
                await remote.execution_client.get_execution(
                    SessionSnapshotRequestV1("attachment", 1, "member"), "instance", "execution",
                )
            release.set()
            results = await asyncio.gather(*pending, return_exceptions=True)
            assert all(type(result) is AppServiceError for result in results)
            assert not remote._pending
            assert remote._counts == {False: 0, True: 0}
        finally:
            release.set()
            await remote.close()
            await asyncio.gather(*pending, return_exceptions=True)
            await serving
            await frames.close()

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("managed_profile", (False, True))
def test_unnegotiated_or_reused_managed_request_id_is_rejected_before_dispatch(managed_profile):
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(left)
        calls = []

        class Semantic(_SemanticClient):
            async def create_managed_mux(self, request):
                calls.append(request)
                raise AssertionError("invalid request must not dispatch")

        semantic = Semantic()
        profile = AppConnectionProfileV1.LOCAL_MANAGED if managed_profile else AppConnectionProfileV1.LOCAL
        server = AppServerConnectionV1(
            semantic, AppFramedStreamV1(right), profile=profile,
            managed_mux=semantic if managed_profile else None,
        )
        serving = asyncio.create_task(server.serve())
        try:
            assert await frames.receive() == connection_hello(profile)
            await frames.send(connection_hello(profile))
            await frames.send(encode_request(AppRequestV1("1", AppOperationV1.MUX_LIST, MuxListV1())))
            await frames.receive()
            await frames.send(encode_call(ManagedMuxCallV1("1" if managed_profile else "2", _request())))
            with pytest.raises(InvalidAppMessageError):
                await serving
            assert calls == []
        finally:
            await server.close()
            await frames.close()
            await asyncio.gather(serving, return_exceptions=True)

    asyncio.run(asyncio.wait_for(run(), 5))


def test_raw_mixed_requests_share_server_capacity_and_reject_overflow_before_dispatch():
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(left)
        entered = asyncio.Queue()
        release = asyncio.Event()

        class Semantic(_SemanticClient):
            async def create_managed_mux(self, request):
                entered.put_nowait("managed")
                await release.wait()
                return ManagedMuxCreatedV1(request.operation_id, request.instance_id, request.name, "mux")

            async def list_muxes(self):
                entered.put_nowait("app")
                await release.wait()
                return await super().list_muxes()

        semantic = Semantic()
        profile = AppConnectionProfileV1.LOCAL_MANAGED
        server = AppServerConnectionV1(semantic, AppFramedStreamV1(right), profile=profile, managed_mux=semantic)
        serving = asyncio.create_task(server.serve())
        try:
            assert await frames.receive() == connection_hello(profile)
            await frames.send(connection_hello(profile))
            for number in range(1, 17):
                payload = (encode_call(ManagedMuxCallV1(str(number), _request())) if number % 2
                           else encode_request(AppRequestV1(str(number), AppOperationV1.MUX_LIST, MuxListV1())))
                await frames.send(payload)
                assert await entered.get() == ("managed" if number % 2 else "app")
            assert server._counts == {False: 16, True: 0}
            await frames.send(encode_call(ManagedMuxCallV1("17", _request())))
            result = decode_response(await frames.receive())
            assert result == ManagedMuxResponseV1("17", AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE))
            assert entered.empty()
            assert server._counts == {False: 16, True: 0}
            release.set()
            for _ in range(16):
                await frames.receive()
            await _until(lambda: server._counts == {False: 0, True: 0})
        finally:
            release.set()
            await frames.close()
            await server.close()
            await asyncio.gather(serving, return_exceptions=True)

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("missing", ("managed_mux_client", "discovery_client", "execution_client"))
@pytest.mark.parametrize("raises", (False, True))
def test_declared_capability_borrow_failure_closes_original_scope_without_fallback(tmp_path, missing, raises):
    async def run():
        closed = []

        class Scope:
            def __getattr__(self, name):
                if name == missing:
                    if raises:
                        raise RuntimeError("private getter failure")
                    return None
                if name == "execution_client":
                    return SimpleNamespace(service_instance_id="instance")
                return object()

            async def close(self):
                closed.append(self)

        scope = Scope()

        def fallback():
            pytest.fail("no fallback is permitted")

        directory = LocalConnectionDirectoryV1(tmp_path / "connection")
        server = LocalAppServerV1(
            directory, "managed", application_id="coding.default", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),),
            scope_factory=fallback, managed_mux_scope_factory=lambda: scope,
            discovery_scope_factory=fallback, execution_scope_factory=fallback,
            request_stop=lambda _: pytest.fail("borrow failure must not stop service"),
        )
        client = LocalAppClientConnectionV1(directory, "managed")
        try:
            await server.start()
            with pytest.raises(AppServiceError):
                await client.start()
            await _until(lambda: server.connection_counts == (0, 0))
            assert closed == [scope]
        finally:
            await client.close()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(run(), 10))
