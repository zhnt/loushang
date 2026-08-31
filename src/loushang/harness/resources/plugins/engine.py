"""Single inert Plugin manifest/engine negotiation authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from loushang.harness.resources.plugins.declarations import (
    PLUGIN_DECLARATION_IR_VERSION,
    PluginContributionIndex,
)

PLUGIN_MANIFEST_VERSION: Final = 1
PLUGIN_ENGINE_API_VERSION: Final = 1
MANAGED_SKILL_ACTION_CONFIGURATION_KEY: Final = "managedSkillActions"
PLUGIN_ENGINE_FEATURES: Final = frozenset(
    {
        "capability-provider-v2",
        "catalog-consumer-v1",
        "declaration-document-v1",
        "in-process-definition-v1",
        "managed-skill-action-v1",
        "resource-item-v1",
        "symbol-reference-v2",
    }
)
STABLE_PLUGIN_MANIFEST_FIELDS: Final = frozenset(
    {
        "contributionIndex",
        "engine",
        "manifestVersion",
        "name",
        "packageRoot",
        "version",
    }
)
_ENGINE_FIELDS = frozenset(
    {
        "apiVersion",
        "declarationIrVersion",
        "requiredFeatures",
    }
)


@dataclass(frozen=True, slots=True)
class PluginEngineContract:
    manifest_version: int
    api_version: int
    declaration_ir_version: int
    required_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PluginEngineDiagnostic:
    code: str
    message: str


def inspect_plugin_engine_contract(
    payload: Mapping[object, object],
    *,
    contribution_index: PluginContributionIndex | None = None,
) -> tuple[PluginEngineContract | None, tuple[PluginEngineDiagnostic, ...]]:
    """Inspect a stable contract; manifests with no version/engine remain legacy."""

    claims_stable_contract = "manifestVersion" in payload or "engine" in payload
    if not claims_stable_contract:
        if contribution_index is not None and any(
            MANAGED_SKILL_ACTION_CONFIGURATION_KEY in item.configuration
            for item in contribution_index.items
        ):
            return None, (
                PluginEngineDiagnostic(
                    code="plugin_engine_contract_missing",
                    message=(
                        "Managed Skill actions require a stable Plugin engine "
                        "contract"
                    ),
                ),
            )
        return None, ()
    diagnostics: list[PluginEngineDiagnostic] = []
    if set(payload) != STABLE_PLUGIN_MANIFEST_FIELDS:
        diagnostics.append(
            PluginEngineDiagnostic(
                code="plugin_manifest_exact_field_mismatch",
                message="Stable Plugin manifest fields do not match version 1",
            )
        )
    manifest_version = payload.get("manifestVersion")
    if type(manifest_version) is not int or manifest_version != PLUGIN_MANIFEST_VERSION:
        diagnostics.append(
            PluginEngineDiagnostic(
                code="unsupported_plugin_manifest_version",
                message="Unsupported Plugin manifest version",
            )
        )
    engine = payload.get("engine")
    if not isinstance(engine, dict):
        diagnostics.append(
            PluginEngineDiagnostic(
                code="plugin_engine_contract_missing",
                message="Stable Plugin manifest requires an engine contract",
            )
        )
        return None, tuple(diagnostics)
    if set(engine) != _ENGINE_FIELDS:
        diagnostics.append(
            PluginEngineDiagnostic(
                code="plugin_engine_exact_field_mismatch",
                message="Plugin engine contract fields do not match version 1",
            )
        )
    api_version = engine.get("apiVersion")
    declaration_version = engine.get("declarationIrVersion")
    if type(api_version) is not int or api_version != PLUGIN_ENGINE_API_VERSION:
        diagnostics.append(
            PluginEngineDiagnostic(
                code="unsupported_plugin_engine_api_version",
                message="Unsupported Plugin engine API version",
            )
        )
    if (
        type(declaration_version) is not int
        or declaration_version != PLUGIN_DECLARATION_IR_VERSION
    ):
        diagnostics.append(
            PluginEngineDiagnostic(
                code="unsupported_plugin_declaration_ir_version",
                message="Unsupported Plugin declaration IR version",
            )
        )
    required = engine.get("requiredFeatures")
    if (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or required != sorted(set(required))
    ):
        diagnostics.append(
            PluginEngineDiagnostic(
                code="plugin_engine_features_not_canonical",
                message="Plugin required features must be sorted unique strings",
            )
        )
        features: tuple[str, ...] = ()
    else:
        features = tuple(required)
        unsupported = tuple(
            item for item in features if item not in PLUGIN_ENGINE_FEATURES
        )
        if unsupported:
            diagnostics.append(
                PluginEngineDiagnostic(
                    code="unsupported_plugin_engine_feature",
                    message="Plugin requires unsupported engine features: "
                    + ", ".join(unsupported),
                )
            )
    if contribution_index is not None:
        for item in contribution_index.items:
            if MANAGED_SKILL_ACTION_CONFIGURATION_KEY not in item.configuration:
                continue
            if (
                item.kind != "resource_item"
                or item.configuration[MANAGED_SKILL_ACTION_CONFIGURATION_KEY] is not True
            ):
                diagnostics.append(
                    PluginEngineDiagnostic(
                        code="plugin_engine_feature_configuration_invalid",
                        message=(
                            "managedSkillActions is reserved for Resource items "
                            "that declare managed Skill actions"
                        ),
                    )
                )
        expected_features = required_plugin_engine_features(contribution_index)
        missing = tuple(sorted(expected_features - set(features)))
        if missing:
            diagnostics.append(
                PluginEngineDiagnostic(
                    code="plugin_engine_feature_declaration_incomplete",
                    message="Plugin engine contract omits required features: "
                    + ", ".join(missing),
                )
            )
        extra = tuple(sorted(set(features) - expected_features))
        if extra:
            diagnostics.append(
                PluginEngineDiagnostic(
                    code="plugin_engine_feature_declaration_extraneous",
                    message="Plugin engine contract declares unused features: "
                    + ", ".join(extra),
                )
            )
    contract = (
        PluginEngineContract(
            manifest_version=PLUGIN_MANIFEST_VERSION,
            api_version=PLUGIN_ENGINE_API_VERSION,
            declaration_ir_version=PLUGIN_DECLARATION_IR_VERSION,
            required_features=features,
        )
        if not diagnostics
        else None
    )
    return contract, tuple(diagnostics)


def required_plugin_engine_features(
    contribution_index: PluginContributionIndex,
) -> frozenset[str]:
    features: set[str] = set()
    for item in contribution_index.items:
        if item.kind == "capability_provider":
            features.update({"capability-provider-v2", "symbol-reference-v2"})
        elif item.kind in {"command_pack", "tool_pack"}:
            features.add("catalog-consumer-v1")
        elif item.kind == "resource_item":
            features.add("resource-item-v1")
            if item.configuration.get(MANAGED_SKILL_ACTION_CONFIGURATION_KEY) is True:
                features.add("managed-skill-action-v1")
        if item.declaration_source.kind == "document":
            features.add("declaration-document-v1")
        elif item.declaration_source.kind == "in_process":
            features.add("in-process-definition-v1")
    return frozenset(features)


__all__ = [
    "PLUGIN_ENGINE_API_VERSION",
    "PLUGIN_ENGINE_FEATURES",
    "PLUGIN_MANIFEST_VERSION",
    "MANAGED_SKILL_ACTION_CONFIGURATION_KEY",
    "STABLE_PLUGIN_MANIFEST_FIELDS",
    "PluginEngineContract",
    "PluginEngineDiagnostic",
    "inspect_plugin_engine_contract",
    "required_plugin_engine_features",
]
