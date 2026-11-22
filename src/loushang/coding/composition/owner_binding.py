"""Prepare Session owner registration and roll back uncommitted construction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.coding.arch._plugin_tool_owner import CodingArchToolRegistrationSlot
from loushang.coding.composition.base_owners import CodingBaseToolRegistrationSlot
from loushang.coding.composition.base_plugin import build_coding_base_plugin_owners
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolRegistrationSlot
from loushang.harness.session.command_controller import SessionCommandGenerationRegistry
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
    from loushang.harness.session.capability_composition_inputs import (
        SessionCapabilityOwnerGenerationBinding,
    )
    from loushang.harness.session.tool_owner_binding import DeferredToolRegistrationSlot


@dataclass(frozen=True, slots=True)
class PreparedOwnerBindings:
    generations: tuple[SessionCapabilityOwnerGenerationBinding, ...]
    command_registry: SessionCommandGenerationRegistry | None
    tool_slots: tuple[DeferredToolRegistrationSlot, ...]


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
    """Bind the prepared owners to the registry and their late Tool slots."""
    owner_bindings: list[SessionCapabilityOwnerGenerationBinding] = []
    base_tool_registration_slot = None
    # A Catalog-owned Session starts with an explicit empty command registry.
    command_generations = (
        SessionCommandGenerationRegistry() if has_catalog_bootstrap else None
    )
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
        if command_generations is None:
            command_generations = SessionCommandGenerationRegistry()
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
        if base_owners.tool is not None:
            base_tool_registration_slot = CodingBaseToolRegistrationSlot()
            owner_bindings.append(base_owners.tool.bind(base_tool_registration_slot))
        if base_owners.command is not None:
            owner_bindings.append(base_owners.command.bind(command_generations))
    tool_slots: list[DeferredToolRegistrationSlot] = []
    for tool_owner, slot_type in (
        (lsp_tool_owner, CodingLspToolRegistrationSlot),
        (arch_tool_owner, CodingArchToolRegistrationSlot),
    ):
        if tool_owner is not None:
            slot = slot_type()
            owner_bindings.append(tool_owner.bind(slot))
            tool_slots.append(slot)
    if base_tool_registration_slot is not None:
        tool_slots.append(base_tool_registration_slot)
    return PreparedOwnerBindings(
        tuple(owner_bindings), command_generations, tuple(tool_slots)
    )
