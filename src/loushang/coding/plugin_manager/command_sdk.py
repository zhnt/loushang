"""Local Coding Plugin management command SDK over the fenced Product owner.

This is separate from the public Plugin author namespace and does not open a
Product Session. The caller supplies an exact Desired State revision and a
replayable operation id for each command.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.package.epoch_layout import coding_fenced_product_exists
from loushang.coding.package.management_binding import (
    build_coding_fenced_product_management_cli_ports as build_coding_fenced_product_management_cli_ports,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    matches_coding_workspace_layout,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout as resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.plugin_management.application import (
    PluginManagementApplicationPorts,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredActionV1,
    PluginDesiredCommandAuthorityV1,
    PluginDesiredCommandRequestV1,
    resume_plugin_desired_operation,
    submit_plugin_desired_command,
)
from loushang.harness.workspace.paths import (
    assert_workspace_directory_identity,
    capture_workspace_directory_identity,
    is_workspace_directory_identity,
    require_workspace_directory,
)

_WORKSPACE_UNAVAILABLE = "Plugin management workspace is unavailable"


class CodingPluginManagementCommandSdkError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPluginManagementCommandClientV1:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_identity: tuple[int, int]
    owner_profile: Literal["sdk", "tui"] = "sdk"

    def __post_init__(self) -> None:
        if not matches_coding_workspace_layout(self.workspace, self.layout):
            raise ValueError("Coding management workspace scope is invalid")
        if not is_workspace_directory_identity(self.workspace_identity):
            raise ValueError("Coding management workspace identity is invalid")
        if not isinstance(self.owner_profile, str) or self.owner_profile not in {
            "sdk",
            "tui",
        }:
            raise ValueError("Coding management owner profile is invalid")

    def snapshot(
        self, *, correlation_id: str, plugin_ids: tuple[str, ...] = ()
    ) -> dict[str, object]:
        ports = self._ports()
        return ports.queries.snapshot(
            PluginManagementQueryV1(
                correlation_id=correlation_id,
                product_id=CODING_PRODUCT_ID,
                installation_scope="workspace",
                scope_id=self.layout.scope_id,
                plugin_ids=tuple(sorted(set(plugin_ids))),
            )
        ).to_dict()

    def submit_desired(
        self,
        *,
        plugin_id: str,
        action: PluginDesiredActionV1,
        expected_inventory_revision: int,
        operation_id: str,
        correlation_id: str,
    ) -> dict[str, object]:
        ports = self._ports()
        result = submit_plugin_desired_command(
            ports,
            self._authority(),
            PluginDesiredCommandRequestV1(
                correlation_id=correlation_id,
                operation_id=operation_id,
                plugin_id=plugin_id,
                action=action,
                expected_inventory_revision=expected_inventory_revision,
            ),
        )
        return result.to_dict()

    def repair_own_desired_operation(
        self, operation_id: str, *, correlation_id: str
    ) -> dict[str, object]:
        """Settle only a pending command originally issued by this SDK owner."""

        return resume_plugin_desired_operation(
            self._ports(),
            self._authority(),
            operation_id=operation_id,
            correlation_id=correlation_id,
        ).to_dict()

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> dict[str, object] | None:
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("Coding management operation id is invalid")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("Coding management correlation id is invalid")
        result = self._ports().commands.operation(
            operation_id, correlation_id=correlation_id
        )
        return None if result is None else result.to_dict()

    def _ports(self) -> PluginManagementApplicationPorts:
        self._assert_workspace_identity()
        _require_fenced_product(self.layout)
        ports = build_coding_fenced_product_management_cli_ports(
            self.layout, workspace_guard=self._assert_workspace_identity
        )
        self._assert_workspace_identity()
        return ports

    def _assert_workspace_identity(self) -> None:
        assert_workspace_directory_identity(
            self.workspace,
            self.workspace_identity,
            changed=lambda: CodingPluginManagementCommandSdkError(
                "Coding management workspace changed",
                code="coding_management_workspace_changed",
            ),
        )

    def _authority(self) -> PluginDesiredCommandAuthorityV1:
        actor_id, policy_revision = {
            "sdk": ("coding:sdk", "coding-plugin-management-sdk-v1"),
            "tui": ("coding:tui", "coding-plugin-management-tui-v1"),
        }[self.owner_profile]
        return PluginDesiredCommandAuthorityV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            actor_id=actor_id,
            policy_revision=policy_revision,
        )


def open_coding_plugin_management_command_client(
    workspace: str | Path,
) -> CodingPluginManagementCommandClientV1:
    return _open_command_client(workspace, owner_profile="sdk")


def open_coding_plugin_management_tui_command_client(
    workspace: str | Path,
) -> CodingPluginManagementCommandClientV1:
    """Bind the local TUI actor to the same fenced Product command owner."""

    return _open_command_client(workspace, owner_profile="tui")


def _open_command_client(
    workspace: str | Path,
    *,
    owner_profile: Literal["sdk", "tui"],
) -> CodingPluginManagementCommandClientV1:
    root = require_workspace_directory(workspace, unavailable=_WORKSPACE_UNAVAILABLE)
    layout = resolve_coding_plugin_lifecycle_state_layout(root)
    _require_fenced_product(layout)
    identity = capture_workspace_directory_identity(
        root, unavailable=_WORKSPACE_UNAVAILABLE
    )
    return CodingPluginManagementCommandClientV1(
        workspace=root,
        layout=layout,
        workspace_identity=identity,
        owner_profile=owner_profile,
    )


def _require_fenced_product(layout: CodingPluginLifecycleStateLayout) -> None:
    if not coding_fenced_product_exists(layout):
        raise CodingPluginManagementCommandSdkError(
            "Coding Plugin Product is not fenced",
            code="coding_product_not_fenced",
        )


__all__ = [
    "CodingPluginManagementCommandClientV1",
    "CodingPluginManagementCommandSdkError",
    "open_coding_plugin_management_command_client",
    "open_coding_plugin_management_tui_command_client",
]
