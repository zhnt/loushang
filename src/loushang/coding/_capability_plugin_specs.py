"""Closed first-party specifications consumed by Coding's neutral composer."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.arch._plugin_tool_owner import CodingArchToolOwner
from loushang.coding.arch._provider_api import (
    CODING_ARCH_CAPABILITY_DEFINITION,
    CodingArchPluginConfigV1,
)
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolOwner
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CodingLspPluginConfigV1,
)
from loushang.coding.plugin_dependency_grants import (
    coding_arch_default_plugin_root,
    coding_lsp_default_plugin_root,
)
from loushang.harness.capabilities.contracts import CapabilityDefinition

CodingCapabilityPluginConfig = CodingLspPluginConfigV1 | CodingArchPluginConfigV1
CodingCapabilityToolOwner = CodingLspToolOwner | CodingArchToolOwner


@dataclass(frozen=True, slots=True)
class CodingCapabilityPluginSpec:
    """All Product policy needed to compose one first-party Provider package."""

    plugin_id: str
    capability: CapabilityDefinition
    source_root: Callable[[], Path]
    configuration_type: type[object]
    provider_id: str
    provider_contribution_id: str
    provider_owner_policy_revision: str
    tool_catalog_id: str
    tool_contribution_id: str
    requested_authorities: tuple[str, ...]
    tool_owner_factory: Callable[..., CodingCapabilityToolOwner]


CODING_CAPABILITY_PLUGIN_SPECS: tuple[CodingCapabilityPluginSpec, ...] = (
    CodingCapabilityPluginSpec(
        plugin_id="coding.lsp.default",
        capability=CODING_LSP_CAPABILITY_DEFINITION,
        source_root=coding_lsp_default_plugin_root,
        configuration_type=CodingLspPluginConfigV1,
        provider_id="coding.lsp.default",
        provider_contribution_id="coding-lsp-default",
        provider_owner_policy_revision="coding-lsp-owner-1",
        tool_catalog_id="coding.lsp.tools",
        tool_contribution_id="coding-lsp-tools",
        requested_authorities=("filesystem", "process"),
        tool_owner_factory=CodingLspToolOwner,
    ),
    CodingCapabilityPluginSpec(
        plugin_id="coding.arch.default",
        capability=CODING_ARCH_CAPABILITY_DEFINITION,
        source_root=coding_arch_default_plugin_root,
        configuration_type=CodingArchPluginConfigV1,
        provider_id="coding.arch.default",
        provider_contribution_id="coding-arch-default",
        provider_owner_policy_revision="coding-arch-owner-1",
        tool_catalog_id="coding.arch.tools",
        tool_contribution_id="coding-arch-tools",
        requested_authorities=("filesystem",),
        tool_owner_factory=CodingArchToolOwner,
    ),
)

CODING_CAPABILITY_PLUGIN_SPEC_BY_ID = {
    spec.plugin_id: spec for spec in CODING_CAPABILITY_PLUGIN_SPECS
}
CODING_CAPABILITY_PLUGIN_IDS = frozenset(CODING_CAPABILITY_PLUGIN_SPEC_BY_ID)


def ordered_coding_capability_plugin_specs(
    plugin_ids: Iterable[str],
) -> tuple[CodingCapabilityPluginSpec, ...]:
    selected = frozenset(plugin_ids)
    unknown = selected - CODING_CAPABILITY_PLUGIN_IDS
    if unknown:
        raise ValueError(
            "Unknown Coding Capability Plugin ids: " + ", ".join(sorted(unknown))
        )
    return tuple(
        spec for spec in CODING_CAPABILITY_PLUGIN_SPECS if spec.plugin_id in selected
    )


__all__ = [
    "CODING_CAPABILITY_PLUGIN_IDS",
    "CODING_CAPABILITY_PLUGIN_SPECS",
    "CODING_CAPABILITY_PLUGIN_SPEC_BY_ID",
    "CodingCapabilityPluginConfig",
    "CodingCapabilityPluginSpec",
    "CodingCapabilityToolOwner",
    "ordered_coding_capability_plugin_specs",
]
