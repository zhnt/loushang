"""Select Coding owners for Session registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from loushang.coding.arch._plugin_tool_owner import CodingArchToolRegistrationSlot
from loushang.coding.composition.base_owners import CodingBaseToolRegistrationSlot
from loushang.coding.composition.base_plugin import build_coding_base_plugin_owners
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolRegistrationSlot
from loushang.harness.session.tool_owner_binding import (
    PreparedOwnerBindings,
    prepare_session_owner_bindings,
)
from loushang.harness.tools.workspace.factory import ToolsOptions

if TYPE_CHECKING:
    from loushang.coding.arch._plugin_tool_owner import CodingArchToolOwner
    from loushang.coding.composition.base_plugin import (
        CodingBasePluginAssembly,
        CodingBasePluginSessionAssembly,
    )
    from loushang.coding.composition.base_product import CodingBaseProductCompilation
    from loushang.coding.composition.capability_plugins import (
        CodingCapabilityPluginCompositionAssembly,
    )
    from loushang.coding.lsp._plugin_tool_owner import CodingLspToolOwner
    from loushang.harness.config.agent import SettingsManager
    from loushang.harness.diagnostics.service import DiagnosticsService


def prepare_owner_bindings(
    *,
    has_catalog_bootstrap: bool,
    base_assembly: CodingBasePluginAssembly | None,
    base_session_assembly: CodingBasePluginSessionAssembly | None,
    product_base: CodingBaseProductCompilation | None,
    capability_assembly: CodingCapabilityPluginCompositionAssembly | None,
    lsp_tool_owner: CodingLspToolOwner | None,
    arch_tool_owner: CodingArchToolOwner | None,
    settings_manager: SettingsManager | None,
    diagnostics_service: DiagnosticsService | None,
    clock: Callable[[], int] | None,
    product_label: str,
) -> PreparedOwnerBindings:
    """Select Coding owners and hand their registration to Harness Session."""
    base_owners = None
    plugin_assembly = (
        capability_assembly.plugin_assembly
        if capability_assembly is not None
        else (
            base_session_assembly.plugin_assembly
            if base_session_assembly is not None
            else None
        )
    )
    if base_assembly is not None or product_base is not None:
        if clock is None or (product_base is None and plugin_assembly is None):
            raise ValueError(f"{product_label} base owner inputs are unavailable")
        if product_base is not None:
            base_host_environment = product_base.host_environment
        else:
            assert base_assembly is not None
            base_host_environment = base_assembly.host_environment
        get_external_tool_policy = getattr(
            settings_manager,
            "get_external_tool_policy",
            None,
        )
        get_shell_path = getattr(settings_manager, "get_shell_path", None)
        get_shell_command_prefix = getattr(
            settings_manager,
            "get_shell_command_prefix",
            None,
        )
        tool_options = ToolsOptions(
            diagnostics_service=diagnostics_service,
            external_tool_policy=(
                get_external_tool_policy()
                if callable(get_external_tool_policy)
                else None
            ),
            host_environment=base_host_environment,
            shell_path=(get_shell_path() if callable(get_shell_path) else None),
            command_prefix=(
                get_shell_command_prefix()
                if callable(get_shell_command_prefix)
                else None
            ),
        )
        if product_base is not None:
            base_owners = product_base.build_owners(
                clock=clock,
                tool_options=tool_options,
            )
        else:
            assert base_assembly is not None
            assert plugin_assembly is not None
            base_owners = build_coding_base_plugin_owners(
                base_assembly,
                plugin_assembly,
                clock=clock,
                tool_options=tool_options,
            )
    return prepare_session_owner_bindings(
        require_command_registry=has_catalog_bootstrap or base_owners is not None,
        base_tool=(
            (base_owners.tool.bind, CodingBaseToolRegistrationSlot)
            if base_owners is not None and base_owners.tool is not None
            else None
        ),
        base_command=(
            base_owners.command.bind
            if base_owners is not None and base_owners.command is not None
            else None
        ),
        capability_tools=tuple(
            (owner.bind, slot_type)
            for owner, slot_type in (
                (lsp_tool_owner, CodingLspToolRegistrationSlot),
                (arch_tool_owner, CodingArchToolRegistrationSlot),
            )
            if owner is not None
        ),
    )
