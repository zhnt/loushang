from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding.hosted.foreground import NamedMuxProvisioner


def test_foreground_provisioner_rejects_unissued_permits_and_fences_stop(tmp_path):
    async def scenario():
        owner = NamedMuxProvisioner(tmp_path)
        captured = []

        async def commit(request):
            captured.append(request)
            permit = owner.prepare(request)
            await permit.acquire()
            permit.check_creation(None)
            await permit.close()

        await owner.ensure_named("gui-temporary", commit)
        await owner.ensure_named("gui-temporary", commit)
        assert captured[0] == captured[1]
        with pytest.raises(ValueError, match="not_admitted"):
            owner.prepare(replace(captured[0], authority="forged"))
        permit = owner.prepare(captured[0])
        owner.fenced = True
        with pytest.raises(ValueError, match="fenced"):
            await permit.acquire()
        with pytest.raises(ValueError, match="not_admitted"):
            NamedMuxProvisioner(tmp_path).prepare(captured[0])

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform == "win32", reason="foreground Unix service owner")
def test_foreground_workspace_and_named_mux_survive_restart(tmp_path):
    from loushang.appserver.local import LocalAppClientConnectionV1
    from loushang.appserver.local_record import LocalConnectionDirectoryV1
    from loushang.appserver.protocol import WorkspaceModelsRequestV1, WorkspaceRequestV1

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instances = []
    muxes = []
    for _ in range(2):
        with (tmp_path / "host.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", 'loushang.coding.hosted.foreground'],
                cwd=Path(__file__).resolve().parents[2],
                env={**os.environ, "LOUSHANG_HOME": str(home)}, stdout=log, stderr=log,
            )
            try:
                endpoint = home / "state/macos-host/endpoint.json"
                deadline = time.monotonic() + 20
                while process.poll() is None and time.monotonic() < deadline:
                    if endpoint.exists() and json.loads(endpoint.read_text())["pid"] == process.pid:
                        instances.append(json.loads(endpoint.read_text())["instanceId"])
                        break
                    time.sleep(0.05)
                else:
                    pytest.fail((tmp_path / "host.log").read_text())

                async def check():
                    directory = LocalConnectionDirectoryV1(home / "state/macos-host/connections")
                    connection = LocalAppClientConnectionV1(directory, "workspace")
                    try:
                        await connection.start()
                        await connection.client.workspace(WorkspaceRequestV1("register", str(workspace)))
                        await connection.client.workspace(WorkspaceRequestV1("open", str(workspace)))
                        result = await connection.client.list_muxes()
                        assert len(result.mux_spaces) == 1
                        muxes.append(result.mux_spaces[0].mux_space_id)
                        assert (await connection.client.workspace_models(WorkspaceModelsRequestV1(str(workspace)))).models
                    finally:
                        await connection.close()
                        directory.close()

                asyncio.run(check())
            finally:
                process.terminate()
                assert process.wait(timeout=20) == 0, (tmp_path / "host.log").read_text()
    assert instances[0] != instances[1]
    assert muxes[0] == muxes[1]


def test_foreground_named_operations_are_stable_across_instances(tmp_path):
    async def scenario():
        issued = []

        async def commit(request):
            issued.append(request)

        for _ in range(2):
            await NamedMuxProvisioner(tmp_path).ensure_named("gui-temporary", commit)
        assert issued[0].operation_id == issued[1].operation_id
        assert issued[0].instance_id != issued[1].instance_id
        assert issued[0].authority != issued[1].authority

    asyncio.run(scenario())
