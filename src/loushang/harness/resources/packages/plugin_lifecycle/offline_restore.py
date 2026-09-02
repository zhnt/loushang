"""Dark PLC9B4c3a protocol for isolated pre-B offline restoration.

The owner coordinates already-authenticated snapshot evidence, isolated native
materialization, and exclusive legacy-runtime activation.  It never writes the
Package epoch, lifecycle, handoff, cleanup, Desired, binding, or Instance
journals.  Native POSIX and Windows materializers remain later slices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverCoordinationPort,
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_OFFLINE_RESTORE_REQUEST_VERSION = 1
PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION = 1
PACKAGE_OFFLINE_RESTORE_MATERIALIZATION_RECEIPT_VERSION = 1
PACKAGE_LEGACY_RUNTIME_ACTIVATION_RECEIPT_VERSION = 1
PACKAGE_OFFLINE_RESTORE_FAILURE_VERSION = 1
PACKAGE_OFFLINE_RESTORE_RESULT_VERSION = 1

PackageOfflineRestoreDisposition = Literal["restored", "rejected"]
PackageOfflineRestoreCode = Literal[
    "ok",
    "package_runtime_epoch_unsupported",
    "package_offline_restore_stale",
    "package_offline_restore_snapshot_invalid",
    "package_offline_restore_materialization_invalid",
    "package_offline_restore_activation_invalid",
]
PackageOfflineRestoreFailureCode = Literal[
    "package_runtime_epoch_unsupported",
    "package_offline_restore_stale",
    "package_offline_restore_snapshot_invalid",
    "package_offline_restore_materialization_invalid",
    "package_offline_restore_activation_invalid",
]
PackageOfflineRestoreFailureStage = Literal[
    "pre_restore",
    "materializing",
    "activating",
]
PackageOfflineRestoreOperatorAction = Literal["retry", "repair"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,255}\Z")

PACKAGE_PRE_B_SNAPSHOT_DOMAINS = (
    "binding_history",
    "desired_state",
    "enablement_state",
    "fence_record",
    "instance_state",
    "legacy_root_pointer",
    "lock_history",
    "source_configuration",
    "store_bytes",
)


class PackageOfflineRestoreError(RuntimeError):
    """Fail-closed local cleanup or contract failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        evidence_ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evidence_ref = evidence_ref


