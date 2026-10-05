"""Local Coding Plugin management command SDK over the fenced Product owner.

This is separate from the public Plugin author namespace and does not open a
Product Session. The caller supplies an exact Desired State revision and a
replayable operation id for each command.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_product_management_cli import (
    build_coding_fenced_product_management_cli_ports,
    coding_fenced_product_exists,
)
from .product_plan import CODING_PRODUCT_ID


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
        if (
            not isinstance(self.workspace, Path)
            or not self.workspace.is_absolute()
            or self.workspace != self.workspace.resolve(strict=True)
            or not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or self.layout
            != resolve_coding_plugin_lifecycle_state_layout(self.workspace)
        ):
            raise ValueError("Coding management workspace scope is invalid")
        if (
            type(self.workspace_identity) is not tuple
            or len(self.workspace_identity) != 2
            or any(
                type(item) is not int or item < 0 for item in self.workspace_identity
            )
        ):
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
        if not coding_fenced_product_exists(self.layout):
            raise CodingPluginManagementCommandSdkError(
                "Coding Plugin Product is not fenced",
                code="coding_product_not_fenced",
            )
        ports = build_coding_fenced_product_management_cli_ports(
            self.layout, workspace_guard=self._assert_workspace_identity
        )
        self._assert_workspace_identity()
        return ports

    def _assert_workspace_identity(self) -> None:
        try:
            metadata = self.workspace.lstat()
            current = self.workspace.resolve(strict=True)
        except OSError as exc:
            raise CodingPluginManagementCommandSdkError(
                "Coding management workspace changed",
                code="coding_management_workspace_changed",
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or current != self.workspace
            or (metadata.st_dev, metadata.st_ino) != self.workspace_identity
        ):
            raise CodingPluginManagementCommandSdkError(
                "Coding management workspace changed",
                code="coding_management_workspace_changed",
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
    return _open_coding_plugin_management_command_client(workspace, owner_profile="sdk")


def open_coding_plugin_management_tui_command_client(
    workspace: str | Path,
) -> CodingPluginManagementCommandClientV1:
    """Bind the local TUI actor to the same fenced Product command owner."""

    return _open_coding_plugin_management_command_client(workspace, owner_profile="tui")


def _open_coding_plugin_management_command_client(
    workspace: str | Path,
    *,
    owner_profile: Literal["sdk", "tui"],
) -> CodingPluginManagementCommandClientV1:
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Plugin management workspace is unavailable")
    layout = resolve_coding_plugin_lifecycle_state_layout(root)
    if not coding_fenced_product_exists(layout):
        raise CodingPluginManagementCommandSdkError(
            "Coding Plugin Product is not fenced",
            code="coding_product_not_fenced",
        )
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Plugin management workspace is unavailable")
    return CodingPluginManagementCommandClientV1(
        workspace=root,
        layout=layout,
        workspace_identity=(metadata.st_dev, metadata.st_ino),
        owner_profile=owner_profile,
    )


__all__ = [
    "CodingPluginManagementCommandClientV1",
    "CodingPluginManagementCommandSdkError",
    "open_coding_plugin_management_command_client",
    "open_coding_plugin_management_tui_command_client",
]
