"""Native fault probe: delay publication of an actual Hosting lease only.

The installed Product CLI, process backend and terminal remain unchanged.
Only the test-owned host wrapper delays returning its already-adopted lease
until real host.close has completed. This exercises cancellation at the
publication boundary without introducing a production test switch.
"""

from __future__ import annotations

import asyncio
import sys

from loushang.coding.cli.hosted_client import main
from loushang.harnesstui.mux import terminal
from loushang.hosting import runtime

create_host = runtime.create_process_host
run_terminal = terminal.run_hosted_mux_shell


async def observe_terminal(*args, **kwargs):
    print("G17 terminal invoked", flush=True)
    return await run_terminal(*args, **kwargs)


class HeldPublicationHost:
    def __init__(self, **kwargs):
        self._host = create_host(**kwargs)
        self._closed = asyncio.Event()

    async def start(self, *args):
        lease = await self._host.start(*args)
        print("G17 publication held", flush=True)
        try:
            await self._closed.wait()
        except asyncio.CancelledError:
            # A real backend can finish publication after cancellation. Preserve
            # that race deliberately; the host still owns/reaps the real child.
            print("G17 publication cancelled", flush=True)
            await self._closed.wait()
        print("G17 late lease returned", flush=True)
        return lease

    async def close(self):
        await self._host.close()
        self._closed.set()


runtime.create_process_host = HeldPublicationHost
terminal.run_hosted_mux_shell = observe_terminal
raise SystemExit(main(sys.argv[1:]))
