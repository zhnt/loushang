"""Actual installed stdio command; not isolated-wheel or terminal acceptance."""

from __future__ import annotations

import asyncio

import pytest

from loushang.ai.types import UserMessage
from loushang.appserver.framing import AppFramedStreamV1, AsyncioStreamTransportV1
from loushang.appserver.protocol import (
    MuxCreateV1,
    MuxSelectorV1,
    SessionListV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.coding.cli.hosted import parse_launch
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.coding.session_manager import SessionManager
from loushang.harnesstui.mux import open_hosted_mux_profile

from .test_hosted_discovery import _create
from .test_hosted_subprocess import _argv, _environment, _installed_command


@pytest.mark.parametrize("kind", list(SessionScopeV1))
def test_G17_COMPAT_installed_stdio_discovers_and_resumes_admitted_history(
    tmp_path, kind
):
    async def scenario():
        launch, _ = parse_launch(_argv(tmp_path))
        scope = next(item for item in launch.scopes if item.scope is kind)
        await _create(CodingHostedSessionCatalogV1((scope,)), scope)
        (path,) = scope.session_dir.glob("*.jsonl")
        manager = await SessionManager.open(path)
        try:
            await manager.append_message(
                UserMessage(
                    role="user",
                    content="Historical message before installed resume",
                    timestamp=1.0,
                )
            )
        finally:
            await manager.dispose_runtime_profile()
        process = await asyncio.create_subprocess_exec(
            _installed_command(),
            *_argv(tmp_path),
            "--session-discovery",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(tmp_path),
        )
        assert process.stdin and process.stdout and process.stderr
        errors = asyncio.create_task(process.stderr.read())
        client = RemoteAppClientV1(
            AppFramedStreamV1(AsyncioStreamTransportV1(process.stdout, process.stdin)),
            profile=AppConnectionProfileV1.STDIO_DISCOVERY,
            phase_timeout=30,
        )
        controller = None
        try:
            await client.start()
            discovery = client.discovery_client
            assert discovery is not None
            page = await discovery.list_sessions(
                SessionListV1("coding", kind, scope.fingerprint)
            )
            assert page.complete and len(page.candidates) == 1
            identity = page.candidates[0].identity
            await client.create_mux(MuxCreateV1("resumed"))
            controller = await open_hosted_mux_profile(
                client, selector=MuxSelectorV1(name="resumed")
            )
            state = await controller.open_member(
                SessionOpenSpecV1(
                    product_id=identity.product_id,
                    continuity_id=identity.continuity_id,
                    scope=identity.scope,
                    scope_fingerprint=identity.scope_fingerprint,
                    session_id=identity.session_id,
                    title="Resumed",
                )
            )
            assert state.active_window is not None
            assert state.active_window.session_id == identity.session_id
            snapshot = await client.snapshot_session(
                SessionSnapshotRequestV1(
                    state.attachment_id,
                    state.controller_generation,
                    state.active_window.member_id,
                )
            )
            assert snapshot.identity == identity
            assert [record.text for record in snapshot.records] == [
                "Historical message before installed resume",
            ]
            assert state.active_window.records == list(snapshot.records)
            assert not state.active_window.running
            await controller.close()
            controller = None
            await client.close()
            await asyncio.wait_for(process.wait(), 15)
            stderr = await errors
            assert process.returncode == 0, stderr.decode(errors="replace")
            assert not stderr
        finally:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), 10)
            if controller is not None:
                await asyncio.gather(controller.close(), return_exceptions=True)
            await asyncio.gather(client.close(), return_exceptions=True)
            process.stdin.close()
            await asyncio.gather(errors, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 60))
