"""Strict frozen-settings match for installed local data Plugin Sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .package_legacy_classification import (
    classify_coding_legacy_source_configuration,
)

CodingLegacySourceScope = Literal["global", "project"]
_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalConfiguredSourceV1:
    scope: CodingLegacySourceScope
    path: str


def match_coding_legacy_local_skill_configured_source(
    projection: object,
    *,
    source_identity: str,
    installed_source_identities: tuple[str, ...] | None = None,
) -> CodingLegacyLocalConfiguredSourceV1 | None:
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
        or not 0 < len(identities) <= 16
        or any(
            type(identity) is not str or not identity.startswith("local:/")
            for identity in identities
        )
        or len(identities) != len(set(identities))
        or source_identity not in identities
    ):
        raise ValueError("Legacy local data Source set is invalid")
    classification = classify_coding_legacy_source_configuration(projection)
    if any(item.plugin_id not in _BUILTINS for item in classification.disabled_plugins):
        raise ValueError("Legacy local data settings need a separate migration")
    assert isinstance(projection, dict)
    scopes = projection["scopes"]
    configured: dict[str, CodingLegacyLocalConfiguredSourceV1] = {}
    configured_scopes = 0
    for scope in ("global", "project"):
        patch = scopes[scope]["sourcePatch"]
        if set(patch) - {"disabled_plugins", "plugin_sources"}:
            raise ValueError("Legacy local data settings need a separate migration")
        if "plugin_sources" not in patch:
            continue
        values = patch["plugin_sources"]
        if values:
            configured_scopes += 1
        for path in values:
            if (
                not isinstance(path, str)
                or not Path(path).is_absolute()
                or any(part in {".", ".."} for part in path.split("/"))
                or f"local:{path}" not in identities
            ):
                raise ValueError(
                    "Configured Source must be the same installed local Source"
                )
            if path in configured:
                raise ValueError("Legacy Skill configured Sources are duplicated")
            configured[path] = CodingLegacyLocalConfiguredSourceV1(scope, path)
    if (
        len(configured) > len(identities)
        or len(classification.configured_source_keys) != configured_scopes
    ):
        raise ValueError("Legacy local data settings need a separate migration")
    return configured.get(source_identity.removeprefix("local:"))


__all__ = [
    "CodingLegacyLocalConfiguredSourceV1",
    "CodingLegacySourceScope",
    "match_coding_legacy_local_skill_configured_source",
]
