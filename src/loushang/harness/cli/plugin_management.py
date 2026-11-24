"""Transport bindings and terminal commands for Plugin management."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, TypeGuard, cast, runtime_checkable

from loushang.harness.host.types import HostActionResult
from loushang.harness.plugin_management import (
    PluginManagementApplicationPorts,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.application import (
    PluginSourceProjectionSourcePort,
)
from loushang.harness.plugin_management.desired_command import PluginDesiredActionV1
from loushang.harness.plugin_management.operations import (
    PLUGIN_DESIRED_ACTIONS,
    desired_state_for_action,
)
from loushang.harness.plugin_management.read_binding import (
    empty_management_read_ports,
    read_only_management_ports,
)


def _validate_profile_identity(
    product_id: str,
    installation_scope: str,
    scope_id: str,
    actor_id: str,
    policy_revision: str,
) -> None:
    for value, name in (
        (product_id, "Product id"),
        (scope_id, "scope id"),
        (actor_id, "actor id"),
        (policy_revision, "policy revision"),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be non-empty")
    if installation_scope not in {"process", "tenant", "workspace"}:
        raise ValueError("Unsupported Plugin Installation scope")


@dataclass(frozen=True, slots=True)
class PluginManagementCliBinding:
    ports: PluginManagementApplicationPorts
    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    actor_id: str
    policy_revision: str
    publish_compatibility_projection: Callable[[], None] | None = None
    fresh_product: bool = False

    def __post_init__(self) -> None:
        _validate_profile_identity(
            self.product_id,
            self.installation_scope,
            self.scope_id,
            self.actor_id,
            self.policy_revision,
        )
        if type(self.fresh_product) is not bool:
            raise TypeError("Plugin management Product mode is invalid")

    def query(
        self,
        *,
        correlation_id: str,
        plugin_ids: tuple[str, ...] = (),
    ) -> PluginManagementProjectionV1:
        return self.ports.queries.snapshot(
            PluginManagementQueryV1(
                correlation_id=correlation_id,
                product_id=self.product_id,
                installation_scope=self.installation_scope,
                scope_id=self.scope_id,
                plugin_ids=tuple(sorted(set(plugin_ids))),
            )
        )

    def publish_compatibility(self) -> None:
        """Publish an optional Product-owned downgrade view after a write."""

        if self.publish_compatibility_projection is not None:
            self.publish_compatibility_projection()


@dataclass(frozen=True, slots=True)
class PluginManagementCliProfile:
    """Immutable Product facts shared by the command and read bindings."""

    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    actor_id: str
    policy_revision: str
    def __post_init__(self) -> None:
        _validate_profile_identity(
            self.product_id,
            self.installation_scope,
            self.scope_id,
            self.actor_id,
            self.policy_revision,
        )


@runtime_checkable
class PluginManagementCliReadOwnerStrategy(Protocol):
    """Only owner reads needed to choose fenced, legacy, or empty state."""

    @property
    def source(self) -> PluginSourceProjectionSourcePort: ...

    def fenced_product_exists(self) -> bool: ...

    def open_fenced_ports(self) -> PluginManagementApplicationPorts: ...

    def legacy_state_exists(self) -> bool: ...

    def open_legacy_read_ports(self) -> PluginManagementApplicationPorts: ...


@runtime_checkable
class PluginManagementCliCommandOwnerStrategy(Protocol):
    """Owner commands and Product-owned legacy startup cleanup."""

    def fenced_product_exists(self) -> bool: ...

    def open_fenced_ports(self) -> PluginManagementApplicationPorts: ...

    def acquire_legacy_startup(self) -> Callable[[], None] | None: ...

    def open_legacy_ports(self) -> PluginManagementApplicationPorts: ...

    def bind_legacy_compatibility(self) -> Callable[[], None] | None: ...


def bind_plugin_management_cli_commands(
    profile: PluginManagementCliProfile,
    owner: PluginManagementCliCommandOwnerStrategy,
) -> PluginManagementCliBinding:
    """Open one command owner; roll back a Product startup claim on failure."""

    if profile is None or not isinstance(profile, PluginManagementCliProfile):
        raise TypeError("Plugin management command Product profile is required")
    if not isinstance(owner, PluginManagementCliCommandOwnerStrategy):
        raise TypeError("Plugin management command owner strategy is required")
    if owner.fenced_product_exists():
        return PluginManagementCliBinding(
            ports=owner.open_fenced_ports(),
            product_id=profile.product_id,
            installation_scope=profile.installation_scope,
            scope_id=profile.scope_id,
            actor_id=profile.actor_id,
            policy_revision=profile.policy_revision,
            fresh_product=True,
        )
    release_on_failure = owner.acquire_legacy_startup()
    try:
        ports = owner.open_legacy_ports()
        publish = owner.bind_legacy_compatibility()
        if publish is not None:
            publish()
        return PluginManagementCliBinding(
            ports=ports,
            product_id=profile.product_id,
            installation_scope=profile.installation_scope,
            scope_id=profile.scope_id,
            actor_id=profile.actor_id,
            policy_revision=profile.policy_revision,
            publish_compatibility_projection=publish,
        )
    except BaseException:
        if release_on_failure is not None:
            release_on_failure()
        raise


def bind_plugin_management_cli_read(
    profile: PluginManagementCliProfile,
    owner: PluginManagementCliReadOwnerStrategy,
) -> PluginManagementCliBinding:
    """Choose the owner's existing state without starting or repairing it."""

    if profile is None or not isinstance(profile, PluginManagementCliProfile):
        raise TypeError("Plugin management read Product profile is required")
    if not isinstance(owner, PluginManagementCliReadOwnerStrategy):
        raise TypeError("Plugin management read owner strategy is required")
    if owner.fenced_product_exists():
        ports = owner.open_fenced_ports()
        fresh_product = True
    elif owner.legacy_state_exists():
        ports = owner.open_legacy_read_ports()
        fresh_product = False
    else:
        ports = empty_management_read_ports(owner.source)
        fresh_product = False
    return PluginManagementCliBinding(
        ports=read_only_management_ports(ports),
        product_id=profile.product_id,
        installation_scope=profile.installation_scope,
        scope_id=profile.scope_id,
        actor_id=profile.actor_id,
        policy_revision=profile.policy_revision,
        fresh_product=fresh_product,
    )


