"""Private single-use grants from a captured Resource Catalog owner."""

from __future__ import annotations

import weakref
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, init=False)
class _ResourceCatalogOwnerGrant:
    """Opaque, single-use proof minted by one exact Catalog owner view."""

    def __init__(self) -> None:
        raise TypeError("Resource Catalog owner grants are owner-minted")


@dataclass(frozen=True, slots=True)
class _ResourceCatalogOwnerGrantRecord:
    owner_ref: weakref.ReferenceType[object]
    grant: _ResourceCatalogOwnerGrant
    snapshot: object
    skill_projection: object
    catalog_generation: int
    snapshot_fingerprint: str


_OWNER_GRANTS: dict[int, _ResourceCatalogOwnerGrantRecord] = {}


def _mint_resource_catalog_owner_grant(
    owner: object,
    *,
    snapshot: object,
    skill_projection: object,
) -> _ResourceCatalogOwnerGrant:
    """Mint one claim for an owner-created exact-generation Catalog view."""

    catalog_generation = getattr(snapshot, "catalog_generation", None)
    snapshot_fingerprint = getattr(snapshot, "snapshot_fingerprint", None)
    if (
        type(catalog_generation) is not int
        or not isinstance(snapshot_fingerprint, str)
        or getattr(skill_projection, "catalog_generation", None)
        != catalog_generation
        or getattr(skill_projection, "catalog_snapshot_fingerprint", None)
        != snapshot_fingerprint
        or getattr(owner, "snapshot", None) is not snapshot
        or getattr(owner, "skill_projection", None) is not skill_projection
    ):
        raise TypeError("Resource Catalog owner grant requires one exact projection")
    grant = object.__new__(_ResourceCatalogOwnerGrant)
    grant_id = id(grant)

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _OWNER_GRANTS.get(grant_id)
        if current is not None and current.owner_ref is reference:
            _OWNER_GRANTS.pop(grant_id, None)

    owner_ref = weakref.ref(owner, discard)
    _OWNER_GRANTS[grant_id] = _ResourceCatalogOwnerGrantRecord(
        owner_ref=owner_ref,
        grant=grant,
        snapshot=snapshot,
        skill_projection=skill_projection,
        catalog_generation=catalog_generation,
        snapshot_fingerprint=snapshot_fingerprint,
    )
    return grant


def _consume_resource_catalog_owner_grant(
    grant: object,
    *,
    owner: object,
    snapshot: object,
    skill_projection: object,
) -> None:
    """Consume an exact live owner claim before binding a downstream consumer."""

    if type(grant) is not _ResourceCatalogOwnerGrant:
        raise TypeError("Catalog action owner requires a Resource owner grant")
    record = _OWNER_GRANTS.get(id(grant))
    if (
        record is None
        or record.grant is not grant
        or record.owner_ref() is not owner
        or record.snapshot is not snapshot
        or record.skill_projection is not skill_projection
        or getattr(owner, "snapshot", None) is not snapshot
        or getattr(owner, "skill_projection", None) is not skill_projection
        or getattr(snapshot, "catalog_generation", None)
        != record.catalog_generation
        or getattr(snapshot, "snapshot_fingerprint", None)
        != record.snapshot_fingerprint
        or getattr(skill_projection, "catalog_generation", None)
        != record.catalog_generation
        or getattr(skill_projection, "catalog_snapshot_fingerprint", None)
        != record.snapshot_fingerprint
    ):
        raise TypeError("Catalog action owner requires a live Resource owner grant")
    _OWNER_GRANTS.pop(id(grant), None)


__all__: list[str] = []
