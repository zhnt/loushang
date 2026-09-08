from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCreateV1,
    MuxSelectorV1,
    SessionListV1,
    SessionOpenSpecV1,
)
from loushang.coding.cli.mux import main
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.coding.hosted_local import CodingLocalCommandV1
from loushang.harnesstui.mux import open_hosted_mux_profile
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui.input import InputEvent

from .test_hosted_discovery import _create
from .test_hosted_local import _local_launch
from .test_hosted_session import _model, _stream
from .test_mux_command import _serve


def test_G17_COMPAT_local_describe_selects_discovery_without_state(tmp_path, capsys):
    assert main([*_serve(tmp_path), "--session-discovery", "--describe"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["profile"] == "local-detachable-discovery/v1"
    assert str(tmp_path) not in output.out
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_G17_COMPAT_local_launch_requires_exact_activation(tmp_path, value):
    with pytest.raises(TypeError, match="invalid discovery activation"):
        replace(_local_launch(tmp_path), session_discovery=value)
    assert not tuple(tmp_path.iterdir())


def test_G17_PRODUCT_local_discovery_views_resume_interact_and_detach(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("LOUSHANG_TMPDIR", str(tmp_path / "scratch"))

    async def scenario():
        launch = replace(_local_launch(tmp_path), session_discovery=True)
        for scope in launch.application.scopes:
            await _create(CodingHostedSessionCatalogV1((scope,)), scope, 2)
        command = CodingLocalCommandV1(
            launch, model=_model(), stream_fn=_stream, tools=[]
        )
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        clients = [
            LocalAppClientConnectionV1(directory, launch.endpoint) for _ in range(2)
        ]
        stop = LocalAppClientConnectionV1(
            directory, launch.endpoint, mode=LocalConnectionModeV1.STOP
        )
        controllers = []
        try:
            await command.start()
            for client in clients:
                await client.start()
            for connection, scope in zip(
                clients, launch.application.scopes, strict=True
            ):
                port = connection.discovery_client
                assert port is not None
                query = SessionListV1("coding", scope.scope, scope.fingerprint, limit=1)
                page = await port.list_sessions(query)
                assert page.complete and page.continuation
                other = clients[1] if connection is clients[0] else clients[0]
                assert other.discovery_client is not None
                with pytest.raises(AppServiceError) as stale:
                    await other.discovery_client.list_sessions(
                        replace(query, continuation=page.continuation)
                    )
                assert stale.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
                name = scope.scope.value
                await connection.client.create_mux(MuxCreateV1(name))
                controller = await open_hosted_mux_profile(
                    connection.client, selector=MuxSelectorV1(name=name)
                )
                controllers.append(controller)
                identity = page.candidates[0].identity
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
                await controller.submit("after local resume")
                assert state.active_window is not None
                # The turn reply and the scoped event relay are independent.
                async with asyncio.timeout(5):
                    while len(state.active_window.records) < 2:
                        await controller.poll()
                        assert not state.snapshot_required
                        await asyncio.sleep(0.001)
                assert [record.text for record in state.active_window.records] == [
                    "after local resume",
                    "real Coding response",
                ]
                await controller.close()
            await clients[0].close()
            assert len((await clients[1].client.list_muxes()).mux_spaces) == 2
            await stop.start()
            assert stop.stop_requested
            await command.wait_closed()
            assert not command.cleanup_pending
        finally:
            await asyncio.gather(
                *(controller.close() for controller in controllers),
                return_exceptions=True,
            )
            await asyncio.gather(
                *(client.close() for client in [*clients, stop]), return_exceptions=True
            )
            await command.close(retry_timeout=5)
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 30))


def test_G17_PRODUCT_picker_resumes_both_scopes_interacts_and_retains_history(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("LOUSHANG_TMPDIR", str(tmp_path / "scratch"))

    async def settle(shell):
        while shell.pending_actions:
            await asyncio.sleep(0.001)

    async def scenario():
        launch = replace(_local_launch(tmp_path), session_discovery=True)
        for scope in launch.application.scopes:
            await _create(CodingHostedSessionCatalogV1((scope,)), scope)
        command = CodingLocalCommandV1(
            launch, model=_model(), stream_fn=_stream, tools=[]
        )
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        connection = LocalAppClientConnectionV1(directory, launch.endpoint)
        stop = LocalAppClientConnectionV1(
            directory, launch.endpoint, mode=LocalConnectionModeV1.STOP
        )
        shells = []
        try:
            await command.start()
            await connection.start()
            scopes = tuple((item.scope, item.fingerprint) for item in connection.scopes)
            for scope in launch.application.scopes:
                name = scope.scope.value
                await connection.client.create_mux(MuxCreateV1(name))
                shell = HostedMuxShellV1(
                    connection.client,
                    selector=MuxSelectorV1(name=name),
                    product_id="coding",
                    scopes=scopes,
                    discovery_client=connection.discovery_client,
                )
                shells.append(shell)
                await shell.start()
                shell.handle(InputEvent(kind="text", text=f"/sessions {name}"))
                shell.handle(InputEvent(kind="key", key="enter"))
                await settle(shell)
                assert shell.picker.page is not None and shell.picker.page.complete
                identity = shell.picker.page.candidates[0].identity
                assert identity.scope is scope.scope
                shell.handle(InputEvent(kind="key", key="enter"))
                await settle(shell)
                assert shell.state.active_window.session_id == identity.session_id
                shell.handle(InputEvent(kind="text", text="continue from picker"))
                shell.handle(InputEvent(kind="key", key="enter"))
                await settle(shell)
                async with asyncio.timeout(5):
                    while len(shell.state.active_window.records) < 2:
                        await shell.poll()
                        assert not shell.state.snapshot_required
                        await asyncio.sleep(0.001)
                await shell.close()
                assert not shell.cleanup_pending
                # Logical UI detach leaves the native connection and application alive.
                restored = await open_hosted_mux_profile(
                    connection.client, selector=MuxSelectorV1(name=name)
                )
                try:
                    assert [
                        row.text for row in restored.state.active_window.records
                    ] == [
                        "continue from picker",
                        "real Coding response",
                    ]
                finally:
                    await restored.close()
            assert len((await connection.client.list_muxes()).mux_spaces) == 2
            await stop.start()
            await command.wait_closed()
            assert not command.cleanup_pending
        finally:
            await asyncio.gather(
                *(shell.close() for shell in shells), return_exceptions=True
            )
            await asyncio.gather(
                connection.close(), stop.close(), return_exceptions=True
            )
            await command.close(retry_timeout=5)
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 30))
