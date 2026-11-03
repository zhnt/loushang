"""Conservative reference accounting for dependency Store GC planning.

This is a read model. It does not reserve a dependency or authorize deletion.
Only a Product-verified successful root deletion may release a holder here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementRecordV1,
    same_content_dependency_settlement,
)


class PackageDependencyGcTargetError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageDependencyRetentionV1:
    dependency_ref: VerifiedArtifactRefV1
    holder_root_ref_ids: tuple[str, ...]
    live_root_ref_ids: tuple[str, ...]
    disposition: Literal["retained", "orphan_candidate"]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dependency_ref, VerifiedArtifactRefV1)
            or not self.holder_root_ref_ids
            or self.holder_root_ref_ids != tuple(sorted(set(self.holder_root_ref_ids)))
            or self.live_root_ref_ids != tuple(sorted(set(self.live_root_ref_ids)))
            or not set(self.live_root_ref_ids) <= set(self.holder_root_ref_ids)
            or self.disposition
            != ("retained" if self.live_root_ref_ids else "orphan_candidate")
        ):
            raise ValueError("Dependency retention evidence is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "dependencyRefId": self.dependency_ref.ref_id,
            "holderRootRefIds": list(self.holder_root_ref_ids),
            "liveRootRefIds": list(self.live_root_ref_ids),
            "disposition": self.disposition,
        }


@dataclass(frozen=True, slots=True)
class PackageDependencyGcTargetV1:
    """Exact physical dependency identity, still without deletion authority."""

    retention: PackageDependencyRetentionV1
    publisher_set_id: str
    settlement: PackageStoreSettlementRecordV1

    @property
    def settlement_id(self) -> str:
        return self.settlement.settlement_id


@dataclass(frozen=True, slots=True)
class PackageDependencyGcInspectionV1:
    """Pathless operator read, never a deletion permit."""

    retention: PackageDependencyRetentionV1
    target: PackageDependencyGcTargetV1 | None = None
    reason_code: str | None = None
    deletion_state: Literal[
        "not_started", "started", "retryable_failure", "terminal_failure", "succeeded"
    ] = "not_started"
    deletion_start_id: str | None = None
    latest_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.retention, PackageDependencyRetentionV1):
            raise TypeError("Dependency retention evidence is required")
        if self.target is not None and (
            not isinstance(self.target, PackageDependencyGcTargetV1)
            or self.target.retention != self.retention
            or self.reason_code is not None
        ):
            raise ValueError("Dependency GC target inspection is invalid")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str)
            or not self.reason_code
            or self.retention.disposition != "orphan_candidate"
        ):
            raise ValueError("Dependency GC refusal is invalid")
        if self.retention.disposition == "retained" and (
            self.target is not None or self.reason_code is not None
        ):
            raise ValueError("Retained dependency cannot have a deletion target")
        if self.retention.disposition == "orphan_candidate" and (
            (self.target is None) == (self.reason_code is None)
        ):
            raise ValueError("Orphan dependency needs a target or refusal")
        if (
            self.deletion_state
            not in {
                "not_started",
                "started",
                "retryable_failure",
                "terminal_failure",
                "succeeded",
            }
            or (
                self.deletion_state == "not_started"
                and (
                    self.deletion_start_id is not None
                    or self.latest_attempt_id is not None
                )
            )
            or (
                self.deletion_state != "not_started"
                and (self.target is None or not self.deletion_start_id)
            )
            or (
                self.deletion_state
                in {"retryable_failure", "terminal_failure", "succeeded"}
                and not self.latest_attempt_id
            )
            or (self.deletion_state == "started" and self.latest_attempt_id is not None)
        ):
            raise ValueError("Dependency GC deletion state is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            **self.retention.to_dict(),
            "targetSettlementId": (
                None if self.target is None else self.target.settlement_id
            ),
            "targetStatus": (
                "retained"
                if self.retention.disposition == "retained"
                else self.deletion_state
                if self.target is not None and self.deletion_state != "not_started"
                else "exact_target"
                if self.target is not None
                else "evidence_conflict"
            ),
            "reasonCode": self.reason_code,
            "deletionStartId": self.deletion_start_id,
            "latestAttemptId": self.latest_attempt_id,
        }


def project_package_dependency_retention(
    committed_sets: tuple[PackageCommittedSetRecordV1, ...],
    *,
    successfully_deleted_root_ref_ids: frozenset[str],
) -> tuple[PackageDependencyRetentionV1, ...]:
    """Keep every dependency while any committed root lacks delete proof."""

    if not all(
        isinstance(item, PackageCommittedSetRecordV1) for item in committed_sets
    ):
        raise TypeError("Committed Package set records are required")
    if not isinstance(successfully_deleted_root_ref_ids, frozenset) or not all(
        isinstance(item, str) for item in successfully_deleted_root_ref_ids
    ):
        raise TypeError("Verified Product root deletion identities are required")
    refs: dict[str, VerifiedArtifactRefV1] = {}
    holders: dict[str, set[str]] = {}
    known_roots: set[str] = set()
    for record in committed_sets:
        root_id = record.committed_set.root_ref.ref_id
        if root_id in known_roots:
            raise ValueError("Committed Package root ref is aliased")
        known_roots.add(root_id)
        for ref in record.committed_set.dependency_refs:
            previous = refs.setdefault(ref.ref_id, ref)
            if previous != ref:
                raise ValueError("Dependency ref identity is ambiguous")
            holders.setdefault(ref.ref_id, set()).add(root_id)
    if not successfully_deleted_root_ref_ids <= known_roots:
        raise ValueError("Root deletion proof has no committed Package set")
    return tuple(
        PackageDependencyRetentionV1(
            dependency_ref=refs[ref_id],
            holder_root_ref_ids=tuple(sorted(root_ids)),
            live_root_ref_ids=tuple(
                sorted(root_ids - successfully_deleted_root_ref_ids)
            ),
            disposition=(
                "retained"
                if root_ids - successfully_deleted_root_ref_ids
                else "orphan_candidate"
            ),
        )
        for ref_id, root_ids in sorted(holders.items())
    )


def resolve_package_dependency_gc_target(
    retention: PackageDependencyRetentionV1,
    *,
    committed_sets: tuple[PackageCommittedSetRecordV1, ...],
    settlements: tuple[PackageStoreSettlementRecordV1, ...],
) -> PackageDependencyGcTargetV1:
    """Join an orphan candidate to one Store settlement and publisher graph."""

    if not isinstance(retention, PackageDependencyRetentionV1):
        raise TypeError("Exact dependency retention evidence is required")
    if not all(
        isinstance(item, PackageCommittedSetRecordV1) for item in committed_sets
    ):
        raise TypeError("Committed Package set records are required")
    if not all(
        isinstance(item, PackageStoreSettlementRecordV1) for item in settlements
    ):
        raise TypeError("Dependency Store settlement records are required")
    if retention.disposition != "orphan_candidate":
        raise PackageDependencyGcTargetError(
            "Dependency still has a live holder",
            code="plugin_package_gc_dependency_retained",
        )
    ref = retention.dependency_ref
    if any(
        item.ref_id == ref.ref_id and item != ref
        for record in committed_sets
        for item in record.committed_set.dependency_refs
    ):
        raise PackageDependencyGcTargetError(
            "Dependency ref is aliased by another committed set",
            code="plugin_package_gc_dependency_aliased",
        )
    holders = tuple(
        record
        for record in committed_sets
        if ref in record.committed_set.dependency_refs
    )
    if (
        not holders
        or tuple(sorted(record.committed_set.root_ref.ref_id for record in holders))
        != retention.holder_root_ref_ids
    ):
        raise PackageDependencyGcTargetError(
            "Dependency holder graph changed",
            code="plugin_package_gc_dependency_holders_changed",
        )
    matching = tuple(
        item
        for item in settlements
        if item.store_role == "dependency"
        and item.store_identity == ref.store_identity
        and item.receipt.stable_ref == ref
    )
    if (
        not matching
        or len({item.settlement_id for item in matching}) != len(matching)
        or any(
            not same_content_dependency_settlement(matching[0], item)
            for item in matching[1:]
        )
    ):
        raise PackageDependencyGcTargetError(
            "Dependency has no unique physical Store settlement",
            code="plugin_package_gc_dependency_settlement_unavailable",
        )
    if any(
        item not in matching
        and item.store_identity == ref.store_identity
        and (
            item.final_name == matching[0].final_name
            or item.tree_identity == matching[0].tree_identity
        )
        for item in settlements
    ):
        raise PackageDependencyGcTargetError(
            "Dependency physical tree is aliased",
            code="plugin_package_gc_dependency_aliased",
        )
    publishers = tuple(
        (settlement, record)
        for settlement in matching
        for record in holders
        for staging in (settlement.receipt.staging_request,)
        if settlement.manifest.node_id == staging.node_id
        and record.operation_id == staging.operation_id
        and record.committed_set.attempt_epoch == staging.attempt_epoch
        and record.committed_set.request_fingerprint == staging.request_fingerprint
        and record.committed_set.classification_fingerprint
        == staging.classification_fingerprint
        and record.committed_set.prepublication_graph_digest
        == staging.prepublication_graph_digest
        and any(
            node.node_id == staging.node_id
            and node.plan_node == staging.plan_node
            and node.stable_ref == ref
            for node in record.closure_lock.nodes
        )
    )
    if not publishers or len(
        {record.committed_set.set_id for _, record in publishers}
    ) != len(publishers):
        raise PackageDependencyGcTargetError(
            "Dependency Store settlement lacks its exact committed publisher",
            code="plugin_package_gc_dependency_publisher_changed",
        )
    settlement, publisher = min(publishers, key=lambda pair: pair[0].record_revision)
    return PackageDependencyGcTargetV1(
        retention=retention,
        publisher_set_id=publisher.committed_set.set_id,
        settlement=settlement,
    )


__all__ = [
    "PackageDependencyGcInspectionV1",
    "PackageDependencyGcTargetError",
    "PackageDependencyGcTargetV1",
    "PackageDependencyRetentionV1",
    "project_package_dependency_retention",
    "resolve_package_dependency_gc_target",
]
