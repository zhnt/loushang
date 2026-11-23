"""Classify verified pre-B Coding evidence without authorizing migration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .epoch_layout import CodingLifecyclePreBMembersV1, CodingPackagePreBStoreMembersV1
from .source_snapshot import _LEGACY_DISABLE_SETTING, _source_projection

CodingLegacyWorkspaceKindV1 = Literal[
    "fresh", "disabled_only", "configured_source", "legacy_state"
]
CodingSourceScopeV1 = Literal["global", "project"]
_SOURCE_KEYS = frozenset(
    {"package_roots", "package_sources", "packages", "plugin_sources"}
)


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

    if not isinstance(lifecycle, CodingLifecyclePreBMembersV1) or not isinstance(
        package, CodingPackagePreBStoreMembersV1
    ):
        raise TypeError("Coding pre-B member mappings are required")
    configuration = classify_coding_legacy_source_configuration(source_projection)
    lifecycle_names = tuple(
        f"{domain}:{name}"
        for domain, names in lifecycle.domain_members().items()
        for name in names
    )
    package_names = tuple(
        f"{domain}:{name}"
        for domain, names in package.domain_members().items()
        for name in names
    )
    kind: CodingLegacyWorkspaceKindV1 = (
        "legacy_state"
        if lifecycle_names or package_names
        else "configured_source"
        if configuration.configured_source_keys
        else "disabled_only"
        if configuration.disabled_plugins
        else "fresh"
    )
    return CodingLegacyWorkspaceClassificationV1(
        kind=kind,
        disabled_plugins=configuration.disabled_plugins,
        configured_source_keys=configuration.configured_source_keys,
        lifecycle_members=lifecycle_names,
        package_members=package_names,
    )


def classify_coding_legacy_source_configuration(
    source_projection: object,
) -> CodingLegacySourceConfigurationV1:
    """Validate the frozen settings projection without reading mutable state."""

    disabled, sources = _source_projection.classify(
        source_projection,
        disabled_setting=_LEGACY_DISABLE_SETTING,
        configured_source_keys=_SOURCE_KEYS,
    )
    return CodingLegacySourceConfigurationV1(
        disabled_plugins=tuple(
            CodingScopedLegacyDisableV1(scope, plugin_id) for scope, plugin_id in disabled
        ),
        configured_source_keys=sources,
    )


__all__ = [
    "CodingLegacySourceConfigurationV1",
    "CodingLegacyWorkspaceClassificationV1",
    "CodingLegacyWorkspaceKindV1",
    "CodingScopedLegacyDisableV1",
    "classify_coding_legacy_source_configuration",
    "classify_coding_legacy_workspace",
]
