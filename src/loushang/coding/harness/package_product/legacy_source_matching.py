"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_configured_source as _binding


def match_configured_source(
    projection: object,
    *,
    source_identity: str,
    installed_source_identities: tuple[str, ...] | None,
) -> _binding.CodingLegacyLocalConfiguredSourceV1 | None:
    """Match one old data Source within the complete installed local set.

    This is an inert assessment. It does not consume settings or authorize a
    first fence; the caller must supply the verified frozen projection.
    """

    identities = (
        (source_identity,)
        if installed_source_identities is None
        else installed_source_identities
    )
    if (
        type(source_identity) is not str
        or type(identities) is not tuple
        or not 0 < len(identities) <= _binding._LEGACY_EVIDENCE_MAX_SOURCES
        or any(
            type(identity) is not str or not identity.startswith("local:/")
            for identity in identities
        )
        or len(identities) != len(set(identities))
        or source_identity not in identities
    ):
        raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_001"])
    classification = _binding.classify_coding_legacy_source_configuration(projection)
    if any(
        item.plugin_id not in _binding._BUILTINS
        for item in classification.disabled_plugins
    ):
        raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_002"])
    assert isinstance(projection, dict)
    scopes = projection["scopes"]
    configured: dict[str, _binding.CodingLegacyLocalConfiguredSourceV1] = {}
    configured_scopes = 0
    for scope in ("global", "project"):
        patch = scopes[scope]["sourcePatch"]
        if set(patch) - {"disabled_plugins", "plugin_sources"}:
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_002"])
        if "plugin_sources" not in patch:
            continue
        values = patch["plugin_sources"]
        if values:
            configured_scopes += 1
        for path in values:
            if (
                not isinstance(path, str)
                or not _binding.Path(path).is_absolute()
                or any(part in {".", ".."} for part in path.split("/"))
                or f"local:{path}" not in identities
            ):
                raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_003"])
            if path in configured:
                raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_004"])
            configured[path] = _binding.CodingLegacyLocalConfiguredSourceV1(scope, path)
    if (
        len(configured) > len(identities)
        or len(classification.configured_source_keys) != configured_scopes
    ):
        raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_002"])
    return configured.get(source_identity.removeprefix("local:"))
