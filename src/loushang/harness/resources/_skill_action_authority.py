"""Private live Resource-owner registry for Catalog-managed Skill actions."""

from __future__ import annotations

import weakref
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _CatalogActionRegistration:
    action_ref: weakref.ReferenceType[object]
    owner_identity: object
    catalog_generation: int
    catalog_snapshot_fingerprint: str
    binding_source_fingerprint: str
    skill_root_identity: tuple[int, int]


_REGISTRATIONS: dict[int, _CatalogActionRegistration] = {}


def _register_catalog_managed_skill_action(
    action: object,
    *,
    owner_identity: object,
    catalog_generation: int,
    catalog_snapshot_fingerprint: str,
    binding_source_fingerprint: str,
    skill_root_identity: tuple[int, int],
) -> None:
    """Register one exact action outside its caller-constructible evidence graph."""

    if type(owner_identity) is not object:
        raise TypeError("Catalog action owner identity is invalid")
    action_id = id(action)
    if action_id in _REGISTRATIONS:
        raise RuntimeError("Catalog action identity is already registered")

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _REGISTRATIONS.get(action_id)
        if current is not None and current.action_ref is reference:
            _REGISTRATIONS.pop(action_id, None)

    reference = weakref.ref(action, discard)
    _REGISTRATIONS[action_id] = _CatalogActionRegistration(
        action_ref=reference,
        owner_identity=owner_identity,
        catalog_generation=catalog_generation,
        catalog_snapshot_fingerprint=catalog_snapshot_fingerprint,
        binding_source_fingerprint=binding_source_fingerprint,
        skill_root_identity=skill_root_identity,
    )


def _verify_catalog_managed_skill_action(action: object) -> None:
    """Require a live exact registration minted by the Resource owner."""

    registration = _REGISTRATIONS.get(id(action))
    selection = getattr(action, "selection", None)
    if (
        registration is None
        or registration.action_ref() is not action
        or getattr(action, "_owner_identity", None)
        is not registration.owner_identity
        or getattr(selection, "_owner_identity", None)
        is not registration.owner_identity
        or getattr(selection, "catalog_generation", None)
        != registration.catalog_generation
        or getattr(selection, "catalog_snapshot_fingerprint", None)
        != registration.catalog_snapshot_fingerprint
        or getattr(action, "binding_source_fingerprint", None)
        != registration.binding_source_fingerprint
        or getattr(action, "_skill_root_identity", None)
        != registration.skill_root_identity
    ):
        raise ValueError("Catalog action is not live Resource-owner evidence")


__all__: list[str] = []
