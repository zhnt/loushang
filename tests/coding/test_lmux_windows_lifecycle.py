"""Exercise the installed lmux lifecycle through independent Windows processes."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    WorkspaceRequestV1,
)
from loushang.appservice.managed_mux import project_mux_name

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows managed AppHost lifecycle")


async def _workspace_session(record_root: str, workspace: Path, *, create: bool) -> str:
    directory = LocalConnectionDirectoryV1(Path(record_root))
    connection = LocalAppClientConnectionV1(directory, "workspace")
    try:
        await connection.start()
        client = connection.client
        if create:
            await client.workspace(WorkspaceRequestV1("register", str(workspace)))
        result = await client.workspace(WorkspaceRequestV1("open", str(workspace)))
        (info,) = result.workspaces
        assert Path(info.path) == workspace
        selector = MuxSelectorV1(name=project_mux_name(info.path))
        if create:
            await client.attach_mux(MuxAttachV1(selector))
            session = SessionOpenSpecV1(
                "coding", "windows-native-test", info.scope, info.scope_fingerprint, "Windows Session",
            )
            mux = await client.open_member(MuxMemberOpenV1(selector, session))
        else:
            mux = await client.read_mux(MuxReadV1(selector))
        (member,) = mux.members
        return member.session.session_id
    finally:
        await connection.close()
        directory.close()


def test_windows_lmux_starts_reuses_stops_and_restarts(tmp_path):
    env = {
        **os.environ,
        "LOUSHANG_HOME": str(tmp_path / "home"),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"),
        "LOUSHANG_TMPDIR": str(tmp_path / "scratch"),
    }
    command = [sys.executable, "-m", "loushang.coding.cli.lmux"]

    def invoke(*args):
        completed = subprocess.run(
            [*command, *args], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=45,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout.splitlines()[-1])

    name = "windows-native"
    workspace = tmp_path / "Windows Project"
    workspace.mkdir()
    active = False
    try:
        first = invoke("server", "start", "--name", name)
        active = True
        assert first["status"] == "service_ready"
        assert invoke("server", "start", "--name", name)["instanceId"] == first["instanceId"]

        observed = invoke("status", "--server", name)
        assert observed["serviceId"] == first["serviceId"]
        assert observed["instanceId"] == first["instanceId"]
        assert observed["recordedPhase"] == "committed"
        assert not observed["cleanlyStopped"]
        session_id = asyncio.run(_workspace_session(first["recordRoot"], workspace, create=True))

        stopped = invoke("stop", "--server", name, "--yes")
        active = False
        assert stopped["status"] == "stopped"
        assert invoke("status", "--server", name)["cleanlyStopped"]

        second = invoke("server", "start", "--name", name)
        active = True
        assert second["status"] == "service_ready"
        assert second["serviceId"] == first["serviceId"]
        assert second["instanceId"] != first["instanceId"]
        assert asyncio.run(_workspace_session(second["recordRoot"], workspace, create=False)) == session_id
        assert invoke("stop", "--server", name, "--yes")["status"] == "stopped"
        active = False
    finally:
        if active:
            subprocess.run(
                [*command, "stop", "--server", name, "--yes"], env=env, cwd=tmp_path,
                capture_output=True, text=True, timeout=45,
            )
