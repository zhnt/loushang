"""One guarded read of the three independent Product A2 rebind observations.

This joins identities for operator evidence. Durable rebind still requires a
mutation-side recheck and an explicit owner authorization decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductAcquiredCleanupObservationV1,
    PackageProductPinnedCleanupObservationV1,
    PackageProductRebindCleanupObservationV1,
    PackageProductResolvingCleanupObservationV1,
)
from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseObservationV1,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceObservationV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackagePublishedSetCheckpointV1,
    PackageStagingCheckpointV1,
)


class PackageProductRebindPreflightError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductRebindPreflightV1:
    source: PackageProductRebindSourceObservationV1
    lease: PackageProductRebindLeaseObservationV1
    cleanup: PackageProductRebindCleanupObservationV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, PackageProductRebindSourceObservationV1)
            or not isinstance(self.lease, PackageProductRebindLeaseObservationV1)
            or not isinstance(self.cleanup, PackageProductRebindCleanupObservationV1)
        ):
            raise TypeError("Typed Package rebind owner observations are required")
        identities = {
            (
                item.operation_id,
                item.request_fingerprint,
                item.attempt_epoch,
                item.attempt_revision,
            )
            for item in (self.source, self.lease, self.cleanup)
        }
        if len(identities) != 1:
            raise PackageProductRebindPreflightError(
                "Package rebind owner observations changed attempt",
                code="package_rebind_preflight_attempt_changed",
            )
        if self.source.resolution_evidence_refs != (
            self.cleanup.resolution_evidence_refs
        ):
            raise PackageProductRebindPreflightError(
                "Package resolution changed during rebind preflight",
                code="package_rebind_preflight_resolution_changed",
            )


class PackageProductAcquiredRebindPreflightError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductAcquiredRebindPreflightV1:
    """Join one active acquired attempt's three read-only owner proofs."""

    source: PackageProductRebindSourceObservationV1
    lease: PackageProductRebindLeaseObservationV1
    cleanup: PackageProductAcquiredCleanupObservationV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, PackageProductRebindSourceObservationV1)
            or not isinstance(self.lease, PackageProductRebindLeaseObservationV1)
            or not isinstance(
                self.cleanup, PackageProductAcquiredCleanupObservationV1
            )
        ):
            raise TypeError("Typed acquired Package rebind observations are required")
        status = self.cleanup.status
        identities = {
            (
                item.operation_id,
                item.request_fingerprint,
                item.attempt_epoch,
                item.attempt_revision,
            )
            for item in (self.source, self.lease, status)
        }
        if len(identities) != 1:
            raise PackageProductAcquiredRebindPreflightError(
                "Acquired Package rebind owner observations changed attempt",
                code="package_rebind_preflight_attempt_changed",
            )
        if self.source.resolution_evidence_refs != (
            self.cleanup.resolution_evidence_refs
        ):
            raise PackageProductAcquiredRebindPreflightError(
                "Acquired Package resolution changed during rebind preflight",
                code="package_rebind_preflight_resolution_changed",
            )


@dataclass(frozen=True, slots=True)
class PackageProductResolvingRebindPreflightV1:
    """Join active closure-resolution Source, lease, and Store proofs."""

    source: PackageProductRebindSourceObservationV1
    lease: PackageProductRebindLeaseObservationV1
    cleanup: PackageProductResolvingCleanupObservationV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, PackageProductRebindSourceObservationV1)
            or not isinstance(self.lease, PackageProductRebindLeaseObservationV1)
            or not isinstance(
                self.cleanup, PackageProductResolvingCleanupObservationV1
            )
        ):
            raise TypeError("Typed resolving Package observations are required")
        status = self.cleanup.status
        identities = {
            (
                item.operation_id,
                item.request_fingerprint,
                item.attempt_epoch,
                item.attempt_revision,
            )
            for item in (self.source, self.lease, status)
        }
        if len(identities) != 1:
            raise PackageProductRebindPreflightError(
                "Resolving Package owner observations changed attempt",
                code="package_rebind_preflight_attempt_changed",
            )
        if self.source.resolution_evidence_refs != (
            self.cleanup.resolution_evidence_refs
        ):
            raise PackageProductRebindPreflightError(
                "Resolving Package resolution changed during preflight",
                code="package_rebind_preflight_resolution_changed",
            )


