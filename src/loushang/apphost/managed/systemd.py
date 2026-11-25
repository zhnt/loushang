"""Local AppHost endpoints and handoff to an external systemd manager."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import cast

from loushang.apphost.local_application import (
    _LocalApplicationStartup,
    publish_local_service_endpoint,
)
from loushang.hosting.foreground_service import (
    in_current_systemd_scope,
    notify_systemd_ready,
    read_systemd_user_unit,
)
from loushang.hosting.foreground_service import (
    run_systemd_user_action as run_systemd_user_action,
)


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


def start_systemd_application(
    control: Callable[[str, str | None], Coroutine[object, object, dict[str, object]]],
    notify_socket: str,
    endpoint: Callable[[], Path],
    *,
    control_error: type[Exception],
) -> bool:
    """Publish the exact managed service endpoint before handing off its PID."""
    started = None
    try:
        if asyncio.run(control("status", None))["state"] == "running":
            return False
        result = asyncio.run(control("start", None))
        pid = result.get("pid")
        if result["state"] != "running" or type(pid) is not int or pid <= 0:
            return False
        if not in_current_systemd_scope(pid):
            return False
        started = result
        publish_local_service_endpoint(endpoint(), {"recordRoot": started["recordRoot"]})
        notify_systemd_ready(notify_socket, pid=pid)
    except (control_error, OSError, ValueError, KeyError):
        if started is not None:
            instance = cast("str | None", started.get("instanceId"))
            asyncio.run(control("stop", instance))
        return False
    return True


def read_systemd_application_state(
    unit: str, endpoint: Callable[[], Path], *, error: Callable[[str], Exception],
) -> dict[str, object]:
    properties = read_systemd_user_unit(unit)
    if properties.get("LoadState") != "loaded":
        raise error("management_unavailable")
    state = properties.get("ActiveState", "")
    if state != "active":
        return {"state": {
            "inactive": "not_running", "activating": "starting",
            "deactivating": "stopping", "failed": "exited",
        }.get(state, "unknown")}
    instance = properties.get("InvocationID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", instance):
        raise error("management_unavailable")
    try:
        record_root = json.loads(endpoint().read_text())["recordRoot"]
        if type(record_root) is not str or not Path(record_root).is_absolute():
            raise ValueError("invalid record root")
    except (OSError, ValueError, KeyError, TypeError) as cause:
        raise error("management_unavailable") from cause
    return {"state": "running", "instanceId": instance, "recordRoot": record_root}


def control_systemd_application(
    operation: str, expected: str | None, *, unit: str, endpoint: Callable[[], Path],
    error: Callable[[str], Exception],
) -> dict[str, object]:
    if expected is not None and read_systemd_application_state(unit, endpoint, error=error).get("instanceId") != expected:
        raise error("instance_changed")
    if operation != "status" and run_systemd_user_action(operation, unit, quiet=True) != 0:
        raise error(f"{operation}_failed")
    return read_systemd_application_state(unit, endpoint, error=error)
