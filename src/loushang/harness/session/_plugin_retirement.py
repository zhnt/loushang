"""Report exact Session owner retirement through the existing ledger ports."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from loushang.harness.plugin_management.retirement_sets import (
    PluginOwnerRetirementOutcomeV1,
    PluginOwnerRetirementPlanV1,
    PluginOwnerRetirementTargetV1,
)

if TYPE_CHECKING:
    from loushang.harness.plugin_management.instance_runtime import (
        PluginInstanceRuntimeInventorySnapshotV1,
    )
    from loushang.harness.plugin_management.retirement import PluginRetirementIntentV1
    from loushang.harness.plugin_management.retirement_sets import (
        PluginRetirementSetLedger,
    )
    from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
    from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt


OwnerRetirementUnavailableReason = Literal[
    "set_unavailable", "plan_unavailable", "outcome_unavailable",
]


class RetiredOwnerFamilyView(Protocol):
    @property
    def receipts(self) -> tuple[OwnerGenerationRetirementReceipt, ...]: ...

    @property
    def retirement_outcome_reference(self) -> str | None: ...


class OwnerRetirementEvidenceSource(Protocol):
    def retired_families_for_instance(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
    ) -> tuple[RetiredOwnerFamilyView, ...]: ...


@dataclass(frozen=True, slots=True)
class OwnerRetirementReportPolicy:
    closure_namespace: str
    outcome_namespace: str
    success_result_code: str
    unavailable_error: Callable[[OwnerRetirementUnavailableReason], Exception]


def report_exact_owner_retirement(
    intent: PluginRetirementIntentV1,
    runtime_snapshot: PluginInstanceRuntimeInventorySnapshotV1,
    *,
    retirement_sets: PluginRetirementSetLedger,
    owner_evidence: OwnerRetirementEvidenceSource,
    policy: OwnerRetirementReportPolicy,
) -> None:
    """Report or wait; callers retain locking, cleanup and family release.

    The evidence source retains its original loading and repair behavior.
    Returning None does not certify that any runtime or lease has retired.
    """

    retirement_set = retirement_sets.snapshot().retirement_set(intent.retirement_id)
    if retirement_set is None:
        raise policy.unavailable_error("set_unavailable")
    if retirement_set.plan is None and any(
        family.lease_kind == "session_membership"
        and any(
            member.instance_revision_ref == intent.instance_revision_ref
            for member in family.members
        )
        for family in runtime_snapshot.open_families
    ):
        # A family that acquired before cutover may still publish its exact
        # owner generations. Seal only after all Session families retire their
        # receipts or close without publishing.
        return
    families = owner_evidence.retired_families_for_instance(
        intent.instance_revision_ref
    )
    receipts = tuple(receipt for family in families for receipt in family.receipts)
    targets = tuple(
        PluginOwnerRetirementTargetV1.create(
            owner_reference=receipt.owner_reference,
            owner_generation_reference=receipt.owner_generation_reference,
            retirement_handle=receipt.retirement_handle,
            contribution_ids=receipt.contribution_ids,
        )
        for receipt in receipts
    )
    canonical_targets = tuple(sorted(targets, key=lambda item: item.target_id))
    closure_digest = hashlib.sha256(
        repr(tuple(item.target_id for item in canonical_targets)).encode("utf-8")
    ).hexdigest()
    # Repeat the exact plan and outcomes after a partially reported handoff.
    committed = retirement_sets.commit_plan(
        PluginOwnerRetirementPlanV1.create(
            retirement_id=intent.retirement_id,
            owner_closure_reference=f"{policy.closure_namespace}:{closure_digest}",
            targets=canonical_targets,
        )
    )
    if committed.plan is None:
        raise policy.unavailable_error("plan_unavailable")
    outcome_references = {
        (
            receipt.owner_reference,
            receipt.owner_generation_reference,
            receipt.retirement_handle,
        ): family.retirement_outcome_reference
        for family in families
        for receipt in family.receipts
    }
    for target in committed.plan.targets:
        outcome_reference = outcome_references[
            (
                target.owner_reference,
                target.owner_generation_reference,
                target.retirement_handle,
            )
        ]
        if outcome_reference is None:
            raise policy.unavailable_error("outcome_unavailable")
        identity = hashlib.sha256(
            repr((intent.retirement_id, target.target_id)).encode("utf-8")
        ).hexdigest()
        retirement_sets.record_outcome(
            PluginOwnerRetirementOutcomeV1(
                retirement_id=intent.retirement_id,
                target_id=target.target_id,
                operation_id=f"{policy.outcome_namespace}:{identity}",
                idempotency_key=f"{policy.outcome_namespace}:{identity}",
                attempt=1,
                disposition="succeeded",
                result_code=policy.success_result_code,
                owner_outcome_reference=outcome_reference,
            )
        )
