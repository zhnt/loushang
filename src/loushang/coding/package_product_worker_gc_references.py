"""Shared read-only Package GC reference join for Coding Worker attempts."""

from __future__ import annotations

from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1 as PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.plugin_management.records import (
    PluginPackageRevisionRefV1 as PluginPackageRevisionRefV1,
)
from loushang.harness.worker.history._retention import (
    gc_revision_refs,
    matching_gc_revision_refs,
)

coding_worker_gc_revision_refs = gc_revision_refs


matching_coding_worker_gc_revision_refs = matching_gc_revision_refs


__all__ = [
    "coding_worker_gc_revision_refs",
    "matching_coding_worker_gc_revision_refs",
]
