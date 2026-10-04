"""Read-only Product proof that a new runtime replaced the original lease.

The caller must hold the Product's admitted epoch guard. This observation does
not claim cleanup, Source, or executable rebind authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeAdmissionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.product_admission_binding import (
    PackageProductAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingJournal,
)


class PackageProductLeaseSnapshotPort(Protocol):
    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1: ...


class PackageProductRebindLeaseReadError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductRebindLeaseObservationV1:
    operation_id: str
    request_fingerprint: str
    attempt_epoch: int
    attempt_revision: int
    original_binding_id: str
    original_admission_request_id: str
    new_admission_request_id: str
    store_id: str
    old_lease_id: str
    new_lease_id: str
    lease_snapshot_id: str
    lease_owner_revision: int
    prior_proposed_binding_id: str | None = None
    prior_proposed_lease_id: str | None = None
    pending_decision_id: str | None = None
    prior_pinned_binding_id: str | None = None
    prior_pinned_lease_id: str | None = None
    pending_pinned_decision_id: str | None = None
    prior_staging_binding_id: str | None = None
    prior_staging_lease_id: str | None = None
    pending_staging_decision_id: str | None = None


class PackageProductRebindLeaseReader:
    """Join lifecycle, original admission, and current lease owner facts."""

    def __init__(
        self,
        *,
        lifecycle: PackageLifecycleJournal,
        original_bindings: PackageProductAdmissionBindingJournal,
        proposed_bindings: PackageProductRebindAdmissionBindingJournal | None = None,
        pinned_bindings: PackageProductPinnedAdoptionBindingJournal | None = None,
        staging_bindings: PackageProductStagingAdoptionBindingJournal | None = None,
        snapshots: PackageProductLeaseSnapshotPort,
        current_admission_request: PackageEpochRuntimeAdmissionRequestV1,
    ) -> None:
        if not isinstance(lifecycle, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(original_bindings, PackageProductAdmissionBindingJournal):
            raise TypeError("Product original admission binding is required")
        if proposed_bindings is not None and not isinstance(
            proposed_bindings, PackageProductRebindAdmissionBindingJournal
        ):
            raise TypeError("Product proposed rebind bindings are invalid")
        if pinned_bindings is not None and not isinstance(
            pinned_bindings, PackageProductPinnedAdoptionBindingJournal
        ):
            raise TypeError("Product pinned adoption bindings are invalid")
        if staging_bindings is not None and not isinstance(
            staging_bindings, PackageProductStagingAdoptionBindingJournal
        ):
            raise TypeError("Product staging adoption bindings are invalid")
        if not callable(getattr(snapshots, "snapshot", None)):
            raise TypeError("Product lease snapshot owner is required")
        if not isinstance(
            current_admission_request, PackageEpochRuntimeAdmissionRequestV1
        ):
            raise TypeError("Current Product admission request is required")
        self._lifecycle = lifecycle
        self._bindings = original_bindings
        self._proposed_bindings = proposed_bindings
        self._pinned_bindings = pinned_bindings
        self._staging_bindings = staging_bindings
        self._snapshots = snapshots
        self._current_request = current_admission_request

    def observe_abandoned_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Prove a later admission replaced a claim before acquisition effects."""

        return self.observe(operation_id, _claim_phases=("classified", "acquiring"))

    def observe_acquired_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Prove the selected root-stage admission has exited."""

        return self.observe(
            operation_id, _claim_phases=("acquired", "inspecting", "extracted")
        )

    def observe_resolving_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Prove the selected closure-resolution admission has exited."""

        return self.observe(operation_id, _claim_phases=("resolving_closure",))

    def observe_verified_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Prove the selected verified-closure admission has exited."""

        return self.observe(operation_id, _claim_phases=("closure_verified",))

    def observe_pinned_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Prove the selected pinning admission has exited."""

        return self.observe(operation_id, _claim_phases=("transaction_pinned",))

    def observe_published_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Prove the set publisher exited before a new Product admission."""

        return self.observe(operation_id, _claim_phases=("set_published",))

    def observe(
        self, operation_id: str, *, _claim_phases: tuple[str, ...] = ()
    ) -> PackageProductRebindLeaseObservationV1:
        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindLeaseReadError(
                "Package operation is absent",
                code="package_rebind_operation_missing",
            )
        request, status = original
        selected = self._lifecycle.latest_rebind(operation_id)
        abandoned = (
            selected is not None
            and selected.request == request
            and status.disposition == "active"
            and status.phase in _claim_phases
            and status.attempt_epoch == selected.decision.expected_attempt_epoch + 1
            and status.attempt_revision > selected.record_revision
            and status.request_fingerprint == selected.decision.request_fingerprint
        )
        original_retained = (
            selected is None
            and _claim_phases in (("transaction_pinned",), ("set_published",))
            and isinstance(request, PackageLifecycleRequestV2)
            and status.disposition == "active"
            and status.phase in _claim_phases
            and status.attempt_epoch == 1
            and status.request_fingerprint == request.request_fingerprint
        )
        eligible = (
            abandoned or original_retained
            if _claim_phases
            else status.disposition == "retryable_failure"
            and status.failure is not None
            and status.failure.operator_action == "retry"
        )
        if (
            not isinstance(request, PackageLifecycleRequestV2)
            or not eligible
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            raise PackageProductRebindLeaseReadError(
                (
                    "Claimed Package attempt has advanced beyond safe interruption"
                    if _claim_phases == ("classified", "acquiring")
                    else "Claimed Package attempt is not an eligible closure claim"
                    if _claim_phases == ("resolving_closure",)
                    else "Claimed Package attempt is not an eligible root claim"
                    if _claim_phases
                    else "Package operation has no failed Plugin attempt"
                ),
                code=(
                    (
                        "package_rebind_claim_not_unstarted"
                        if _claim_phases == ("classified", "acquiring")
                        else "package_rebind_claim_not_resolving"
                        if _claim_phases == ("resolving_closure",)
                        else "package_rebind_claim_not_acquired"
                    )
                    if _claim_phases
                    else "package_rebind_attempt_not_retryable"
                ),
            )
        binding = self._bindings.read_binding(operation_id)
        if binding is None:
            raise PackageProductRebindLeaseReadError(
                "Original Product admission binding is absent",
                code="package_rebind_original_admission_missing",
            )
        old_request = binding.admission.request
        current = self._current_request
        if (
            binding.request_fingerprint != request.request_fingerprint
            or old_request.admission_request_id != request.runtime_admission_request_id
        ):
            raise PackageProductRebindLeaseReadError(
                "Original Product admission changed",
                code="package_rebind_original_admission_changed",
            )
        if old_request.admission_request_id == current.admission_request_id:
            raise PackageProductRebindLeaseReadError(
                "Package attempt still uses its original runtime admission",
                code="package_rebind_same_admission",
            )
        if (
            old_request.store_id != current.store_id
            or old_request.fence_id != current.fence_id
            or old_request.runtime_epoch != current.runtime_epoch
            or old_request.store_root_identity != current.store_root_identity
        ):
            raise PackageProductRebindLeaseReadError(
                "Package Store epoch changed across runtime admissions",
                code="package_rebind_store_epoch_changed",
            )
        snapshot = self._snapshots.snapshot(store_id=current.store_id)
        if (
            not isinstance(snapshot, PackageEpochLeaseSnapshotV1)
            or snapshot.store_id != current.store_id
        ):
            raise PackageProductRebindLeaseReadError(
                "Current Product lease snapshot changed Store",
                code="package_rebind_lease_snapshot_invalid",
            )
        active = {lease.lease_id: lease for lease in snapshot.active_leases}
        current_lease = active.get(current.lease_id)
        if (
            current_lease is None
            or current_lease.runtime_id != current.runtime_id
            or current_lease.runtime_epoch != current.runtime_epoch
            or current_lease.store_root_identity != current.store_root_identity
        ):
            raise PackageProductRebindLeaseReadError(
                "New Product runtime lease is not live",
                code="package_rebind_new_lease_absent",
            )
        if old_request.lease_id in active:
            raise PackageProductRebindLeaseReadError(
                "Original Product runtime lease is still active",
                code="package_rebind_old_lease_active",
            )
        prior_binding_id = None
        prior_lease_id = None
        pending_decision_id = None
        history = self._lifecycle.read_rebind_history(operation_id)
        for index, prior_decision in enumerate(history):
            proposed = (
                None
                if self._proposed_bindings is None
                else self._proposed_bindings.read_decision(
                    prior_decision.decision.decision_id
                )
            )
            if proposed is None or proposed.decision != prior_decision.decision:
                raise PackageProductRebindLeaseReadError(
                    "Prior Product rebind admission binding is absent",
                    code="package_rebind_proposed_admission_missing",
                )
            prior = proposed.admission.request
            if (
                prior.store_id != current.store_id
                or prior.fence_id != current.fence_id
                or prior.runtime_epoch != current.runtime_epoch
                or prior.store_root_identity != current.store_root_identity
            ):
                raise PackageProductRebindLeaseReadError(
                    "Prior Product rebind changed Store epoch",
                    code="package_rebind_store_epoch_changed",
                )
            latest = index == len(history) - 1
            if latest and prior_decision.status == status:
                pending_decision_id = prior_decision.decision.decision_id
            if prior.admission_request_id == current.admission_request_id:
                if not latest or pending_decision_id is None:
                    raise PackageProductRebindLeaseReadError(
                        "Package attempt still uses its prior runtime admission",
                        code="package_rebind_same_admission",
                    )
            elif prior.lease_id in active:
                raise PackageProductRebindLeaseReadError(
                    "Prior proposed Product runtime lease is still active",
                    code="package_rebind_prior_lease_active",
                )
            prior_binding_id = proposed.binding_id
            prior_lease_id = prior.lease_id
        prior_pinned_binding_id = None
        prior_pinned_lease_id = None
        pending_pinned_decision_id = None
        pinned_history = self._lifecycle.read_pinned_adoption_history(operation_id)
        for index, selected_pin in enumerate(pinned_history):
            proposed_pin = (
                None
                if self._pinned_bindings is None
                else self._pinned_bindings.read_decision(
                    selected_pin.decision.decision_id
                )
            )
            if proposed_pin is None or proposed_pin.decision != selected_pin.decision:
                raise PackageProductRebindLeaseReadError(
                    "Selected pinned admission has no Product binding",
                    code="package_pinned_adoption_binding_missing",
                )
            pin_admission = proposed_pin.admission.request
            if (
                pin_admission.store_id != current.store_id
                or pin_admission.fence_id != current.fence_id
                or pin_admission.runtime_epoch != current.runtime_epoch
                or pin_admission.store_root_identity != current.store_root_identity
            ):
                raise PackageProductRebindLeaseReadError(
                    "Pinned adoption changed Package Store epoch",
                    code="package_pinned_adoption_store_epoch_changed",
                )
            latest = index == len(pinned_history) - 1
            if latest and selected_pin.status == status:
                pending_pinned_decision_id = selected_pin.decision.decision_id
            if pin_admission.admission_request_id == current.admission_request_id:
                if not latest or pending_pinned_decision_id is None:
                    raise PackageProductRebindLeaseReadError(
                        "Package attempt uses a nonselected pinned admission",
                        code="package_pinned_adoption_admission_changed",
                    )
            elif pin_admission.lease_id in active:
                raise PackageProductRebindLeaseReadError(
                    "Prior pinned admission lease is still active",
                    code="package_pinned_adoption_prior_lease_active",
                )
            prior_pinned_binding_id = proposed_pin.binding_id
            prior_pinned_lease_id = pin_admission.lease_id
        prior_staging_binding_id = None
        prior_staging_lease_id = None
        pending_staging_decision_id = None
        staging_history = self._lifecycle.read_staging_adoption_history(operation_id)
        for index, selected_stage in enumerate(staging_history):
            proposed_stage = (
                None
                if self._staging_bindings is None
                else self._staging_bindings.read_decision(
                    selected_stage.decision.decision_id
                )
            )
            if (
                proposed_stage is None
                or proposed_stage.decision != selected_stage.decision
            ):
                raise PackageProductRebindLeaseReadError(
                    "Selected staging admission has no Product binding",
                    code="package_staging_adoption_binding_missing",
                )
            stage_admission = proposed_stage.admission.request
            if (
                stage_admission.store_id != current.store_id
                or stage_admission.fence_id != current.fence_id
                or stage_admission.runtime_epoch != current.runtime_epoch
                or stage_admission.store_root_identity != current.store_root_identity
            ):
                raise PackageProductRebindLeaseReadError(
                    "Staging adoption changed Package Store epoch",
                    code="package_staging_adoption_store_epoch_changed",
                )
            latest = index == len(staging_history) - 1
            if latest and selected_stage.status == status:
                pending_staging_decision_id = selected_stage.decision.decision_id
            if stage_admission.admission_request_id == current.admission_request_id:
                if not latest or pending_staging_decision_id is None:
                    raise PackageProductRebindLeaseReadError(
                        "Package attempt uses a nonselected staging admission",
                        code="package_staging_adoption_admission_changed",
                    )
            elif stage_admission.lease_id in active:
                raise PackageProductRebindLeaseReadError(
                    "Prior staging admission lease is still active",
                    code="package_staging_adoption_prior_lease_active",
                )
            prior_staging_binding_id = proposed_stage.binding_id
            prior_staging_lease_id = stage_admission.lease_id
        return PackageProductRebindLeaseObservationV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            attempt_epoch=status.attempt_epoch,
            attempt_revision=status.attempt_revision,
            original_binding_id=binding.binding_id,
            original_admission_request_id=old_request.admission_request_id,
            new_admission_request_id=current.admission_request_id,
            store_id=current.store_id,
            old_lease_id=old_request.lease_id,
            new_lease_id=current.lease_id,
            lease_snapshot_id=snapshot.snapshot_id,
            lease_owner_revision=snapshot.owner_revision,
            prior_proposed_binding_id=prior_binding_id,
            prior_proposed_lease_id=prior_lease_id,
            pending_decision_id=pending_decision_id,
            prior_pinned_binding_id=prior_pinned_binding_id,
            prior_pinned_lease_id=prior_pinned_lease_id,
            pending_pinned_decision_id=pending_pinned_decision_id,
            prior_staging_binding_id=prior_staging_binding_id,
            prior_staging_lease_id=prior_staging_lease_id,
            pending_staging_decision_id=pending_staging_decision_id,
        )
