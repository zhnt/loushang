"""Dark PLC9B4c0 epoch-fence evidence, journal, and runtime admission."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_EPOCH_FENCE_REQUEST_VERSION = 1
PACKAGE_EPOCH_FENCE_RECEIPT_VERSION = 1
PACKAGE_EPOCH_FENCE_RECORD_VERSION = 1
PACKAGE_EPOCH_RUNTIME_LEASE_VERSION = 1
PACKAGE_EPOCH_LEASE_SNAPSHOT_VERSION = 1
PACKAGE_EPOCH_RUNTIME_ADMISSION_REQUEST_VERSION = 1
PACKAGE_EPOCH_RUNTIME_ADMISSION_RECEIPT_VERSION = 1
PACKAGE_EPOCH_RUNTIME_ADMISSION_FAILURE_VERSION = 1
PACKAGE_EPOCH_RUNTIME_ADMISSION_RESULT_VERSION = 1

PackageEpochRuntimeAdmissionDisposition = Literal["admitted", "rejected"]
PackageEpochRuntimeAdmissionCode = Literal[
    "ok",
    "package_runtime_epoch_unsupported",
]
PackageEpochOperatorAction = Literal["upgrade_runtime", "offline_restore"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,255}\Z")


class PackageEpochFenceError(RuntimeError):
    """Fail-closed epoch journal refusal with one stable code."""

    def __init__(self, message: str, *, code: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageEpochFenceRequestV1:
    """Opaque proof inputs for one already-completed offline root cutover."""

    cutover_id: str
    store_id: str
    prior_epoch: int
    next_epoch: int
    prior_fence_id: str | None
    prior_fence_revision: int
    legacy_root_identity: str
    fenced_root_identity: str
    namespace_id: str
    minimum_runtime_version: str
    minimum_runtime_protocol_epoch: int
    quiescence_receipt_id: str
    snapshot_receipt_id: str
    root_switch_receipt_id: str
    request_version: int = PACKAGE_EPOCH_FENCE_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.cutover_id, name="Package epoch cutover identity")
        _require_safe_id(self.store_id, name="Package store identity")
        _require_non_negative(self.prior_epoch, name="prior Package epoch")
        _require_positive(self.next_epoch, name="next Package epoch")
        _require_non_negative(
            self.prior_fence_revision,
            name="prior Package fence revision",
        )
        for value, name in (
            (self.legacy_root_identity, "legacy Package root identity"),
            (self.fenced_root_identity, "fenced Package root identity"),
            (self.namespace_id, "Package epoch namespace identity"),
            (self.quiescence_receipt_id, "Package quiescence receipt identity"),
            (self.snapshot_receipt_id, "Package snapshot receipt identity"),
            (self.root_switch_receipt_id, "Package root-switch receipt identity"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(
            self.minimum_runtime_version,
            name="minimum Package runtime version",
        )
        _require_positive(
            self.minimum_runtime_protocol_epoch,
            name="minimum Package runtime protocol epoch",
        )
        if self.next_epoch != self.prior_epoch + 1:
            raise ValueError("Package epoch transition must be adjacent")
        if self.legacy_root_identity == self.fenced_root_identity:
            raise ValueError("Package epoch cutover requires a fresh root identity")
        if self.prior_epoch == 0:
            if self.prior_fence_id is not None or self.prior_fence_revision != 0:
                raise ValueError("Genesis Package epoch cannot name a prior fence")
        else:
            if self.prior_fence_id is None:
                raise ValueError("Successor Package epoch requires a prior fence")
            _require_sha256(
                self.prior_fence_id,
                name="prior Package fence identity",
            )
            if self.prior_fence_revision < 1:
                raise ValueError("Successor Package epoch requires a prior revision")
        if self.request_version != PACKAGE_EPOCH_FENCE_REQUEST_VERSION:
            raise ValueError("Unsupported Package epoch fence request")
        if self.cutover_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch cutover identity does not match")

    @classmethod
    def create(
        cls,
        *,
        store_id: str,
        prior_fence: PackageEpochFenceReceiptV1 | None,
        legacy_root_identity: str,
        fenced_root_identity: str,
        namespace_id: str,
        minimum_runtime_version: str,
        minimum_runtime_protocol_epoch: int,
        quiescence_receipt_id: str,
        snapshot_receipt_id: str,
        root_switch_receipt_id: str,
    ) -> PackageEpochFenceRequestV1:
        if prior_fence is not None and not isinstance(
            prior_fence,
            PackageEpochFenceReceiptV1,
        ):
            raise TypeError("Prior Package epoch fence receipt is invalid")
        prior_epoch = 0 if prior_fence is None else prior_fence.epoch
        values = _epoch_request_identity(
            store_id=store_id,
            prior_epoch=prior_epoch,
            next_epoch=prior_epoch + 1,
            prior_fence_id=None if prior_fence is None else prior_fence.fence_id,
            prior_fence_revision=(
                0 if prior_fence is None else prior_fence.fence_revision
            ),
            legacy_root_identity=legacy_root_identity,
            fenced_root_identity=fenced_root_identity,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_receipt_id=snapshot_receipt_id,
            root_switch_receipt_id=root_switch_receipt_id,
            request_version=PACKAGE_EPOCH_FENCE_REQUEST_VERSION,
        )
        return cls(
            cutover_id=_fingerprint(values),
            store_id=store_id,
            prior_epoch=prior_epoch,
            next_epoch=prior_epoch + 1,
            prior_fence_id=None if prior_fence is None else prior_fence.fence_id,
            prior_fence_revision=(
                0 if prior_fence is None else prior_fence.fence_revision
            ),
            legacy_root_identity=legacy_root_identity,
            fenced_root_identity=fenced_root_identity,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_receipt_id=snapshot_receipt_id,
            root_switch_receipt_id=root_switch_receipt_id,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_request_identity(
            store_id=self.store_id,
            prior_epoch=self.prior_epoch,
            next_epoch=self.next_epoch,
            prior_fence_id=self.prior_fence_id,
            prior_fence_revision=self.prior_fence_revision,
            legacy_root_identity=self.legacy_root_identity,
            fenced_root_identity=self.fenced_root_identity,
            namespace_id=self.namespace_id,
            minimum_runtime_version=self.minimum_runtime_version,
            minimum_runtime_protocol_epoch=self.minimum_runtime_protocol_epoch,
            quiescence_receipt_id=self.quiescence_receipt_id,
            snapshot_receipt_id=self.snapshot_receipt_id,
            root_switch_receipt_id=self.root_switch_receipt_id,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"cutoverId": self.cutover_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochFenceRequestV1:
        document = _wire_object(
            value,
            expected={
                "cutoverId",
                "storeId",
                "priorEpoch",
                "nextEpoch",
                "priorFenceId",
                "priorFenceRevision",
                "legacyRootIdentity",
                "fencedRootIdentity",
                "namespaceId",
                "minimumRuntimeVersion",
                "minimumRuntimeProtocolEpoch",
                "quiescenceReceiptId",
                "snapshotReceiptId",
                "rootSwitchReceiptId",
                "requestVersion",
            },
            name="Package epoch fence request",
        )
        return cls(
            cutover_id=_wire_string(document["cutoverId"], name="cutover id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            prior_epoch=_wire_int(document["priorEpoch"], name="prior epoch"),
            next_epoch=_wire_int(document["nextEpoch"], name="next epoch"),
            prior_fence_id=_wire_optional_string(
                document["priorFenceId"],
                name="prior fence id",
            ),
            prior_fence_revision=_wire_int(
                document["priorFenceRevision"],
                name="prior fence revision",
            ),
            legacy_root_identity=_wire_string(
                document["legacyRootIdentity"],
                name="legacy root identity",
            ),
            fenced_root_identity=_wire_string(
                document["fencedRootIdentity"],
                name="fenced root identity",
            ),
            namespace_id=_wire_string(
                document["namespaceId"],
                name="namespace id",
            ),
            minimum_runtime_version=_wire_string(
                document["minimumRuntimeVersion"],
                name="minimum runtime version",
            ),
            minimum_runtime_protocol_epoch=_wire_int(
                document["minimumRuntimeProtocolEpoch"],
                name="minimum runtime protocol epoch",
            ),
            quiescence_receipt_id=_wire_string(
                document["quiescenceReceiptId"],
                name="quiescence receipt id",
            ),
            snapshot_receipt_id=_wire_string(
                document["snapshotReceiptId"],
                name="snapshot receipt id",
            ),
            root_switch_receipt_id=_wire_string(
                document["rootSwitchReceiptId"],
                name="root-switch receipt id",
            ),
            request_version=_wire_int(
                document["requestVersion"],
                name="request version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochFenceReceiptV1:
    """Durable current epoch selected by the Package epoch authority."""

    request: PackageEpochFenceRequestV1
    fence_revision: int
    fence_id: str
    receipt_version: int = PACKAGE_EPOCH_FENCE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, PackageEpochFenceRequestV1):
            raise TypeError("Package epoch fence request is required")
        _require_positive(self.fence_revision, name="Package fence revision")
        _require_sha256(self.fence_id, name="Package epoch fence identity")
        if self.fence_revision != self.request.prior_fence_revision + 1:
            raise ValueError("Package epoch fence revision is not adjacent")
        if self.receipt_version != PACKAGE_EPOCH_FENCE_RECEIPT_VERSION:
            raise ValueError("Unsupported Package epoch fence receipt")
        if self.fence_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch fence identity does not match")

    @classmethod
    def create(
        cls,
        request: PackageEpochFenceRequestV1,
    ) -> PackageEpochFenceReceiptV1:
        if not isinstance(request, PackageEpochFenceRequestV1):
            raise TypeError("Package epoch fence request is required")
        fence_revision = request.prior_fence_revision + 1
        values = _epoch_receipt_identity(
            request=request,
            fence_revision=fence_revision,
            receipt_version=PACKAGE_EPOCH_FENCE_RECEIPT_VERSION,
        )
        return cls(
            request=request,
            fence_revision=fence_revision,
            fence_id=_fingerprint(values),
        )

    @property
    def store_id(self) -> str:
        return self.request.store_id

    @property
    def epoch(self) -> int:
        return self.request.next_epoch

    @property
    def fenced_root_identity(self) -> str:
        return self.request.fenced_root_identity

    @property
    def minimum_runtime_version(self) -> str:
        return self.request.minimum_runtime_version

    @property
    def minimum_runtime_protocol_epoch(self) -> int:
        return self.request.minimum_runtime_protocol_epoch

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_receipt_identity(
            request=self.request,
            fence_revision=self.fence_revision,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"fenceId": self.fence_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochFenceReceiptV1:
        document = _wire_object(
            value,
            expected={"fenceId", "request", "fenceRevision", "receiptVersion"},
            name="Package epoch fence receipt",
        )
        return cls(
            request=PackageEpochFenceRequestV1.from_dict(document["request"]),
            fence_revision=_wire_int(
                document["fenceRevision"],
                name="fence revision",
            ),
            fence_id=_wire_string(document["fenceId"], name="fence id"),
            receipt_version=_wire_int(
                document["receiptVersion"],
                name="receipt version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochFenceRecordV1:
    record_revision: int
    receipt: PackageEpochFenceReceiptV1
    record_version: int = PACKAGE_EPOCH_FENCE_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.record_revision, name="Package epoch record revision")
        if not isinstance(self.receipt, PackageEpochFenceReceiptV1):
            raise TypeError("Package epoch fence receipt is required")
        if self.record_revision != self.receipt.fence_revision:
            raise ValueError("Package epoch record revision changed")
        if self.record_version != PACKAGE_EPOCH_FENCE_RECORD_VERSION:
            raise ValueError("Unsupported Package epoch fence record")

    def to_dict(self) -> dict[str, object]:
        return {
            "recordRevision": self.record_revision,
            "receipt": self.receipt.to_dict(),
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochFenceRecordV1:
        document = _wire_object(
            value,
            expected={"recordRevision", "receipt", "recordVersion"},
            name="Package epoch fence record",
        )
        return cls(
            record_revision=_wire_int(
                document["recordRevision"],
                name="record revision",
            ),
            receipt=PackageEpochFenceReceiptV1.from_dict(document["receipt"]),
            record_version=_wire_int(
                document["recordVersion"],
                name="record version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochRuntimeLeaseV1:
    """Credential-free identity of one active fence-aware runtime lease."""

    lease_id: str
    runtime_id: str
    runtime_epoch: int
    store_root_identity: str
    registration_receipt_id: str
    lease_version: int = PACKAGE_EPOCH_RUNTIME_LEASE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.lease_id, name="Package runtime lease identity")
        _require_safe_id(self.runtime_id, name="Package runtime identity")
        _require_positive(self.runtime_epoch, name="Package runtime epoch")
        _require_sha256(
            self.store_root_identity,
            name="Package runtime root identity",
        )
        _require_sha256(
            self.registration_receipt_id,
            name="Package runtime registration receipt identity",
        )
        if self.lease_version != PACKAGE_EPOCH_RUNTIME_LEASE_VERSION:
            raise ValueError("Unsupported Package epoch runtime lease")
        if self.lease_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package runtime lease identity does not match")

    @classmethod
    def create(
        cls,
        *,
        runtime_id: str,
        runtime_epoch: int,
        store_root_identity: str,
        registration_receipt_id: str,
    ) -> PackageEpochRuntimeLeaseV1:
        values = _epoch_lease_identity(
            runtime_id=runtime_id,
            runtime_epoch=runtime_epoch,
            store_root_identity=store_root_identity,
            registration_receipt_id=registration_receipt_id,
            lease_version=PACKAGE_EPOCH_RUNTIME_LEASE_VERSION,
        )
        return cls(
            lease_id=_fingerprint(values),
            runtime_id=runtime_id,
            runtime_epoch=runtime_epoch,
            store_root_identity=store_root_identity,
            registration_receipt_id=registration_receipt_id,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_lease_identity(
            runtime_id=self.runtime_id,
            runtime_epoch=self.runtime_epoch,
            store_root_identity=self.store_root_identity,
            registration_receipt_id=self.registration_receipt_id,
            lease_version=self.lease_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"leaseId": self.lease_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochRuntimeLeaseV1:
        document = _wire_object(
            value,
            expected={
                "leaseId",
                "runtimeId",
                "runtimeEpoch",
                "storeRootIdentity",
                "registrationReceiptId",
                "leaseVersion",
            },
            name="Package epoch runtime lease",
        )
        return cls(
            lease_id=_wire_string(document["leaseId"], name="lease id"),
            runtime_id=_wire_string(document["runtimeId"], name="runtime id"),
            runtime_epoch=_wire_int(
                document["runtimeEpoch"],
                name="runtime epoch",
            ),
            store_root_identity=_wire_string(
                document["storeRootIdentity"],
                name="store root identity",
            ),
            registration_receipt_id=_wire_string(
                document["registrationReceiptId"],
                name="registration receipt id",
            ),
            lease_version=_wire_int(
                document["leaseVersion"],
                name="lease version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochLeaseSnapshotV1:
    """Owner-revisioned complete active lease set for one Package store."""

    snapshot_id: str
    store_id: str
    owner_revision: int
    active_leases: tuple[PackageEpochRuntimeLeaseV1, ...]
    snapshot_version: int = PACKAGE_EPOCH_LEASE_SNAPSHOT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.snapshot_id, name="Package lease snapshot identity")
        _require_safe_id(self.store_id, name="Package store identity")
        _require_positive(self.owner_revision, name="Package lease owner revision")
        if not self.active_leases:
            raise ValueError("Package lease snapshot must contain an active lease")
        if not all(
            isinstance(lease, PackageEpochRuntimeLeaseV1)
            for lease in self.active_leases
        ):
            raise TypeError("Package lease snapshot contains an invalid lease")
        lease_ids = tuple(lease.lease_id for lease in self.active_leases)
        if lease_ids != tuple(sorted(set(lease_ids))):
            raise ValueError("Package lease snapshot must be uniquely ordered")
        if self.snapshot_version != PACKAGE_EPOCH_LEASE_SNAPSHOT_VERSION:
            raise ValueError("Unsupported Package epoch lease snapshot")
        if self.snapshot_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package lease snapshot identity does not match")

    @classmethod
    def create(
        cls,
        *,
        store_id: str,
        owner_revision: int,
        active_leases: tuple[PackageEpochRuntimeLeaseV1, ...],
    ) -> PackageEpochLeaseSnapshotV1:
        ordered = tuple(sorted(active_leases, key=lambda lease: lease.lease_id))
        values = _epoch_lease_snapshot_identity(
            store_id=store_id,
            owner_revision=owner_revision,
            active_leases=ordered,
            snapshot_version=PACKAGE_EPOCH_LEASE_SNAPSHOT_VERSION,
        )
        return cls(
            snapshot_id=_fingerprint(values),
            store_id=store_id,
            owner_revision=owner_revision,
            active_leases=ordered,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_lease_snapshot_identity(
            store_id=self.store_id,
            owner_revision=self.owner_revision,
            active_leases=self.active_leases,
            snapshot_version=self.snapshot_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"snapshotId": self.snapshot_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochLeaseSnapshotV1:
        document = _wire_object(
            value,
            expected={
                "snapshotId",
                "storeId",
                "ownerRevision",
                "activeLeases",
                "snapshotVersion",
            },
            name="Package epoch lease snapshot",
        )
        leases = _wire_list(document["activeLeases"], name="active leases")
        return cls(
            snapshot_id=_wire_string(document["snapshotId"], name="snapshot id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            owner_revision=_wire_int(
                document["ownerRevision"],
                name="owner revision",
            ),
            active_leases=tuple(
                PackageEpochRuntimeLeaseV1.from_dict(lease) for lease in leases
            ),
            snapshot_version=_wire_int(
                document["snapshotVersion"],
                name="snapshot version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochRuntimeAdmissionRequestV1:
    """Runtime claim bound to an exact current fence, root, and live lease."""

    admission_request_id: str
    store_id: str
    fence_id: str
    runtime_id: str
    runtime_version: str
    runtime_protocol_epoch: int
    runtime_epoch: int
    store_root_identity: str
    lease_id: str
    request_version: int = PACKAGE_EPOCH_RUNTIME_ADMISSION_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(
            self.admission_request_id,
            name="Package epoch admission request identity",
        )
        _require_safe_id(self.store_id, name="Package store identity")
        _require_sha256(self.fence_id, name="Package epoch fence identity")
        _require_safe_id(self.runtime_id, name="Package runtime identity")
        _require_safe_version(self.runtime_version, name="Package runtime version")
        _require_positive(
            self.runtime_protocol_epoch,
            name="Package runtime protocol epoch",
        )
        _require_positive(self.runtime_epoch, name="Package runtime epoch")
        _require_sha256(
            self.store_root_identity,
            name="Package runtime root identity",
        )
        _require_sha256(self.lease_id, name="Package runtime lease identity")
        if self.request_version != PACKAGE_EPOCH_RUNTIME_ADMISSION_REQUEST_VERSION:
            raise ValueError("Unsupported Package epoch runtime admission request")
        if self.admission_request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch admission request identity does not match")

    @classmethod
    def create(
        cls,
        *,
        fence: PackageEpochFenceReceiptV1,
        runtime_id: str,
        runtime_version: str,
        runtime_protocol_epoch: int,
        runtime_epoch: int,
        store_root_identity: str,
        lease_id: str,
    ) -> PackageEpochRuntimeAdmissionRequestV1:
        if not isinstance(fence, PackageEpochFenceReceiptV1):
            raise TypeError("Package epoch fence receipt is required")
        values = _epoch_admission_request_identity(
            store_id=fence.store_id,
            fence_id=fence.fence_id,
            runtime_id=runtime_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            runtime_epoch=runtime_epoch,
            store_root_identity=store_root_identity,
            lease_id=lease_id,
            request_version=PACKAGE_EPOCH_RUNTIME_ADMISSION_REQUEST_VERSION,
        )
        return cls(
            admission_request_id=_fingerprint(values),
            store_id=fence.store_id,
            fence_id=fence.fence_id,
            runtime_id=runtime_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            runtime_epoch=runtime_epoch,
            store_root_identity=store_root_identity,
            lease_id=lease_id,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_admission_request_identity(
            store_id=self.store_id,
            fence_id=self.fence_id,
            runtime_id=self.runtime_id,
            runtime_version=self.runtime_version,
            runtime_protocol_epoch=self.runtime_protocol_epoch,
            runtime_epoch=self.runtime_epoch,
            store_root_identity=self.store_root_identity,
            lease_id=self.lease_id,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionRequestId": self.admission_request_id,
            **self._identity_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochRuntimeAdmissionRequestV1:
        document = _wire_object(
            value,
            expected={
                "admissionRequestId",
                "storeId",
                "fenceId",
                "runtimeId",
                "runtimeVersion",
                "runtimeProtocolEpoch",
                "runtimeEpoch",
                "storeRootIdentity",
                "leaseId",
                "requestVersion",
            },
            name="Package epoch runtime admission request",
        )
        return cls(
            admission_request_id=_wire_string(
                document["admissionRequestId"],
                name="admission request id",
            ),
            store_id=_wire_string(document["storeId"], name="store id"),
            fence_id=_wire_string(document["fenceId"], name="fence id"),
            runtime_id=_wire_string(document["runtimeId"], name="runtime id"),
            runtime_version=_wire_string(
                document["runtimeVersion"],
                name="runtime version",
            ),
            runtime_protocol_epoch=_wire_int(
                document["runtimeProtocolEpoch"],
                name="runtime protocol epoch",
            ),
            runtime_epoch=_wire_int(
                document["runtimeEpoch"],
                name="runtime epoch",
            ),
            store_root_identity=_wire_string(
                document["storeRootIdentity"],
                name="store root identity",
            ),
            lease_id=_wire_string(document["leaseId"], name="lease id"),
            request_version=_wire_int(
                document["requestVersion"],
                name="request version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochRuntimeAdmissionReceiptV1:
    receipt_id: str
    request: PackageEpochRuntimeAdmissionRequestV1
    fence_id: str
    lease_snapshot_id: str
    lease_owner_revision: int
    receipt_version: int = PACKAGE_EPOCH_RUNTIME_ADMISSION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="Package epoch admission receipt id")
        if not isinstance(self.request, PackageEpochRuntimeAdmissionRequestV1):
            raise TypeError("Package epoch runtime admission request is required")
        _require_sha256(self.fence_id, name="Package epoch fence identity")
        _require_sha256(
            self.lease_snapshot_id,
            name="Package lease snapshot identity",
        )
        _require_positive(
            self.lease_owner_revision,
            name="Package lease owner revision",
        )
        if self.fence_id != self.request.fence_id:
            raise ValueError("Package epoch admission fence changed")
        if self.receipt_version != PACKAGE_EPOCH_RUNTIME_ADMISSION_RECEIPT_VERSION:
            raise ValueError("Unsupported Package epoch admission receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch admission receipt id does not match")

    @classmethod
    def create(
        cls,
        request: PackageEpochRuntimeAdmissionRequestV1,
        *,
        snapshot: PackageEpochLeaseSnapshotV1,
    ) -> PackageEpochRuntimeAdmissionReceiptV1:
        values = _epoch_admission_receipt_identity(
            request=request,
            fence_id=request.fence_id,
            lease_snapshot_id=snapshot.snapshot_id,
            lease_owner_revision=snapshot.owner_revision,
            receipt_version=PACKAGE_EPOCH_RUNTIME_ADMISSION_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=request,
            fence_id=request.fence_id,
            lease_snapshot_id=snapshot.snapshot_id,
            lease_owner_revision=snapshot.owner_revision,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_admission_receipt_identity(
            request=self.request,
            fence_id=self.fence_id,
            lease_snapshot_id=self.lease_snapshot_id,
            lease_owner_revision=self.lease_owner_revision,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochRuntimeAdmissionReceiptV1:
        document = _wire_object(
            value,
            expected={
                "receiptId",
                "request",
                "fenceId",
                "leaseSnapshotId",
                "leaseOwnerRevision",
                "receiptVersion",
            },
            name="Package epoch runtime admission receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            request=PackageEpochRuntimeAdmissionRequestV1.from_dict(
                document["request"]
            ),
            fence_id=_wire_string(document["fenceId"], name="fence id"),
            lease_snapshot_id=_wire_string(
                document["leaseSnapshotId"],
                name="lease snapshot id",
            ),
            lease_owner_revision=_wire_int(
                document["leaseOwnerRevision"],
                name="lease owner revision",
            ),
            receipt_version=_wire_int(
                document["receiptVersion"],
                name="receipt version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochRuntimeAdmissionFailureV1:
    failure_id: str
    admission_request_id: str
    evidence_ref: str
    code: Literal["package_runtime_epoch_unsupported"]
    operator_action: PackageEpochOperatorAction
    failure_version: int = PACKAGE_EPOCH_RUNTIME_ADMISSION_FAILURE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.failure_id, "Package epoch admission failure id"),
            (self.admission_request_id, "Package epoch admission request id"),
            (self.evidence_ref, "Package epoch failure evidence"),
        ):
            _require_sha256(value, name=name)
        if self.code != "package_runtime_epoch_unsupported":
            raise ValueError("Unsupported Package epoch admission failure code")
        if self.operator_action not in {"upgrade_runtime", "offline_restore"}:
            raise ValueError("Unsupported Package epoch operator action")
        if self.failure_version != PACKAGE_EPOCH_RUNTIME_ADMISSION_FAILURE_VERSION:
            raise ValueError("Unsupported Package epoch admission failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch admission failure id does not match")

    @classmethod
    def create(
        cls,
        request: PackageEpochRuntimeAdmissionRequestV1,
        *,
        evidence_ref: str,
        operator_action: PackageEpochOperatorAction,
    ) -> PackageEpochRuntimeAdmissionFailureV1:
        values = _epoch_admission_failure_identity(
            admission_request_id=request.admission_request_id,
            evidence_ref=evidence_ref,
            code="package_runtime_epoch_unsupported",
            operator_action=operator_action,
            failure_version=PACKAGE_EPOCH_RUNTIME_ADMISSION_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            admission_request_id=request.admission_request_id,
            evidence_ref=evidence_ref,
            code="package_runtime_epoch_unsupported",
            operator_action=operator_action,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _epoch_admission_failure_identity(
            admission_request_id=self.admission_request_id,
            evidence_ref=self.evidence_ref,
            code=self.code,
            operator_action=self.operator_action,
            failure_version=self.failure_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochRuntimeAdmissionFailureV1:
        document = _wire_object(
            value,
            expected={
                "failureId",
                "admissionRequestId",
                "evidenceRef",
                "code",
                "operatorAction",
                "failureVersion",
            },
            name="Package epoch runtime admission failure",
        )
        code = _wire_string(document["code"], name="failure code")
        action = _wire_string(document["operatorAction"], name="operator action")
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            admission_request_id=_wire_string(
                document["admissionRequestId"],
                name="admission request id",
            ),
            evidence_ref=_wire_string(
                document["evidenceRef"],
                name="evidence ref",
            ),
            code=cast(Literal["package_runtime_epoch_unsupported"], code),
            operator_action=cast(PackageEpochOperatorAction, action),
            failure_version=_wire_int(
                document["failureVersion"],
                name="failure version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochRuntimeAdmissionResultV1:
    admission_request_id: str
    disposition: PackageEpochRuntimeAdmissionDisposition
    code: PackageEpochRuntimeAdmissionCode
    receipt: PackageEpochRuntimeAdmissionReceiptV1 | None
    failure: PackageEpochRuntimeAdmissionFailureV1 | None
    result_version: int = PACKAGE_EPOCH_RUNTIME_ADMISSION_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(
            self.admission_request_id,
            name="Package epoch admission request id",
        )
        if self.disposition == "admitted":
            if self.code != "ok" or self.receipt is None or self.failure is not None:
                raise ValueError("Admitted Package epoch result is inconsistent")
            if self.receipt.request.admission_request_id != self.admission_request_id:
                raise ValueError("Package epoch admission receipt changed")
        elif self.disposition == "rejected":
            if (
                self.code != "package_runtime_epoch_unsupported"
                or self.receipt is not None
                or self.failure is None
                or self.failure.admission_request_id != self.admission_request_id
            ):
                raise ValueError("Rejected Package epoch result is inconsistent")
        else:
            raise ValueError("Unsupported Package epoch admission disposition")
        if self.result_version != PACKAGE_EPOCH_RUNTIME_ADMISSION_RESULT_VERSION:
            raise ValueError("Unsupported Package epoch admission result")

    @classmethod
    def admitted(
        cls,
        receipt: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageEpochRuntimeAdmissionResultV1:
        return cls(
            admission_request_id=receipt.request.admission_request_id,
            disposition="admitted",
            code="ok",
            receipt=receipt,
            failure=None,
        )

    @classmethod
    def rejected(
        cls,
        request: PackageEpochRuntimeAdmissionRequestV1,
        *,
        evidence_ref: str,
        operator_action: PackageEpochOperatorAction,
    ) -> PackageEpochRuntimeAdmissionResultV1:
        failure = PackageEpochRuntimeAdmissionFailureV1.create(
            request,
            evidence_ref=evidence_ref,
            operator_action=operator_action,
        )
        return cls(
            admission_request_id=request.admission_request_id,
            disposition="rejected",
            code="package_runtime_epoch_unsupported",
            receipt=None,
            failure=failure,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionRequestId": self.admission_request_id,
            "disposition": self.disposition,
            "code": self.code,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "failure": None if self.failure is None else self.failure.to_dict(),
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochRuntimeAdmissionResultV1:
        document = _wire_object(
            value,
            expected={
                "admissionRequestId",
                "disposition",
                "code",
                "receipt",
                "failure",
                "resultVersion",
            },
            name="Package epoch runtime admission result",
        )
        disposition = _wire_string(document["disposition"], name="disposition")
        code = _wire_string(document["code"], name="code")
        receipt_value = document["receipt"]
        failure_value = document["failure"]
        return cls(
            admission_request_id=_wire_string(
                document["admissionRequestId"],
                name="admission request id",
            ),
            disposition=cast(PackageEpochRuntimeAdmissionDisposition, disposition),
            code=cast(PackageEpochRuntimeAdmissionCode, code),
            receipt=(
                None
                if receipt_value is None
                else PackageEpochRuntimeAdmissionReceiptV1.from_dict(receipt_value)
            ),
            failure=(
                None
                if failure_value is None
                else PackageEpochRuntimeAdmissionFailureV1.from_dict(failure_value)
            ),
            result_version=_wire_int(
                document["resultVersion"],
                name="result version",
            ),
        )


class PackageEpochFenceReadPort(Protocol):
    def current(self, store_id: str) -> PackageEpochFenceReceiptV1 | None: ...


class PackageEpochLeaseSnapshotPort(Protocol):
    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1: ...


def _encode_epoch_record(record: PackageEpochFenceRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageEpochFenceRecordV1):
        raise TypeError("Package epoch fence record is required")
    return record.to_dict()


def _decode_epoch_record(value: object) -> PackageEpochFenceRecordV1:
    try:
        return PackageEpochFenceRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package epoch fence record is invalid",
            code="invalid_package_epoch_fence_record",
        ) from exc


PACKAGE_EPOCH_FENCE_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_epoch_record,
    decoder=_decode_epoch_record,
)


class PackageEpochFenceJournal:
    """One durable adjacent epoch chain for one stable Package store identity."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def publish(
        self,
        request: PackageEpochFenceRequestV1,
    ) -> PackageEpochFenceReceiptV1:
        if not isinstance(request, PackageEpochFenceRequestV1):
            raise TypeError("Package epoch fence request is required")
        with self._exclusive():
            records = self._load_unlocked()
            if any(record.receipt.request == request for record in records):
                return records[-1].receipt
            current = None if not records else records[-1].receipt
            try:
                _validate_epoch_successor(current, request)
            except ValueError as exc:
                raise self._error(
                    "Package epoch fence compare-and-swap failed",
                    code="package_epoch_fence_stale",
                ) from exc
            receipt = PackageEpochFenceReceiptV1.create(request)
            self._append_unlocked(
                records,
                PackageEpochFenceRecordV1(
                    record_revision=len(records) + 1,
                    receipt=receipt,
                ),
            )
            return receipt

    def current(self, store_id: str) -> PackageEpochFenceReceiptV1 | None:
        _require_safe_id(store_id, name="Package store identity")
        with self._exclusive():
            records = self._load_unlocked()
            if not records:
                return None
            current = records[-1].receipt
            if current.store_id != store_id:
                return None
            return current

    def records(self) -> tuple[PackageEpochFenceRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _append_unlocked(
        self,
        records: tuple[PackageEpochFenceRecordV1, ...],
        record: PackageEpochFenceRecordV1,
    ) -> None:
        if record.record_revision != len(records) + 1:
            raise self._error(
                "Package epoch journal revision changed",
                code="package_epoch_fence_stale",
            )
        append_jsonl_record(
            self._path,
            record,
            record_codec=PACKAGE_EPOCH_FENCE_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PackageEpochFenceRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            _assert_no_duplicate_json_keys(self._path)
            snapshot: JsonlSnapshot[None, PackageEpochFenceRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_EPOCH_FENCE_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
        except (JournalFileError, OSError, UnicodeError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, JournalFileError)
                and exc.code
                in {
                    "invalid_package_epoch_fence_record",
                    "unsupported_package_epoch_fence_record_version",
                }
                else "package_epoch_journal_corrupt"
            )
            raise self._error(
                "Package epoch journal cannot be decoded",
                code=code,
            ) from exc
        records = snapshot.records
        try:
            _validate_epoch_records(records)
        except ValueError as exc:
            raise self._error(
                "Package epoch journal history is invalid",
                code="package_epoch_journal_corrupt",
            ) from exc
        return records

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(self, message: str, *, code: str) -> PackageEpochFenceError:
        return PackageEpochFenceError(message, code=code, path=self._path)


class PackageEpochRuntimeAdmissionOwner:
    """Read-only runtime fence check; it owns no root or lease mutation."""

    def __init__(
        self,
        *,
        fences: PackageEpochFenceReadPort,
        leases: PackageEpochLeaseSnapshotPort,
    ) -> None:
        if not callable(getattr(fences, "current", None)):
            raise TypeError("Package epoch fence reader is required")
        if not callable(getattr(leases, "snapshot", None)):
            raise TypeError("Package epoch lease snapshot owner is required")
        self._fences = fences
        self._leases = leases

    def admit(
        self,
        request: PackageEpochRuntimeAdmissionRequestV1,
    ) -> PackageEpochRuntimeAdmissionResultV1:
        if not isinstance(request, PackageEpochRuntimeAdmissionRequestV1):
            raise TypeError("Package epoch runtime admission request is required")
        fence = self._fences.current(request.store_id)
        if fence is None or not _request_matches_fence(request, fence):
            return PackageEpochRuntimeAdmissionResultV1.rejected(
                request,
                evidence_ref=(request.fence_id if fence is None else fence.fence_id),
                operator_action="upgrade_runtime",
            )
        try:
            snapshot = self._leases.snapshot(store_id=request.store_id)
        except Exception:
            return PackageEpochRuntimeAdmissionResultV1.rejected(
                request,
                evidence_ref=fence.fence_id,
                operator_action="offline_restore",
            )
        if not isinstance(snapshot, PackageEpochLeaseSnapshotV1):
            return PackageEpochRuntimeAdmissionResultV1.rejected(
                request,
                evidence_ref=fence.fence_id,
                operator_action="offline_restore",
            )
        confirmed_fence = self._fences.current(request.store_id)
        if confirmed_fence != fence:
            return PackageEpochRuntimeAdmissionResultV1.rejected(
                request,
                evidence_ref=(
                    fence.fence_id
                    if confirmed_fence is None
                    else confirmed_fence.fence_id
                ),
                operator_action="upgrade_runtime",
            )
        if not _snapshot_admits(request, fence, snapshot):
            return PackageEpochRuntimeAdmissionResultV1.rejected(
                request,
                evidence_ref=snapshot.snapshot_id,
                operator_action="offline_restore",
            )
        return PackageEpochRuntimeAdmissionResultV1.admitted(
            PackageEpochRuntimeAdmissionReceiptV1.create(
                request,
                snapshot=snapshot,
            )
        )


def _request_matches_fence(
    request: PackageEpochRuntimeAdmissionRequestV1,
    fence: PackageEpochFenceReceiptV1,
) -> bool:
    return (
        request.fence_id == fence.fence_id
        and request.store_id == fence.store_id
        and request.runtime_epoch == fence.epoch
        and request.store_root_identity == fence.fenced_root_identity
        and request.runtime_protocol_epoch >= fence.minimum_runtime_protocol_epoch
    )


def _snapshot_admits(
    request: PackageEpochRuntimeAdmissionRequestV1,
    fence: PackageEpochFenceReceiptV1,
    snapshot: PackageEpochLeaseSnapshotV1,
) -> bool:
    if snapshot.store_id != request.store_id:
        return False
    requested = next(
        (
            lease
            for lease in snapshot.active_leases
            if lease.lease_id == request.lease_id
        ),
        None,
    )
    if requested is None:
        return False
    if (
        requested.runtime_id != request.runtime_id
        or requested.runtime_epoch != request.runtime_epoch
        or requested.store_root_identity != request.store_root_identity
    ):
        return False
    return all(
        lease.runtime_epoch == fence.epoch
        and lease.store_root_identity == fence.fenced_root_identity
        for lease in snapshot.active_leases
    )


def _validate_epoch_successor(
    current: PackageEpochFenceReceiptV1 | None,
    request: PackageEpochFenceRequestV1,
) -> None:
    if current is None:
        if (
            request.prior_epoch != 0
            or request.next_epoch != 1
            or request.prior_fence_id is not None
            or request.prior_fence_revision != 0
        ):
            raise ValueError("Package epoch genesis changed")
        return
    if (
        request.store_id != current.store_id
        or request.prior_epoch != current.epoch
        or request.next_epoch != current.epoch + 1
        or request.prior_fence_id != current.fence_id
        or request.prior_fence_revision != current.fence_revision
        or request.legacy_root_identity != current.fenced_root_identity
    ):
        raise ValueError("Package epoch successor changed")


def _validate_epoch_records(
    records: tuple[PackageEpochFenceRecordV1, ...],
) -> None:
    current: PackageEpochFenceReceiptV1 | None = None
    for expected_revision, record in enumerate(records, start=1):
        if record.record_revision != expected_revision:
            raise ValueError("Package epoch record revisions are not dense")
        _validate_epoch_successor(current, record.receipt.request)
        if record.receipt.fence_revision != expected_revision:
            raise ValueError("Package epoch fence revision changed")
        current = record.receipt


def _assert_no_duplicate_json_keys(path: Path) -> None:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("Duplicate JSON object key")
            document[key] = value
        return document

    with path.open("r", encoding="utf-8", newline="") as stream:
        lines = stream.readlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                json.loads(line, object_pairs_hook=reject_duplicates)
            except json.JSONDecodeError:
                if index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                    return
                raise


def _epoch_request_identity(
    *,
    store_id: str,
    prior_epoch: int,
    next_epoch: int,
    prior_fence_id: str | None,
    prior_fence_revision: int,
    legacy_root_identity: str,
    fenced_root_identity: str,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
    quiescence_receipt_id: str,
    snapshot_receipt_id: str,
    root_switch_receipt_id: str,
    request_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "priorEpoch": prior_epoch,
        "nextEpoch": next_epoch,
        "priorFenceId": prior_fence_id,
        "priorFenceRevision": prior_fence_revision,
        "legacyRootIdentity": legacy_root_identity,
        "fencedRootIdentity": fenced_root_identity,
        "namespaceId": namespace_id,
        "minimumRuntimeVersion": minimum_runtime_version,
        "minimumRuntimeProtocolEpoch": minimum_runtime_protocol_epoch,
        "quiescenceReceiptId": quiescence_receipt_id,
        "snapshotReceiptId": snapshot_receipt_id,
        "rootSwitchReceiptId": root_switch_receipt_id,
        "requestVersion": request_version,
    }


def _epoch_receipt_identity(
    *,
    request: PackageEpochFenceRequestV1,
    fence_revision: int,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "request": request.to_dict(),
        "fenceRevision": fence_revision,
        "receiptVersion": receipt_version,
    }


def _epoch_lease_identity(
    *,
    runtime_id: str,
    runtime_epoch: int,
    store_root_identity: str,
    registration_receipt_id: str,
    lease_version: int,
) -> dict[str, object]:
    return {
        "runtimeId": runtime_id,
        "runtimeEpoch": runtime_epoch,
        "storeRootIdentity": store_root_identity,
        "registrationReceiptId": registration_receipt_id,
        "leaseVersion": lease_version,
    }


def _epoch_lease_snapshot_identity(
    *,
    store_id: str,
    owner_revision: int,
    active_leases: tuple[PackageEpochRuntimeLeaseV1, ...],
    snapshot_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "ownerRevision": owner_revision,
        "activeLeases": [lease.to_dict() for lease in active_leases],
        "snapshotVersion": snapshot_version,
    }


def _epoch_admission_request_identity(
    *,
    store_id: str,
    fence_id: str,
    runtime_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    runtime_epoch: int,
    store_root_identity: str,
    lease_id: str,
    request_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "fenceId": fence_id,
        "runtimeId": runtime_id,
        "runtimeVersion": runtime_version,
        "runtimeProtocolEpoch": runtime_protocol_epoch,
        "runtimeEpoch": runtime_epoch,
        "storeRootIdentity": store_root_identity,
        "leaseId": lease_id,
        "requestVersion": request_version,
    }


def _epoch_admission_receipt_identity(
    *,
    request: PackageEpochRuntimeAdmissionRequestV1,
    fence_id: str,
    lease_snapshot_id: str,
    lease_owner_revision: int,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "request": request.to_dict(),
        "fenceId": fence_id,
        "leaseSnapshotId": lease_snapshot_id,
        "leaseOwnerRevision": lease_owner_revision,
        "receiptVersion": receipt_version,
    }


def _epoch_admission_failure_identity(
    *,
    admission_request_id: str,
    evidence_ref: str,
    code: str,
    operator_action: str,
    failure_version: int,
) -> dict[str, object]:
    return {
        "admissionRequestId": admission_request_id,
        "evidenceRef": evidence_ref,
        "code": code,
        "operatorAction": operator_action,
        "failureVersion": failure_version,
    }


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase sha256 value")


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
        raise ValueError(f"{name} must not be negative")


def _wire_object(
    value: object,
    *,
    expected: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ):
        raise TypeError(f"{name} must be an object")
    document = cast(dict[str, object], value)
    if set(document) != expected:
        raise ValueError(f"{name} does not match the versioned schema")
    return document


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return cast(int, value)


def _wire_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return cast(list[object], value)


__all__ = [
    "PackageEpochFenceError",
    "PackageEpochFenceJournal",
    "PackageEpochFenceReadPort",
    "PackageEpochFenceRecordV1",
    "PackageEpochFenceReceiptV1",
    "PackageEpochFenceRequestV1",
    "PackageEpochLeaseSnapshotPort",
    "PackageEpochLeaseSnapshotV1",
    "PackageEpochRuntimeAdmissionFailureV1",
    "PackageEpochRuntimeAdmissionOwner",
    "PackageEpochRuntimeAdmissionReceiptV1",
    "PackageEpochRuntimeAdmissionRequestV1",
    "PackageEpochRuntimeAdmissionResultV1",
    "PackageEpochRuntimeLeaseV1",
]
