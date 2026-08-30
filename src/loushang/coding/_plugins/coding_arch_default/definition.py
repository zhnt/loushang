"""Executable declaration and activation symbols for ``coding.arch.default``."""

from __future__ import annotations

from loushang.coding.arch._provider_api import (
    CodingArchPluginConfigV1,
    coding_arch_capability_provider,
    create_coding_arch_provider,
    dispose_coding_arch_provider,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityProviderContext,
)
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.capability_provider import (
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
)
from loushang.harness.resources.plugins.declarations import PluginDeclaration

CONTRIBUTION_ID = "coding-arch-default"


def create_provider(context: CapabilityProviderContext) -> CapabilityBundleValue:
    """Delegate activation to the exact-version private Product adapter."""

    return create_coding_arch_provider(context)


def dispose_provider(value: CapabilityBundleValue) -> None:
    """Delegate disposal to the exact-version private Product adapter."""

    dispose_coding_arch_provider(value)


def declare(builder: PluginDeclarationBuilder) -> tuple[PluginDeclaration, ...]:
    """Project the approved reservation to inert Provider declaration IR."""

    config = CodingArchPluginConfigV1.from_mapping(
        builder.effective_configuration(contribution_id=CONTRIBUTION_ID)
    )
    builder.add_capability_provider(
        contribution_id=CONTRIBUTION_ID,
        payload=CapabilityProviderDeclarationPayload(
            provider=coding_arch_capability_provider(),
            factory=PluginSymbolReference(
                path="definition.py",
                symbol="create_provider",
                execution_model="in_process",
            ),
            disposer=PluginSymbolReference(
                path="definition.py",
                symbol="dispose_provider",
                execution_model="in_process",
            ),
            binding_inputs=config.to_dict(),
        ),
    )
    return builder.build()
