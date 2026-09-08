from __future__ import annotations

import asyncio
from typing import cast

import pytest

from loushang.appserver.client import AppClientV1
from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol import (
    AppServiceError,
    InvalidAppMessageError,
    MuxListResultV1,
)
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    connection_hello,
)
from loushang.appserver.remote_client import RemoteAppClientV1

from .test_connection import _pair, _SemanticClient


@pytest.mark.parametrize("profile", list(AppConnectionProfileV1))
def test_G16_PROFILE_closed_message_stream_keeps_exact_negotiation(profile):
    async def scenario():
        left, right = _pair()
        server = AppServerConnectionV1(cast(AppClientV1, _SemanticClient()),
                                      AppFramedStreamV1(right), profile=profile)
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        try:
            await client.start()
            assert await client.list_muxes() == MuxListResultV1(())
        finally:
            await client.close()
            await serving
    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G16_PROFILE_local_and_foreground_cannot_silently_negotiate():
    async def scenario():
        left, right = _pair()
        server = AppServerConnectionV1(cast(AppClientV1, _SemanticClient()),
                                      AppFramedStreamV1(right), phase_timeout=0.1)
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=AppConnectionProfileV1.LOCAL,
                                   phase_timeout=0.1)
        serving = asyncio.create_task(server.serve())
        try:
            with pytest.raises(InvalidAppMessageError):
                await client.start()
            with pytest.raises(AppServiceError):
                await serving
        finally:
            await client.close()
            await server.close()
    asyncio.run(asyncio.wait_for(scenario(), 3))


@pytest.mark.parametrize("value", ["local-detachable/v1", "foreground-stdio/v1", None, 1])
def test_G16_PROFILE_unknown_or_untyped_profiles_are_not_admitted(value):
    with pytest.raises(ValueError):
        connection_hello(value)


@pytest.mark.parametrize("override", [False, None, 0.2])
def test_G17_HELLO_override_preserves_default_and_later_phase_budget(override):
    async def scenario():
        left, right = _pair()
        profile = AppConnectionProfileV1.STDIO_DISCOVERY
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile, phase_timeout=0.02)
        frames = AppFramedStreamV1(right)

        async def peer():
            await asyncio.sleep(0.05)
            await frames.send(connection_hello(profile))
            await frames.receive()

        serving = asyncio.create_task(peer())
        try:
            if override is False or override is None:
                with pytest.raises(TimeoutError):
                    await client.start(**({} if override is False else {"timeout": None}))
            else:
                await client.start(timeout=override)
                assert client._timeout == 0.02
                left.block_writes = True
                with pytest.raises(TimeoutError):
                    await client.list_muxes()
                with pytest.raises(AppServiceError):
                    await client.start(timeout=override)
        finally:
            await client.close()
            serving.cancel()
            await asyncio.gather(serving, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), 61, "1"])
def test_G17_HELLO_invalid_override_has_no_state_or_io_effect(timeout):
    async def scenario():
        left, right = _pair()
        client = RemoteAppClientV1(
            AppFramedStreamV1(left), profile=AppConnectionProfileV1.STDIO_DISCOVERY
        )
        with pytest.raises(ValueError, match="invalid connection timeout"):
            await client.start(timeout=timeout)
        assert not client._started and not client._closed and client._reader is None
        assert not left.closed and not right.closed
        await client.close()

    asyncio.run(scenario())