@dataclass(frozen=True, slots=True)
class PackageProductPinnedRebindPreflightV1:
    """Join an acquired retention pin to selected Source and lease proofs."""

    source: PackageProductRebindSourceObservationV1
    lease: PackageProductRebindLeaseObservationV1
    cleanup: PackageProductPinnedCleanupObservationV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, PackageProductRebindSourceObservationV1)
            or not isinstance(self.lease, PackageProductRebindLeaseObservationV1)
            or not isinstance(self.cleanup, PackageProductPinnedCleanupObservationV1)
        ):
            raise TypeError("Typed pinned Package observations are required")
        status = self.cleanup.closure.status
        identities = {
            (
                item.operation_id,
                item.request_fingerprint,
                item.attempt_epoch,
                item.attempt_revision,
            )
            for item in (self.source, self.lease, status)
        }
        if len(identities) != 1:
            raise PackageProductRebindPreflightError(
                "Pinned Package owner observations changed attempt",
                code="package_rebind_preflight_attempt_changed",
            )
        if self.source.resolution_evidence_refs != (
            self.cleanup.closure.resolution_evidence_refs
        ):
            raise PackageProductRebindPreflightError(
                "Pinned Package resolution changed during preflight",
                code="package_rebind_preflight_resolution_changed",
            )


@dataclass(frozen=True, slots=True)
class PackageProductStagingRebindPreflightV1:
    """Join current Source and lease proofs to one physical staging prefix."""

    source: PackageProductRebindSourceObservationV1
    lease: PackageProductRebindLeaseObservationV1
    checkpoint: PackageStagingCheckpointV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, PackageProductRebindSourceObservationV1)
            or not isinstance(self.lease, PackageProductRebindLeaseObservationV1)
            or not isinstance(self.checkpoint, PackageStagingCheckpointV1)
        ):
            raise TypeError("Typed staging Package observations are required")
        status = self.checkpoint.status
        identities = {
            (
                item.operation_id,
                item.request_fingerprint,
                item.attempt_epoch,
                item.attempt_revision,
            )
            for item in (self.source, self.lease, status)
        }
        if len(identities) != 1:
            raise PackageProductRebindPreflightError(
                "Staging Package owner observations changed attempt",
                code="package_rebind_preflight_attempt_changed",
            )
        if (
            self.checkpoint.plan_fingerprint
            not in self.source.resolution_evidence_refs
            or len(self.source.artifact_digests)
            != len(self.checkpoint.receipts) + len(self.checkpoint.missing_node_ids)
        ):
            raise PackageProductRebindPreflightError(
                "Staging Package closure changed Source evidence",
                code="package_rebind_preflight_resolution_changed",
            )


@dataclass(frozen=True, slots=True)
class PackageProductPublishedSetPreflightV1:
    """Join an exact published set to current Source and exited lease proofs."""

    source: PackageProductRebindSourceObservationV1
    lease: PackageProductRebindLeaseObservationV1
    checkpoint: PackagePublishedSetCheckpointV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, PackageProductRebindSourceObservationV1)
            or not isinstance(self.lease, PackageProductRebindLeaseObservationV1)
            or not isinstance(self.checkpoint, PackagePublishedSetCheckpointV1)
        ):
            raise TypeError("Typed published Package observations are required")
        status = self.checkpoint.status
        identities = {
            (
                item.operation_id,
                item.request_fingerprint,
                item.attempt_epoch,
                item.attempt_revision,
            )
            for item in (self.source, self.lease, status)
        }
        if len(identities) != 1:
            raise PackageProductRebindPreflightError(
                "Published Package owner observations changed attempt",
                code="package_rebind_preflight_attempt_changed",
            )
        if (
            self.checkpoint.plan_fingerprint
            not in self.source.resolution_evidence_refs
            or len(self.source.artifact_digests) != len(self.checkpoint.receipts)
        ):
            raise PackageProductRebindPreflightError(
                "Published Package set changed Source evidence",
                code="package_rebind_preflight_resolution_changed",
            )
