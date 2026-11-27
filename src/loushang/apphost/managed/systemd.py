"""Readiness for an explicit foreground AppHost under an external systemd unit."""

from __future__ import annotations

from collections.abc import Callable

from loushang.apphost.local_application import _LocalApplicationStartup
from loushang.hosting.foreground_service import notify_systemd_ready


async def run_systemd_foreground_application(
    command: _LocalApplicationStartup,
    notify_socket: str | None,
    log_ready: Callable[[], None],
) -> None:
    if notify_socket is None:
        await command.run(ready=log_ready)
        return

    def ready() -> None:
        log_ready()
        notify_systemd_ready(notify_socket)

    await command.run_under_service_manager(ready=ready)
