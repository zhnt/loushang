"""Native recovery fault seam over installed Product and real Hosting IO.

Only this test launcher substitutes a fixed child script. The script delegates
to the real service main and holds a genuinely reopened Session before recovery
publication. No factory selection or fault flag enters the shipped CLI.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path


def child(arguments):
    from loushang.appservice.continuity_runtime import AppServiceRecoveryAttemptV1
    from loushang.coding.cli.hosted import main

    recover = AppServiceRecoveryAttemptV1._recover_session

    async def held_recovery(self, identity, title):
        owner = await recover(self, identity, title)
        try:
            marker = Path("recovery-held.pending")
            marker.write_text(json.dumps(asdict(owner.identity)))
            marker.replace("recovery-held")
            await asyncio.Event().wait()
        finally:
            await owner.close()
        return owner

    AppServiceRecoveryAttemptV1._recover_session = held_recovery
    return main(arguments)


def controller(arguments):
    from loushang.coding.cli import hosted_client
    from loushang.harnesstui.mux import terminal

    launch_request = hosted_client._launch_request
    run_terminal = terminal.run_hosted_mux_shell

    def request(launch):
        original = launch_request(launch)
        return replace(original, argv=(
            sys.executable, "-I", str(Path(__file__).resolve()), "--child",
            *original.argv[4:],
        ))

    async def observe_terminal(*args, **kwargs):
        print("G17 terminal invoked", flush=True)
        return await run_terminal(*args, **kwargs)

    hosted_client._launch_request = request
    terminal.run_hosted_mux_shell = observe_terminal
    return hosted_client.main(arguments)


if __name__ == "__main__":
    raise SystemExit(child(sys.argv[2:]) if sys.argv[1] == "--child" else controller(sys.argv[1:]))
