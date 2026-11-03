"""Read-only, exact stage review after a Windows Worker crash lease is repaired."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.worker._native_profile_bridge import (
    _rebuild_windows_lpac_cleanup_spec,
)
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

from .package_product_worker_windows_crash_cleanup_review import (
    _crash_settled_history_matches,
)
from .package_product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_stage_review import (
    FileIdentity,
    _capture_stage_bytes,
    _valid_identity,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REVIEW_BYTES = 32768


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashStageReviewV1:
    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    repaired_lease_id: str
    lease_repair_revision: int
    native_revision: int
    supervisor_revision: int | None
    native_spec_fingerprint: str
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Windows Worker crash stage entrypoint is invalid"
            ) from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.intent_fingerprint,
                    self.native_spec_fingerprint,
                    self.executable_digest,
                )
            )
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or type(self.repaired_lease_id) is not str
            or _DIGEST.fullmatch(self.repaired_lease_id) is None
            or type(self.lease_repair_revision) is not int
            or not 1 <= self.lease_repair_revision < self.lease_owner_revision
            or type(self.native_revision) is not int
            or self.native_revision < 1
            or (
                self.supervisor_revision is not None
                and (
                    type(self.supervisor_revision) is not int
                    or self.supervisor_revision < 1
                )
            )
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or not 0 < self.executable_identity[3] <= 16 * 1024 * 1024
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(item) is not tuple
                or len(item) != 2
                or item[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(item[1])
                for index, item in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker crash stage review is invalid")

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "attemptId": self.attempt_id,
                "directoryIdentities": [
                    [name, list(identity)]
                    for name, identity in self.directory_identities
                ],
                "entrypoint": self.entrypoint,
                "executableDigest": self.executable_digest,
                "executableIdentity": list(self.executable_identity),
                "intentFingerprint": self.intent_fingerprint,
                "leaseOwnerRevision": self.lease_owner_revision,
                "leaseRepairRevision": self.lease_repair_revision,
                "markerIdentity": list(self.marker_identity),
                "nativeRevision": self.native_revision,
                "nativeSpecFingerprint": self.native_spec_fingerprint,
                "repairedLeaseId": self.repaired_lease_id,
                "stageIdentity": list(self.stage_identity),
                "supervisorRevision": self.supervisor_revision,
                "version": 1,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerCrashStageReviewV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_REVIEW_BYTES:
            raise ValueError("Windows Worker crash stage review bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "attemptId",
                    "directoryIdentities",
                    "entrypoint",
                    "executableDigest",
                    "executableIdentity",
                    "intentFingerprint",
                    "leaseOwnerRevision",
                    "leaseRepairRevision",
                    "markerIdentity",
                    "nativeRevision",
                    "nativeSpecFingerprint",
                    "repairedLeaseId",
                    "stageIdentity",
                    "supervisorRevision",
                    "version",
                }
                or value["version"] != 1
            ):
                raise ValueError("Windows Worker crash stage review shape changed")
            directories = value["directoryIdentities"]
            if type(directories) is not list or any(
                type(item) is not list or len(item) != 2 or type(item[1]) is not list
                for item in directories
            ):
                raise ValueError("Windows Worker crash stage directories changed")
            for name in ("stageIdentity", "markerIdentity", "executableIdentity"):
                if type(value[name]) is not list:
                    raise ValueError("Windows Worker crash stage identity changed")
            review = cls(
                attempt_id=value["attemptId"],
                intent_fingerprint=value["intentFingerprint"],
                lease_owner_revision=value["leaseOwnerRevision"],
                repaired_lease_id=value["repairedLeaseId"],
                lease_repair_revision=value["leaseRepairRevision"],
                native_revision=value["nativeRevision"],
                supervisor_revision=value["supervisorRevision"],
                native_spec_fingerprint=value["nativeSpecFingerprint"],
                entrypoint=value["entrypoint"],
                stage_identity=tuple(value["stageIdentity"]),
                directory_identities=tuple(
                    (item[0], tuple(item[1])) for item in directories
                ),
                marker_identity=tuple(value["markerIdentity"]),
                executable_identity=tuple(value["executableIdentity"]),
                executable_digest=value["executableDigest"],
            )
            if review.to_bytes() != raw:
                raise ValueError("Windows Worker crash stage encoding changed")
            return review
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Windows Worker crash stage review bytes are invalid"
            ) from exc

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-windows-worker-crash-stage-review/v1\0" + self.to_bytes()
        ).hexdigest()


def review_coding_windows_product_worker_crash_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashStageReviewV1:
    """Capture a fully settled crash stage while Package leases are quiescent."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker crash stage requires exact Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker crash stage has active leases")
        with product.gc_gate.read_guard():
            return _review_crash_stage_under_gc_guard(
                product,
                attempt_id=attempt_id,
                quiescence=quiescence,
            )


