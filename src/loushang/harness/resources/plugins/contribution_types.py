"""Closed, versioned type system for inert Plugin contributions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

PLUGIN_CONTRIBUTION_TYPE_SYSTEM_VERSION = 1

PLUGIN_CONTRIBUTION_INDEX_VERSION = 2
PLUGIN_DECLARATION_IR_VERSION = 2
PLUGIN_DECLARATION_DOCUMENT_VERSION = 1
PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION = 3
PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION = 3
PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION = 2

PluginContributionKind = Literal[
    "capability_provider",
    "command_pack",
    "continuity_provider",
    "resource_item",
    "tool_pack",
]
PluginContributionExecutionModel = Literal["data_only", "in_process", "local_worker"]
PluginOwnerContributionKind = Literal["resource_item", "tool_pack", "command_pack"]

PLUGIN_CONTRIBUTION_KINDS = frozenset(
    {
        "capability_provider",
        "command_pack",
        "continuity_provider",
        "resource_item",
        "tool_pack",
    }
)
PLUGIN_OWNER_CONTRIBUTION_KINDS = frozenset(
    {"command_pack", "resource_item", "tool_pack"}
)


@dataclass(frozen=True, slots=True)
class PluginContributionTypeRule:
    """One closed contribution arm; ``owner`` remains an inert exact-id reference."""

    kind: PluginContributionKind
    execution_models: frozenset[PluginContributionExecutionModel]
    permits_requested_authorities: bool


@dataclass(frozen=True, slots=True)
class PluginContributionSchema:
    """One exact compatible tuple of Index, declaration IR, and document versions."""

    index_version: int
    declaration_ir_version: int
    declaration_document_version: int
    rules: Mapping[PluginContributionKind, PluginContributionTypeRule]
    type_system_version: int = PLUGIN_CONTRIBUTION_TYPE_SYSTEM_VERSION

    def __post_init__(self) -> None:
        if self.type_system_version != PLUGIN_CONTRIBUTION_TYPE_SYSTEM_VERSION:
            raise ValueError("Unsupported Plugin contribution type-system version")
        if frozenset(self.rules) != PLUGIN_CONTRIBUTION_KINDS:
            raise ValueError("Plugin contribution schema must define every closed kind")
        for kind, rule in self.rules.items():
            if kind != rule.kind or not rule.execution_models:
                raise ValueError("Invalid Plugin contribution type rule")
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))

    @property
    def kinds(self) -> frozenset[str]:
        return PLUGIN_CONTRIBUTION_KINDS

    @property
    def execution_models(self) -> frozenset[str]:
        return frozenset(
            model for rule in self.rules.values() for model in rule.execution_models
        )

    def rule_for(self, kind: object) -> PluginContributionTypeRule | None:
        if not isinstance(kind, str):
            return None
        return self.rules.get(cast(PluginContributionKind, kind))

    def permits_execution_model(self, kind: object, model: object) -> bool:
        rule = self.rule_for(kind)
        return rule is not None and model in rule.execution_models


def _rule(
    kind: PluginContributionKind,
    *execution_models: PluginContributionExecutionModel,
    permits_requested_authorities: bool = False,
) -> PluginContributionTypeRule:
    return PluginContributionTypeRule(
        kind=kind,
        execution_models=frozenset(execution_models),
        permits_requested_authorities=permits_requested_authorities,
    )


PLUGIN_CONTRIBUTION_SCHEMA_V2 = PluginContributionSchema(
    index_version=PLUGIN_CONTRIBUTION_INDEX_VERSION,
    declaration_ir_version=PLUGIN_DECLARATION_IR_VERSION,
    declaration_document_version=PLUGIN_DECLARATION_DOCUMENT_VERSION,
    rules={
        "capability_provider": _rule(
            "capability_provider",
            "in_process",
            permits_requested_authorities=True,
        ),
        "command_pack": _rule("command_pack", "data_only"),
        "continuity_provider": _rule(
            "continuity_provider",
            "in_process",
            permits_requested_authorities=True,
        ),
        "resource_item": _rule("resource_item", "data_only"),
        "tool_pack": _rule("tool_pack", "data_only"),
    },
)

PLUGIN_CONTRIBUTION_SCHEMA_V3 = PluginContributionSchema(
    index_version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    declaration_ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
    declaration_document_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    rules={
        "capability_provider": _rule(
            "capability_provider",
            "in_process",
            "local_worker",
            permits_requested_authorities=True,
        ),
        "command_pack": _rule("command_pack", "data_only"),
        "continuity_provider": _rule(
            "continuity_provider",
            "in_process",
            permits_requested_authorities=True,
        ),
        "resource_item": _rule("resource_item", "data_only"),
        "tool_pack": _rule("tool_pack", "data_only"),
    },
)

PLUGIN_CONTRIBUTION_SCHEMAS = MappingProxyType(
    {
        PLUGIN_CONTRIBUTION_SCHEMA_V2.index_version: PLUGIN_CONTRIBUTION_SCHEMA_V2,
        PLUGIN_CONTRIBUTION_SCHEMA_V3.index_version: PLUGIN_CONTRIBUTION_SCHEMA_V3,
    }
)
PLUGIN_CONTRIBUTION_SCHEMAS_BY_IR_VERSION = MappingProxyType(
    {
        schema.declaration_ir_version: schema
        for schema in PLUGIN_CONTRIBUTION_SCHEMAS.values()
    }
)


def plugin_contribution_schema_for_index(version: object) -> PluginContributionSchema | None:
    if not isinstance(version, int) or isinstance(version, bool):
        return None
    return PLUGIN_CONTRIBUTION_SCHEMAS.get(version)


def plugin_contribution_schema_for_ir(version: object) -> PluginContributionSchema | None:
    if not isinstance(version, int) or isinstance(version, bool):
        return None
    return PLUGIN_CONTRIBUTION_SCHEMAS_BY_IR_VERSION.get(version)


__all__ = [
    "PLUGIN_CONTRIBUTION_INDEX_VERSION",
    "PLUGIN_CONTRIBUTION_KINDS",
    "PLUGIN_CONTRIBUTION_SCHEMA_V2",
    "PLUGIN_CONTRIBUTION_SCHEMA_V3",
    "PLUGIN_CONTRIBUTION_SCHEMAS",
    "PLUGIN_CONTRIBUTION_SCHEMAS_BY_IR_VERSION",
    "PLUGIN_CONTRIBUTION_TYPE_SYSTEM_VERSION",
    "PLUGIN_DECLARATION_DOCUMENT_VERSION",
    "PLUGIN_DECLARATION_IR_VERSION",
    "PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION",
    "PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION",
    "PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION",
    "PLUGIN_OWNER_CONTRIBUTION_KINDS",
    "PluginContributionExecutionModel",
    "PluginContributionKind",
    "PluginContributionSchema",
    "PluginContributionTypeRule",
    "PluginOwnerContributionKind",
    "plugin_contribution_schema_for_index",
    "plugin_contribution_schema_for_ir",
]
