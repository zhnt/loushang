from __future__ import annotations

import asyncio
from typing import cast

import pytest

from loushang.apphost.application import HostedApplicationError
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.foreground import HostedForegroundRuntimeV1
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol import SessionListV1, SessionScopeV1
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from tests.appserver.test_session_discovery_connection import _Discovery

from .test_foreground import _Application, _Pipe


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_COMPAT_foreground_only_borrows_explicit_discovery(enabled):
    async def scenario():
        discovery = _Discovery()

        class Application(_Application):
            @property
            def discovery_client(self):
                assert enabled, "default foreground must not probe discovery"
                return discovery

        app = Application()
        left, right = _Pipe(), _Pipe()
        left.peer, right.peer = right, left
        owner = HostedForegroundRuntimeV1(
            cast(HostedApplicationContinuityRuntimeV1, app),
            right,
            session_discovery=enabled,
        )
        profile = (
            AppConnectionProfileV1.STDIO_DISCOVERY
            if enabled
            else AppConnectionProfileV1.STDIO
        )
        client = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        running = asyncio.create_task(owner.run())
        try:
            await client.start()
            capability = client.discovery_client
            assert (capability is not None) is enabled
            if capability is not None:
                page = await capability.list_sessions(
                    SessionListV1("coding", SessionScopeV1.CWD, "a" * 64)
                )
                assert page == discovery.page
                assert len(discovery.requests) == 1
        finally:
            await client.close()
            await running
        assert not owner.cleanup_pending
        assert app.events == ["application.close", "lease.released"]

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G17_COMPAT_foreground_missing_discovery_refuses_before_hello():
    class Application(_Application):
        discovery_client = None

    async def scenario():
        app = Application()
        left, right = _Pipe(), _Pipe()
        left.peer, right.peer = right, left
        with pytest.raises(
            HostedApplicationError, match="hosted_discovery_unavailable"
        ):
            HostedForegroundRuntimeV1(
                cast(HostedApplicationContinuityRuntimeV1, app),
                right,
                session_discovery=True,
            )
        assert not left.reader._buffer
        assert not right.closed and not app.events  # Caller still owns both.
        await app.close()
        await right.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_G17_COMPAT_foreground_rejects_non_boolean_activation(value):
    async def scenario():
        with pytest.raises(TypeError, match="invalid discovery activation"):
            HostedForegroundRuntimeV1(
                cast(HostedApplicationContinuityRuntimeV1, _Application()),
                _Pipe(),
                session_discovery=value,
            )

    asyncio.run(scenario())
