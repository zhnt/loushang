"""Product-guarded native cleanup for one orphaned Windows Worker attempt.

This settles only LPAC profile and grant debt. Supervisor, Package lease and
payload retirement remain separate Product decisions and cannot be inferred
from this native settlement alone.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_stat_at,
)
from loushang.harness.worker._native_profile_bridge import (
    _rebuild_windows_lpac_cleanup_spec,
    _recover_windows_lpac_containment_cleanup,
)
from loushang.hosting import observe_windows_worker_job_absent
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_PLATFORM_IMPORTS,
    verify_windows_backend_material_expectation,
)

from .package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
    _crash_cleanup_history_matches,
)
from .package_product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningStateJournal,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashNativeSettlementV1:
    attempt_id: str
    native_revision: int
    spec_fingerprint: str


class _PinnedRecoveryStore:
    def __init__(self, journal: WindowsWorkerProvisioningStateJournal, root: int) -> None:
        self._journal = journal
        self._root = root

    def load(self) -> Mapping[str, object] | None:
        return self._journal.load(directory_fd=self._root)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        return self._journal.compare_and_swap(
            expected_revision=expected_revision,
            document=document,
            directory_fd=self._root,
        )


def settle_coding_windows_product_worker_crash_native(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashCleanupReviewV1,
) -> CodingWindowsWorkerCrashNativeSettlementV1:
    """Recheck exact Product evidence under Package→GC locks before effects."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerCrashCleanupReviewV1
        or len(expected_review.orphan_review.orphan_leases) != 1
    ):
        raise ValueError("Windows Worker crash settlement requires exact Product proof")
    expected_orphan = expected_review.orphan_review
    [expected_lease] = expected_orphan.orphan_leases
    attempt_id = expected_orphan.attempt_id
    registry = product.epoch_runtime.registry
    with registry.guard_orphan_recovery(
        store_id=registry.store_id, lease_id=expected_lease.lease_id
    ) as lease:
        if lease != expected_lease:
            raise ValueError("Windows Worker crash lease changed")
        with product.gc_gate.guard():
            current = _review_under_gc_guard(
                product, attempt_id=attempt_id, orphans=(lease,)
            )
            if current != expected_orphan or not _crash_cleanup_history_matches(current):
                raise ValueError("Windows Worker crash cleanup review is stale")
            attempt = current.attempt
            assert attempt is not None and current.receipt_record is not None
            if (
                attempt.supervisor_phase is not None
                and attempt.supervisor_process_settled is not True
            ):
                raise ValueError("Windows Worker crash Supervisor is unsettled")
            native = tuple(
                item
                for item in inspect_coding_windows_product_worker_provisioning_attempts(
                    product
                )
                if item.attempt_id == attempt_id
            )
            if len(native) != 1:
                raise ValueError("Windows Worker native cleanup history changed")
            [provisioned] = native
            identity = provisioned.identity
            if (
                provisioned.phase != attempt.native_phase
                or provisioned.phase_history != attempt.native_phase_history
                or provisioned.witness_present_history
                != attempt.native_witness_present_history
                or provisioned.state_revision != expected_review.native_revision
                or identity["specFingerprint"]
                != expected_review.native_spec_fingerprint
                or attempt.payload_directory_identity
                != expected_review.payload_directory_identity
                or identity["receiptFingerprint"]
                != current.receipt_record.receipt.fingerprint
                or identity["workerRequestFingerprint"]
                != attempt.launch_request_fingerprint
                or identity["jobObjectName"] != attempt.native_job_name
                or identity["nativeProfileId"]
                != current.receipt_record.receipt.policy.native_profile_id
                or identity["nativeProfileCatalogRevision"]
                != current.receipt_record.receipt.policy.native_profile_catalog_revision
            ):
                raise ValueError("Windows Worker native cleanup identity changed")
            stage_name = f"worker-payload-{attempt_id}"
            material = read_coding_windows_worker_installed_backend_release(product)
            verify_windows_backend_material_expectation(material.expectation)
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                stage = open_windows_directory(
                    stage_name,
                    dir_fd=root,
                    share_delete=False,
                    writable=False,
                    read_control=True,
                )
                try:
                    observed = os.fstat(stage)
                    visible = windows_stat_at(root, stage_name)
                    if (
                        (observed.st_dev, observed.st_ino)
                        != expected_review.payload_directory_identity
                        or not os.path.samestat(observed, visible)
                    ):
                        raise ValueError("Windows Worker crash payload stage changed")
                    spec = _rebuild_windows_lpac_cleanup_spec(
                        identity=identity,
                        runtime_root=product.state_root / stage_name,
                        platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                        owner_private_ancestors=True,
                    )
                    if observe_windows_worker_job_absent(
                        cast(str, identity["jobObjectName"])
                    ) is not True:
                        raise ValueError("Windows Worker crash Job is still present")
                    journal = WindowsWorkerProvisioningStateJournal(
                        product.state_root
                        / f"worker-native-provisioning-{attempt_id}.jsonl",
                        identity=identity,
                    )
                    _recover_windows_lpac_containment_cleanup(
                        identity=identity,
                        provision_spec=spec,
                        provisioning_state_store=_PinnedRecoveryStore(journal, root),
                    )
                    latest = journal.load(directory_fd=root)
                    if (
                        latest is None
                        or latest["phase"] != "settled"
                        or not isinstance(latest["witness"], dict)
                        or latest["witness"]["state"] != "SETTLED"
                    ):
                        raise ValueError("Windows Worker native cleanup did not settle")
                    product.assert_root_gc_authority_current()
                    return CodingWindowsWorkerCrashNativeSettlementV1(
                        attempt_id=attempt_id,
                        native_revision=cast(int, latest["stateRevision"]),
                        spec_fingerprint=cast(str, identity["specFingerprint"]),
                    )
                finally:
                    os.close(stage)


__all__ = [
    "CodingWindowsWorkerCrashNativeSettlementV1",
    "settle_coding_windows_product_worker_crash_native",
]
