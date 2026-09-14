"""Opt-in Python-server/Rust-client pipe interop with public fixture keys only.

No sockets, real record files, providers or WebView. The external deadline bounds
this blocking Rust probe; it is not evidence of native transport cancellation.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from contextlib import suppress
from pathlib import Path

from loushang.appserver.framing import AppConnectionClosedError
from loushang.appserver.local_auth import authenticate_local_server
from loushang.appserver.local_record import decode_connection_record

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
EXE = CRATE / "target/debug" / ("auth_probe.exe" if os.name == "nt" else "auth_probe")
CREDENTIALS = decode_connection_record(
    (ROOT / "gui/contracts/fixtures/local-record.json").read_bytes()
).authentication


class PipeTransport:
    def __init__(self, process: asyncio.subprocess.Process, attack: str) -> None:
        self.process, self.attack = process, attack
        self.writes = 0
        self.saved = b""

    async def read(self, size: int) -> bytes:
        assert self.process.stdout is not None
        return await self.process.stdout.read(min(size, 4096))

    async def write(self, data: bytes) -> None:
        assert self.process.stdin is not None
        self.writes += 1
        if self.writes == 1 and self.attack in {
            "wrong_profile",
            "wrong_instance",
            "unknown_field",
            "duplicate_field",
            "invalid_utf8",
            "oversized_header",
            "truncated_frame",
        }:
            body = json.loads(data[4:])
            if self.attack == "wrong_profile":
                body["profile"] = "local-detachable-execution/v1"
            elif self.attack == "wrong_instance":
                body["instance"] = "b" * 32
            elif self.attack == "unknown_field":
                body["extra"] = "no"
            raw = json.dumps(body, separators=(",", ":")).encode()
            if self.attack == "duplicate_field":
                raw = raw[:-1] + b',"profile":"local-detachable/v1"}'
            elif self.attack == "invalid_utf8":
                raw = b"\xff"
            data = len(raw).to_bytes(4, "big") + raw
            if self.attack == "oversized_header":
                data = (2049).to_bytes(4, "big")
            elif self.attack == "truncated_frame":
                self.process.stdin.write(data[:-1])
                await self.process.stdin.drain()
                self.process.stdin.close()
                return
        elif self.writes == 2 and self.attack == "bad_server_proof":
            raw = json.dumps({"proof": "00" * 32}).encode()
            data = len(raw).to_bytes(4, "big") + raw
        elif self.writes == 3:
            self.saved = data
            if self.attack == "tampered_payload":
                data = data[:-1] + bytes([data[-1] ^ 1])
        elif self.writes == 4 and self.attack == "replayed_sequence":
            data = self.saved
        # Fragment header and body to exercise byte-stream, not message IO.
        for chunk in (data[:1], data[1:3], data[3:]):
            self.process.stdin.write(chunk)
            await self.process.stdin.drain()
            await asyncio.sleep(0)

    async def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await self.process.stdin.wait_closed()


async def scenario(attack: str) -> None:
    process = await asyncio.create_subprocess_exec(
        str(EXE),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    transport = PipeTransport(process, attack)
    rejected = False
    try:
        async with asyncio.timeout(10):
            try:
                channel = await authenticate_local_server(transport, CREDENTIALS)
                payloads = ("你好🙂".encode(), b"x" * 1_048_576)
                for payload in payloads:
                    await channel.send(payload)
                    assert await channel.receive() == payload, "echo mismatch"
            except (AppConnectionClosedError, BrokenPipeError, ConnectionResetError):
                rejected = True
            await transport.close()
            code = await process.wait()
            assert process.stderr is not None
            stderr = await process.stderr.read()
            if attack == "valid":
                assert not rejected and code == 0 and not stderr
            else:
                assert rejected and code != 0, f"Attack not rejected: {attack}"
                assert stderr == b"authentication probe failed\n", "unredacted failure"
    finally:
        if process.returncode is None:
            process.kill()
        async with asyncio.timeout(3):
            await transport.close()
            await process.wait()


async def run() -> None:
    attacks = (
        "valid",
        "wrong_profile",
        "wrong_instance",
        "unknown_field",
        "duplicate_field",
        "invalid_utf8",
        "oversized_header",
        "truncated_frame",
        "bad_server_proof",
        "tampered_payload",
        "replayed_sequence",
    )
    for attack in attacks:
        await scenario(attack)
        print(f"auth interop: {attack} passed", flush=True)
    print(f"Python/Rust authentication pipe interop: {len(attacks)} scenarios passed")


if __name__ == "__main__":
    cargo = Path.home() / ".cargo/bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    subprocess.run(
        [
            str(cargo),
            "+1.98.1",
            "build",
            "--offline",
            "--locked",
            "--manifest-path",
            str(CRATE / "Cargo.toml"),
            "--bin",
            "auth_probe",
        ],
        check=True,
        cwd=ROOT,
    )
    asyncio.run(run())
