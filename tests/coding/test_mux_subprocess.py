from __future__ import annotations

import asyncio
import json
import socket
import sys
from secrets import token_hex

import pytest

from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import MuxAttachV1, MuxSelectorV1

from .test_hosted_subprocess import _environment
from .test_mux_command import _selector, _serve


async def _errors(stream):
    tail = b""
    while chunk := await stream.read(4096):
        tail = (tail + chunk)[-16384:]
    return tail


async def _client(root, *args, expected=0):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "loushang.coding.cli.mux",
        *_selector(root),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_environment(root),
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), 30)
        assert process.returncode == expected, errors.decode(errors="replace")
        if expected == 0:
            assert not errors
            return json.loads(output)
        assert output == b""
        return errors
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def test_G16_PROCESS_explicit_server_survives_stdin_eof_and_separate_management_clients(
    tmp_path,
):
    async def scenario():
        root = tmp_path.resolve()
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "loushang.coding.cli.mux",
            *_serve(root),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(root),
        )
        errors = asyncio.create_task(_errors(process.stderr))
        directory = LocalConnectionDirectoryV1(root / "connections")
        controller = LocalAppClientConnectionV1(
            directory, "workspace", expected_product_id="coding"
        )
        try:
            ready = json.loads(await asyncio.wait_for(process.stdout.readline(), 35))
            assert (
                ready["status"] == "ready" and ready["profile"] == "local-detachable/v1"
            )
            assert "key" not in ready and "port" not in ready
            assert str(root) not in str(ready)
            process.stdin.close()  # EOF is not an application stop in G16.
            await process.stdin.wait_closed()
            assert (await _client(root, "list"))["muxes"] == []
            mux = await _client(root, "create", "dev")
            assert mux["name"] == "dev"
            assert (await _client(root, "list"))["muxes"][0]["muxId"] == mux["muxId"]
            await controller.start()
            await controller.client.attach_mux(MuxAttachV1(MuxSelectorV1(name="dev")))
            assert b"already_attached" in await _client(
                root, "close", "dev", "--yes", expected=1
            )
            assert len((await controller.client.list_muxes()).mux_spaces) == 1
            await controller.close()
            assert (await _client(root, "close", "dev", "--yes"))[
                "status"
            ] == "mux_closed"
            assert (await _client(root, "list"))["muxes"] == []
            assert (await _client(root, "stop"))["status"] == "stop_requested"
            assert await asyncio.wait_for(process.wait(), 20) == 0
            assert await errors == b""
        except BaseException as error:
            if process.returncode is None:
                process.kill()
                await process.wait()
            diagnostics = await errors
            if diagnostics:
                error.add_note(diagnostics.decode(errors="replace"))
            raise
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await controller.close()
            directory.close()
            await asyncio.gather(errors, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 120))


@pytest.mark.skipif(sys.platform != "linux", reason="systemd host mode requires Linux")
def test_systemd_host_notifies_after_publish_and_cleans_up_on_sigterm(tmp_path):
    async def scenario():
        root = tmp_path.resolve()
        address = f"loushang-mux-test-{token_hex(16)}"
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
            notify.bind("\0" + address)
            notify.setblocking(False)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "loushang.coding.cli.mux",
                *_serve(root),
                "--systemd",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**_environment(root), "NOTIFY_SOCKET": "@" + address},
            )
            errors = asyncio.create_task(_errors(process.stderr))
            try:
                notification = await asyncio.wait_for(
                    asyncio.get_running_loop().sock_recv(notify, 128), 35
                )
                assert notification == b"READY=1"
                assert (await _client(root, "list"))["muxes"] == []
                process.terminate()
                assert await asyncio.wait_for(process.wait(), 35) == 0
                assert not list((root / "connections").glob("*.json"))
                assert await errors == b""
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                diagnostics = await errors
                if diagnostics:
                    print(diagnostics.decode(errors="replace"), file=sys.stderr)

    asyncio.run(asyncio.wait_for(scenario(), 110))
