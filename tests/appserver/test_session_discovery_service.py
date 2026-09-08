from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.appservice import AppServiceV1, InProcessAppClientV1
from loushang.appservice.ports import (
    HostedSessionResolutionErrorV1,
    HostedSessionResolutionFailureV1,
)

from .test_connection import _pair


class _UntrustedMissing(HostedSessionResolutionErrorV1):
    pass


@pytest.mark.parametrize("profile", [
    AppConnectionProfileV1.STDIO_DISCOVERY, AppConnectionProfileV1.LOCAL_DISCOVERY,
])
@pytest.mark.parametrize("failure,expected", [
    (HostedSessionResolutionErrorV1(HostedSessionResolutionFailureV1.MISSING), AppErrorCodeV1.NOT_FOUND),
    (HostedSessionResolutionErrorV1(HostedSessionResolutionFailureV1.UNAVAILABLE), AppErrorCodeV1.SESSION_UNAVAILABLE),
    (_UntrustedMissing(HostedSessionResolutionFailureV1.MISSING), AppErrorCodeV1.SESSION_UNAVAILABLE),
    (ValueError("private-product-path-sentinel"), AppErrorCodeV1.SESSION_UNAVAILABLE),
])
def test_G17_AUTHORITY_product_failure_reaches_wire_as_exact_redacted_code(profile, failure, expected):
    class Resolver:
        async def open_session(self, _request):
            raise failure

    async def scenario():
        service = AppServiceV1(product_id="coding", resolver=Resolver())
        left, right = _pair()
        server = AppServerConnectionV1(
            InProcessAppClientV1(service), AppFramedStreamV1(right), profile=profile,
        )
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        try:
            await remote.start()
            await remote.create_mux(MuxCreateV1("dev"))
            with pytest.raises(AppServiceError) as error:
                await remote.open_member(MuxMemberOpenV1(
                    MuxSelectorV1(name="dev"), SessionOpenSpecV1(
                        product_id="coding", continuity_id="continuity",
                        scope=SessionScopeV1.CWD, scope_fingerprint="a" * 64,
                        title="Resume", session_id="missing",
                    ),
                ))
            assert error.value.code is expected
            assert "sentinel" not in str(error.value)
        finally:
            await remote.close()
            await serving
            await service.close()
    asyncio.run(asyncio.wait_for(scenario(), 3))
