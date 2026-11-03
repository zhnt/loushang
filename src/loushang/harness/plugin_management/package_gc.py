"""Read-only PLC9D package-GC and cleanup-debt projection.

The projection exposes durable owner evidence, not a deletion capability. A
candidate must still be rechecked and reserved by a future Store GC owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loushang.harness.plugin_management.package_lifecycle import (
    PluginCleanupTaskSnapshotV1,
    PluginPackageGcCandidateV1,
    PluginPackageLifecycleSnapshotV1,
    PluginPackageRetentionSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1

PLUGIN_PACKAGE_GC_OPERATOR_PROJECTION_VERSION = 1


class PluginPackageGcSnapshotSourcePort(Protocol):
    def snapshot(self) -> PluginPackageLifecycleSnapshotV1: ...


@dataclass(frozen=True, slots=True)
class PluginPackageGcOperatorRowV1:
    package_revision: PluginPackageRevisionRefV1
    blocker_codes: tuple[str, ...]
    candidate: PluginPackageGcCandidateV1 | None
    cleanup_tasks: tuple[PluginCleanupTaskSnapshotV1, ...]

    def __post_init__(self) -> None:
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("Package GC blocker codes must be sorted and unique")
        if (self.candidate is None) != bool(self.blocker_codes):
            raise ValueError("Package GC candidate and blockers disagree")
        if self.candidate is not None and (
            self.candidate.package_revision != self.package_revision
        ):
            raise ValueError("Package GC candidate names another revision")
        if self.cleanup_tasks != tuple(
            sorted(self.cleanup_tasks, key=lambda item: item.task.cleanup_id)
        ):
            raise ValueError("Package GC cleanup tasks must be sorted")
        if any(
            item.task.package_revision != self.package_revision
            for item in self.cleanup_tasks
        ):
            raise ValueError("Package GC cleanup task names another revision")

    def to_dict(self) -> dict[str, object]:
        candidate = self.candidate
        return {
            "blockerCodes": list(self.blocker_codes),
            "candidate": (
                None
                if candidate is None
                else {
                    "candidateId": candidate.candidate_id,
                    "candidateVersion": candidate.candidate_version,
                    "desiredInventoryRevision": candidate.desired_inventory_revision,
                    "instanceRuntimeRevision": candidate.instance_runtime_revision,
                    "packageJournalRevision": candidate.package_journal_revision,
                    "recoveryBarrierId": candidate.recovery_barrier_id,
                }
            ),
            "cleanupTasks": [
                {
                    "cleanupId": item.task.cleanup_id,
                    "state": item.state,
                    "attemptCount": len(item.attempts),
                    "leaseOpen": item.lease_open,
                    "lastResultCode": (
                        None if not item.attempts else item.attempts[-1].result_code
                    ),
                    "retryNotBeforeEpochMs": (
                        None
                        if not item.attempts
                        else item.attempts[-1].retry_not_before_epoch_ms
                    ),
                    "lastRepairAction": (
                        None
                        if not item.repair_decisions
                        else item.repair_decisions[-1].action
                    ),
                }
                for item in self.cleanup_tasks
            ],
            "packageRevision": self.package_revision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PluginPackageGcOperatorProjectionV1:
    startup_id: str
    package_journal_revision: int
    recovery_complete: bool
    packages: tuple[PluginPackageGcOperatorRowV1, ...]
    projection_version: int = PLUGIN_PACKAGE_GC_OPERATOR_PROJECTION_VERSION

    def __post_init__(self) -> None:
        if self.projection_version != PLUGIN_PACKAGE_GC_OPERATOR_PROJECTION_VERSION:
            raise ValueError("Unsupported Package GC operator projection")
        if self.packages != tuple(
            sorted(
                self.packages, key=lambda item: _package_sort_key(item.package_revision)
            )
        ):
            raise ValueError("Package GC operator rows must be sorted")
        if len({item.package_revision for item in self.packages}) != len(self.packages):
            raise ValueError("Package GC operator rows must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "packageJournalRevision": self.package_journal_revision,
            "packages": [item.to_dict() for item in self.packages],
            "projectionVersion": self.projection_version,
            "recoveryComplete": self.recovery_complete,
            "startupId": self.startup_id,
        }


class PluginPackageGcReadModel:
    """Project every known revision, including history-only GC candidates."""

    def __init__(self, lifecycle: PluginPackageGcSnapshotSourcePort) -> None:
        self._lifecycle = lifecycle

    def snapshot(self) -> PluginPackageGcOperatorProjectionV1:
        source = self._lifecycle.snapshot()
        tasks_by_package: dict[
            PluginPackageRevisionRefV1, list[PluginCleanupTaskSnapshotV1]
        ] = {}
        for item in source.cleanup_tasks:
            tasks_by_package.setdefault(item.task.package_revision, []).append(item)
        return PluginPackageGcOperatorProjectionV1(
            startup_id=source.startup_id,
            package_journal_revision=source.journal_revision,
            recovery_complete=source.startup_recovered,
            packages=tuple(
                _row(item, source, tasks_by_package.get(item.package_revision, []))
                for item in source.packages
            ),
        )


def _row(
    retained: PluginPackageRetentionSnapshotV1,
    source: PluginPackageLifecycleSnapshotV1,
    cleanup_tasks: list[PluginCleanupTaskSnapshotV1],
) -> PluginPackageGcOperatorRowV1:
    blockers = set()
    if not source.startup_recovered:
        blockers.add("startup_recovery")
    for values, code in (
        (retained.desired_installations, "desired_installation"),
        (retained.nonretired_instances, "nonretired_instance"),
        (retained.open_runtime_family_ids, "runtime_family"),
        (retained.open_pin_ids, "retention_pin"),
        (retained.open_cleanup_ids, "cleanup_lease"),
        (retained.terminal_failure_cleanup_ids, "terminal_cleanup_failure"),
    ):
        if values:
            blockers.add(code)
    return PluginPackageGcOperatorRowV1(
        package_revision=retained.package_revision,
        blocker_codes=tuple(sorted(blockers)),
        candidate=retained.gc_candidate,
        cleanup_tasks=tuple(cleanup_tasks),
    )


def _package_sort_key(
    package_revision: PluginPackageRevisionRefV1,
) -> tuple[str, str, str, str, str]:
    return (
        package_revision.plugin_id,
        package_revision.plugin_version or "",
        package_revision.package_content_digest,
        package_revision.dependency_lock_digest,
        package_revision.package_source_identity,
    )


__all__ = [
    "PLUGIN_PACKAGE_GC_OPERATOR_PROJECTION_VERSION",
    "PluginPackageGcOperatorProjectionV1",
    "PluginPackageGcOperatorRowV1",
    "PluginPackageGcReadModel",
    "PluginPackageGcSnapshotSourcePort",
]
