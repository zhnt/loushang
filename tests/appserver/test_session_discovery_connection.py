from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast

import pytest

from loushang.appserver.client import AppClientV1
from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppOperationV1,
    AppRequestV1,
    AppServiceError,
    InvalidAppMessageError,
    MuxListResultV1,
    SessionListResultV1,
    SessionListV1,
    SessionScopeV1,
    decode_response,
    encode_request,
)
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    connection_hello,
)
from loushang.appserver.remote_client import RemoteAppClientV1

from .test_connection import _pair, _SemanticClient
from .test_session_discovery_protocol import FINGERPRINT, _page


class _Discovery:
    def __init__(self):
        self.requests = []
        self.page = _page()

    async def list_sessions(self, request: SessionListV1) -> SessionListResultV1:
        self.requests.append(request)
        return self.page


def _request() -> SessionListV1:
    return SessionListV1("coding", SessionScopeV1.CWD, FINGERPRINT)


@pytest.mark.parametrize("profile", [
    AppConnectionProfileV1.STDIO_DISCOVERY, AppConnectionProfileV1.LOCAL_DISCOVERY,
])
def test_G17_COMPAT_discovery_profile_uses_explicit_borrowed_port(profile):
    async def scenario():
        left, right = _pair()
        discovery = _Discovery()
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right),
            profile=profile, discovery=discovery,
        )
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        assert client.discovery_client is None
        try:
            await client.start()
            assert client.discovery_client is client
            assert await client.list_sessions(_request()) == _page()
            assert discovery.requests == [_request()]
            assert await client.list_muxes() == MuxListResultV1(())
        finally:
            await client.close()
            await serving
        assert client.discovery_client is None
    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize("profile", [
    AppConnectionProfileV1.STDIO, AppConnectionProfileV1.LOCAL,
])
def test_G17_COMPAT_legacy_remote_rejects_discovery_without_wire_effect(profile):
    async def scenario():
        left, right = _pair()
        discovery = _Discovery()
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right),
            profile=profile, discovery=discovery,
        )
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        try:
            await client.start()
            assert client.discovery_client is None
            before = client._next_id
            with pytest.raises(AppServiceError) as error:
                await client.list_sessions(_request())
            assert error.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            assert not discovery.requests and client._next_id == before
            assert await client.list_muxes() == MuxListResultV1(())
        finally:
            await client.close()
            await serving
    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize("profile", [
    AppConnectionProfileV1.STDIO, AppConnectionProfileV1.LOCAL,
])
def test_G17_COMPAT_legacy_server_rejects_injected_discovery_before_product(profile):
    async def scenario():
        left, right = _pair()
        discovery = _Discovery()
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right),
            profile=profile, discovery=discovery,
        )
        frames = AppFramedStreamV1(left)
        serving = asyncio.create_task(server.serve())
        try:
            assert await frames.receive() == connection_hello(profile)
            await frames.send(connection_hello(profile))
            await frames.send(encode_request(AppRequestV1(
                "1", AppOperationV1.SESSIONS_LIST, _request(),
            )))
            result = decode_response(await frames.receive()).result
            assert result == AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            assert not discovery.requests
        finally:
            await frames.close()
            await serving
    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G17_COMPAT_absent_semantic_discovery_port_is_closed_failure():
    async def scenario():
        left, right = _pair()
        profile = AppConnectionProfileV1.STDIO_DISCOVERY
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right), profile=profile,
        )
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        try:
            await client.start()
            with pytest.raises(AppServiceError) as error:
                await client.list_sessions(_request())
            assert error.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        finally:
            await client.close()
            await serving
    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G17_COMPAT_cross_scope_discovery_response_is_rejected():
    async def scenario():
        left, right = _pair()
        profile = AppConnectionProfileV1.STDIO_DISCOVERY
        discovery = _Discovery()
        discovery.page = replace(_page(), candidates=(), scope=SessionScopeV1.USER_HOME)
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right),
            profile=profile, discovery=discovery,
        )
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        try:
            await client.start()
            with pytest.raises(InvalidAppMessageError):
                await client.list_sessions(_request())
        finally:
            await client.close()
            await serving
    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G17_COMPAT_legacy_hello_bytes_remain_exact():
    assert connection_hello(AppConnectionProfileV1.STDIO) == (
        b'{"profile":"foreground-stdio/v1","protocolVersion":"loushang.app/v1"}'
    )
    assert connection_hello(AppConnectionProfileV1.LOCAL) == (
        b'{"profile":"local-detachable/v1","protocolVersion":"loushang.app/v1"}'
    )


@pytest.mark.parametrize("server_profile,client_profile", [
    (server, client)
    for server in AppConnectionProfileV1 for client in AppConnectionProfileV1
    if server is not client
])
def test_G17_COMPAT_profile_mismatch_never_reaches_semantic_dispatch(
    server_profile, client_profile,
):
    async def scenario():
        left, right = _pair()
        discovery = _Discovery()
        server = AppServerConnectionV1(
            cast(AppClientV1, _SemanticClient()), AppFramedStreamV1(right),
            profile=server_profile, discovery=discovery, phase_timeout=0.2,
        )
        client = RemoteAppClientV1(
            AppFramedStreamV1(left), profile=client_profile, phase_timeout=0.2,
        )
        serving = asyncio.create_task(server.serve())
        try:
            with pytest.raises(InvalidAppMessageError):
                await client.start()
            with pytest.raises(AppServiceError):
                await serving
            assert not discovery.requests
            assert client.discovery_client is None
        finally:
            await client.close()
            await server.close()
    asyncio.run(asyncio.wait_for(scenario(), 3))
