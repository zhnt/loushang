"""Stable public Plugin authoring and inert validation SDK."""

from loushang.harness.resources.skill_actions import (
    ManagedSkillActionDeclaration,
    SkillActionEffect,
)
from loushang.plugin._authoring import (
    CapabilityProviderSpec,
    Contract,
    PluginDefinitionBuilder,
    PluginDefinitionFunction,
    ResourceItemSpec,
    capability_provider,
    capability_requirement,
    plugin_definition,
    resource,
    skill_action,
    skill_action_effect,
)
from loushang.plugin._package import (
    PluginPackageArtifact,
    PluginPackageSpec,
    package,
)
from loushang.plugin._validation import (
    PLUGIN_ENGINE_API_VERSION,
    PLUGIN_ENGINE_FEATURES,
    PLUGIN_MANIFEST_VERSION,
    PluginValidationDiagnostic,
    PluginValidationResult,
    validate_package,
)

__all__ = [
    "PLUGIN_ENGINE_API_VERSION",
    "PLUGIN_ENGINE_FEATURES",
    "PLUGIN_MANIFEST_VERSION",
    "CapabilityProviderSpec",
    "Contract",
    "PluginDefinitionBuilder",
    "PluginDefinitionFunction",
    "PluginPackageArtifact",
    "PluginPackageSpec",
    "PluginValidationDiagnostic",
    "PluginValidationResult",
    "ResourceItemSpec",
    "ManagedSkillActionDeclaration",
    "SkillActionEffect",
    "capability_provider",
    "capability_requirement",
    "plugin_definition",
    "package",
    "resource",
    "skill_action",
    "skill_action_effect",
    "validate_package",
]
