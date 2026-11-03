"""Read-only, fail-closed PLC9D resolution of one exact Store root target.

This function consumes caller-held owner snapshots. It neither reserves a
revision nor authorizes physical deletion.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingV1,
    PluginPackageGcClaimV1,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementRecordV1,
)


class PluginPackageGcTargetError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PluginPackageGcRootTargetV1:
    claim: PluginPackageGcClaimV1
    binding: PluginPackageGcBindingV1
    committed_set: PackageCommittedSetRecordV1
    settlement: PackageStoreSettlementRecordV1

    @property
    def settlement_id(self) -> str:
        return self.settlement.settlement_id


def resolve_plugin_package_gc_root_target(
    package_revision: PluginPackageRevisionRefV1,
    *,
    bindings: tuple[PluginPackageGcBindingV1, ...],
    claims: tuple[PluginPackageGcClaimV1, ...],
    committed_sets: tuple[PackageCommittedSetRecordV1, ...],
    settlements: tuple[PackageStoreSettlementRecordV1, ...],
) -> PluginPackageGcRootTargetV1:
    """Resolve one root; missing evidence or an alias blocks GC."""

    if not isinstance(package_revision, PluginPackageRevisionRefV1):
        raise TypeError("Exact Package revision is required")
    if not all(isinstance(item, PluginPackageGcBindingV1) for item in bindings):
        raise TypeError("Durable Package GC bindings are required")
    if not all(isinstance(item, PluginPackageGcClaimV1) for item in claims):
        raise TypeError("Durable Package GC precommit claims are required")
    if not all(isinstance(item, PackageCommittedSetRecordV1) for item in committed_sets):
        raise TypeError("Durable committed Package sets are required")
    if not all(isinstance(item, PackageStoreSettlementRecordV1) for item in settlements):
        raise TypeError("Durable Store settlements are required")

    matching_bindings = tuple(
        item for item in bindings if item.package_revision == package_revision
    )
    if len(matching_bindings) != 1:
        raise PluginPackageGcTargetError(
            "Package revision has no unique B handoff",
            code="plugin_package_gc_binding_unavailable",
        )
    binding = matching_bindings[0]
    request = binding.request
    ref = request.root_ref
    matching_claims = tuple(
        item
        for item in claims
        if item.request == request and item.package_revision == package_revision
    )
    if len(matching_claims) != 1:
        raise PluginPackageGcTargetError(
            "Package root lacks a unique precommit claim",
            code="plugin_package_gc_claim_unavailable",
        )
    if any(
        item != matching_claims[0]
        and item.request.root_ref.ref_id == ref.ref_id
        for item in claims
    ):
        raise PluginPackageGcTargetError(
            "Store root ref has another pending or committed claim",
            code="plugin_package_gc_root_aliased",
        )
    if any(
        item != binding and item.request.root_ref.ref_id == ref.ref_id
        for item in bindings
    ):
        raise PluginPackageGcTargetError(
            "Store root ref has another desired handoff",
            code="plugin_package_gc_root_aliased",
        )

    matching_sets = tuple(
        item for item in committed_sets if item.committed_set.set_id == request.committed_set_id
    )
    if len(matching_sets) != 1:
        raise PluginPackageGcTargetError(
            "Committed Package set is missing or ambiguous",
            code="plugin_package_gc_set_unavailable",
        )
    committed_record = matching_sets[0]
    committed = committed_record.committed_set
    root_node = next(
        item
        for item in committed_record.closure_lock.nodes
        if item.node_id == committed_record.closure_lock.root_node_id
    )
    if (
        committed.root_ref != ref
        or committed.operation_id != request.operation_id
        or committed.attempt_epoch != request.attempt_epoch
        or committed.request_fingerprint != request.request_fingerprint
        or committed.product_id != request.product_id
        or committed.scope_id != request.scope_id
        or committed.installation_id != request.installation_id
        or committed.plugin_id != request.plugin_id
        or root_node.stable_ref != ref
        or package_revision.dependency_lock_digest != committed.closure_lock_digest
        or package_revision.package_source_identity
        != root_node.plan_node.canonical_source_identity
    ):
        raise PluginPackageGcTargetError(
            "Product handoff does not match the committed Package set",
            code="plugin_package_gc_set_mismatch",
        )
    if any(
        item != committed_record and item.committed_set.root_ref.ref_id == ref.ref_id
        for item in committed_sets
    ):
        raise PluginPackageGcTargetError(
            "Store root ref is shared by another committed set",
            code="plugin_package_gc_root_aliased",
        )

    matching_settlements = tuple(
        item
        for item in settlements
        if item.store_role == "root"
        and item.store_identity == ref.store_identity
        and item.receipt.stable_ref == ref
    )
    if len(matching_settlements) != 1:
        raise PluginPackageGcTargetError(
            "Store root has no unique physical settlement",
            code="plugin_package_gc_settlement_unavailable",
        )
    settlement = matching_settlements[0]
    staging = settlement.receipt.staging_request
    if (
        staging.operation_id != committed.operation_id
        or staging.attempt_epoch != committed.attempt_epoch
        or staging.request_fingerprint != committed.request_fingerprint
        or staging.classification_fingerprint != committed.classification_fingerprint
        or staging.node_id != root_node.node_id
        or staging.plan_node != root_node.plan_node
        or staging.prepublication_graph_digest != committed.prepublication_graph_digest
        or settlement.manifest.node_id != root_node.node_id
    ):
        raise PluginPackageGcTargetError(
            "Store settlement does not match the committed root node",
            code="plugin_package_gc_settlement_mismatch",
        )
    if any(
        item != settlement
        and item.store_identity == settlement.store_identity
        and (
            item.final_name == settlement.final_name
            or item.tree_identity == settlement.tree_identity
        )
        for item in settlements
    ):
        raise PluginPackageGcTargetError(
            "Store physical root is aliased",
            code="plugin_package_gc_root_aliased",
        )
    return PluginPackageGcRootTargetV1(
        claim=matching_claims[0],
        binding=binding,
        committed_set=committed_record,
        settlement=settlement,
    )


__all__ = [
    "PluginPackageGcRootTargetV1",
    "PluginPackageGcTargetError",
    "resolve_plugin_package_gc_root_target",
]
