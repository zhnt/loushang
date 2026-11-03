"""Coding Product trust classes for typed external data Resources."""

from __future__ import annotations

from typing import Literal

CodingLegacyDataResourceKind = Literal["skill", "prompt", "theme"]

_TRUST_CLASS_BY_RESOURCE_KIND: dict[CodingLegacyDataResourceKind, str] = {
    "skill": "legacy-local-reacquired",
    "prompt": "legacy-local-reacquired-prompt",
    "theme": "legacy-local-reacquired-theme",
}
LEGACY_LOCAL_DATA_TRUST_CLASSES = frozenset(_TRUST_CLASS_BY_RESOURCE_KIND.values())

LEGACY_LOCAL_DATA_OWNER_BY_TRUST_CLASS = {
    "legacy-local-reacquired": "resources.skill",
    "legacy-local-reacquired-prompt": "resources.prompt",
    "legacy-local-reacquired-theme": "resources.theme",
}

EXTERNAL_DATA_TRUST_CLASSES_ORDERED = (
    "local-data-only",
    "legacy-local-reacquired",
    "legacy-local-reacquired-prompt",
    "legacy-local-reacquired-theme",
)
EXTERNAL_DATA_TRUST_CLASSES = frozenset(EXTERNAL_DATA_TRUST_CLASSES_ORDERED)


def permits_external_data_owner(trust_class: str, owner: str) -> bool:
    if trust_class == "local-data-only":
        return True
    return LEGACY_LOCAL_DATA_OWNER_BY_TRUST_CLASS.get(trust_class) == owner


def trust_class_for_legacy_data_resource(
    resource_kind: CodingLegacyDataResourceKind,
) -> str:
    return _TRUST_CLASS_BY_RESOURCE_KIND[resource_kind]
