"""Strict frozen-settings match for installed local data Plugin Sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .legacy_classification import _SOURCE_KEYS
from .source_snapshot import _LEGACY_DISABLE_SETTING, _source_projection

CodingLegacySourceScope = Literal["global", "project"]
_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})


_LEGACY_EVIDENCE_MAX_SOURCES = 16


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
    if type(source_identity) is not str:
        raise ValueError("Legacy local data Source set is invalid")
    configured = _index_configured_sources(
        projection, identities, required_identity=source_identity
    )
    return configured.get(source_identity.removeprefix("local:"))


def _index_configured_sources(
    projection: object,
    identities: tuple[str, ...],
    *,
    required_identity: str | None = None,
) -> dict[str, CodingLegacyLocalConfiguredSourceV1]:
    """Verify every configured source against one exact local installation set."""
    scoped_paths = _source_projection.index_configured_local_sources(
        projection,
        identities,
        required_identity=required_identity,
        max_sources=_LEGACY_EVIDENCE_MAX_SOURCES,
        builtin_ids=_BUILTINS,
        disabled_setting=_LEGACY_DISABLE_SETTING,
        configured_source_keys=_SOURCE_KEYS,
    )
    return {
        path: CodingLegacyLocalConfiguredSourceV1(scope, path)
        for path, scope in scoped_paths.items()
    }


__all__ = [
    "CodingLegacyLocalConfiguredSourceV1",
    "CodingLegacySourceScope",
    "match_coding_legacy_local_skill_configured_source",
]
