"""Read-only Product proof for a retained Windows LPAC crash cleanup attempt.

This review never carries a native spec or grants a cleanup effect. A writer
must repeat every observation while holding its Package and Product locks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker._native_profile_bridge import (
    _rebuild_windows_lpac_cleanup_spec,
)
from loushang.hosting import observe_windows_worker_job_absent
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

from .package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
    _review_under_gc_guard,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_CRASH_PHASES = frozenset(
    {
        "profile_effect",
        "profile_created",
        "grant_effect",
        "grants_applied",
        "verified",
        "active",
        "debt",
        "cleaning",
        "revoke_effect",
        "grants_revoked",
        "delete_effect",
        "profile_deleted",
    }
)
_TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"profile_effect", "settled"}),
    "profile_effect": frozenset({"profile_created", "debt", "cleaning", "settled"}),
    "profile_created": frozenset({"grant_effect", "debt", "cleaning"}),
    "grant_effect": frozenset({"grants_applied", "debt", "cleaning"}),
    "grants_applied": frozenset({"verified", "debt", "cleaning"}),
    "verified": frozenset({"active", "debt", "cleaning"}),
    "active": frozenset({"debt", "cleaning"}),
    "debt": frozenset({"cleaning"}),
    "cleaning": frozenset({"revoke_effect", "debt"}),
    "revoke_effect": frozenset({"grants_revoked", "debt", "cleaning"}),
    "grants_revoked": frozenset({"delete_effect", "debt"}),
    "delete_effect": frozenset({"profile_deleted", "debt"}),
    "profile_deleted": frozenset({"settled", "debt"}),
    "settled": frozenset(),
}


class CodingWindowsWorkerCrashCleanupReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashCleanupReviewV1:
    """One time-bound observation; it grants no native cleanup authority."""

    orphan_review: CodingWindowsWorkerOrphanRuntimeReviewV1
    native_revision: int
    native_spec_fingerprint: str
    payload_directory_identity: tuple[int, int]


def _valid_crash_cleanup_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> bool:
    return _valid_crash_effect_history(attempt, settled=False)


def _valid_crash_native_settlement_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> bool:
    return _valid_crash_effect_history(attempt, settled=True)


def _valid_crash_effect_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1, *, settled: bool
) -> bool:
    phases = attempt.native_phase_history
    witnesses = attempt.native_witness_present_history
    ending = "settled" if settled else attempt.native_phase
    if (
        phases is None
        or witnesses is None
        or not phases
        or phases[0] != "reserved"
        or (phases[-1] != "settled" if settled else phases[-1] not in _CRASH_PHASES)
        or phases[-1] != ending
        or len(phases) != len(witnesses)
        or len(phases) != attempt.native_revision
    ):
        return False
    if settled and (
        attempt.native_witness_state != "SETTLED"
        or phases[-6:]
        != (
            "cleaning",
            "revoke_effect",
            "grants_revoked",
            "delete_effect",
            "profile_deleted",
            "settled",
        )
    ):
        return False
    for index, phase in enumerate(phases):
        if phase not in _TRANSITIONS:
            return False
        if index and phase not in _TRANSITIONS[phases[index - 1]]:
            return False
        if witnesses[index] != (phase not in {"reserved", "profile_effect"}):
            return False
    return True


def _crash_cleanup_history_matches(
    review: CodingWindowsWorkerOrphanRuntimeReviewV1,
) -> bool:
    attempt = review.attempt
    expected_debts = (
        ("payload_retained", "launch_intent_retained", "native_unsettled"),
        (
            "payload_retained",
            "launch_intent_retained",
            "native_unsettled",
            "supervisor_unsettled",
        ),
        (
            "payload_retained",
            "launch_intent_retained",
            "native_unsettled",
            "supervisor_history_missing",
        ),
    )
    return (
        not review.missing_proofs
        and attempt is not None
        and review.receipt_record is not None
        and attempt.observed_debts in expected_debts
        and _valid_crash_cleanup_history(attempt)
        and attempt.payload_directory_identity is not None
        and attempt.native_revision is not None
    )


def _crash_settled_history_matches(
    review: CodingWindowsWorkerOrphanRuntimeReviewV1,
    *,
    repaired_lease: bool = False,
) -> bool:
    attempt = review.attempt
    return (
        review.missing_proofs == (("orphan_lease_absent",) if repaired_lease else ())
        and attempt is not None
        and review.receipt_record is not None
        and attempt.observed_debts
        in (
            ("payload_retained", "launch_intent_retained"),
            (
                "payload_retained",
                "launch_intent_retained",
                "supervisor_history_missing",
            ),
        )
        and (
            (attempt.supervisor_phase is None)
            or (
                attempt.supervisor_phase == "process_settled"
                and attempt.supervisor_process_settled is True
            )
        )
        and _valid_crash_native_settlement_history(attempt)
        and attempt.payload_directory_identity is not None
        and attempt.native_revision is not None
    )


def review_coding_windows_product_worker_crash_cleanup(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashCleanupReviewV1:
    """Join an orphan, exact stage and current LPAC spec without an effect."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker crash cleanup review requires a Product")
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.read_guard():
        review = _review_under_gc_guard(product, attempt_id=attempt_id, orphans=orphans)
        attempt = review.attempt
        receipt = review.receipt_record
        if not _crash_cleanup_history_matches(review):
            raise CodingWindowsWorkerCrashCleanupReviewError(
                "coding_worker_crash_cleanup_history_unverified"
            )
        assert attempt is not None and receipt is not None
        assert attempt.native_revision is not None
        assert attempt.payload_directory_identity is not None
        native = tuple(
            item
            for item in inspect_coding_windows_product_worker_provisioning_attempts(
                product
            )
            if item.attempt_id == attempt_id
        )
        if len(native) != 1:
            raise CodingWindowsWorkerCrashCleanupReviewError(
                "coding_worker_crash_cleanup_native_identity_unverified"
            )
        [provisioned] = native
        identity = provisioned.identity
        if (
            provisioned.phase != attempt.native_phase
            or provisioned.state_revision != attempt.native_revision
            or provisioned.phase_history != attempt.native_phase_history
            or provisioned.witness_present_history
            != attempt.native_witness_present_history
            or identity["workerRequestFingerprint"]
            != attempt.launch_request_fingerprint
            or identity["receiptFingerprint"] != receipt.receipt.fingerprint
            or identity["jobObjectName"] != attempt.native_job_name
            or identity["nativeProfileId"] != receipt.receipt.policy.native_profile_id
            or identity["nativeProfileCatalogRevision"]
            != receipt.receipt.policy.native_profile_catalog_revision
        ):
            raise CodingWindowsWorkerCrashCleanupReviewError(
                "coding_worker_crash_cleanup_native_identity_unverified"
            )
        stage = product.state_root / f"worker-payload-{attempt_id}"
        _rebuild_windows_lpac_cleanup_spec(
            identity=identity,
            runtime_root=stage,
            platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
            owner_private_ancestors=True,
        )
        product.assert_root_gc_authority_current()
        if (
            observe_windows_worker_job_absent(cast(str, identity["jobObjectName"]))
            is not True
        ):
            raise CodingWindowsWorkerCrashCleanupReviewError(
                "coding_worker_crash_cleanup_job_unverified"
            )
        current = next(
            (
                item
                for item in _inspect_windows_worker_recovery_inventory_under_gc_guard(
                    product
                )
                if item.attempt_id == attempt_id
            ),
            None,
        )
        if current != attempt:
            raise CodingWindowsWorkerCrashCleanupReviewError(
                "coding_worker_crash_cleanup_history_changed"
            )
        current_native = tuple(
            item
            for item in inspect_coding_windows_product_worker_provisioning_attempts(
                product
            )
            if item.attempt_id == attempt_id
        )
        if current_native != native:
            raise CodingWindowsWorkerCrashCleanupReviewError(
                "coding_worker_crash_cleanup_history_changed"
            )
        product.assert_root_gc_authority_current()
        return CodingWindowsWorkerCrashCleanupReviewV1(
            orphan_review=review,
            native_revision=attempt.native_revision,
            native_spec_fingerprint=cast(str, identity["specFingerprint"]),
            payload_directory_identity=attempt.payload_directory_identity,
        )


__all__ = [
    "CodingWindowsWorkerCrashCleanupReviewError",
    "CodingWindowsWorkerCrashCleanupReviewV1",
    "review_coding_windows_product_worker_crash_cleanup",
]
