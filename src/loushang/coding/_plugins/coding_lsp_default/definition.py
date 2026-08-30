"""Executable declaration and activation symbols for ``coding.lsp.default``."""

from __future__ import annotations

from loushang.coding.lsp._provider_api import (
    CodingLspPluginConfigV1,
    coding_lsp_capability_provider,
    create_coding_lsp_provider,
    dispose_coding_lsp_provider,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityProviderContext,
)
from loushang.plugin import (
    PluginDefinitionBuilder,
    capability_provider,
    plugin_definition,
)

CONTRIBUTION_ID = "coding-lsp-default"


def create_provider(context: CapabilityProviderContext) -> CapabilityBundleValue:
    """Delegate activation to the exact-version private Product adapter."""

    return create_coding_lsp_provider(context)


async def dispose_provider(value: CapabilityBundleValue) -> None:
    """Delegate disposal to the exact-version private Product adapter."""

    await dispose_coding_lsp_provider(value)


@plugin_definition
def declare(plugin: PluginDefinitionBuilder) -> None:
    """Project the approved reservation to inert Provider declaration IR."""

    CodingLspPluginConfigV1.from_mapping(
        plugin.effective_configuration(contribution_id=CONTRIBUTION_ID)
    )
    provider = coding_lsp_capability_provider()
    plugin.add(
        capability_provider(
            contribution_id=CONTRIBUTION_ID,
            capability=provider.capability_id,
            provider_id=provider.provider_id,
            implementation_version=provider.implementation_version,
            contract=(
                provider.compatible_contract.minimum,
                provider.compatible_contract.maximum,
            ),
            facets=provider.facets,
            requirements=provider.requirements,
            authorities=tuple(sorted(provider.required_authorities)),
            factory="definition.py:create_provider",
            disposer="definition.py:dispose_provider",
        ),
    )
