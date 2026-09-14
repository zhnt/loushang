"""Bounded attachment/snapshot/detach loopback fixture; no live AppHost."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from loushang.appserver.execution import model as em
from loushang.appserver.execution.codec import (
    decode_call,
    execution_hello,
)
from loushang.appserver.execution.codec import (
    encode_response as execution_response,
)
from loushang.appserver.framing import AsyncioStreamTransportV1
from loushang.appserver.local_auth import authenticate_local_server
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import model as pm
from loushang.appserver.protocol.codec import decode_request, encode_response
from loushang.appserver.protocol.errors import AppErrorCodeV1, AppFailureV1

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
EXE = CRATE / "target/debug/connection_probe.exe"
GENERATION = 2**100 + 1


def fixture():
    sessions = []
    for index in range(2):
        identity = pm.SessionIdentityV1(
            "coding",
            f"continuity-{index}",
            f"session-{index}",
            pm.SessionScopeV1.CWD,
            "b" * 64,
        )
        member = pm.MuxSpaceMemberV1(
            f"member-{index}", identity, f"会话 {index}", index + 1
        )
        source = pm.SessionSnapshotV1(
            identity,
            member.title,
            2**100 + 3,
            0,
            False,
            (pm.TranscriptRecordV1(pm.TranscriptRecordKindV1.USER, "你好🙂"),),
        )
        sessions.append(pm.AttachedSessionV1(member, source))
    mux = pm.MuxSpaceV1(
        "mux", "gui-fixture", 2**100 + 2, tuple(item.member for item in sessions)
    )
    return pm.MuxAttachmentV1("attachment", mux, GENERATION, tuple(sessions))


async def scenario(root: Path, mode: str) -> None:
    directory = LocalConnectionDirectoryV1(root)
    tasks = []
    record = None
    seen = []
    attachment = fixture()

    async def peer(reader, writer):
        transport = AsyncioStreamTransportV1(reader, writer)
        try:
            assert record is not None
            channel = await authenticate_local_server(transport, record.authentication)
            assert await channel.receive() == b"app"
            hello = execution_hello("local-detachable-execution/v1", "service-fixture")
            await channel.send(hello)
            assert await channel.receive() == hello
            call = decode_request(await channel.receive())
            assert call.operation is pm.AppOperationV1.MUX_ATTACH
            assert call.request_id == "1"
            assert call.payload.selector.name == "gui-fixture"
            seen.append("attach")
            if mode == "already-attached":
                await channel.send(
                    encode_response(
                        pm.AppResponseV1(
                            call.request_id,
                            AppFailureV1(AppErrorCodeV1.ALREADY_ATTACHED),
                        )
                    )
                )
                assert await reader.read() == b"", (
                    "conflict must not trigger takeover or retry"
                )
                return
            raw = encode_response(pm.AppResponseV1(call.request_id, attachment))
            if mode == "bad-attachment":
                value = json.loads(raw)
                value["result"]["sessions"][0]["member"]["memberId"] = "wrong-member"
                raw = json.dumps(value).encode()
            await channel.send(raw)
            if mode == "bad-attachment":
                assert await reader.read() == b""
                return
            for index, session in enumerate(attachment.sessions):
                call = decode_call(await channel.receive())
                assert call.operation is em.ExecutionOperationV1.SNAPSHOT
                assert call.request_id == str(index + 2)
                assert (
                    call.control.attachment_id == "attachment"
                    and call.control.controller_generation == GENERATION
                )
                assert call.control.member_id == session.member.member_id
                assert call.expected_instance_id == "service-fixture"
                seen.append(f"snapshot-{index}")
                idle = em.ExecutionObservationV1()
                snapshot = em.ExecutionSessionSnapshotV1(
                    "service-fixture",
                    em.ExecutionSourceSnapshotV1(session.snapshot, idle),
                    em.ExecutionSessionViewV1(session.member.session, 0, idle),
                )
                raw = execution_response(
                    em.ExecutionResponseV1(call.request_id, snapshot)
                )
                if index == 1 and mode in {
                    "instance-changed",
                    "identity-changed",
                    "cursor-regressed",
                    "wrong-request",
                    "bad-snapshot",
                }:
                    value = json.loads(raw)
                    if mode == "instance-changed":
                        value["result"]["serviceInstanceId"] = "other-instance"
                    elif mode == "identity-changed":
                        value["result"]["source"]["source"]["identity"]["sessionId"] = (
                            "other-session"
                        )
                        value["result"]["executions"]["identity"]["sessionId"] = (
                            "other-session"
                        )
                    elif mode == "cursor-regressed":
                        value["result"]["source"]["source"]["cursor"] = 0
                    elif mode == "wrong-request":
                        value["requestId"] = "other-request"
                    else:
                        value["result"]["source"]["source"]["cursor"] = True
                    raw = json.dumps(value).encode()
                await channel.send(raw)
            call = decode_request(await channel.receive())
            assert call.operation is pm.AppOperationV1.MUX_DETACH
            assert call.request_id == str(len(attachment.sessions) + 2)
            assert (
                call.payload.attachment_id == "attachment"
                and call.payload.controller_generation == GENERATION
            )
            seen.append("detach")
            result = (
                AppFailureV1(AppErrorCodeV1.CLEANUP_INCOMPLETE)
                if mode == "detach-failed"
                else pm.AckV1()
            )
            await channel.send(
                encode_response(pm.AppResponseV1(call.request_id, result))
            )
            assert await reader.read() == b"", (
                "must close after detach, not stop application"
            )
        finally:
            await transport.close()

    server = await asyncio.start_server(
        lambda r, w: tasks.append(asyncio.create_task(peer(r, w))), "127.0.0.1", 0
    )
    process = None
    try:
        record = directory.acquire("workspace").publish(
            application_id="application",
            product_id="coding",
            port=server.sockets[0].getsockname()[1],
            scopes=(LocalRecordScopeV1(pm.SessionScopeV1.CWD, "b" * 64),),
            session_execution=True,
        )
        process = await asyncio.create_subprocess_exec(
            str(EXE),
            str(root),
            "3000",
            "-1",
            "--attach",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with asyncio.timeout(6):
            stdout, stderr = await process.communicate()
            await asyncio.gather(*tasks)
        if mode == "valid":
            assert process.returncode == 0 and not stderr
            assert (
                stdout
                == b"attachment snapshots verified; detached; connection closed; instance=service-fixture\n"
            )
        else:
            assert process.returncode == 1 and not stdout
            assert stderr == b"connection probe failed\n"
        assert seen == (
            ["attach"]
            if mode in {"already-attached", "bad-attachment"}
            else ["attach", "snapshot-0", "snapshot-1", "detach"]
        )
        assert server.is_serving()
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        directory.close()


async def run(parent):
    modes = (
        "valid",
        "already-attached",
        "bad-attachment",
        "instance-changed",
        "identity-changed",
        "cursor-regressed",
        "wrong-request",
        "bad-snapshot",
        "detach-failed",
    )
    for mode in modes:
        await scenario(parent / mode, mode)
        print(f"Attachment lifecycle: {mode} passed", flush=True)
    print("Windows attachment lifecycle: 9 scenarios passed")


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Attachment lifecycle fixture requires Windows")
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
    with tempfile.TemporaryDirectory(prefix="gui-attachment-contract-") as temporary:
        asyncio.run(run(Path(temporary).resolve()))
