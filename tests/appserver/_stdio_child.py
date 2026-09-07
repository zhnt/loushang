"""Native transport fixture, not the G14 production Product composition."""

from __future__ import annotations

import asyncio
import sys
from typing import cast

from loushang.appserver.client import AppClientV1
from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol import (
    AckV1,
    AppServiceError,
    MuxListResultV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.appserver.stdio import InheritedStdioTransportV1


class _Client:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def list_muxes(self) -> MuxListResultV1:
        return MuxListResultV1(())

    async def start_turn(self, _request: TurnTextV1) -> AckV1:
        await self.release.wait()
        return AckV1()

    async def interrupt_turn(self, _request: TurnInterruptV1) -> AckV1:
        self.release.set()
        return AckV1()


async def main() -> None:
    transport = InheritedStdioTransportV1(
        input_fd=sys.stdin.fileno(), output_fd=sys.stdout.fileno()
    )
    server = AppServerConnectionV1(
        cast(AppClientV1, _Client()), AppFramedStreamV1(transport), phase_timeout=1.0
    )
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AppServiceError as error:
        print(error.code.value, file=sys.stderr)
        raise SystemExit(1) from None
