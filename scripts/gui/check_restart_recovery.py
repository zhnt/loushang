"""Opt-in real CLI restart regression using the production Rust snapshot adapter.

Only temporary state is used. No provider requests, model overrides or CI gates.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from native_tools import cargo_path, native_binary

from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxSelectorV1,
    SessionSubmissionModeV1,
)

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
PROBE = native_binary(CRATE / "target/debug", "snapshot_probe")
MUX = "restart-regression"


def command(root: Path, action: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "loushang.coding.cli.mux",
        "--connection-root",
        str(root / "connection"),
        "--endpoint",
        "workspace",
        action,
    ]


async def snapshot(root: Path) -> dict:
    process = await asyncio.create_subprocess_exec(
        str(PROBE),
        str(root / "connection"),
        "5000",
        MUX,
        "--prepare-default",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def run(root: Path) -> None:
    (root / "workspace").mkdir()
    original = None
    history = None
    instances: set[str] = set()
    for cycle in range(3):
        host = await asyncio.create_subprocess_exec(
            *command(root, "serve"),
            "--workspace",
            str(root / "workspace"),
            "--application-root",
            str(root / "app"),
            "--application-id",
            "gui.restart",
            "--cwd-sessions",
            str(root / "cwd-sessions"),
            "--home-sessions",
            str(root / "home-sessions"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert host.stdout is not None
            ready = json.loads(await asyncio.wait_for(host.stdout.readline(), 15))
            assert ready["status"] == "ready"
            client = LocalAppClientConnectionV1(
                LocalConnectionDirectoryV1(root / "connection"), "workspace"
            )
            await client.start()
            try:
                if cycle == 0:
                    await client.client.create_mux(MuxCreateV1(MUX))
                else:
                    attached = await client.client.attach_mux(
                        MuxAttachV1(MuxSelectorV1(name=MUX))
                    )
                    assert len(attached.sessions) == 1
                    assert (
                        attached.sessions[0].snapshot.submission_mode
                        is SessionSubmissionModeV1.EXECUTION
                    )
                    await client.client.detach_mux(
                        MuxDetachV1(
                            attached.attachment_id, attached.controller_generation
                        )
                    )
            finally:
                await client.close()
            current = await snapshot(root)
            assert len(current["sessions"]) == 1
            assert current["serviceInstanceId"] not in instances
            instances.add(current["serviceInstanceId"])
            identity = current["sessions"][0]["source"]["source"]["identity"]
            members = current["muxSpace"]["members"]
            persisted = {
                p.name: p.read_bytes() for p in (root / "cwd-sessions").glob("*.jsonl")
            }
            assert persisted
            if original is None:
                original = (identity, members)
                history = persisted
            else:
                assert (identity, members) == original, (
                    "restart duplicated or replaced the Session"
                )
                assert persisted == history, "restart changed transcript history"
            print(
                f"Restart cycle {cycle}: native snapshot accepted; Session and history preserved",
                flush=True,
            )
            stop = await asyncio.create_subprocess_exec(
                *command(root, "stop"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(stop.communicate(), 10)
            assert stop.returncode == 0
            await asyncio.wait_for(host.communicate(), 15)
            assert host.returncode == 0
        finally:
            if host.returncode is None:
                host.terminate()
                try:
                    await asyncio.wait_for(host.communicate(), 5)
                except TimeoutError:
                    host.kill()
                    await host.communicate()


if __name__ == "__main__":
    subprocess.run(
        [
            str(cargo_path()),
            "+1.98.1",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(CRATE / "Cargo.toml"),
            "--bin",
            "snapshot_probe",
        ],
        check=True,
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="gui-restart-regression-") as temporary:
        asyncio.run(asyncio.wait_for(run(Path(temporary).resolve()), 120))
