"""Strict frozen-settings match for installed local data Plugin Sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path as Path
from typing import Literal

from loushang.coding.harness.package_product import legacy_source_matching as _programs

from .legacy_classification import (
    classify_coding_legacy_source_configuration as classify_coding_legacy_source_configuration,
)

CodingLegacySourceScope = Literal["global", "project"]
_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})


_LEGACY_EVIDENCE_MAX_SOURCES = 16

_LEGACY_EVIDENCE_VALUES = {
    "value_001": "Legacy local data Source set is invalid",
    "value_002": "Legacy local data settings need a separate migration",
    "value_003": "Configured Source must be the same installed local Source",
    "value_004": "Legacy Skill configured Sources are duplicated",
}


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

    return _programs.match_configured_source(
        projection,
        source_identity=source_identity,
        installed_source_identities=installed_source_identities,
    )


__all__ = [
    "CodingLegacyLocalConfiguredSourceV1",
    "CodingLegacySourceScope",
    "match_coding_legacy_local_skill_configured_source",
]
