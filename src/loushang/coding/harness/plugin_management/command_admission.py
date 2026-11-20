"""Acquire scoped command ports after checking the Product workspace fence."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager import command_sdk as _command
from loushang.harness.workspace.paths import (
    capture_workspace_directory_identity,
    require_workspace_directory,
)

_WORKSPACE_UNAVAILABLE = "Plugin management workspace is unavailable"


def open_command_client(
    workspace: str | Path,
    *,
    owner_profile: Literal["sdk", "tui"],
) -> _command.CodingPluginManagementCommandClientV1:
    root = require_workspace_directory(workspace, unavailable=_WORKSPACE_UNAVAILABLE)
    layout = _command.resolve_coding_plugin_lifecycle_state_layout(root)
    _command._require_fenced_product(layout)
    identity = capture_workspace_directory_identity(
        root, unavailable=_WORKSPACE_UNAVAILABLE
    )
    return _command.CodingPluginManagementCommandClientV1(
        workspace=root,
        layout=layout,
        workspace_identity=identity,
        owner_profile=owner_profile,
    )


def open_command_ports(
    self: _command.CodingPluginManagementCommandClientV1,
) -> _command.PluginManagementApplicationPorts:
    self._assert_workspace_identity()
    _command._require_fenced_product(self.layout)
    ports = _command.build_coding_fenced_product_management_cli_ports(
        self.layout, workspace_guard=self._assert_workspace_identity
    )
    self._assert_workspace_identity()
    return ports
