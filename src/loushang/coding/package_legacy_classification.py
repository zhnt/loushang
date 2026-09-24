"""Classify verified pre-B Coding evidence without authorizing migration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .package_epoch_layout import (
    CodingLifecyclePreBMembersV1,
    CodingPackagePreBStoreMembersV1,
)

CodingLegacyWorkspaceKindV1 = Literal[
    "fresh", "disabled_only", "configured_source", "legacy_state"
]
CodingSourceScopeV1 = Literal["global", "project"]
_SCOPES: tuple[CodingSourceScopeV1, ...] = ("global", "project")
_SOURCE_KEYS = frozenset(
    {"package_roots", "package_sources", "packages", "plugin_sources"}
)
_PROJECTION_KEYS = frozenset({"disabled_plugins", *_SOURCE_KEYS, "resource_roots"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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
    if not isinstance(source_projection, dict) or set(source_projection) != {
        "productId",
        "projectionVersion",
        "scopes",
    }:
        raise ValueError("Coding Source projection is invalid")
    if (
        source_projection["productId"] != "coding"
        or type(source_projection["projectionVersion"]) is not int
        or source_projection["projectionVersion"] != 1
    ):
        raise ValueError("Coding Source projection version is unsupported")
    scopes = source_projection["scopes"]
    if not isinstance(scopes, dict) or set(scopes) != set(_SCOPES):
        raise ValueError("Coding Source projection scopes are invalid")

    disabled: list[CodingScopedLegacyDisableV1] = []
    sources: list[str] = []
    for scope in _SCOPES:
        layer = scopes[scope]
        if not isinstance(layer, dict) or set(layer) != {
            "present",
            "rawSha256",
            "settingsPath",
            "sourcePatch",
        }:
            raise ValueError("Coding Source projection layer is invalid")
        present, digest, path, patch = (
            layer["present"],
            layer["rawSha256"],
            layer["settingsPath"],
            layer["sourcePatch"],
        )
        if (
            type(present) is not bool
            or (
                present
                and (not isinstance(digest, str) or not _SHA256.fullmatch(digest))
            )
            or (not present and digest is not None)
            or not isinstance(path, str)
            or not path.startswith("/")
            or not isinstance(patch, dict)
            or not set(patch) <= _PROJECTION_KEYS
            or (not present and patch)
        ):
            raise ValueError("Coding Source projection layer is invalid")
        for key, value in patch.items():
            if not isinstance(value, list):
                raise ValueError("Coding legacy Source setting is invalid")
            if key == "disabled_plugins":
                if any(not isinstance(item, str) or not item for item in value):
                    raise ValueError("Coding legacy disabled Plugin is invalid")
                if len(value) != len(set(value)):
                    raise ValueError("Coding legacy disabled Plugin is duplicated")
                disabled.extend(
                    CodingScopedLegacyDisableV1(scope, item) for item in value
                )
            elif key in _SOURCE_KEYS and value:
                sources.append(f"{scope}:{key}")

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
        if sources
        else "disabled_only"
        if disabled
        else "fresh"
    )
    return CodingLegacyWorkspaceClassificationV1(
        kind=kind,
        disabled_plugins=tuple(disabled),
        configured_source_keys=tuple(sources),
        lifecycle_members=lifecycle_names,
        package_members=package_names,
    )


__all__ = [
    "CodingLegacyWorkspaceClassificationV1",
    "CodingLegacyWorkspaceKindV1",
    "CodingScopedLegacyDisableV1",
    "classify_coding_legacy_workspace",
]
