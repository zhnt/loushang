"""Windows loopback fixture: admitted record -> auth -> hello -> owned close.

No existing service/provider, remote network, GUI or product runtime is involved.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from loushang.appserver.execution.codec import execution_hello
from loushang.appserver.framing import (
    AppConnectionClosedError,
    AsyncioStreamTransportV1,
)
from loushang.appserver.local_auth import authenticate_local_server
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import SessionScopeV1

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
EXE = CRATE / "target/debug/connection_probe.exe"


async def scenario(root: Path, attack: str) -> None:
    directory = LocalConnectionDirectoryV1(root)
    tasks: list[asyncio.Task] = []
    modes = [attack, "valid"]
    record = None

    async def peer(reader, writer):
        mode = modes.pop(0)
        transport = AsyncioStreamTransportV1(reader, writer)
        try:
            if mode in {"auth-stall", "cancel-auth"}:
                assert await reader.read() == b""
                return
            if mode == "slow-header":
                # One byte at a time: a per-read timeout would keep extending.
                for byte in b"\x00\x00\x00\x40" + b"x" * 16:
                    writer.write(bytes([byte]))
                    await writer.drain()
                    await asyncio.sleep(0.12)
                assert await reader.read() == b""
                return
            assert record is not None
            channel = await authenticate_local_server(transport, record.authentication)
            assert await channel.receive() == b"app", "must never send stop mode"
            if mode in {"hello-stall", "cancel-hello"}:
                assert await reader.read() == b""
                return
            profile = "local-detachable-execution/v1"
            if mode == "wrong-profile":
                profile = "local-detachable-discovery-execution/v1"
            hello = execution_hello(profile, "service-fixture")
            if mode == "noncanonical-hello":
                hello = json.dumps(json.loads(hello), indent=2).encode()
            await channel.send(hello)
            if mode in {"wrong-profile", "noncanonical-hello"}:
                assert await reader.read() == b""
                return
            assert await channel.receive() == hello
            assert await reader.read() == b"", "client must close borrowed connection"
        except (AppConnectionClosedError, ConnectionError):
            if mode == "valid":
                raise
        finally:
            try:
                await transport.close()
            except ConnectionError:
                if mode == "valid":
                    raise

    def accepted(reader, writer):
        tasks.append(asyncio.create_task(peer(reader, writer)))

    server = await asyncio.start_server(accepted, "127.0.0.1", 0)
    try:
        record = directory.acquire("workspace").publish(
            application_id="application",
            product_id="coding",
            port=server.sockets[0].getsockname()[1],
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "b" * 64),),
            session_execution=True,
        )
        for mode in (attack, "valid"):
            cancel = 100 if mode.startswith("cancel-") else -1
            timeout = (
                300 if mode in {"auth-stall", "hello-stall", "slow-header"} else 2000
            )
            started = time.monotonic()
            process = await asyncio.create_subprocess_exec(
                str(EXE),
                str(root),
                str(timeout),
                str(cancel),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(5):
                    stdout, stderr = await process.communicate()
                elapsed = time.monotonic() - started
                if mode == "valid":
                    assert process.returncode == 0 and not stderr
                    assert (
                        stdout
                        == b"hello verified; connection closed; instance=service-fixture\n"
                    )
                else:
                    assert process.returncode == 1 and not stdout
                    assert stderr == b"connection probe failed\n"
                    if cancel >= 0:
                        assert elapsed < 1.5, "cancel waited for startup deadline"
                    if timeout == 300:
                        assert elapsed < 1.5, "startup deadline was extended"
                assert server.is_serving(), "client must not shut down listener"
                async with asyncio.timeout(2):
                    await asyncio.gather(*tasks)
                tasks.clear()
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        assert not modes
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        directory.close()


async def run(parent: Path) -> None:
    attacks = (
        "valid",
        "auth-stall",
        "hello-stall",
        "cancel-auth",
        "cancel-hello",
        "slow-header",
        "wrong-profile",
        "noncanonical-hello",
    )
    for attack in attacks:
        await scenario(parent / attack, attack)
        print(f"Connection lifecycle: {attack} + fresh client passed", flush=True)
    print("Windows loopback lifecycle: 8 scenarios / 16 connections passed")


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Connection lifecycle fixture requires Windows")
    subprocess.run(
        [
            str(Path.home() / ".cargo/bin/cargo.exe"),
            "+1.98.1",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(CRATE / "Cargo.toml"),
            "--bin",
            "connection_probe",
        ],
        check=True,
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="gui-connection-contract-") as temporary:
        asyncio.run(run(Path(temporary).resolve()))
