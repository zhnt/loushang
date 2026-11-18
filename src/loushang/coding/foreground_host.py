"""Foreground workspace-capable AppHost for an external service manager.

launchd owns the process lifetime. The application continuity lease owns its
Mux history; no second native-process registry or watchdog is introduced.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import token_hex

from loushang.appserver.managed_mux import ManagedMuxCreatedV1, ManagedMuxCreateV1
from loushang.appservice.managed_mux import CommitMux, ManagedMuxServiceBindingV1
from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.machine_resources import prepare_private_directory_chain

from .managed_bootstrap import CodingManagedApplicationLaunchV1
from .managed_local import CodingManagedLocalCommandV1, CodingManagedLocalLaunchV1


@dataclass
class _CreationAdmission:
    owner: NamedMuxProvisioner
    request: ManagedMuxCreateV1

    async def acquire(self) -> None:
        if self.owner.fenced or self.owner.issued.get(self.request.operation_id) != self.request:
            raise ValueError("foreground_mux_fenced")

    def check_creation(self, previous: ManagedMuxCreatedV1 | None) -> None:
        if previous is not None and (previous.operation_id, previous.name) != (
            self.request.operation_id, self.request.name,
        ):
            raise ValueError("foreground_mux_conflict")

    async def close(self) -> None:
        # This permit borrows process-local authority; there is no native lease.
        return None


class NamedMuxProvisioner:
    """Mint only internal named-Mux permits, fenced with this Host instance.

    Stable operation IDs replay the application's existing continuity receipts
    after restart. A per-process secret prevents callers from minting permits.
    AppService retains its state lock and original permit through the commit.
    """

    def __init__(self, application_root: Path) -> None:
        self.service = sha256(str(application_root).encode()).hexdigest()
        self.instance = token_hex(16)
        self.fenced = False
        self.issued: dict[str, ManagedMuxCreateV1] = {}
        self.binding = ManagedMuxServiceBindingV1(
            "coding.default", self.service, self.instance, self.prepare,
            ensure_named=self.ensure_named,
        )

    def prepare(self, request: ManagedMuxCreateV1) -> _CreationAdmission:
        if self.fenced or self.issued.get(request.operation_id) != request:
            raise ValueError("foreground_mux_not_admitted")
        return _CreationAdmission(self, request)

    async def ensure_named(self, name: str, commit: CommitMux) -> None:
        operation = sha256(("foreground-named-mux/v1:" + name).encode()).hexdigest()[:32]
        request = self.issued.setdefault(operation, ManagedMuxCreateV1(
            self.service, self.instance, operation, name, token_hex(32),
        ))
        await commit(request)


async def run_host(home: Path) -> None:
    state = home / "state/macos-host"
    connections = state / "connections"
    for directory in (home, state, connections):
        prepare_private_directory_chain(directory)
    application = state / "application"
    provisioner = NamedMuxProvisioner(application)
    command = CodingManagedLocalCommandV1(CodingManagedLocalLaunchV1(
        CodingManagedApplicationLaunchV1(
            home, application, "coding.default", home / "data/sessions",
        ), connections, "workspace", session_discovery=True,
        instance_id=provisioner.instance, managed_mux=provisioner.binding,
    ))
    task = asyncio.current_task()
    assert task is not None
    stopping = False

    def stop() -> None:
        nonlocal stopping
        stopping = True
        provisioner.fenced = True
        command.fence()
        task.cancel()

    def ready() -> None:
        temporary = state / "endpoint.tmp"
        temporary.write_text(json.dumps({
            "pid": os.getpid(), "instanceId": provisioner.instance,
            "recordRoot": str(connections),
        }) + "\n")
        temporary.replace(state / "endpoint.json")

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop)
    loop.add_signal_handler(signal.SIGINT, stop)
    try:
        await command.run(ready=ready)
    except asyncio.CancelledError:
        if not stopping:
            raise
    finally:
        provisioner.fenced = True
        await command.close()
        loop.remove_signal_handler(signal.SIGTERM)
        loop.remove_signal_handler(signal.SIGINT)


def main() -> None:
    asyncio.run(run_host(resolve_platform_home()))


if __name__ == "__main__":
    main()