_SAFE_CODE = re.compile(r"[a-z0-9_]{1,96}\Z")
_USAGE = (
    "Usage: /plugins [list | explain OPERATION_ID | enable ID | disable ID | "
    "remove ID | repair OPERATION_ID]"
)


def is_plugin_terminal_error_code(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _SAFE_CODE.fullmatch(value) is not None


def is_plugin_terminal_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.isprintable() for item in value
    )


def valid_plugin_terminal_identifier(value: str) -> bool:
    return 0 < len(value) <= 256 and value.isascii() and value.isprintable()


class PluginTerminalCommandClient(Protocol):
    @property
    def layout(self) -> object: ...

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


def execute_plugin_management_terminal_command(
    workspace: str | Path,
    text: str,
    *,
    open_client: Callable[[str | Path], PluginTerminalCommandClient],
    product_id: str,
) -> HostActionResult:
    """Execute one explicit local command; Product owns every state transition."""

    tokens = text.split()
    if (
        len(tokens) != 3
        or tokens[0] != "/plugins"
        or tokens[1] not in PLUGIN_DESIRED_ACTIONS | {"repair"}
        or not valid_plugin_terminal_identifier(tokens[2])
    ):
        return HostActionResult(error_message=_USAGE)
    action, subject = tokens[1:]
    try:
        client = open_client(workspace)
        if action == "repair":
            return _repair_terminal_operation(client, subject, product_id=product_id)
        return _submit_terminal_operation(client, action, subject, product_id=product_id)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if not is_plugin_terminal_error_code(code):
            code = "plugin_management_unavailable"
        return HostActionResult(error_message=f"Plugin command failed: {code}")


def _submit_terminal_operation(
    client: PluginTerminalCommandClient,
    action: str,
    plugin_id: str,
    *,
    product_id: str,
) -> HostActionResult:
    snapshot = client.snapshot(
        correlation_id=f"{product_id}:tui:plugins:{action}:read",
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
    if current == desired_state_for_action(action):
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
                "productId": product_id,
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
        correlation_id=f"{product_id}:tui:plugins:{action}:submit",
    )
    return _format_terminal_operation(document, operation_id=operation_id, action=action)


def _repair_terminal_operation(
    client: PluginTerminalCommandClient, operation_id: str, *, product_id: str
) -> HostActionResult:
    document = client.repair_own_desired_operation(
        operation_id, correlation_id=f"{product_id}:tui:plugins:repair"
    )
    disposition = document.get("disposition")
    if disposition == "unknown":
        return HostActionResult(status_message=f"Plugin operation unknown: {operation_id}")
    if disposition not in {"already_terminal", "replayed_pending"}:
        raise ValueError("Plugin repair result is invalid")
    result = document.get("result")
    if not isinstance(result, dict):
        raise ValueError("Plugin repair result is invalid")
    outcome = _format_terminal_operation(result, operation_id=operation_id, action="repair")
    if outcome.error_message is not None:
        return outcome
    return HostActionResult(
        status_message=f"Plugin operation {disposition}: {operation_id}; "
        "new Session required to observe changes."
    )


def _format_terminal_operation(
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
        or not is_plugin_terminal_error_code(code)
    ):
        raise ValueError("Plugin operation failure is invalid")
    return HostActionResult(
        error_message=f"Plugin {action} failed: {code}; operation {operation_id}"
    )


__all__ = [
    "PluginManagementCliBinding",
    "PluginManagementCliCommandOwnerStrategy",
    "PluginManagementCliProfile",
    "PluginManagementCliReadOwnerStrategy",
    "bind_plugin_management_cli_commands",
    "bind_plugin_management_cli_read",
    "execute_plugin_management_terminal_command",
    "is_plugin_terminal_error_code",
    "is_plugin_terminal_string_list",
    "PluginTerminalCommandClient",
    "valid_plugin_terminal_identifier",
]
