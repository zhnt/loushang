"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_classification as _binding


def classify_workspace_evidence(
    source_projection: object,
    *,
    lifecycle: _binding.CodingLifecyclePreBMembersV1,
    package: _binding.CodingPackagePreBStoreMembersV1,
) -> _binding.CodingLegacyWorkspaceClassificationV1:
    """Partition exact snapshot inputs while preserving settings scope.

    The caller must supply the verified Source projection while its settings
    locks are held. This function never reads old bytes or grants a B revision.
    """

    if not isinstance(
        lifecycle, _binding.CodingLifecyclePreBMembersV1
    ) or not isinstance(package, _binding.CodingPackagePreBStoreMembersV1):
        raise TypeError(_binding._LEGACY_EVIDENCE_VALUES["value_001"])
    configuration = _binding.classify_coding_legacy_source_configuration(
        source_projection
    )
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
    kind: _binding.CodingLegacyWorkspaceKindV1 = (
        "legacy_state"
        if lifecycle_names or package_names
        else "configured_source"
        if configuration.configured_source_keys
        else "disabled_only"
        if configuration.disabled_plugins
        else "fresh"
    )
    return _binding.CodingLegacyWorkspaceClassificationV1(
        kind=kind,
        disabled_plugins=configuration.disabled_plugins,
        configured_source_keys=configuration.configured_source_keys,
        lifecycle_members=lifecycle_names,
        package_members=package_names,
    )


def classify_source_projection(
    source_projection: object,
) -> _binding.CodingLegacySourceConfigurationV1:
    """Validate the frozen settings projection without reading mutable state."""

    if not isinstance(source_projection, dict) or set(source_projection) != {
        "productId",
        "projectionVersion",
        "scopes",
    }:
        raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_002"])
    if (
        source_projection["productId"] != _binding._LEGACY_EVIDENCE_VALUES["value_003"]
        or type(source_projection["projectionVersion"]) is not int
        or source_projection["projectionVersion"] != 1
    ):
        raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_004"])
    scopes = source_projection["scopes"]
    if not isinstance(scopes, dict) or set(scopes) != set(_binding._SCOPES):
        raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_005"])

    disabled: list[_binding.CodingScopedLegacyDisableV1] = []
    sources: list[str] = []
    for scope in _binding._SCOPES:
        layer = scopes[scope]
        if not isinstance(layer, dict) or set(layer) != {
            "present",
            "rawSha256",
            "settingsPath",
            "sourcePatch",
        }:
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_006"])
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
                and (
                    not isinstance(digest, str)
                    or not _binding._SHA256.fullmatch(digest)
                )
            )
            or (not present and digest is not None)
            or not isinstance(path, str)
            or not _binding.Path(path).is_absolute()
            or ".." in _binding.Path(path).parts
            or not isinstance(patch, dict)
            or not set(patch) <= _binding._PROJECTION_KEYS
            or (not present and patch)
            or ("packages" in patch and "package_sources" in patch)
        ):
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_006"])
        for key, value in patch.items():
            if not isinstance(value, list):
                raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_007"])
            if key == "disabled_plugins":
                if any(not isinstance(item, str) or not item for item in value):
                    raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_008"])
                if len(value) != len(set(value)):
                    raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_009"])
                disabled.extend(
                    _binding.CodingScopedLegacyDisableV1(scope, item) for item in value
                )
            elif key in {"packages", "package_sources"}:
                if any(not valid_package_source(item) for item in value):
                    raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_010"])
            elif any(not isinstance(item, str) or not item for item in value):
                raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_007"])
            if key in _binding._SOURCE_KEYS and value:
                sources.append(f"{scope}:{key}")

    return _binding.CodingLegacySourceConfigurationV1(
        disabled_plugins=tuple(disabled),
        configured_source_keys=tuple(sources),
    )


def valid_package_source(value: object) -> bool:
    if isinstance(value, str):
        return bool(value)
    if not isinstance(value, dict) or not set(value) <= {
        "source",
        *_binding._PACKAGE_FILTER_KEYS,
    }:
        return False
    source = value.get("source")
    if not isinstance(source, str) or not source:
        return False
    return all(
        isinstance(items, list)
        and all(isinstance(item, str) and item for item in items)
        for key, items in value.items()
        if key in _binding._PACKAGE_FILTER_KEYS
    )