@dataclass(frozen=True, slots=True)
class PackageOfflineRestoreSnapshotEvidenceV1:
    """Complete authenticated pre-B backup manifest around the cutover proof."""

    evidence_id: str
    snapshot: PackageEpochCutoverSnapshotReceiptV1
    snapshot_tree_digest: str
    state_manifest_digest: str
    covered_domains: tuple[str, ...] = PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    evidence_version: int = PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.evidence_id, name="offline snapshot evidence identity")
        if not isinstance(self.snapshot, PackageEpochCutoverSnapshotReceiptV1):
            raise TypeError("Package epoch snapshot receipt is required")
        _require_sha256(
            self.snapshot_tree_digest,
            name="Package snapshot tree digest",
        )
        _require_sha256(
            self.state_manifest_digest,
            name="Package pre-B state manifest digest",
        )
        if self.covered_domains != PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Package pre-B snapshot domains are incomplete")
        if self.evidence_version != PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION:
            raise ValueError("Unsupported Package offline snapshot evidence")
        if self.evidence_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package offline snapshot evidence does not match")

    @classmethod
    def create(
        cls,
        snapshot: PackageEpochCutoverSnapshotReceiptV1,
        *,
        snapshot_tree_digest: str,
        state_manifest_digest: str,
    ) -> PackageOfflineRestoreSnapshotEvidenceV1:
        if not isinstance(snapshot, PackageEpochCutoverSnapshotReceiptV1):
            raise TypeError("Package epoch snapshot receipt is required")
        values = _snapshot_evidence_identity(
            snapshot=snapshot,
            snapshot_tree_digest=snapshot_tree_digest,
            state_manifest_digest=state_manifest_digest,
            covered_domains=PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
            evidence_version=PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION,
        )
        return cls(
            evidence_id=_fingerprint(values),
            snapshot=snapshot,
            snapshot_tree_digest=snapshot_tree_digest,
            state_manifest_digest=state_manifest_digest,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _snapshot_evidence_identity(
            snapshot=self.snapshot,
            snapshot_tree_digest=self.snapshot_tree_digest,
            state_manifest_digest=self.state_manifest_digest,
            covered_domains=self.covered_domains,
            evidence_version=self.evidence_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"evidenceId": self.evidence_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageOfflineRestoreSnapshotEvidenceV1:
        document = _wire_object(
            value,
            expected={
                "evidenceId",
                "snapshot",
                "snapshotTreeDigest",
                "stateManifestDigest",
                "coveredDomains",
                "evidenceVersion",
            },
            name="Package offline snapshot evidence",
        )
        return cls(
            evidence_id=_wire_string(document["evidenceId"], name="evidence id"),
            snapshot=PackageEpochCutoverSnapshotReceiptV1.from_dict(
                document["snapshot"]
            ),
            snapshot_tree_digest=_wire_string(
                document["snapshotTreeDigest"], name="snapshot tree digest"
            ),
            state_manifest_digest=_wire_string(
                document["stateManifestDigest"], name="state manifest digest"
            ),
            covered_domains=_wire_string_tuple(
                document["coveredDomains"], name="covered domains"
            ),
            evidence_version=_wire_int(
                document["evidenceVersion"], name="evidence version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageOfflineRestoreRequestV1:
    """Pathless request binding one genesis backup and current B fence."""

    request_id: str
    store_id: str
    current_fence_id: str
    current_fence_revision: int
    current_epoch: int
    current_root_identity: str
    genesis_fence_id: str
    genesis_fence_revision: int
    legacy_root_identity: str
    snapshot_receipt_id: str
    snapshot_evidence_id: str
    snapshot_id: str
    snapshot_tree_digest: str
    state_manifest_digest: str
    snapshot_revision: int
    snapshot_entry_count: int
    snapshot_byte_count: int
    restore_namespace_id: str
    legacy_runtime_version: str
    request_version: int = PACKAGE_OFFLINE_RESTORE_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.request_id, "Package offline-restore request identity"),
            (self.current_fence_id, "current Package fence identity"),
            (self.current_root_identity, "current Package root identity"),
            (self.genesis_fence_id, "genesis Package fence identity"),
            (self.legacy_root_identity, "legacy Package root identity"),
            (self.snapshot_receipt_id, "Package snapshot receipt identity"),
            (self.snapshot_evidence_id, "Package snapshot evidence identity"),
            (self.snapshot_id, "Package snapshot identity"),
            (self.snapshot_tree_digest, "Package snapshot tree digest"),
            (self.state_manifest_digest, "Package state manifest digest"),
            (self.restore_namespace_id, "Package restore namespace identity"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.store_id, name="Package store identity")
        _require_positive(
            self.current_fence_revision,
            name="current Package fence revision",
        )
        _require_positive(self.current_epoch, name="current Package epoch")
        _require_positive(
            self.genesis_fence_revision,
            name="genesis Package fence revision",
        )
        _require_positive(self.snapshot_revision, name="Package snapshot revision")
        _require_non_negative(
            self.snapshot_entry_count,
            name="Package snapshot entry count",
        )
        _require_non_negative(
            self.snapshot_byte_count,
            name="Package snapshot byte count",
        )
        _require_safe_version(
            self.legacy_runtime_version,
            name="legacy Package runtime version",
        )
        if self.genesis_fence_revision != 1:
            raise ValueError("Offline restore requires the genesis Package fence")
        if self.current_fence_revision < self.genesis_fence_revision:
            raise ValueError("Current Package fence predates genesis")
        if self.request_version != PACKAGE_OFFLINE_RESTORE_REQUEST_VERSION:
            raise ValueError("Unsupported Package offline-restore request")
        if self.request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package offline-restore request identity does not match")

    @classmethod
    def create(
        cls,
        *,
        current_fence: PackageEpochFenceReceiptV1,
        genesis_fence: PackageEpochFenceReceiptV1,
        snapshot_evidence: PackageOfflineRestoreSnapshotEvidenceV1,
        restore_namespace_id: str,
        legacy_runtime_version: str,
    ) -> PackageOfflineRestoreRequestV1:
        for receipt, name in (
            (current_fence, "current Package epoch fence"),
            (genesis_fence, "genesis Package epoch fence"),
        ):
            if not isinstance(receipt, PackageEpochFenceReceiptV1):
                raise TypeError(f"{name} is required")
        if not isinstance(
            snapshot_evidence,
            PackageOfflineRestoreSnapshotEvidenceV1,
        ):
            raise TypeError("Package offline snapshot evidence is required")
        snapshot = snapshot_evidence.snapshot
        if (
            current_fence.store_id != genesis_fence.store_id
            or snapshot.store_id != genesis_fence.store_id
        ):
            raise ValueError("Package offline-restore store changed")
        if genesis_fence.epoch != 1 or genesis_fence.fence_revision != 1:
            raise ValueError("Offline restore requires the genesis Package fence")
        if (
            current_fence.epoch < genesis_fence.epoch
            or current_fence.fence_revision < genesis_fence.fence_revision
            or genesis_fence.request.snapshot_receipt_id != snapshot.receipt_id
            or genesis_fence.request.legacy_root_identity
            != snapshot.legacy_root_identity
        ):
            raise ValueError("Package genesis snapshot evidence changed")
        values = _restore_request_identity(
            store_id=current_fence.store_id,
            current_fence_id=current_fence.fence_id,
            current_fence_revision=current_fence.fence_revision,
            current_epoch=current_fence.epoch,
            current_root_identity=current_fence.fenced_root_identity,
            genesis_fence_id=genesis_fence.fence_id,
            genesis_fence_revision=genesis_fence.fence_revision,
            legacy_root_identity=snapshot.legacy_root_identity,
            snapshot_receipt_id=snapshot.receipt_id,
            snapshot_evidence_id=snapshot_evidence.evidence_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_tree_digest=snapshot_evidence.snapshot_tree_digest,
            state_manifest_digest=snapshot_evidence.state_manifest_digest,
            snapshot_revision=snapshot.snapshot_revision,
            snapshot_entry_count=snapshot.entry_count,
            snapshot_byte_count=snapshot.byte_count,
            restore_namespace_id=restore_namespace_id,
            legacy_runtime_version=legacy_runtime_version,
            request_version=PACKAGE_OFFLINE_RESTORE_REQUEST_VERSION,
        )
        return cls(
            request_id=_fingerprint(values),
            store_id=current_fence.store_id,
            current_fence_id=current_fence.fence_id,
            current_fence_revision=current_fence.fence_revision,
            current_epoch=current_fence.epoch,
            current_root_identity=current_fence.fenced_root_identity,
            genesis_fence_id=genesis_fence.fence_id,
            genesis_fence_revision=genesis_fence.fence_revision,
            legacy_root_identity=snapshot.legacy_root_identity,
            snapshot_receipt_id=snapshot.receipt_id,
            snapshot_evidence_id=snapshot_evidence.evidence_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_tree_digest=snapshot_evidence.snapshot_tree_digest,
            state_manifest_digest=snapshot_evidence.state_manifest_digest,
            snapshot_revision=snapshot.snapshot_revision,
            snapshot_entry_count=snapshot.entry_count,
            snapshot_byte_count=snapshot.byte_count,
            restore_namespace_id=restore_namespace_id,
            legacy_runtime_version=legacy_runtime_version,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _restore_request_identity(
            store_id=self.store_id,
            current_fence_id=self.current_fence_id,
            current_fence_revision=self.current_fence_revision,
            current_epoch=self.current_epoch,
            current_root_identity=self.current_root_identity,
            genesis_fence_id=self.genesis_fence_id,
            genesis_fence_revision=self.genesis_fence_revision,
            legacy_root_identity=self.legacy_root_identity,
            snapshot_receipt_id=self.snapshot_receipt_id,
            snapshot_evidence_id=self.snapshot_evidence_id,
            snapshot_id=self.snapshot_id,
            snapshot_tree_digest=self.snapshot_tree_digest,
            state_manifest_digest=self.state_manifest_digest,
            snapshot_revision=self.snapshot_revision,
            snapshot_entry_count=self.snapshot_entry_count,
            snapshot_byte_count=self.snapshot_byte_count,
            restore_namespace_id=self.restore_namespace_id,
            legacy_runtime_version=self.legacy_runtime_version,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"requestId": self.request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageOfflineRestoreRequestV1:
        document = _wire_object(
            value,
            expected={"requestId", *_RESTORE_REQUEST_WIRE_KEYS},
            name="Package offline-restore request",
        )
        return cls(
            request_id=_wire_string(document["requestId"], name="request id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            current_fence_id=_wire_string(
                document["currentFenceId"], name="current fence id"
            ),
            current_fence_revision=_wire_int(
                document["currentFenceRevision"], name="current fence revision"
            ),
            current_epoch=_wire_int(document["currentEpoch"], name="current epoch"),
            current_root_identity=_wire_string(
                document["currentRootIdentity"], name="current root identity"
            ),
            genesis_fence_id=_wire_string(
                document["genesisFenceId"], name="genesis fence id"
            ),
            genesis_fence_revision=_wire_int(
                document["genesisFenceRevision"], name="genesis fence revision"
            ),
            legacy_root_identity=_wire_string(
                document["legacyRootIdentity"], name="legacy root identity"
            ),
            snapshot_receipt_id=_wire_string(
                document["snapshotReceiptId"], name="snapshot receipt id"
            ),
            snapshot_evidence_id=_wire_string(
                document["snapshotEvidenceId"], name="snapshot evidence id"
            ),
            snapshot_id=_wire_string(document["snapshotId"], name="snapshot id"),
            snapshot_tree_digest=_wire_string(
                document["snapshotTreeDigest"], name="snapshot tree digest"
            ),
            state_manifest_digest=_wire_string(
                document["stateManifestDigest"], name="state manifest digest"
            ),
            snapshot_revision=_wire_int(
                document["snapshotRevision"], name="snapshot revision"
            ),
            snapshot_entry_count=_wire_int(
                document["snapshotEntryCount"], name="snapshot entry count"
            ),
            snapshot_byte_count=_wire_int(
                document["snapshotByteCount"], name="snapshot byte count"
            ),
            restore_namespace_id=_wire_string(
                document["restoreNamespaceId"], name="restore namespace id"
            ),
            legacy_runtime_version=_wire_string(
                document["legacyRuntimeVersion"], name="legacy runtime version"
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageOfflineRestoreMaterializationReceiptV1:
    """Pathless proof of an exact snapshot in an isolated legacy root."""

    materialization_receipt_id: str
    request_id: str
    store_id: str
    snapshot_receipt_id: str
    snapshot_evidence_id: str
    snapshot_id: str
    snapshot_revision: int
    restore_namespace_id: str
    legacy_root_identity: str
    restored_root_identity: str
    quiescence_receipt_id: str
    snapshot_tree_digest: str
    state_manifest_digest: str
    entry_count: int
    byte_count: int
    legacy_snapshot_exact: bool = True
    b_namespace_unreachable: bool = True
    receipt_version: int = PACKAGE_OFFLINE_RESTORE_MATERIALIZATION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.materialization_receipt_id, "restore materialization identity"),
            (self.request_id, "Package offline-restore request identity"),
            (self.snapshot_receipt_id, "Package snapshot receipt identity"),
            (self.snapshot_evidence_id, "Package snapshot evidence identity"),
            (self.snapshot_id, "Package snapshot identity"),
            (self.restore_namespace_id, "Package restore namespace identity"),
            (self.legacy_root_identity, "legacy Package root identity"),
            (self.restored_root_identity, "restored Package root identity"),
            (self.quiescence_receipt_id, "Package quiescence receipt identity"),
            (self.snapshot_tree_digest, "Package snapshot tree digest"),
            (self.state_manifest_digest, "Package state manifest digest"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.store_id, name="Package store identity")
        _require_positive(self.snapshot_revision, name="Package snapshot revision")
        _require_non_negative(self.entry_count, name="Package snapshot entry count")
        _require_non_negative(self.byte_count, name="Package snapshot byte count")
        if type(self.legacy_snapshot_exact) is not bool or not (
            self.legacy_snapshot_exact
        ):
            raise ValueError("Offline restore must prove the exact legacy snapshot")
        if type(self.b_namespace_unreachable) is not bool or not (
            self.b_namespace_unreachable
        ):
            raise ValueError("Offline restore must isolate the B namespace")
        if (
            self.receipt_version
            != PACKAGE_OFFLINE_RESTORE_MATERIALIZATION_RECEIPT_VERSION
        ):
            raise ValueError("Unsupported restore materialization receipt")
        if self.materialization_receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Restore materialization receipt does not match")

    @classmethod
    def create(
        cls,
        request: PackageOfflineRestoreRequestV1,
        *,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
        quiescence_receipt_id: str,
        restored_root_identity: str,
    ) -> PackageOfflineRestoreMaterializationReceiptV1:
        if not isinstance(request, PackageOfflineRestoreRequestV1):
            raise TypeError("Package offline-restore request is required")
        if not isinstance(snapshot, PackageOfflineRestoreSnapshotEvidenceV1):
            raise TypeError("Package offline snapshot evidence is required")
        receipt = snapshot.snapshot
        values = _materialization_identity(
            request_id=request.request_id,
            store_id=request.store_id,
            snapshot_receipt_id=receipt.receipt_id,
            snapshot_evidence_id=snapshot.evidence_id,
            snapshot_id=receipt.snapshot_id,
            snapshot_revision=receipt.snapshot_revision,
            restore_namespace_id=request.restore_namespace_id,
            legacy_root_identity=receipt.legacy_root_identity,
            restored_root_identity=restored_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_tree_digest=snapshot.snapshot_tree_digest,
            state_manifest_digest=snapshot.state_manifest_digest,
            entry_count=receipt.entry_count,
            byte_count=receipt.byte_count,
            legacy_snapshot_exact=True,
            b_namespace_unreachable=True,
            receipt_version=(
                PACKAGE_OFFLINE_RESTORE_MATERIALIZATION_RECEIPT_VERSION
            ),
        )
        return cls(
            materialization_receipt_id=_fingerprint(values),
            request_id=request.request_id,
            store_id=request.store_id,
            snapshot_receipt_id=receipt.receipt_id,
            snapshot_evidence_id=snapshot.evidence_id,
            snapshot_id=receipt.snapshot_id,
            snapshot_revision=receipt.snapshot_revision,
            restore_namespace_id=request.restore_namespace_id,
            legacy_root_identity=receipt.legacy_root_identity,
            restored_root_identity=restored_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_tree_digest=snapshot.snapshot_tree_digest,
            state_manifest_digest=snapshot.state_manifest_digest,
            entry_count=receipt.entry_count,
            byte_count=receipt.byte_count,
        )

    def matches(
        self,
        request: PackageOfflineRestoreRequestV1,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    ) -> bool:
        receipt = snapshot.snapshot
        return (
            self.request_id == request.request_id
            and self.store_id == request.store_id
            and self.snapshot_receipt_id == receipt.receipt_id
            and self.snapshot_evidence_id == snapshot.evidence_id
            and self.snapshot_id == receipt.snapshot_id
            and self.snapshot_revision == receipt.snapshot_revision
            and self.restore_namespace_id == request.restore_namespace_id
            and self.legacy_root_identity == receipt.legacy_root_identity
            and self.snapshot_tree_digest == snapshot.snapshot_tree_digest
            and self.state_manifest_digest == snapshot.state_manifest_digest
            and self.entry_count == receipt.entry_count
            and self.byte_count == receipt.byte_count
            and self.legacy_snapshot_exact
            and self.b_namespace_unreachable
        )

    def _identity_dict(self) -> dict[str, object]:
        return _materialization_identity(
            request_id=self.request_id,
            store_id=self.store_id,
            snapshot_receipt_id=self.snapshot_receipt_id,
            snapshot_evidence_id=self.snapshot_evidence_id,
            snapshot_id=self.snapshot_id,
            snapshot_revision=self.snapshot_revision,
            restore_namespace_id=self.restore_namespace_id,
            legacy_root_identity=self.legacy_root_identity,
            restored_root_identity=self.restored_root_identity,
            quiescence_receipt_id=self.quiescence_receipt_id,
            snapshot_tree_digest=self.snapshot_tree_digest,
            state_manifest_digest=self.state_manifest_digest,
            entry_count=self.entry_count,
            byte_count=self.byte_count,
            legacy_snapshot_exact=self.legacy_snapshot_exact,
            b_namespace_unreachable=self.b_namespace_unreachable,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "materializationReceiptId": self.materialization_receipt_id,
            **self._identity_dict(),
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> PackageOfflineRestoreMaterializationReceiptV1:
        document = _wire_object(
            value,
            expected={"materializationReceiptId", *_MATERIALIZATION_WIRE_KEYS},
            name="Package restore materialization receipt",
        )
        return cls(
            materialization_receipt_id=_wire_string(
                document["materializationReceiptId"],
                name="materialization receipt id",
            ),
            request_id=_wire_string(document["requestId"], name="request id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            snapshot_receipt_id=_wire_string(
                document["snapshotReceiptId"], name="snapshot receipt id"
            ),
            snapshot_evidence_id=_wire_string(
                document["snapshotEvidenceId"], name="snapshot evidence id"
            ),
            snapshot_id=_wire_string(document["snapshotId"], name="snapshot id"),
            snapshot_revision=_wire_int(
                document["snapshotRevision"], name="snapshot revision"
            ),
            restore_namespace_id=_wire_string(
                document["restoreNamespaceId"], name="restore namespace id"
            ),
            legacy_root_identity=_wire_string(
                document["legacyRootIdentity"], name="legacy root identity"
            ),
            restored_root_identity=_wire_string(
                document["restoredRootIdentity"], name="restored root identity"
            ),
            quiescence_receipt_id=_wire_string(
                document["quiescenceReceiptId"], name="quiescence receipt id"
            ),
            snapshot_tree_digest=_wire_string(
                document["snapshotTreeDigest"], name="snapshot tree digest"
            ),
            state_manifest_digest=_wire_string(
                document["stateManifestDigest"], name="state manifest digest"
            ),
            entry_count=_wire_int(document["entryCount"], name="entry count"),
            byte_count=_wire_int(document["byteCount"], name="byte count"),
            legacy_snapshot_exact=_wire_bool(
                document["legacySnapshotExact"], name="legacy snapshot exact"
            ),
            b_namespace_unreachable=_wire_bool(
                document["bNamespaceUnreachable"],
                name="B namespace unreachable",
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLegacyRuntimeActivationReceiptV1:
    """Exclusive old-runtime activation bound to one restored root."""

    activation_receipt_id: str
    request_id: str
    materialization_receipt_id: str
    store_id: str
    restored_root_identity: str
    runtime_instance_id: str
    runtime_lease_id: str
    legacy_runtime_version: str
    exclusive_old_runtime: bool = True
    receipt_version: int = PACKAGE_LEGACY_RUNTIME_ACTIVATION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.activation_receipt_id, "legacy runtime activation identity"),
            (self.request_id, "Package offline-restore request identity"),
            (self.materialization_receipt_id, "restore materialization identity"),
            (self.restored_root_identity, "restored Package root identity"),
            (self.runtime_instance_id, "legacy runtime instance identity"),
            (self.runtime_lease_id, "legacy runtime lease identity"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.store_id, name="Package store identity")
        _require_safe_version(
            self.legacy_runtime_version,
            name="legacy Package runtime version",
        )
        if type(self.exclusive_old_runtime) is not bool or not (
            self.exclusive_old_runtime
        ):
            raise ValueError("Offline restore requires exclusive old-runtime startup")
        if self.receipt_version != PACKAGE_LEGACY_RUNTIME_ACTIVATION_RECEIPT_VERSION:
            raise ValueError("Unsupported legacy runtime activation receipt")
        if self.activation_receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Legacy runtime activation receipt does not match")

    @classmethod
    def create(
        cls,
        request: PackageOfflineRestoreRequestV1,
        *,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
        runtime_instance_id: str,
        runtime_lease_id: str,
    ) -> PackageLegacyRuntimeActivationReceiptV1:
        if not isinstance(request, PackageOfflineRestoreRequestV1):
            raise TypeError("Package offline-restore request is required")
        if not isinstance(
            materialization,
            PackageOfflineRestoreMaterializationReceiptV1,
        ):
            raise TypeError("Package restore materialization receipt is required")
        values = _activation_identity(
            request_id=request.request_id,
            materialization_receipt_id=(
                materialization.materialization_receipt_id
            ),
            store_id=request.store_id,
            restored_root_identity=materialization.restored_root_identity,
            runtime_instance_id=runtime_instance_id,
            runtime_lease_id=runtime_lease_id,
            legacy_runtime_version=request.legacy_runtime_version,
            exclusive_old_runtime=True,
            receipt_version=PACKAGE_LEGACY_RUNTIME_ACTIVATION_RECEIPT_VERSION,
        )
        return cls(
            activation_receipt_id=_fingerprint(values),
            request_id=request.request_id,
            materialization_receipt_id=(
                materialization.materialization_receipt_id
            ),
            store_id=request.store_id,
            restored_root_identity=materialization.restored_root_identity,
            runtime_instance_id=runtime_instance_id,
            runtime_lease_id=runtime_lease_id,
            legacy_runtime_version=request.legacy_runtime_version,
        )

    def matches(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> bool:
        return (
            self.request_id == request.request_id
            and self.materialization_receipt_id
            == materialization.materialization_receipt_id
            and self.store_id == request.store_id
            and self.restored_root_identity
            == materialization.restored_root_identity
            and self.legacy_runtime_version == request.legacy_runtime_version
            and self.exclusive_old_runtime
        )

    def _identity_dict(self) -> dict[str, object]:
        return _activation_identity(
            request_id=self.request_id,
            materialization_receipt_id=self.materialization_receipt_id,
            store_id=self.store_id,
            restored_root_identity=self.restored_root_identity,
            runtime_instance_id=self.runtime_instance_id,
            runtime_lease_id=self.runtime_lease_id,
            legacy_runtime_version=self.legacy_runtime_version,
            exclusive_old_runtime=self.exclusive_old_runtime,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "activationReceiptId": self.activation_receipt_id,
            **self._identity_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyRuntimeActivationReceiptV1:
        document = _wire_object(
            value,
            expected={"activationReceiptId", *_ACTIVATION_WIRE_KEYS},
            name="legacy Package runtime activation receipt",
        )
        return cls(
            activation_receipt_id=_wire_string(
                document["activationReceiptId"], name="activation receipt id"
            ),
            request_id=_wire_string(document["requestId"], name="request id"),
            materialization_receipt_id=_wire_string(
                document["materializationReceiptId"],
                name="materialization receipt id",
            ),
            store_id=_wire_string(document["storeId"], name="store id"),
            restored_root_identity=_wire_string(
                document["restoredRootIdentity"], name="restored root identity"
            ),
            runtime_instance_id=_wire_string(
                document["runtimeInstanceId"], name="runtime instance id"
            ),
            runtime_lease_id=_wire_string(
                document["runtimeLeaseId"], name="runtime lease id"
            ),
            legacy_runtime_version=_wire_string(
                document["legacyRuntimeVersion"], name="legacy runtime version"
            ),
            exclusive_old_runtime=_wire_bool(
                document["exclusiveOldRuntime"], name="exclusive old runtime"
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


_FAILURE_POLICY: dict[
    PackageOfflineRestoreFailureCode,
    tuple[
        PackageOfflineRestoreFailureStage,
        bool,
        PackageOfflineRestoreOperatorAction,
    ],
] = {
    "package_runtime_epoch_unsupported": ("pre_restore", True, "retry"),
    "package_offline_restore_stale": ("pre_restore", True, "retry"),
    "package_offline_restore_snapshot_invalid": ("pre_restore", False, "repair"),
    "package_offline_restore_materialization_invalid": (
        "materializing",
        True,
        "repair",
    ),
    "package_offline_restore_activation_invalid": ("activating", True, "repair"),
}


@dataclass(frozen=True, slots=True)
class PackageOfflineRestoreFailureV1:
    failure_id: str
    request_id: str
    evidence_ref: str
    code: PackageOfflineRestoreFailureCode
    stage: PackageOfflineRestoreFailureStage
    retryable: bool
    operator_action: PackageOfflineRestoreOperatorAction
    failure_version: int = PACKAGE_OFFLINE_RESTORE_FAILURE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.failure_id, "Package offline-restore failure identity"),
            (self.request_id, "Package offline-restore request identity"),
            (self.evidence_ref, "Package offline-restore failure evidence"),
        ):
            _require_sha256(value, name=name)
        expected = _FAILURE_POLICY.get(self.code)
        if expected is None or expected != (
            self.stage,
            self.retryable,
            self.operator_action,
        ):
            raise ValueError("Package offline-restore failure policy changed")
        if self.failure_version != PACKAGE_OFFLINE_RESTORE_FAILURE_VERSION:
            raise ValueError("Unsupported Package offline-restore failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package offline-restore failure does not match")

    @classmethod
    def create(
        cls,
        request: PackageOfflineRestoreRequestV1,
        *,
        code: PackageOfflineRestoreFailureCode,
        evidence_ref: str,
    ) -> PackageOfflineRestoreFailureV1:
        stage, retryable, operator_action = _FAILURE_POLICY[code]
        values = _failure_identity(
            request_id=request.request_id,
            evidence_ref=evidence_ref,
            code=code,
            stage=stage,
            retryable=retryable,
            operator_action=operator_action,
            failure_version=PACKAGE_OFFLINE_RESTORE_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            request_id=request.request_id,
            evidence_ref=evidence_ref,
            code=code,
            stage=stage,
            retryable=retryable,
            operator_action=operator_action,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _failure_identity(
            request_id=self.request_id,
            evidence_ref=self.evidence_ref,
            code=self.code,
            stage=self.stage,
            retryable=self.retryable,
            operator_action=self.operator_action,
            failure_version=self.failure_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageOfflineRestoreFailureV1:
        document = _wire_object(
            value,
            expected={
                "failureId",
                "requestId",
                "evidenceRef",
                "code",
                "stage",
                "retryable",
                "operatorAction",
                "failureVersion",
            },
            name="Package offline-restore failure",
        )
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            request_id=_wire_string(document["requestId"], name="request id"),
            evidence_ref=_wire_string(document["evidenceRef"], name="evidence ref"),
            code=cast(
                PackageOfflineRestoreFailureCode,
                _wire_string(document["code"], name="code"),
            ),
            stage=cast(
                PackageOfflineRestoreFailureStage,
                _wire_string(document["stage"], name="stage"),
            ),
            retryable=_wire_bool(document["retryable"], name="retryable"),
            operator_action=cast(
                PackageOfflineRestoreOperatorAction,
                _wire_string(document["operatorAction"], name="operator action"),
            ),
            failure_version=_wire_int(
                document["failureVersion"], name="failure version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageOfflineRestoreResultV1:
    request_id: str
    disposition: PackageOfflineRestoreDisposition
    code: PackageOfflineRestoreCode
    materialization: PackageOfflineRestoreMaterializationReceiptV1 | None
    activation: PackageLegacyRuntimeActivationReceiptV1 | None
    failure: PackageOfflineRestoreFailureV1 | None
    result_version: int = PACKAGE_OFFLINE_RESTORE_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.request_id, name="Package offline-restore request identity")
        nested_request_ids = tuple(
            value.request_id
            for value in (self.materialization, self.activation, self.failure)
            if value is not None
        )
        if any(value != self.request_id for value in nested_request_ids):
            raise ValueError("Package offline-restore result request identity changed")
        if self.disposition == "restored":
            valid = (
                self.code == "ok"
                and self.materialization is not None
                and self.activation is not None
                and self.failure is None
                and self.activation.materialization_receipt_id
                == self.materialization.materialization_receipt_id
            )
        elif self.disposition == "rejected":
            valid = (
                self.code != "ok"
                and self.materialization is None
                and self.activation is None
                and self.failure is not None
                and self.failure.code == self.code
            )
        else:
            valid = False
        if not valid:
            raise ValueError("Package offline-restore result is inconsistent")
        if self.result_version != PACKAGE_OFFLINE_RESTORE_RESULT_VERSION:
            raise ValueError("Unsupported Package offline-restore result")

    @classmethod
    def restored(
        cls,
        request: PackageOfflineRestoreRequestV1,
        *,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
        activation: PackageLegacyRuntimeActivationReceiptV1,
    ) -> PackageOfflineRestoreResultV1:
        return cls(
            request_id=request.request_id,
            disposition="restored",
            code="ok",
            materialization=materialization,
            activation=activation,
            failure=None,
        )

    @classmethod
    def rejected(
        cls,
        request: PackageOfflineRestoreRequestV1,
        *,
        code: PackageOfflineRestoreFailureCode,
        evidence_ref: str,
    ) -> PackageOfflineRestoreResultV1:
        return cls(
            request_id=request.request_id,
            disposition="rejected",
            code=code,
            materialization=None,
            activation=None,
            failure=PackageOfflineRestoreFailureV1.create(
                request,
                code=code,
                evidence_ref=evidence_ref,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "requestId": self.request_id,
            "disposition": self.disposition,
            "code": self.code,
            "materialization": (
                None if self.materialization is None else self.materialization.to_dict()
            ),
            "activation": None if self.activation is None else self.activation.to_dict(),
            "failure": None if self.failure is None else self.failure.to_dict(),
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageOfflineRestoreResultV1:
        document = _wire_object(
            value,
            expected={
                "requestId",
                "disposition",
                "code",
                "materialization",
                "activation",
                "failure",
                "resultVersion",
            },
            name="Package offline-restore result",
        )
        materialization = document["materialization"]
        activation = document["activation"]
        failure = document["failure"]
        return cls(
            request_id=_wire_string(document["requestId"], name="request id"),
            disposition=cast(
                PackageOfflineRestoreDisposition,
                _wire_string(document["disposition"], name="disposition"),
            ),
            code=cast(
                PackageOfflineRestoreCode,
                _wire_string(document["code"], name="code"),
            ),
            materialization=(
                None
                if materialization is None
                else PackageOfflineRestoreMaterializationReceiptV1.from_dict(
                    materialization
                )
            ),
            activation=(
                None
                if activation is None
                else PackageLegacyRuntimeActivationReceiptV1.from_dict(activation)
            ),
            failure=(
                None
                if failure is None
                else PackageOfflineRestoreFailureV1.from_dict(failure)
            ),
            result_version=_wire_int(
                document["resultVersion"], name="result version"
            ),
        )


class PackageOfflineRestoreSnapshotEvidencePort(Protocol):
    def snapshot(
        self,
        snapshot_receipt_id: str,
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None: ...


class PackageOfflineRestoreMaterializationPort(Protocol):
    def restore(
        self,
        request: PackageOfflineRestoreRequestV1,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
        quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    ) -> PackageOfflineRestoreMaterializationReceiptV1: ...

    def discard(
        self,
        receipt: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> None: ...


class PackageLegacyRuntimeActivationPort(Protocol):
    def activate(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> PackageLegacyRuntimeActivationReceiptV1: ...

    def deactivate(self, receipt: PackageLegacyRuntimeActivationReceiptV1) -> None: ...


class PackageOfflineRestoreOwner:
    """Coordinate exact genesis restore without mutating any B authority."""

    def __init__(
        self,
        *,
        store_id: str,
        epoch_journal: PackageEpochFenceJournal,
        coordination: PackageEpochCutoverCoordinationPort,
        snapshots: PackageOfflineRestoreSnapshotEvidencePort,
        materialization: PackageOfflineRestoreMaterializationPort,
        activation: PackageLegacyRuntimeActivationPort,
    ) -> None:
        _require_safe_id(store_id, name="Package store identity")
        if not isinstance(epoch_journal, PackageEpochFenceJournal):
            raise TypeError("Package epoch fence journal is required")
        required = (
            (coordination, ("exclusive_quiescence",), "coordination owner"),
            (snapshots, ("snapshot",), "snapshot evidence owner"),
            (
                materialization,
                ("restore", "discard"),
                "restore materialization owner",
            ),
            (activation, ("activate", "deactivate"), "legacy runtime owner"),
        )
        for owner, methods, name in required:
            if any(not callable(getattr(owner, method, None)) for method in methods):
                raise TypeError(f"Package offline-restore {name} is required")
        self._store_id = store_id
        self._journal = epoch_journal
        self._coordination = coordination
        self._snapshots = snapshots
        self._materialization = materialization
        self._activation = activation

    def restore(
        self,
        request: PackageOfflineRestoreRequestV1,
    ) -> PackageOfflineRestoreResultV1:
        if not isinstance(request, PackageOfflineRestoreRequestV1):
            raise TypeError("Package offline-restore request is required")
        if request.store_id != self._store_id:
            return self._rejected(
                request,
                code="package_offline_restore_stale",
                evidence_ref=request.current_fence_id,
            )
        exclusive = self._coordination.exclusive_quiescence(store_id=self._store_id)
        with exclusive as quiescence:
            if (
                not isinstance(quiescence, PackageEpochCutoverQuiescenceReceiptV1)
                or quiescence.store_id != self._store_id
            ):
                return self._rejected(
                    request,
                    code="package_runtime_epoch_unsupported",
                    evidence_ref=request.current_fence_id,
                )
            if not quiescence.is_quiescent:
                return self._rejected(
                    request,
                    code="package_runtime_epoch_unsupported",
                    evidence_ref=quiescence.first_active_evidence,
                )
            if not self._fences_match(request):
                return self._rejected(
                    request,
                    code="package_offline_restore_stale",
                    evidence_ref=request.current_fence_id,
                )
            snapshot = self._snapshots.snapshot(request.snapshot_receipt_id)
            if not self._snapshot_matches(request, snapshot):
                return self._rejected(
                    request,
                    code="package_offline_restore_snapshot_invalid",
                    evidence_ref=request.snapshot_receipt_id,
                )
            assert isinstance(snapshot, PackageOfflineRestoreSnapshotEvidenceV1)
            materialization = self._materialization.restore(
                request,
                snapshot,
                quiescence,
            )
            if not isinstance(
                materialization,
                PackageOfflineRestoreMaterializationReceiptV1,
            ) or not materialization.matches(request, snapshot):
                if isinstance(
                    materialization,
                    PackageOfflineRestoreMaterializationReceiptV1,
                ):
                    self._discard(materialization)
                    evidence_ref = materialization.materialization_receipt_id
                else:
                    evidence_ref = request.request_id
                return self._rejected(
                    request,
                    code="package_offline_restore_materialization_invalid",
                    evidence_ref=evidence_ref,
                )
            if not self._fences_match(request):
                self._discard(materialization)
                return self._rejected(
                    request,
                    code="package_offline_restore_stale",
                    evidence_ref=request.current_fence_id,
                )
            activation = self._activation.activate(request, materialization)
            if not isinstance(
                activation,
                PackageLegacyRuntimeActivationReceiptV1,
            ) or not activation.matches(request, materialization):
                if isinstance(activation, PackageLegacyRuntimeActivationReceiptV1):
                    self._deactivate(activation)
                    evidence_ref = activation.activation_receipt_id
                else:
                    evidence_ref = request.request_id
                self._discard(materialization)
                return self._rejected(
                    request,
                    code="package_offline_restore_activation_invalid",
                    evidence_ref=evidence_ref,
                )
            if not self._fences_match(request):
                self._deactivate(activation)
                self._discard(materialization)
                return self._rejected(
                    request,
                    code="package_offline_restore_stale",
                    evidence_ref=request.current_fence_id,
                )
            return PackageOfflineRestoreResultV1.restored(
                request,
                materialization=materialization,
                activation=activation,
            )

    def _fences_match(self, request: PackageOfflineRestoreRequestV1) -> bool:
        records = self._journal.records()
        if not records:
            return False
        genesis = records[0].receipt
        current = records[-1].receipt
        if any(record.receipt.store_id != self._store_id for record in records):
            return False
        return (
            genesis.epoch == 1
            and genesis.fence_revision == 1
            and genesis.fence_id == request.genesis_fence_id
            and genesis.request.snapshot_receipt_id == request.snapshot_receipt_id
            and genesis.request.legacy_root_identity == request.legacy_root_identity
            and current.fence_id == request.current_fence_id
            and current.fence_revision == request.current_fence_revision
            and current.epoch == request.current_epoch
            and current.fenced_root_identity == request.current_root_identity
        )

    @staticmethod
    def _snapshot_matches(
        request: PackageOfflineRestoreRequestV1,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1 | None,
    ) -> bool:
        return isinstance(snapshot, PackageOfflineRestoreSnapshotEvidenceV1) and (
            snapshot.evidence_id == request.snapshot_evidence_id
            and snapshot.snapshot.store_id == request.store_id
            and snapshot.snapshot.receipt_id == request.snapshot_receipt_id
            and snapshot.snapshot.snapshot_id == request.snapshot_id
            and snapshot.snapshot.snapshot_revision == request.snapshot_revision
            and snapshot.snapshot.legacy_root_identity
            == request.legacy_root_identity
            and snapshot.snapshot.entry_count == request.snapshot_entry_count
            and snapshot.snapshot.byte_count == request.snapshot_byte_count
            and snapshot.snapshot_tree_digest == request.snapshot_tree_digest
            and snapshot.state_manifest_digest == request.state_manifest_digest
            and snapshot.covered_domains == PACKAGE_PRE_B_SNAPSHOT_DOMAINS
        )

    def _discard(
        self,
        receipt: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> None:
        try:
            self._materialization.discard(receipt)
        except Exception as exc:
            raise PackageOfflineRestoreError(
                "Isolated Package restore cleanup failed",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.materialization_receipt_id,
            ) from exc

    def _deactivate(self, receipt: PackageLegacyRuntimeActivationReceiptV1) -> None:
        try:
            self._activation.deactivate(receipt)
        except Exception as exc:
            raise PackageOfflineRestoreError(
                "Legacy Package runtime deactivation failed",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.activation_receipt_id,
            ) from exc

    @staticmethod
    def _rejected(
        request: PackageOfflineRestoreRequestV1,
        *,
        code: PackageOfflineRestoreFailureCode,
        evidence_ref: str,
    ) -> PackageOfflineRestoreResultV1:
        return PackageOfflineRestoreResultV1.rejected(
            request,
            code=code,
            evidence_ref=evidence_ref,
        )


_RESTORE_REQUEST_WIRE_KEYS = {
    "storeId",
    "currentFenceId",
    "currentFenceRevision",
    "currentEpoch",
    "currentRootIdentity",
    "genesisFenceId",
    "genesisFenceRevision",
    "legacyRootIdentity",
    "snapshotReceiptId",
    "snapshotEvidenceId",
    "snapshotId",
    "snapshotTreeDigest",
    "stateManifestDigest",
    "snapshotRevision",
    "snapshotEntryCount",
    "snapshotByteCount",
    "restoreNamespaceId",
    "legacyRuntimeVersion",
    "requestVersion",
}

_MATERIALIZATION_WIRE_KEYS = {
    "requestId",
    "storeId",
    "snapshotReceiptId",
    "snapshotEvidenceId",
    "snapshotId",
    "snapshotRevision",
    "restoreNamespaceId",
    "legacyRootIdentity",
    "restoredRootIdentity",
    "quiescenceReceiptId",
    "snapshotTreeDigest",
    "stateManifestDigest",
    "entryCount",
    "byteCount",
    "legacySnapshotExact",
    "bNamespaceUnreachable",
    "receiptVersion",
}

_ACTIVATION_WIRE_KEYS = {
    "requestId",
    "materializationReceiptId",
    "storeId",
    "restoredRootIdentity",
    "runtimeInstanceId",
    "runtimeLeaseId",
    "legacyRuntimeVersion",
    "exclusiveOldRuntime",
    "receiptVersion",
}


def _snapshot_evidence_identity(
    *,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    snapshot_tree_digest: str,
    state_manifest_digest: str,
    covered_domains: tuple[str, ...],
    evidence_version: int,
) -> dict[str, object]:
    return {
        "snapshot": snapshot.to_dict(),
        "snapshotTreeDigest": snapshot_tree_digest,
        "stateManifestDigest": state_manifest_digest,
        "coveredDomains": list(covered_domains),
        "evidenceVersion": evidence_version,
    }


def _restore_request_identity(
    *,
    store_id: str,
    current_fence_id: str,
    current_fence_revision: int,
    current_epoch: int,
    current_root_identity: str,
    genesis_fence_id: str,
    genesis_fence_revision: int,
    legacy_root_identity: str,
    snapshot_receipt_id: str,
    snapshot_evidence_id: str,
    snapshot_id: str,
    snapshot_tree_digest: str,
    state_manifest_digest: str,
    snapshot_revision: int,
    snapshot_entry_count: int,
    snapshot_byte_count: int,
    restore_namespace_id: str,
    legacy_runtime_version: str,
    request_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "currentFenceId": current_fence_id,
        "currentFenceRevision": current_fence_revision,
        "currentEpoch": current_epoch,
        "currentRootIdentity": current_root_identity,
        "genesisFenceId": genesis_fence_id,
        "genesisFenceRevision": genesis_fence_revision,
        "legacyRootIdentity": legacy_root_identity,
        "snapshotReceiptId": snapshot_receipt_id,
        "snapshotEvidenceId": snapshot_evidence_id,
        "snapshotId": snapshot_id,
        "snapshotTreeDigest": snapshot_tree_digest,
        "stateManifestDigest": state_manifest_digest,
        "snapshotRevision": snapshot_revision,
        "snapshotEntryCount": snapshot_entry_count,
        "snapshotByteCount": snapshot_byte_count,
        "restoreNamespaceId": restore_namespace_id,
        "legacyRuntimeVersion": legacy_runtime_version,
        "requestVersion": request_version,
    }


def _materialization_identity(
    *,
    request_id: str,
    store_id: str,
    snapshot_receipt_id: str,
    snapshot_evidence_id: str,
    snapshot_id: str,
    snapshot_revision: int,
    restore_namespace_id: str,
    legacy_root_identity: str,
    restored_root_identity: str,
    quiescence_receipt_id: str,
    snapshot_tree_digest: str,
    state_manifest_digest: str,
    entry_count: int,
    byte_count: int,
    legacy_snapshot_exact: bool,
    b_namespace_unreachable: bool,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "requestId": request_id,
        "storeId": store_id,
        "snapshotReceiptId": snapshot_receipt_id,
        "snapshotEvidenceId": snapshot_evidence_id,
        "snapshotId": snapshot_id,
        "snapshotRevision": snapshot_revision,
        "restoreNamespaceId": restore_namespace_id,
        "legacyRootIdentity": legacy_root_identity,
        "restoredRootIdentity": restored_root_identity,
        "quiescenceReceiptId": quiescence_receipt_id,
        "snapshotTreeDigest": snapshot_tree_digest,
        "stateManifestDigest": state_manifest_digest,
        "entryCount": entry_count,
        "byteCount": byte_count,
        "legacySnapshotExact": legacy_snapshot_exact,
        "bNamespaceUnreachable": b_namespace_unreachable,
        "receiptVersion": receipt_version,
    }


def _activation_identity(
    *,
    request_id: str,
    materialization_receipt_id: str,
    store_id: str,
    restored_root_identity: str,
    runtime_instance_id: str,
    runtime_lease_id: str,
    legacy_runtime_version: str,
    exclusive_old_runtime: bool,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "requestId": request_id,
        "materializationReceiptId": materialization_receipt_id,
        "storeId": store_id,
        "restoredRootIdentity": restored_root_identity,
        "runtimeInstanceId": runtime_instance_id,
        "runtimeLeaseId": runtime_lease_id,
        "legacyRuntimeVersion": legacy_runtime_version,
        "exclusiveOldRuntime": exclusive_old_runtime,
        "receiptVersion": receipt_version,
    }


def _failure_identity(
    *,
    request_id: str,
    evidence_ref: str,
    code: PackageOfflineRestoreFailureCode,
    stage: PackageOfflineRestoreFailureStage,
    retryable: bool,
    operator_action: PackageOfflineRestoreOperatorAction,
    failure_version: int,
) -> dict[str, object]:
    return {
        "requestId": request_id,
        "evidenceRef": evidence_ref,
        "code": code,
        "stage": stage,
        "retryable": retryable,
        "operatorAction": operator_action,
        "failureVersion": failure_version,
    }


def _fingerprint(value: dict[str, object]) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _wire_object(
    value: object,
    *,
    expected: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be an object")
    if set(value) != expected:
        raise ValueError(f"{name} does not match its versioned schema")
    return cast(dict[str, object], value)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{name} must be a string array")
    return tuple(value)


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_safe_version(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_VERSION.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_positive(value: int, *, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be positive")


def _require_non_negative(value: int, *, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be non-negative")


__all__: tuple[str, ...] = ()
