from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace

import pytest

from loushang.appserver.framing import (
    AppConnectionClosedError,
    AsyncioStreamTransportV1,
)
from loushang.appserver.local import (
    LocalAppClientConnectionV1,
    LocalAppServerV1,
    LocalConnectionModeV1,
)
from loushang.appserver.local_auth import (
    LocalAuthenticationError,
    authenticate_local_client,
)
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    InvalidAppMessageError,
    MuxListResultV1,
    SessionListV1,
    SessionScopeV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1

from .test_local import _Scope, _until
from .test_local_record import _scopes
from .test_session_discovery_connection import _Discovery


def _server(directory, *, enabled=True, capability="available", request_stop=None):
    scopes = []
    discovery = _Discovery()

    class DiscoveryScope(_Scope):
        @property
        def discovery_client(self):
            if capability == "raises":
                raise RuntimeError("private missing capability")
            return discovery if capability == "available" else None

    def legacy_factory():
        scope = _Scope()  # Intentionally no discovery attribute.
        scopes.append(scope)
        return scope

    def discovery_factory():
        scope = DiscoveryScope()
        scopes.append(scope)
        return scope

    server = LocalAppServerV1(
        directory,
        "workspace",
        application_id="application",
        product_id="coding",
        scopes=_scopes(),
        scope_factory=legacy_factory,
        discovery_scope_factory=discovery_factory if enabled else None,
        request_stop=request_stop or (lambda _: pytest.fail("unexpected STOP")),
        auth_timeout=1,
        close_timeout=1,
    )
    return server, scopes, discovery


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_COMPAT_authenticated_record_selects_local_discovery(tmp_path, enabled):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "connections")
        server, scopes, discovery = _server(directory, enabled=enabled)
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            assert client.discovery_client is None
            await server.start()
            record = directory.read("workspace")
            assert record.session_discovery is enabled
            await client.start()
            assert await client.client.list_muxes() == MuxListResultV1(())
            port = client.discovery_client
            assert (port is not None) is enabled
            if port is not None:
                assert (
                    await port.list_sessions(
                        SessionListV1("coding", SessionScopeV1.CWD, "a" * 64)
                    )
                    == discovery.page
                )
            await client.close()
            assert client.discovery_client is None
            await _until(lambda: server.connection_counts == (0, 0))
            assert len(scopes) == 1 and scopes[0].closed
            assert directory.read("workspace") == record
        finally:
            await client.close()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_AUTH_capability_tamper_fails_before_scope_construction(
    tmp_path, monkeypatch, enabled
):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "connections")
        server, scopes, discovery = _server(directory, enabled=enabled)
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            await server.start()
            tampered = replace(server.record, session_discovery=not enabled)
            monkeypatch.setattr(directory, "read", lambda _: tampered)
            with pytest.raises(LocalAuthenticationError):
                await client.start()
            await _until(lambda: server.connection_counts == (0, 0))
            assert not scopes and not discovery.requests
        finally:
            await client.close()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("capability", ["missing", "raises"])
def test_G17_LIFETIMES_missing_port_closes_the_exact_created_scope(
    tmp_path, capability
):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "connections")
        server, scopes, discovery = _server(directory, capability=capability)
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            await server.start()
            with pytest.raises(AppConnectionClosedError):
                await client.start()
            await _until(lambda: server.connection_counts == (0, 0))
            assert len(scopes) == 1 and scopes[0].closed
            assert not discovery.requests
        finally:
            await client.close()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_COMPAT_cross_profile_app_hello_is_not_a_downgrade(tmp_path, enabled):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "connections")
        server, scopes, discovery = _server(directory, enabled=enabled)
        client = writer = None
        try:
            await server.start()
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", server.record.port
            )
            frames = await authenticate_local_client(
                AsyncioStreamTransportV1(reader, writer),
                server.record.authentication,
            )
            await frames.send(b"app")
            profile = (
                AppConnectionProfileV1.LOCAL
                if enabled
                else AppConnectionProfileV1.LOCAL_DISCOVERY
            )
            client = RemoteAppClientV1(frames, profile=profile)
            with pytest.raises(InvalidAppMessageError):
                await client.start()
            await _until(lambda: server.connection_counts == (0, 0))
            assert len(scopes) == 1 and scopes[0].closed
            assert not discovery.requests
        finally:
            if client is not None:
                await client.close()
            if writer is not None:
                writer.close()
                with suppress(ConnectionError):
                    await writer.wait_closed()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_G17_COMPAT_discovery_keeps_reserved_stop_without_extra_scope(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "connections")
        replies = []
        server, scopes, discovery = _server(directory, request_stop=replies.append)
        clients = [LocalAppClientConnectionV1(directory, "workspace") for _ in range(7)]
        stop = LocalAppClientConnectionV1(
            directory, "workspace", mode=LocalConnectionModeV1.STOP
        )
        try:
            await server.start()
            for client in clients:
                await client.start()
            assert server.connection_counts == (0, 7)
            await stop.start()
            assert stop.stop_requested and stop.discovery_client is None
            assert len(replies) == 1
            await replies[0]
            assert len(scopes) == 7 and not discovery.requests
        finally:
            await asyncio.gather(*(client.close() for client in [*clients, stop]))
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))
