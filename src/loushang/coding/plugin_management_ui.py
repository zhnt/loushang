"""Coding TUI commands over the fenced Product's Plugin management owner."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast

from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.plugin_management_command_sdk import (
    open_coding_plugin_management_tui_command_client,
)
from loushang.harness.host.types import HostActionResult
from loushang.harness.plugin_management.desired_command import PluginDesiredActionV1

_SAFE_CODE = re.compile(r"[a-z0-9_]{1,96}\Z")
_ACTIONS = frozenset({"enable", "disable", "remove"})
_TARGET = {
    "enable": "installed_enabled",
    "disable": "installed_disabled",
    "remove": "absent",
}
_USAGE = (
    "Usage: /plugins [list | explain OPERATION_ID | enable ID | disable ID | "
    "remove ID | repair OPERATION_ID]"
)


class CodingPluginUiCommandClient(Protocol):
    @property
    def layout(self) -> CodingPluginLifecycleStateLayout: ...

    def snapshot(
        self, *, correlation_id: str, plugin_ids: tuple[str, ...] = ()
    ) -> dict[str, object]: ...

    def submit_desired(
        self,
        *,
        plugin_id: str,
        action: PluginDesiredActionV1,
        expected_inventory_revision: int,
        operation_id: str,
        correlation_id: str,
    ) -> dict[str, object]: ...

    def repair_own_desired_operation(
        self, operation_id: str, *, correlation_id: str
    ) -> dict[str, object]: ...


def execute_coding_plugin_management_ui_command(
    workspace: str | Path,
    text: str,
    *,
    open_client: Callable[[str | Path], CodingPluginUiCommandClient] = (
        open_coding_plugin_management_tui_command_client
    ),
) -> HostActionResult:
    """Execute one explicit local command; Product owns every state transition."""

    tokens = text.split()
    if (
        len(tokens) != 3
        or tokens[0] != "/plugins"
        or tokens[1] not in _ACTIONS | {"repair"}
        or not 0 < len(tokens[2]) <= 256
        or not tokens[2].isascii()
        or not tokens[2].isprintable()
    ):
        return HostActionResult(error_message=_USAGE)
    action, subject = tokens[1:]
    try:
        client = open_client(workspace)
        if action == "repair":
            return _repair(client, subject)
        return _submit(client, action, subject)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
            code = "plugin_management_unavailable"
        return HostActionResult(error_message=f"Plugin command failed: {code}")


def _submit(
    client: CodingPluginUiCommandClient,
    action: str,
    plugin_id: str,
) -> HostActionResult:
    snapshot = client.snapshot(
        correlation_id=f"coding:tui:plugins:{action}:read",
        plugin_ids=(plugin_id,),
    )
    revisions = snapshot.get("ownerRevisions")
    revision = revisions.get("desiredState") if isinstance(revisions, dict) else None
    installations = snapshot.get("installations")
    if type(revision) is not int or revision < 0 or not isinstance(installations, list):
        raise ValueError("Plugin management snapshot is invalid")
    matches = [
        item
        for item in installations
        if isinstance(item, dict)
        and isinstance(item.get("installationKey"), dict)
        and item["installationKey"].get("pluginId") == plugin_id
    ]
    if len(matches) != 1:
        return HostActionResult(error_message=f"Plugin is not installed: {plugin_id}")
    current = matches[0].get("desiredState")
    if current == _TARGET[action]:
        return HostActionResult(status_message=f"Plugin already {current}: {plugin_id}")
    if current not in {"installed_enabled", "installed_disabled"}:
        return HostActionResult(error_message=f"Plugin is not installed: {plugin_id}")
    scope_id = getattr(client.layout, "scope_id", None)
    if not isinstance(scope_id, str) or not scope_id:
        raise ValueError("Plugin management scope is invalid")
    identity = sha256(
        json.dumps(
            {
                "action": action,
                "pluginId": plugin_id,
                "productId": "coding",
                "revision": revision,
                "scopeId": scope_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    operation_id = f"tui-plugin-desired:{identity}"
    document = client.submit_desired(
        plugin_id=plugin_id,
        action=cast(PluginDesiredActionV1, action),
        expected_inventory_revision=revision,
        operation_id=operation_id,
        correlation_id=f"coding:tui:plugins:{action}:submit",
    )
    return _format_operation(document, operation_id=operation_id, action=action)


def _repair(client: CodingPluginUiCommandClient, operation_id: str) -> HostActionResult:
    document = client.repair_own_desired_operation(
        operation_id, correlation_id="coding:tui:plugins:repair"
    )
    disposition = document.get("disposition")
    if disposition == "unknown":
        return HostActionResult(status_message=f"Plugin operation unknown: {operation_id}")
    if disposition not in {"already_terminal", "replayed_pending"}:
        raise ValueError("Plugin repair result is invalid")
    result = document.get("result")
    if not isinstance(result, dict):
        raise ValueError("Plugin repair result is invalid")
    outcome = _format_operation(result, operation_id=operation_id, action="repair")
    if outcome.error_message is not None:
        return outcome
    return HostActionResult(
        status_message=f"Plugin operation {disposition}: {operation_id}; "
        "new Session required to observe changes."
    )


def _format_operation(
    document: dict[str, object], *, operation_id: str, action: str
) -> HostActionResult:
    event = document.get("operation")
    if not isinstance(event, dict):
        raise ValueError("Plugin operation result is invalid")
    command = event.get("command")
    mutation = command.get("mutation") if isinstance(command, dict) else None
    if not isinstance(mutation, dict) or mutation.get("operationId") != operation_id:
        raise ValueError("Plugin operation changed identity")
    status = event.get("status")
    if status in {"accepted", "running"}:
        return HostActionResult(
            status_message=f"Plugin {action} pending: {operation_id}; "
            f"use /plugins repair {operation_id}."
        )
    result = event.get("result")
    if status != "terminal" or not isinstance(result, dict):
        raise ValueError("Plugin operation status is invalid")
    if result.get("disposition") == "succeeded":
        return HostActionResult(
            status_message=f"Plugin {action} succeeded: {operation_id}; "
            "new Session required to observe changes."
        )
    code = result.get("errorCode")
    if (
        result.get("disposition") != "failed"
        or not isinstance(code, str)
        or _SAFE_CODE.fullmatch(code) is None
    ):
        raise ValueError("Plugin operation failure is invalid")
    return HostActionResult(
        error_message=f"Plugin {action} failed: {code}; operation {operation_id}"
    )


__all__ = ["execute_coding_plugin_management_ui_command"]
