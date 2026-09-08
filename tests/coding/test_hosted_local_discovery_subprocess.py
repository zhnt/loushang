"""Actual installed local CLI; isolated wheel/terminal evidence remains separate."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from loushang.ai.types import UserMessage
from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    MuxCreateV1,
    MuxSelectorV1,
    SessionListV1,
    SessionOpenSpecV1,
)
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.coding.session_manager import SessionManager
from loushang.harnesstui.mux import open_hosted_mux_profile

from .test_hosted_discovery import _create
from .test_hosted_local import _local_launch
from .test_hosted_subprocess import _environment
from .test_mux_command import _serve
from .test_mux_subprocess import _errors


def test_G17_COMPAT_installed_local_discovery_history_detach_and_stop(tmp_path):
    async def scenario():
        launch = _local_launch(tmp_path)
        for scope in launch.application.scopes:
            await _create(CodingHostedSessionCatalogV1((scope,)), scope)
            (path,) = scope.session_dir.glob("*.jsonl")
            manager = await SessionManager.open(path)
            try:
                await manager.append_message(
                    UserMessage(
                        role="user",
                        content=f"Historical {scope.scope.value}",
                        timestamp=1.0,
                    )
                )
            finally:
                await manager.dispose_runtime_profile()
        executable = Path(sys.executable).parent / (
            "loushang-mux.exe" if os.name == "nt" else "loushang-mux"
        )
        assert executable.is_file()
        process = await asyncio.create_subprocess_exec(
            str(executable),
            *_serve(tmp_path),
            "--session-discovery",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(tmp_path),
        )
        assert process.stdin and process.stdout and process.stderr
        errors = asyncio.create_task(_errors(process.stderr))
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        clients = [
            LocalAppClientConnectionV1(directory, launch.endpoint) for _ in range(2)
        ]
        stop = LocalAppClientConnectionV1(
            directory, launch.endpoint, mode=LocalConnectionModeV1.STOP
        )
        controllers = []
        try:
            ready = json.loads(await asyncio.wait_for(process.stdout.readline(), 35))
            assert ready["status"] == "ready"
            assert ready["profile"] == "local-detachable-discovery/v1"
            assert str(tmp_path) not in str(ready)
            process.stdin.close()  # Local server lifetime is independent of stdin EOF.
            await process.stdin.wait_closed()
            for client, scope in zip(clients, launch.application.scopes, strict=True):
                await client.start()
                assert client.discovery_client is not None
                page = await client.discovery_client.list_sessions(
                    SessionListV1("coding", scope.scope, scope.fingerprint)
                )
                assert page.complete and len(page.candidates) == 1
                identity = page.candidates[0].identity
                name = scope.scope.value
                await client.client.create_mux(MuxCreateV1(name))
                controller = await open_hosted_mux_profile(
                    client.client, selector=MuxSelectorV1(name=name)
                )
                controllers.append(controller)
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
                assert [record.text for record in state.active_window.records] == [
                    f"Historical {name}"
                ]
                await controller.close()
                await client.close()
            replacement = LocalAppClientConnectionV1(directory, launch.endpoint)
            clients.append(replacement)
            await replacement.start()
            assert len((await replacement.client.list_muxes()).mux_spaces) == 2
            restored = await open_hosted_mux_profile(
                replacement.client,
                selector=MuxSelectorV1(name="cwd"),
            )
            controllers.append(restored)
            assert (
                restored.state is not None and restored.state.active_window is not None
            )
            assert [record.text for record in restored.state.active_window.records] == [
                "Historical cwd",
            ]
            await restored.close()
            assert process.returncode is None
            await stop.start()
            assert stop.stop_requested
            assert await asyncio.wait_for(process.wait(), 20) == 0
            assert await errors == b""
        except BaseException as error:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), 10)
            diagnostics = await errors
            if diagnostics:
                error.add_note(diagnostics.decode(errors="replace"))
            raise
        finally:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), 10)
            await asyncio.gather(
                *(controller.close() for controller in controllers),
                return_exceptions=True,
            )
            await asyncio.gather(
                *(client.close() for client in [*clients, stop]), return_exceptions=True
            )
            directory.close()
            process.stdin.close()
            await asyncio.gather(errors, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 90))