def _review_crash_stage_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
) -> CodingWindowsWorkerCrashStageReviewV1:
    product.assert_root_gc_authority_current()
    joined = _review_under_gc_guard(product, attempt_id=attempt_id, orphans=())
    if not _crash_settled_history_matches(joined, repaired_lease=True):
        raise ValueError("Windows Worker crash stage history is unverified")
    attempt = joined.attempt
    receipt = joined.receipt_record
    assert attempt is not None and receipt is not None
    assert attempt.native_revision is not None
    assert attempt.payload_directory_identity is not None
    repair_record = _require_repair_record(
        quiescence, runtime_id=receipt.receipt.policy.product_runtime_id
    )
    intent = _read_intent_under_gc_guard(product, attempt_id)
    if (
        intent is None
        or attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
    ):
        raise ValueError("Windows Worker crash stage launch intent changed")
    native = tuple(
        item
        for item in inspect_coding_windows_product_worker_provisioning_attempts(product)
        if item.attempt_id == attempt_id
    )
    if len(native) != 1:
        raise ValueError("Windows Worker crash stage native history is unverified")
    [provisioned] = native
    identity = provisioned.identity
    if (
        provisioned.phase != "settled"
        or provisioned.state_revision != attempt.native_revision
        or provisioned.phase_history != attempt.native_phase_history
        or provisioned.witness_present_history != attempt.native_witness_present_history
        or identity["workerRequestFingerprint"] != intent.request_fingerprint
        or identity["receiptFingerprint"] != receipt.receipt.fingerprint
        or identity["jobObjectName"] != attempt.native_job_name
        or identity["nativeProfileId"] != receipt.receipt.policy.native_profile_id
        or identity["nativeProfileCatalogRevision"]
        != receipt.receipt.policy.native_profile_catalog_revision
    ):
        raise ValueError("Windows Worker crash stage native identity changed")
    _rebuild_windows_lpac_cleanup_spec(
        identity=identity,
        runtime_root=product.state_root / f"worker-payload-{attempt_id}",
        platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
        owner_private_ancestors=True,
    )
    captured = _capture_stage_bytes(
        product,
        attempt_id=attempt_id,
        expected_stage=attempt.payload_directory_identity,
        intent=intent,
    )
    product.assert_root_gc_authority_current()
    return CodingWindowsWorkerCrashStageReviewV1(
        attempt_id=attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=quiescence.owner_revision,
        repaired_lease_id=repair_record.lease.lease_id,
        lease_repair_revision=repair_record.record_revision,
        native_revision=attempt.native_revision,
        supervisor_revision=attempt.supervisor_revision,
        native_spec_fingerprint=cast(str, identity["specFingerprint"]),
        entrypoint=captured.entrypoint,
        stage_identity=captured.stage_identity,
        directory_identities=captured.directory_identities,
        marker_identity=captured.marker_identity,
        executable_identity=captured.executable_identity,
        executable_digest=captured.executable_digest,
    )


def _require_repair_record(
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    *,
    runtime_id: str,
    expected: tuple[str, int] | None = None,
) -> PackageEpochRuntimeLeaseRecordV1:
    repaired = tuple(
        record
        for record in quiescence.repaired_runtime_records
        if record.lease.runtime_id == runtime_id
    )
    if len(repaired) != 1:
        raise ValueError("Windows Worker crash lease repair is unverified")
    [record] = repaired
    if record.record_revision >= quiescence.owner_revision or (
        expected is not None
        and (record.lease.lease_id, record.record_revision) != expected
    ):
        raise ValueError("Windows Worker crash lease repair revision changed")
    return record


__all__ = [
    "CodingWindowsWorkerCrashStageReviewV1",
    "review_coding_windows_product_worker_crash_stage",
]
