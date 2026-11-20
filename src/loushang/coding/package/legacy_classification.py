"""Classify verified pre-B Coding evidence without authorizing migration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path as Path
from typing import Literal

from loushang.coding.harness.package_product import legacy_classification as _programs

from .epoch_layout import CodingLifecyclePreBMembersV1, CodingPackagePreBStoreMembersV1

CodingLegacyWorkspaceKindV1 = Literal[
    "fresh", "disabled_only", "configured_source", "legacy_state"
]
CodingSourceScopeV1 = Literal["global", "project"]
_SCOPES: tuple[CodingSourceScopeV1, ...] = ("global", "project")
_SOURCE_KEYS = frozenset(
    {"package_roots", "package_sources", "packages", "plugin_sources"}
)
_PROJECTION_KEYS = frozenset({"disabled_plugins", *_SOURCE_KEYS, "resource_roots"})
_PACKAGE_FILTER_KEYS = frozenset({"extensions", "skills", "prompts", "themes"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


_LEGACY_EVIDENCE_VALUES = {
    "value_001": "Coding pre-B member mappings are required",
    "value_002": "Coding Source projection is invalid",
    "value_003": "coding",
    "value_004": "Coding Source projection version is unsupported",
    "value_005": "Coding Source projection scopes are invalid",
    "value_006": "Coding Source projection layer is invalid",
    "value_007": "Coding legacy Source setting is invalid",
    "value_008": "Coding legacy disabled Plugin is invalid",
    "value_009": "Coding legacy disabled Plugin is duplicated",
    "value_010": "Coding legacy Package Source is invalid",
}


@dataclass(frozen=True, slots=True)
class CodingScopedLegacyDisableV1:
    scope: CodingSourceScopeV1
    plugin_id: str


@dataclass(frozen=True, slots=True)
class CodingLegacyWorkspaceClassificationV1:
    """Inventory only; neither Source nor Product admission follows from it."""

    kind: CodingLegacyWorkspaceKindV1
    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    configured_source_keys: tuple[str, ...]
    lifecycle_members: tuple[str, ...]
    package_members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodingLegacySourceConfigurationV1:
    """Scope-preserving settings classification without consulting old roots."""

    disabled_plugins: tuple[CodingScopedLegacyDisableV1, ...]
    configured_source_keys: tuple[str, ...]


def classify_coding_legacy_workspace(
    source_projection: object,
    *,
    lifecycle: CodingLifecyclePreBMembersV1,
    package: CodingPackagePreBStoreMembersV1,
) -> CodingLegacyWorkspaceClassificationV1:
    """Partition exact snapshot inputs while preserving settings scope.

    The caller must supply the verified Source projection while its settings
    locks are held. This function never reads old bytes or grants a B revision.
    """

    return _programs.classify_workspace_evidence(
        source_projection, lifecycle=lifecycle, package=package
    )


def classify_coding_legacy_source_configuration(
    source_projection: object,
) -> CodingLegacySourceConfigurationV1:
    """Validate the frozen settings projection without reading mutable state."""

    return _programs.classify_source_projection(source_projection)


def _valid_package_source(value: object) -> bool:
    return _programs.valid_package_source(value)


__all__ = [
    "CodingLegacySourceConfigurationV1",
    "CodingLegacyWorkspaceClassificationV1",
    "CodingLegacyWorkspaceKindV1",
    "CodingScopedLegacyDisableV1",
    "classify_coding_legacy_source_configuration",
    "classify_coding_legacy_workspace",
]
