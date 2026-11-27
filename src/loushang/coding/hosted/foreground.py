"""Foreground workspace-capable AppHost for an external service manager.

The caller or external supervisor owns the process lifetime. The application
continuity lease owns its Mux history.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from loushang.apphost.local_application import (
    ForegroundNamedMuxProvisioner,
    publish_local_service_endpoint,
)
from loushang.coding.hosted.managed.bootstrap import CodingManagedApplicationLaunchV1
from loushang.coding.hosted.managed.local import (
    CodingManagedLocalCommandV1,
    CodingManagedLocalLaunchV1,
)
from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.machine_resources import prepare_private_directory_chain


class NamedMuxProvisioner(ForegroundNamedMuxProvisioner):
    """Bind the original foreground Mux authority to the Coding application."""

    def __init__(self, application_root: Path) -> None:
        super().__init__(application_root, application_id="coding.default")


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
    def ready() -> None:
        publish_local_service_endpoint(state / "endpoint.json", {
            "pid": os.getpid(), "instanceId": provisioner.instance,
            "recordRoot": str(connections),
        })

    await command.run_under_service_manager(
        ready=ready, include_interrupt=True, fence_external_admission=provisioner.fence,
    )


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(run_host(resolve_platform_home()))


if __name__ == "__main__":
    main()
