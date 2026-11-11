"""Shared read-only Package GC reference join for Coding Worker attempts."""

from __future__ import annotations

from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.worker.history._retention import (
    gc_revision_refs,
    matching_gc_revision_refs,
)


def coding_worker_gc_revision_refs(
    snapshot: PluginPackageGcReservationSnapshotV1,
) -> frozenset[PluginPackageRevisionRefV1]:
    """Extract Package revision pins from a versioned owner snapshot."""

    return gc_revision_refs(snapshot)


def matching_coding_worker_gc_revision_refs(
    *,
    plugin_id: str,
    package_content_digest: str,
    reservations: frozenset[PluginPackageRevisionRefV1],
) -> tuple[PluginPackageRevisionRefV1, ...]:
    """Keep every active reservation for the exact Plugin and Wheel artifact.

    The dependency lock may differ across retained Package revisions. This
    observation is not an attempt-level absence proof or prune authorization.
    """

    return matching_gc_revision_refs(
        plugin_id=plugin_id,
        package_content_digest=package_content_digest,
        reservations=reservations,
    )


__all__ = [
    "coding_worker_gc_revision_refs",
    "matching_coding_worker_gc_revision_refs",
]
