from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from loushang.appserver.framing import AppFramedStreamV1, AsyncioStreamTransportV1
from loushang.appserver.protocol import (
    AckV1,
    MuxListResultV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.appserver.remote_client import StdioAppClientV1


def test_G14_PLATFORMS_native_stdio_negotiation_prompt_interrupt_and_eof() -> None:
    async def scenario() -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("_stdio_child.py")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        )
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        errors = asyncio.create_task(process.stderr.read())
        client = StdioAppClientV1(
            AppFramedStreamV1(AsyncioStreamTransportV1(process.stdout, process.stdin))
        )
        try:
            await client.start()
            prompt = asyncio.create_task(
                client.start_turn(TurnTextV1("a", 1, "m", "你好\n"))
            )
            assert await client.list_muxes() == MuxListResultV1(())
            assert await client.interrupt_turn(TurnInterruptV1("a", 1, "m")) == AckV1()
            assert await prompt == AckV1()
            await client.close()
            assert await asyncio.wait_for(process.wait(), 10) == 0
            assert await errors == b""
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(errors, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_G14_OWNERSHIP_parked_stdin_read_cannot_prevent_process_exit() -> None:
    async def scenario() -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("_stdio_child.py")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        )
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        output = asyncio.create_task(process.stdout.read())
        errors = asyncio.create_task(process.stderr.read())
        try:
            # Deliberately keep stdin open without answering the server hello.
            assert await asyncio.wait_for(process.wait(), 10) == 1
            assert await output
            assert (
                await errors == b"service_closed\n"
                or await errors == b"service_closed\r\n"
            )
        finally:
            process.stdin.close()
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(output, errors, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 20))
