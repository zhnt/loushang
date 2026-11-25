"""Coding Product binding for the shared Plugin terminal command."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from loushang.coding.plugin_manager.command_sdk import (
    open_coding_plugin_management_tui_command_client,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.cli.plugin_management import (
    PluginTerminalCommandClient,
    execute_plugin_management_terminal_command,
)
from loushang.harness.cli.plugin_preview import render_plugin_support_status
from loushang.harness.host.types import HostActionResult


class CodingPluginUiCommandClient(PluginTerminalCommandClient, Protocol):
    @property
    def layout(self) -> CodingPluginLifecycleStateLayout: ...


def execute_coding_plugin_management_ui_command(
    workspace: str | Path,
    text: str,
    *,
    open_client: Callable[[str | Path], CodingPluginUiCommandClient] = (
        open_coding_plugin_management_tui_command_client
    ),
) -> HostActionResult:
    return execute_plugin_management_terminal_command(
        workspace, text, open_client=open_client, product_id="coding"
    )


def format_coding_plugin_support_status(document: dict[str, object]) -> str:
    return render_plugin_support_status(document)


__all__ = ["execute_coding_plugin_management_ui_command"]
