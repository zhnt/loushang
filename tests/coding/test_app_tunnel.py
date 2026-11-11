"""The Rust workspace client uses an app-only grant through a forwarded port."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.requires_host_runtime,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lifecycle"),
]


def test_managed_app_tunnel_accepts_rust_without_web_or_local_record(tmp_path):
    manifest = Path(__file__).resolve().parents[2] / "gui/contracts/rust/Cargo.toml"
    subprocess.run(
        [
            "cargo",
            "build",
            "--offline",
            "--locked",
            "--manifest-path",
            str(manifest),
            "--bin",
            "workspace_probe",
        ],
        check=True,
        timeout=120,
    )
    probe = manifest.parent / "target/debug/workspace_probe"
    home = tmp_path / "host"
    home.mkdir(mode=0o700)
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(manifest.parents[3] / "src"),
        "LOUSHANG_HOME": str(home),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "LOUSHANG_TMPDIR": str(tmp_path / "temporary"),
    }
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        server_port = reserved.getsockname()[1]

    def host(*arguments):
        return subprocess.check_output(
            [sys.executable, "-m", "loushang.coding.cli.lmux", *arguments],
            env=env,
            text=True,
            timeout=90,
        )

    credential = Path(
        host("server", "provision-tunnel", "--port", str(server_port)).strip()
    )
    client = tmp_path / "client"
    client.mkdir(mode=0o700)
    admitted = client / credential.name
    shutil.copy2(credential, admitted)

    async def scenario():
        peers = set()

        async def forward(reader, writer):
            task = asyncio.current_task()
            peers.add(task)
            upstream = None
            try:
                remote, upstream = await asyncio.open_connection(
                    "127.0.0.1", server_port
                )

                async def copy(source, sink):
                    while chunk := await source.read(65536):
                        sink.write(chunk)
                        await sink.drain()
                    sink.write_eof()

                await asyncio.gather(copy(reader, upstream), copy(remote, writer))
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                for stream in (writer, upstream):
                    if stream is not None:
                        stream.close()
                        with suppress(OSError):
                            await stream.wait_closed()
                peers.discard(task)

        async with await asyncio.start_server(forward, "127.0.0.1", 0) as relay:
            port = relay.sockets[0].getsockname()[1]

            async def request(*arguments, check=True):
                process = await asyncio.create_subprocess_exec(
                    str(probe),
                    "--tunnel-port",
                    str(port),
                    str(client),
                    *arguments,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                output, errors = await asyncio.wait_for(process.communicate(), 15)
                if check:
                    assert process.returncode == 0, errors.decode()
                    return json.loads(output)
                assert process.returncode != 0

            try:
                opened = await request("register", str(workspace))
                assert opened[0]["path"] == str(workspace)
                assert await request("list") == opened
                original = admitted.read_bytes()
                wrong = json.loads(original)
                wrong["key"] = "00" * 32
                admitted.write_text(json.dumps(wrong))
                await request("list", check=False)
                admitted.write_bytes(original)
                assert await request("list") == opened
                return opened
            finally:
                await asyncio.gather(*tuple(peers))

    started = json.loads(host("server", "start"))
    try:
        assert started["status"] == "service_ready"
        opened = asyncio.run(asyncio.wait_for(scenario(), 30))
        assert opened[0]["path"] == str(workspace)
    finally:
        stopped = host("stop", "--server", started["serviceId"], "--yes").splitlines()[
            -1
        ]
        assert json.loads(stopped)["status"] == "stopped"
