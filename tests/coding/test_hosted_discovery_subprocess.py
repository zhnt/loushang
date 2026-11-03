"""Actual installed stdio command; not isolated-wheel or terminal acceptance."""

from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.appserver.framing import AppFramedStreamV1, AsyncioStreamTransportV1
from loushang.appserver.protocol import (
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxCreateV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionListV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.appservice.execution_contract import ExecutionStatusV1
from loushang.coding.cli.hosted import parse_launch
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.harnesstui.mux import open_hosted_mux_profile

from ._hosted_composition_seed import seed_hosted_history
from .test_hosted_discovery import _create
from .test_hosted_subprocess import _argv, _child, _environment, _installed_command


@pytest.mark.parametrize("kind", list(SessionScopeV1))
def test_G17_COMPAT_installed_stdio_discovers_and_resumes_admitted_history(
    tmp_path, kind
):
    async def scenario():
        launch, _ = parse_launch(_argv(tmp_path))
        scope = next(item for item in launch.scopes if item.scope is kind)
        await _create(CodingHostedSessionCatalogV1((scope,)), scope)
        await seed_hosted_history(scope, "Historical message before installed resume")
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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux writable Hosted Resume")
def test_G17_PRODUCT_stdio_resume_uses_stable_execution_and_commits_once(tmp_path):
    async def scenario():
        launch, _ = parse_launch(_argv(tmp_path))
        scope = next(
            item for item in launch.scopes if item.scope is SessionScopeV1.CWD
        )
        await _create(CodingHostedSessionCatalogV1((scope,)), scope)
        await seed_hosted_history(scope, "before stdio resume")
        async with _child(
            tmp_path,
            profile=AppConnectionProfileV1.STDIO_DISCOVERY_EXECUTION,
        ) as client:
            discovery = client.discovery_client
            execution = client.execution_client
            assert discovery is not None and execution is not None
            page = await discovery.list_sessions(
                SessionListV1("coding", SessionScopeV1.CWD, scope.fingerprint)
            )
            identity = page.candidates[0].identity
            await client.create_mux(MuxCreateV1("resumed"))
            controller = await open_hosted_mux_profile(
                client, selector=MuxSelectorV1(name="resumed")
            )
            try:
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
                control = SessionSnapshotRequestV1(
                    state.attachment_id,
                    state.controller_generation,
                    state.active_window.member_id,
                )
                accepted = await execution.submit_execution(
                    control,
                    execution.service_instance_id,
                    "stdio-resume-input",
                    "after stdio resume",
                )
                while True:
                    for envelope in await client.read_events(
                        attachment_id=control.attachment_id,
                        controller_generation=control.controller_generation,
                    ):
                        if (
                            envelope.event.kind
                            is SessionEventKindV1.INTERACTION_REQUESTED
                        ):
                            assert envelope.event.interaction_id is not None
                            await client.respond_interaction(
                                InteractionRespondV1(
                                    control.attachment_id,
                                    control.controller_generation,
                                    control.member_id,
                                    envelope.event.interaction_id,
                                    InteractionOutcomeV1.APPROVE,
                                )
                            )
                    current = await execution.get_execution(
                        control,
                        execution.service_instance_id,
                        accepted.state.execution_id,
                    )
                    if current.state.status.terminal:
                        break
                    await asyncio.sleep(0)
                assert current.state.status is ExecutionStatusV1.SUCCEEDED
                snapshot = await client.snapshot_session(control)
                assert [
                    record.text
                    for record in snapshot.records
                    if record.kind.value != "status"
                ] == [
                    "before stdio resume",
                    "after stdio resume",
                    "真实跨进程回复\nG14",
                ]
                repeated = await execution.submit_execution(
                    control,
                    execution.service_instance_id,
                    "stdio-resume-input",
                    "after stdio resume",
                )
                assert repeated.state.execution_id == accepted.state.execution_id
            finally:
                await controller.close()

    asyncio.run(asyncio.wait_for(scenario(), 120))
