"""POSIX-native offline epoch cutover for PLC9B4c1.

The durable head of ``PackageEpochFenceJournal`` is the only current-root
pointer.  A fresh sibling namespace is prepared and identity-pinned first;
publishing the adjacent fence is the single atomic visibility edge.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceError,
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_EPOCH_CUTOVER_QUIESCENCE_RECEIPT_VERSION = 1
PACKAGE_EPOCH_CUTOVER_SNAPSHOT_RECEIPT_VERSION = 1
PACKAGE_POSIX_EPOCH_CUTOVER_REQUEST_VERSION = 1
PACKAGE_POSIX_EPOCH_ROOT_SWITCH_RECEIPT_VERSION = 1
PACKAGE_POSIX_EPOCH_CUTOVER_FAILURE_VERSION = 1
PACKAGE_POSIX_EPOCH_CUTOVER_RESULT_VERSION = 1

PackagePosixEpochCutoverDisposition = Literal["fenced", "rejected"]
PackagePosixEpochCutoverCode = Literal[
    "ok",
    "package_runtime_epoch_unsupported",
]
PackagePosixEpochCutoverBarrier = Literal["pre_fence"]
PackageEpochCutoverOperatorAction = Literal["upgrade_runtime"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,255}\Z")
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ROOT_SWITCH_AUTHORITY = "package_epoch_journal_v1"

_NativeIdentity = tuple[int, int]


class PackagePosixEpochCutoverError(RuntimeError):
    """Fail-closed native cutover refusal with one stable code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageEpochCutoverQuiescenceReceiptV1:
    """Complete lease/registration projection held under one exclusive lock."""

    receipt_id: str
    store_id: str
    owner_revision: int
    active_runtime_lease_ids: tuple[str, ...]
    active_pre_fence_registration_ids: tuple[str, ...]
    receipt_version: int = PACKAGE_EPOCH_CUTOVER_QUIESCENCE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="Package quiescence receipt identity")
        _require_safe_id(self.store_id, name="Package store identity")
        _require_positive(self.owner_revision, name="Package coordination revision")
        _require_ordered_sha256_values(
            self.active_runtime_lease_ids,
            name="active Package runtime leases",
        )
        _require_ordered_sha256_values(
            self.active_pre_fence_registration_ids,
            name="active pre-fence registrations",
        )
        if set(self.active_runtime_lease_ids) & set(
            self.active_pre_fence_registration_ids
        ):
            raise ValueError("Package quiescence evidence roles overlap")
        if (
            self.receipt_version
            != PACKAGE_EPOCH_CUTOVER_QUIESCENCE_RECEIPT_VERSION
        ):
            raise ValueError("Unsupported Package epoch quiescence receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch quiescence receipt does not match")

    @classmethod
    def create(
        cls,
        *,
        store_id: str,
        owner_revision: int,
        active_runtime_lease_ids: tuple[str, ...],
        active_pre_fence_registration_ids: tuple[str, ...],
    ) -> PackageEpochCutoverQuiescenceReceiptV1:
        runtime_ids = tuple(sorted(active_runtime_lease_ids))
        pre_fence_ids = tuple(sorted(active_pre_fence_registration_ids))
        values = _quiescence_identity(
            store_id=store_id,
            owner_revision=owner_revision,
            active_runtime_lease_ids=runtime_ids,
            active_pre_fence_registration_ids=pre_fence_ids,
            receipt_version=PACKAGE_EPOCH_CUTOVER_QUIESCENCE_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            store_id=store_id,
            owner_revision=owner_revision,
            active_runtime_lease_ids=runtime_ids,
            active_pre_fence_registration_ids=pre_fence_ids,
        )

    @property
    def is_quiescent(self) -> bool:
        return not self.active_runtime_lease_ids and not (
            self.active_pre_fence_registration_ids
        )

    @property
    def first_active_evidence(self) -> str:
        values = tuple(
            sorted(
                self.active_runtime_lease_ids
                + self.active_pre_fence_registration_ids
            )
        )
        if not values:
            raise ValueError("Quiescent receipt has no active evidence")
        return values[0]

    def _identity_dict(self) -> dict[str, object]:
        return _quiescence_identity(
            store_id=self.store_id,
            owner_revision=self.owner_revision,
            active_runtime_lease_ids=self.active_runtime_lease_ids,
            active_pre_fence_registration_ids=(
                self.active_pre_fence_registration_ids
            ),
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochCutoverQuiescenceReceiptV1:
        document = _wire_object(
            value,
            expected={
                "receiptId",
                "storeId",
                "ownerRevision",
                "activeRuntimeLeaseIds",
                "activePreFenceRegistrationIds",
                "receiptVersion",
            },
            name="Package epoch quiescence receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            owner_revision=_wire_int(
                document["ownerRevision"],
                name="owner revision",
            ),
            active_runtime_lease_ids=_wire_string_tuple(
                document["activeRuntimeLeaseIds"],
                name="active runtime lease ids",
            ),
            active_pre_fence_registration_ids=_wire_string_tuple(
                document["activePreFenceRegistrationIds"],
                name="active pre-fence registration ids",
            ),
            receipt_version=_wire_int(
                document["receiptVersion"],
                name="receipt version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageEpochCutoverSnapshotReceiptV1:
    """Opaque durable pre-cutover snapshot proof from the snapshot owner."""

    receipt_id: str
    store_id: str
    legacy_root_identity: str
    quiescence_receipt_id: str
    snapshot_id: str
    snapshot_revision: int
    entry_count: int
    byte_count: int
    receipt_version: int = PACKAGE_EPOCH_CUTOVER_SNAPSHOT_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.receipt_id, "Package snapshot receipt identity"),
            (self.legacy_root_identity, "legacy Package root identity"),
            (self.quiescence_receipt_id, "Package quiescence receipt identity"),
            (self.snapshot_id, "Package snapshot identity"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.store_id, name="Package store identity")
        _require_positive(self.snapshot_revision, name="Package snapshot revision")
        _require_non_negative(self.entry_count, name="Package snapshot entry count")
        _require_non_negative(self.byte_count, name="Package snapshot byte count")
        if self.receipt_version != PACKAGE_EPOCH_CUTOVER_SNAPSHOT_RECEIPT_VERSION:
            raise ValueError("Unsupported Package epoch snapshot receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package epoch snapshot receipt does not match")

    @classmethod
    def create(
        cls,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
        snapshot_id: str,
        snapshot_revision: int,
        entry_count: int,
        byte_count: int,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        values = _snapshot_identity(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_id=snapshot_id,
            snapshot_revision=snapshot_revision,
            entry_count=entry_count,
            byte_count=byte_count,
            receipt_version=PACKAGE_EPOCH_CUTOVER_SNAPSHOT_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_id=snapshot_id,
            snapshot_revision=snapshot_revision,
            entry_count=entry_count,
            byte_count=byte_count,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _snapshot_identity(
            store_id=self.store_id,
            legacy_root_identity=self.legacy_root_identity,
            quiescence_receipt_id=self.quiescence_receipt_id,
            snapshot_id=self.snapshot_id,
            snapshot_revision=self.snapshot_revision,
            entry_count=self.entry_count,
            byte_count=self.byte_count,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochCutoverSnapshotReceiptV1:
        document = _wire_object(
            value,
            expected={
                "receiptId",
                "storeId",
                "legacyRootIdentity",
                "quiescenceReceiptId",
                "snapshotId",
                "snapshotRevision",
                "entryCount",
                "byteCount",
                "receiptVersion",
            },
            name="Package epoch snapshot receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            legacy_root_identity=_wire_string(
                document["legacyRootIdentity"],
                name="legacy root identity",
            ),
            quiescence_receipt_id=_wire_string(
                document["quiescenceReceiptId"],
                name="quiescence receipt id",
            ),
            snapshot_id=_wire_string(document["snapshotId"], name="snapshot id"),
            snapshot_revision=_wire_int(
                document["snapshotRevision"],
                name="snapshot revision",
            ),
            entry_count=_wire_int(document["entryCount"], name="entry count"),
            byte_count=_wire_int(document["byteCount"], name="byte count"),
            receipt_version=_wire_int(
                document["receiptVersion"],
                name="receipt version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackagePosixEpochCutoverRequestV1:
    """Pathless command for one exact adjacent POSIX epoch transition."""

    request_id: str
    store_id: str
    prior_epoch: int
    prior_fence_id: str | None
    prior_fence_revision: int
    expected_legacy_root_identity: str
    namespace_id: str
    minimum_runtime_version: str
    minimum_runtime_protocol_epoch: int
    request_version: int = PACKAGE_POSIX_EPOCH_CUTOVER_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.request_id, name="Package cutover request identity")
        _require_safe_id(self.store_id, name="Package store identity")
        _require_non_negative(self.prior_epoch, name="prior Package epoch")
        _require_non_negative(
            self.prior_fence_revision,
            name="prior Package fence revision",
        )
        _require_sha256(
            self.expected_legacy_root_identity,
            name="expected legacy Package root identity",
        )
        _require_sha256(self.namespace_id, name="Package namespace identity")
        _require_safe_version(
            self.minimum_runtime_version,
            name="minimum Package runtime version",
        )
        _require_positive(
            self.minimum_runtime_protocol_epoch,
            name="minimum Package runtime protocol epoch",
        )
        if self.prior_epoch == 0:
            if self.prior_fence_id is not None or self.prior_fence_revision != 0:
                raise ValueError("Genesis Package cutover cannot name a prior fence")
        else:
            if self.prior_fence_id is None:
                raise ValueError("Successor Package cutover requires a prior fence")
            _require_sha256(self.prior_fence_id, name="prior Package fence identity")
            if self.prior_fence_revision < 1:
                raise ValueError("Successor Package cutover requires a revision")
        if self.request_version != PACKAGE_POSIX_EPOCH_CUTOVER_REQUEST_VERSION:
            raise ValueError("Unsupported POSIX Package epoch cutover request")
        if self.request_id != _fingerprint(self._identity_dict()):
            raise ValueError("POSIX Package epoch cutover request does not match")

    @classmethod
    def create(
        cls,
        *,
        store_id: str,
        prior_fence: PackageEpochFenceReceiptV1 | None,
        expected_legacy_root_identity: str,
        namespace_id: str,
        minimum_runtime_version: str,
        minimum_runtime_protocol_epoch: int,
    ) -> PackagePosixEpochCutoverRequestV1:
        if prior_fence is not None and not isinstance(
            prior_fence,
            PackageEpochFenceReceiptV1,
        ):
            raise TypeError("Prior Package epoch fence receipt is invalid")
        if prior_fence is not None and prior_fence.store_id != store_id:
            raise ValueError("Prior Package epoch fence store changed")
        prior_epoch = 0 if prior_fence is None else prior_fence.epoch
        prior_fence_id = None if prior_fence is None else prior_fence.fence_id
        prior_fence_revision = (
            0 if prior_fence is None else prior_fence.fence_revision
        )
        values = _cutover_request_identity(
            store_id=store_id,
            prior_epoch=prior_epoch,
            prior_fence_id=prior_fence_id,
            prior_fence_revision=prior_fence_revision,
            expected_legacy_root_identity=expected_legacy_root_identity,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            request_version=PACKAGE_POSIX_EPOCH_CUTOVER_REQUEST_VERSION,
        )
        return cls(
            request_id=_fingerprint(values),
            store_id=store_id,
            prior_epoch=prior_epoch,
            prior_fence_id=prior_fence_id,
            prior_fence_revision=prior_fence_revision,
            expected_legacy_root_identity=expected_legacy_root_identity,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
        )

    @property
    def next_epoch(self) -> int:
        return self.prior_epoch + 1

    def _identity_dict(self) -> dict[str, object]:
        return _cutover_request_identity(
            store_id=self.store_id,
            prior_epoch=self.prior_epoch,
            prior_fence_id=self.prior_fence_id,
            prior_fence_revision=self.prior_fence_revision,
            expected_legacy_root_identity=self.expected_legacy_root_identity,
            namespace_id=self.namespace_id,
            minimum_runtime_version=self.minimum_runtime_version,
            minimum_runtime_protocol_epoch=self.minimum_runtime_protocol_epoch,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"requestId": self.request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackagePosixEpochCutoverRequestV1:
        document = _wire_object(
            value,
            expected={
                "requestId",
                "storeId",
                "priorEpoch",
                "priorFenceId",
                "priorFenceRevision",
                "expectedLegacyRootIdentity",
                "namespaceId",
                "minimumRuntimeVersion",
                "minimumRuntimeProtocolEpoch",
                "requestVersion",
            },
            name="POSIX Package epoch cutover request",
        )
        return cls(
            request_id=_wire_string(document["requestId"], name="request id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            prior_epoch=_wire_int(document["priorEpoch"], name="prior epoch"),
            prior_fence_id=_wire_optional_string(
                document["priorFenceId"],
                name="prior fence id",
            ),
            prior_fence_revision=_wire_int(
                document["priorFenceRevision"],
                name="prior fence revision",
            ),
            expected_legacy_root_identity=_wire_string(
                document["expectedLegacyRootIdentity"],
                name="expected legacy root identity",
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
            request_version=_wire_int(
                document["requestVersion"],
                name="request version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackagePosixEpochRootSwitchReceiptV1:
    """Evidence that one namespace is selected by the epoch-journal edge."""

    switch_receipt_id: str
    request_id: str
    store_id: str
    prior_epoch: int
    next_epoch: int
    legacy_root_identity: str
    fenced_root_identity: str
    namespace_id: str
    quiescence_receipt_id: str
    snapshot_receipt_id: str
    switch_authority: str = _ROOT_SWITCH_AUTHORITY
    receipt_version: int = PACKAGE_POSIX_EPOCH_ROOT_SWITCH_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.switch_receipt_id, "Package root-switch receipt identity"),
            (self.request_id, "Package cutover request identity"),
            (self.legacy_root_identity, "legacy Package root identity"),
            (self.fenced_root_identity, "fenced Package root identity"),
            (self.namespace_id, "Package namespace identity"),
            (self.quiescence_receipt_id, "Package quiescence receipt identity"),
            (self.snapshot_receipt_id, "Package snapshot receipt identity"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.store_id, name="Package store identity")
        _require_non_negative(self.prior_epoch, name="prior Package epoch")
        _require_positive(self.next_epoch, name="next Package epoch")
        if self.next_epoch != self.prior_epoch + 1:
            raise ValueError("Package root switch must be adjacent")
        if self.legacy_root_identity == self.fenced_root_identity:
            raise ValueError("Package root switch requires a fresh identity")
        if self.switch_authority != _ROOT_SWITCH_AUTHORITY:
            raise ValueError("Unsupported Package root-switch authority")
        if self.receipt_version != PACKAGE_POSIX_EPOCH_ROOT_SWITCH_RECEIPT_VERSION:
            raise ValueError("Unsupported POSIX Package root-switch receipt")
        if self.switch_receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("POSIX Package root-switch receipt does not match")

    @classmethod
    def create(
        cls,
        request: PackagePosixEpochCutoverRequestV1,
        *,
        fenced_root_identity: str,
        quiescence_receipt_id: str,
        snapshot_receipt_id: str,
    ) -> PackagePosixEpochRootSwitchReceiptV1:
        if not isinstance(request, PackagePosixEpochCutoverRequestV1):
            raise TypeError("POSIX Package epoch cutover request is required")
        values = _root_switch_identity(
            request_id=request.request_id,
            store_id=request.store_id,
            prior_epoch=request.prior_epoch,
            next_epoch=request.next_epoch,
            legacy_root_identity=request.expected_legacy_root_identity,
            fenced_root_identity=fenced_root_identity,
            namespace_id=request.namespace_id,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_receipt_id=snapshot_receipt_id,
            switch_authority=_ROOT_SWITCH_AUTHORITY,
            receipt_version=PACKAGE_POSIX_EPOCH_ROOT_SWITCH_RECEIPT_VERSION,
        )
        return cls(
            switch_receipt_id=_fingerprint(values),
            request_id=request.request_id,
            store_id=request.store_id,
            prior_epoch=request.prior_epoch,
            next_epoch=request.next_epoch,
            legacy_root_identity=request.expected_legacy_root_identity,
            fenced_root_identity=fenced_root_identity,
            namespace_id=request.namespace_id,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_receipt_id=snapshot_receipt_id,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _root_switch_identity(
            request_id=self.request_id,
            store_id=self.store_id,
            prior_epoch=self.prior_epoch,
            next_epoch=self.next_epoch,
            legacy_root_identity=self.legacy_root_identity,
            fenced_root_identity=self.fenced_root_identity,
            namespace_id=self.namespace_id,
            quiescence_receipt_id=self.quiescence_receipt_id,
            snapshot_receipt_id=self.snapshot_receipt_id,
            switch_authority=self.switch_authority,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"switchReceiptId": self.switch_receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackagePosixEpochRootSwitchReceiptV1:
        document = _wire_object(
            value,
            expected={
                "switchReceiptId",
                "requestId",
                "storeId",
                "priorEpoch",
                "nextEpoch",
                "legacyRootIdentity",
                "fencedRootIdentity",
                "namespaceId",
                "quiescenceReceiptId",
                "snapshotReceiptId",
                "switchAuthority",
                "receiptVersion",
            },
            name="POSIX Package root-switch receipt",
        )
        return cls(
            switch_receipt_id=_wire_string(
                document["switchReceiptId"],
                name="switch receipt id",
            ),
            request_id=_wire_string(document["requestId"], name="request id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            prior_epoch=_wire_int(document["priorEpoch"], name="prior epoch"),
            next_epoch=_wire_int(document["nextEpoch"], name="next epoch"),
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
            quiescence_receipt_id=_wire_string(
                document["quiescenceReceiptId"],
                name="quiescence receipt id",
            ),
            snapshot_receipt_id=_wire_string(
                document["snapshotReceiptId"],
                name="snapshot receipt id",
            ),
            switch_authority=_wire_string(
                document["switchAuthority"],
                name="switch authority",
            ),
            receipt_version=_wire_int(
                document["receiptVersion"],
                name="receipt version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackagePosixEpochCutoverFailureV1:
    failure_id: str
    request_id: str
    evidence_ref: str
    barrier: PackagePosixEpochCutoverBarrier
    code: Literal["package_runtime_epoch_unsupported"]
    operator_action: PackageEpochCutoverOperatorAction
    failure_version: int = PACKAGE_POSIX_EPOCH_CUTOVER_FAILURE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.failure_id, "Package cutover failure identity"),
            (self.request_id, "Package cutover request identity"),
            (self.evidence_ref, "Package cutover failure evidence"),
        ):
            _require_sha256(value, name=name)
        if self.barrier != "pre_fence":
            raise ValueError("Unsupported Package cutover failure barrier")
        if self.code != "package_runtime_epoch_unsupported":
            raise ValueError("Unsupported Package cutover failure code")
        if self.operator_action != "upgrade_runtime":
            raise ValueError("Unsupported Package cutover operator action")
        if self.failure_version != PACKAGE_POSIX_EPOCH_CUTOVER_FAILURE_VERSION:
            raise ValueError("Unsupported POSIX Package cutover failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("POSIX Package cutover failure does not match")

    @classmethod
    def pre_fence(
        cls,
        request: PackagePosixEpochCutoverRequestV1,
        *,
        evidence_ref: str,
    ) -> PackagePosixEpochCutoverFailureV1:
        values = _cutover_failure_identity(
            request_id=request.request_id,
            evidence_ref=evidence_ref,
            barrier="pre_fence",
            code="package_runtime_epoch_unsupported",
            operator_action="upgrade_runtime",
            failure_version=PACKAGE_POSIX_EPOCH_CUTOVER_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            request_id=request.request_id,
            evidence_ref=evidence_ref,
            barrier="pre_fence",
            code="package_runtime_epoch_unsupported",
            operator_action="upgrade_runtime",
        )

    def _identity_dict(self) -> dict[str, object]:
        return _cutover_failure_identity(
            request_id=self.request_id,
            evidence_ref=self.evidence_ref,
            barrier=self.barrier,
            code=self.code,
            operator_action=self.operator_action,
            failure_version=self.failure_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackagePosixEpochCutoverFailureV1:
        document = _wire_object(
            value,
            expected={
                "failureId",
                "requestId",
                "evidenceRef",
                "barrier",
                "code",
                "operatorAction",
                "failureVersion",
            },
            name="POSIX Package epoch cutover failure",
        )
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            request_id=_wire_string(document["requestId"], name="request id"),
            evidence_ref=_wire_string(
                document["evidenceRef"],
                name="evidence ref",
            ),
            barrier=cast(
                PackagePosixEpochCutoverBarrier,
                _wire_string(document["barrier"], name="barrier"),
            ),
            code=cast(
                Literal["package_runtime_epoch_unsupported"],
                _wire_string(document["code"], name="code"),
            ),
            operator_action=cast(
                PackageEpochCutoverOperatorAction,
                _wire_string(document["operatorAction"], name="operator action"),
            ),
            failure_version=_wire_int(
                document["failureVersion"],
                name="failure version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackagePosixEpochCutoverResultV1:
    request_id: str
    disposition: PackagePosixEpochCutoverDisposition
    code: PackagePosixEpochCutoverCode
    fence: PackageEpochFenceReceiptV1 | None
    switch_receipt: PackagePosixEpochRootSwitchReceiptV1 | None
    failure: PackagePosixEpochCutoverFailureV1 | None
    result_version: int = PACKAGE_POSIX_EPOCH_CUTOVER_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.request_id, name="Package cutover request identity")
        if self.disposition == "fenced":
            if (
                self.code != "ok"
                or self.fence is None
                or self.switch_receipt is None
                or self.failure is not None
            ):
                raise ValueError("Fenced Package cutover result is inconsistent")
            if (
                self.switch_receipt.request_id != self.request_id
                or self.fence.request.root_switch_receipt_id
                != self.switch_receipt.switch_receipt_id
            ):
                raise ValueError("Fenced Package cutover evidence changed")
        elif self.disposition == "rejected":
            if (
                self.code != "package_runtime_epoch_unsupported"
                or self.fence is not None
                or self.switch_receipt is not None
                or self.failure is None
                or self.failure.request_id != self.request_id
            ):
                raise ValueError("Rejected Package cutover result is inconsistent")
        else:
            raise ValueError("Unsupported Package cutover disposition")
        if self.result_version != PACKAGE_POSIX_EPOCH_CUTOVER_RESULT_VERSION:
            raise ValueError("Unsupported POSIX Package cutover result")

    @classmethod
    def fenced(
        cls,
        request: PackagePosixEpochCutoverRequestV1,
        *,
        fence: PackageEpochFenceReceiptV1,
        switch_receipt: PackagePosixEpochRootSwitchReceiptV1,
    ) -> PackagePosixEpochCutoverResultV1:
        return cls(
            request_id=request.request_id,
            disposition="fenced",
            code="ok",
            fence=fence,
            switch_receipt=switch_receipt,
            failure=None,
        )

    @classmethod
    def rejected(
        cls,
        request: PackagePosixEpochCutoverRequestV1,
        *,
        evidence_ref: str,
    ) -> PackagePosixEpochCutoverResultV1:
        return cls(
            request_id=request.request_id,
            disposition="rejected",
            code="package_runtime_epoch_unsupported",
            fence=None,
            switch_receipt=None,
            failure=PackagePosixEpochCutoverFailureV1.pre_fence(
                request,
                evidence_ref=evidence_ref,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "requestId": self.request_id,
            "disposition": self.disposition,
            "code": self.code,
            "fence": None if self.fence is None else self.fence.to_dict(),
            "switchReceipt": (
                None if self.switch_receipt is None else self.switch_receipt.to_dict()
            ),
            "failure": None if self.failure is None else self.failure.to_dict(),
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackagePosixEpochCutoverResultV1:
        document = _wire_object(
            value,
            expected={
                "requestId",
                "disposition",
                "code",
                "fence",
                "switchReceipt",
                "failure",
                "resultVersion",
            },
            name="POSIX Package epoch cutover result",
        )
        fence_value = document["fence"]
        switch_value = document["switchReceipt"]
        failure_value = document["failure"]
        return cls(
            request_id=_wire_string(document["requestId"], name="request id"),
            disposition=cast(
                PackagePosixEpochCutoverDisposition,
                _wire_string(document["disposition"], name="disposition"),
            ),
            code=cast(
                PackagePosixEpochCutoverCode,
                _wire_string(document["code"], name="code"),
            ),
            fence=(
                None
                if fence_value is None
                else PackageEpochFenceReceiptV1.from_dict(fence_value)
            ),
            switch_receipt=(
                None
                if switch_value is None
                else PackagePosixEpochRootSwitchReceiptV1.from_dict(switch_value)
            ),
            failure=(
                None
                if failure_value is None
                else PackagePosixEpochCutoverFailureV1.from_dict(failure_value)
            ),
            result_version=_wire_int(
                document["resultVersion"],
                name="result version",
            ),
        )


class PackageEpochCutoverCoordinationPort(Protocol):
    def exclusive_quiescence(
        self,
        *,
        store_id: str,
    ) -> AbstractContextManager[PackageEpochCutoverQuiescenceReceiptV1]: ...


class PackageEpochCutoverSnapshotPort(Protocol):
    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1: ...


class PackagePosixEpochCutoverOwner:
    """Configured POSIX capability owner; public records remain pathless."""

    def __init__(
        self,
        authority_root: str | Path,
        *,
        store_id: str,
        epoch_journal: PackageEpochFenceJournal,
        coordination: PackageEpochCutoverCoordinationPort,
        snapshots: PackageEpochCutoverSnapshotPort,
        legacy_root_name: str = "legacy",
        epochs_root_name: str = "epochs",
        before_fence_probe=None,
    ) -> None:
        if os.name != "posix" or not _supports_posix_rooted_io():
            raise PackagePosixEpochCutoverError(
                "POSIX Package epoch cutover is unavailable",
                code="package_epoch_cutover_unavailable",
            )
        if not isinstance(authority_root, (str, Path)):
            raise TypeError("Package epoch authority root must be a filesystem path")
        raw_root = Path(authority_root)
        if (
            not raw_root.is_absolute()
            or ".." in raw_root.parts
            or raw_root == Path(raw_root.anchor)
        ):
            raise PackagePosixEpochCutoverError(
                "Package epoch authority root must be absolute and normalized",
                code="package_epoch_cutover_identity_changed",
            )
        _require_safe_id(store_id, name="Package store identity")
        _require_component(legacy_root_name, name="legacy Package root name")
        _require_component(epochs_root_name, name="Package epochs root name")
        if legacy_root_name == epochs_root_name:
            raise ValueError("Legacy and epoch Package roots must be distinct")
        if not isinstance(epoch_journal, PackageEpochFenceJournal):
            raise TypeError("Package epoch fence journal is required")
        if not callable(getattr(coordination, "exclusive_quiescence", None)):
            raise TypeError("Package epoch coordination owner is required")
        if not callable(getattr(snapshots, "capture", None)):
            raise TypeError("Package epoch snapshot owner is required")
        if before_fence_probe is not None and not callable(before_fence_probe):
            raise TypeError("Package epoch pre-fence probe must be callable")
        self._root = raw_root
        self._store_id = store_id
        self._journal = epoch_journal
        self._coordination = coordination
        self._snapshots = snapshots
        self._legacy_name = legacy_root_name
        self._epochs_name = epochs_root_name
        self._before_fence_probe = before_fence_probe
        pinned = _PinnedPosixAuthority.open(self._root)
        try:
            legacy_fd = pinned.open_authority_child(self._legacy_name)
            epochs_fd = pinned.open_authority_child(self._epochs_name)
            try:
                self._authority_identities = pinned.identities
                self._legacy_genesis_identity = _directory_identity(legacy_fd)
                self._epochs_identity = _directory_native_identity(epochs_fd)
            finally:
                os.close(epochs_fd)
                os.close(legacy_fd)
        except Exception as exc:
            raise _native_error(exc) from exc
        finally:
            pinned.close()

    def current_root_identity(self) -> str:
        current = self._journal.current(self._store_id)
        pinned = self._open_pinned()
        root_fd: int | None = None
        epochs_fd: int | None = None
        try:
            epochs_fd = pinned.open_authority_child(
                self._epochs_name,
                expected_identity=self._epochs_identity,
            )
            if current is None:
                root_fd = pinned.open_authority_child(self._legacy_name)
                observed = _directory_identity(root_fd)
                if observed != self._legacy_genesis_identity:
                    raise _identity_changed()
                return observed
            root_fd = _open_directory_at(epochs_fd, current.request.namespace_id)
            observed = _directory_identity(root_fd)
            if observed != current.fenced_root_identity:
                raise _identity_changed()
            return observed
        except PackagePosixEpochCutoverError:
            raise
        except Exception as exc:
            raise _native_error(exc) from exc
        finally:
            if root_fd is not None:
                os.close(root_fd)
            if epochs_fd is not None:
                os.close(epochs_fd)
            pinned.close()

    def cutover(
        self,
        request: PackagePosixEpochCutoverRequestV1,
    ) -> PackagePosixEpochCutoverResultV1:
        if not isinstance(request, PackagePosixEpochCutoverRequestV1):
            raise TypeError("POSIX Package epoch cutover request is required")
        if request.store_id != self._store_id:
            raise PackagePosixEpochCutoverError(
                "Package epoch cutover store changed",
                code="package_epoch_fence_stale",
            )
        current = self._journal.current(self._store_id)
        replay = self._exact_replay(request, current)
        if replay is not None:
            return replay
        self._validate_prior(request, current)
        try:
            exclusive = self._coordination.exclusive_quiescence(
                store_id=self._store_id
            )
            with exclusive as quiescence:
                locked_current = self._journal.current(self._store_id)
                replay = self._exact_replay(request, locked_current)
                if replay is not None:
                    return replay
                self._validate_prior(request, locked_current)
                return self._cutover_exclusive(
                    request,
                    locked_current,
                    quiescence,
                )
        except PackagePosixEpochCutoverError:
            raise
        except PackageEpochFenceError as exc:
            raise PackagePosixEpochCutoverError(
                "Package epoch fence compare-and-swap failed",
                code=exc.code,
            ) from exc
        except Exception as exc:
            raise _native_error(exc) from exc

    def _cutover_exclusive(
        self,
        request: PackagePosixEpochCutoverRequestV1,
        current: PackageEpochFenceReceiptV1 | None,
        quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    ) -> PackagePosixEpochCutoverResultV1:
        if not isinstance(quiescence, PackageEpochCutoverQuiescenceReceiptV1):
            raise PackagePosixEpochCutoverError(
                "Package quiescence evidence is invalid",
                code="package_epoch_cutover_quiescence_unavailable",
            )
        if quiescence.store_id != self._store_id:
            raise PackagePosixEpochCutoverError(
                "Package quiescence store changed",
                code="package_epoch_cutover_quiescence_unavailable",
            )
        if not quiescence.is_quiescent:
            return PackagePosixEpochCutoverResultV1.rejected(
                request,
                evidence_ref=quiescence.first_active_evidence,
            )
        if self._journal.current(self._store_id) != current:
            raise PackagePosixEpochCutoverError(
                "Package epoch changed before native cutover",
                code="package_epoch_fence_stale",
            )

        pinned = self._open_pinned()
        epochs_fd: int | None = None
        legacy_fd: int | None = None
        new_fd: int | None = None
        new_identity: str | None = None
        created = False
        fenced = False
        try:
            epochs_fd = pinned.open_authority_child(
                self._epochs_name,
                expected_identity=self._epochs_identity,
            )
            if current is None:
                legacy_fd = pinned.open_authority_child(self._legacy_name)
            else:
                legacy_fd = _open_directory_at(
                    epochs_fd,
                    current.request.namespace_id,
                )
            observed_legacy = _directory_identity(legacy_fd)
            if observed_legacy != request.expected_legacy_root_identity:
                raise _identity_changed()
            snapshot = self._snapshots.capture(
                store_id=self._store_id,
                legacy_root_identity=observed_legacy,
                quiescence_receipt_id=quiescence.receipt_id,
            )
            _validate_snapshot(snapshot, request, quiescence)
            try:
                os.mkdir(request.namespace_id, mode=0o700, dir_fd=epochs_fd)
                created = True
            except FileExistsError as exc:
                raise PackagePosixEpochCutoverError(
                    "Package epoch namespace already exists",
                    code="package_epoch_cutover_namespace_conflict",
                ) from exc
            new_fd = _open_directory_at(epochs_fd, request.namespace_id)
            new_identity = _directory_identity(new_fd)
            if new_identity == observed_legacy:
                raise _identity_changed()
            os.fsync(new_fd)
            os.fsync(epochs_fd)
            switch = PackagePosixEpochRootSwitchReceiptV1.create(
                request,
                fenced_root_identity=new_identity,
                quiescence_receipt_id=quiescence.receipt_id,
                snapshot_receipt_id=snapshot.receipt_id,
            )
            epoch_request = PackageEpochFenceRequestV1.create(
                store_id=self._store_id,
                prior_fence=current,
                legacy_root_identity=observed_legacy,
                fenced_root_identity=new_identity,
                namespace_id=request.namespace_id,
                minimum_runtime_version=request.minimum_runtime_version,
                minimum_runtime_protocol_epoch=(
                    request.minimum_runtime_protocol_epoch
                ),
                quiescence_receipt_id=quiescence.receipt_id,
                snapshot_receipt_id=snapshot.receipt_id,
                root_switch_receipt_id=switch.switch_receipt_id,
            )
            if self._before_fence_probe is not None:
                self._before_fence_probe()
            pinned.assert_visible()
            if _directory_identity(legacy_fd) != observed_legacy:
                raise _identity_changed()
            if _directory_identity(new_fd) != new_identity:
                raise _identity_changed()
            if os.listdir(new_fd):
                raise PackagePosixEpochCutoverError(
                    "Fresh Package epoch namespace is not empty",
                    code="package_epoch_cutover_namespace_conflict",
                )
            visible_epochs = pinned.open_authority_child(
                self._epochs_name,
                expected_identity=self._epochs_identity,
            )
            try:
                visible_new = _open_directory_at(
                    visible_epochs,
                    request.namespace_id,
                )
                try:
                    if _directory_identity(visible_new) != new_identity:
                        raise _identity_changed()
                finally:
                    os.close(visible_new)
            finally:
                os.close(visible_epochs)
            if self._journal.current(self._store_id) != current:
                raise PackagePosixEpochCutoverError(
                    "Package epoch changed before fence publication",
                    code="package_epoch_fence_stale",
                )
            fence = self._journal.publish(epoch_request)
            fenced = True
            if fence.request != epoch_request:
                raise PackagePosixEpochCutoverError(
                    "Package epoch fence publication changed",
                    code="package_epoch_fence_stale",
                )
            return PackagePosixEpochCutoverResultV1.fenced(
                request,
                fence=fence,
                switch_receipt=switch,
            )
        except Exception:
            if created and not fenced and epochs_fd is not None and new_identity:
                _remove_created_epoch(
                    epochs_fd,
                    request.namespace_id,
                    expected_identity=new_identity,
                )
            raise
        finally:
            if new_fd is not None:
                os.close(new_fd)
            if legacy_fd is not None:
                os.close(legacy_fd)
            if epochs_fd is not None:
                os.close(epochs_fd)
            pinned.close()

    def _exact_replay(
        self,
        request: PackagePosixEpochCutoverRequestV1,
        current: PackageEpochFenceReceiptV1 | None,
    ) -> PackagePosixEpochCutoverResultV1 | None:
        if current is None or current.epoch != request.next_epoch:
            return None
        epoch_request = current.request
        if (
            epoch_request.store_id != request.store_id
            or epoch_request.prior_epoch != request.prior_epoch
            or epoch_request.prior_fence_id != request.prior_fence_id
            or epoch_request.prior_fence_revision != request.prior_fence_revision
            or epoch_request.legacy_root_identity
            != request.expected_legacy_root_identity
            or epoch_request.namespace_id != request.namespace_id
            or epoch_request.minimum_runtime_version
            != request.minimum_runtime_version
            or epoch_request.minimum_runtime_protocol_epoch
            != request.minimum_runtime_protocol_epoch
        ):
            return None
        if self.current_root_identity() != epoch_request.fenced_root_identity:
            raise _identity_changed()
        switch = PackagePosixEpochRootSwitchReceiptV1.create(
            request,
            fenced_root_identity=epoch_request.fenced_root_identity,
            quiescence_receipt_id=epoch_request.quiescence_receipt_id,
            snapshot_receipt_id=epoch_request.snapshot_receipt_id,
        )
        if switch.switch_receipt_id != epoch_request.root_switch_receipt_id:
            raise _identity_changed()
        if self._journal.current(self._store_id) != current:
            raise PackagePosixEpochCutoverError(
                "Package epoch changed during exact replay",
                code="package_epoch_fence_stale",
            )
        return PackagePosixEpochCutoverResultV1.fenced(
            request,
            fence=current,
            switch_receipt=switch,
        )

    def _validate_prior(
        self,
        request: PackagePosixEpochCutoverRequestV1,
        current: PackageEpochFenceReceiptV1 | None,
    ) -> None:
        if current is None:
            valid = (
                request.prior_epoch == 0
                and request.prior_fence_id is None
                and request.prior_fence_revision == 0
            )
        else:
            valid = (
                request.prior_epoch == current.epoch
                and request.prior_fence_id == current.fence_id
                and request.prior_fence_revision == current.fence_revision
                and request.expected_legacy_root_identity
                == current.fenced_root_identity
            )
        if not valid:
            raise PackagePosixEpochCutoverError(
                "Package epoch cutover compare-and-swap failed",
                code="package_epoch_fence_stale",
            )

    def _open_pinned(self) -> _PinnedPosixAuthority:
        try:
            return _PinnedPosixAuthority.open(
                self._root,
                expected_identities=self._authority_identities,
            )
        except Exception as exc:
            raise _native_error(exc) from exc


class _PinnedPosixAuthority:
    def __init__(
        self,
        root: Path,
        descriptors: tuple[int, ...],
        identities: tuple[_NativeIdentity, ...],
    ) -> None:
        self._root = root
        self._descriptors = descriptors
        self.identities = identities

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        expected_identities: tuple[_NativeIdentity, ...] | None = None,
    ) -> _PinnedPosixAuthority:
        descriptors = _open_ancestor_chain(root)
        try:
            identities = tuple(
                _directory_native_identity(descriptor)
                for descriptor in descriptors
            )
            if expected_identities is not None and identities != expected_identities:
                raise _identity_changed()
            _require_private_directory(descriptors[-1])
            return cls(root, descriptors, identities)
        except Exception:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            raise

    @property
    def descriptor(self) -> int:
        return self._descriptors[-1]

    def open_authority_child(
        self,
        name: str,
        *,
        expected_identity: _NativeIdentity | None = None,
    ) -> int:
        descriptor = _open_directory_at(self.descriptor, name)
        if (
            expected_identity is not None
            and _directory_native_identity(descriptor) != expected_identity
        ):
            os.close(descriptor)
            raise _identity_changed()
        return descriptor

    def assert_visible(self) -> None:
        for descriptor, expected in zip(
            self._descriptors,
            self.identities,
            strict=True,
        ):
            if _directory_native_identity(descriptor) != expected:
                raise _identity_changed()
        _require_private_directory(self.descriptor)
        visible = _open_ancestor_chain(self._root)
        try:
            observed = tuple(_directory_native_identity(fd) for fd in visible)
            if observed != self.identities:
                raise _identity_changed()
        finally:
            for descriptor in reversed(visible):
                os.close(descriptor)

    def close(self) -> None:
        while self._descriptors:
            descriptor, self._descriptors = (
                self._descriptors[-1],
                self._descriptors[:-1],
            )
            os.close(descriptor)


def _open_ancestor_chain(root: Path) -> tuple[int, ...]:
    descriptors: list[int] = []
    try:
        current = os.open(root.anchor, _directory_open_flags())
        descriptors.append(current)
        for component in root.parts[1:]:
            current = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current,
            )
            descriptors.append(current)
        return tuple(descriptors)
    except Exception:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _open_directory_at(parent_fd: int, name: str) -> int:
    _require_component(name, name="Package namespace component")
    descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    try:
        _require_private_directory(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _remove_created_epoch(
    epochs_fd: int,
    namespace_id: str,
    *,
    expected_identity: str,
) -> None:
    descriptor: int | None = None
    try:
        descriptor = _open_directory_at(epochs_fd, namespace_id)
        if _directory_identity(descriptor) != expected_identity:
            raise _identity_changed()
        os.close(descriptor)
        descriptor = None
        os.rmdir(namespace_id, dir_fd=epochs_fd)
        os.fsync(epochs_fd)
    except Exception as exc:
        raise PackagePosixEpochCutoverError(
            "Unfenced Package epoch residue cannot be removed safely",
            code="package_epoch_cutover_cleanup_failed",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_snapshot(
    snapshot: object,
    request: PackagePosixEpochCutoverRequestV1,
    quiescence: PackageEpochCutoverQuiescenceReceiptV1,
) -> None:
    if not isinstance(snapshot, PackageEpochCutoverSnapshotReceiptV1) or (
        snapshot.store_id != request.store_id
        or snapshot.legacy_root_identity
        != request.expected_legacy_root_identity
        or snapshot.quiescence_receipt_id != quiescence.receipt_id
    ):
        raise PackagePosixEpochCutoverError(
            "Package epoch snapshot evidence is invalid",
            code="package_epoch_cutover_snapshot_unavailable",
        )


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _directory_native_identity(descriptor: int) -> _NativeIdentity:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise _identity_changed()
    return (metadata.st_dev, metadata.st_ino)


def _directory_identity(descriptor: int) -> str:
    device, inode = _directory_native_identity(descriptor)
    return _fingerprint(
        {
            "device": device,
            "fileType": "directory",
            "inode": inode,
            "identityVersion": 1,
        }
    )


def _require_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise _identity_changed()


def _supports_posix_rooted_io() -> bool:
    return bool(
        os.open in os.supports_dir_fd
        and os.listdir in os.supports_fd
        and os.mkdir in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )


def _identity_changed() -> PackagePosixEpochCutoverError:
    return PackagePosixEpochCutoverError(
        "POSIX Package epoch root identity changed",
        code="package_epoch_cutover_identity_changed",
    )


def _native_error(exc: BaseException) -> PackagePosixEpochCutoverError:
    if isinstance(exc, PackagePosixEpochCutoverError):
        return exc
    code = (
        "package_epoch_cutover_identity_changed"
        if isinstance(exc, OSError)
        and exc.errno
        in {
            errno.ELOOP,
            errno.ENOTDIR,
            errno.ENOENT,
            errno.EXDEV,
        }
        else "package_epoch_cutover_unavailable"
    )
    return PackagePosixEpochCutoverError(
        "POSIX Package epoch cutover failed closed",
        code=code,
    )


def _quiescence_identity(
    *,
    store_id: str,
    owner_revision: int,
    active_runtime_lease_ids: tuple[str, ...],
    active_pre_fence_registration_ids: tuple[str, ...],
    receipt_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "ownerRevision": owner_revision,
        "activeRuntimeLeaseIds": list(active_runtime_lease_ids),
        "activePreFenceRegistrationIds": list(
            active_pre_fence_registration_ids
        ),
        "receiptVersion": receipt_version,
    }


def _snapshot_identity(
    *,
    store_id: str,
    legacy_root_identity: str,
    quiescence_receipt_id: str,
    snapshot_id: str,
    snapshot_revision: int,
    entry_count: int,
    byte_count: int,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "legacyRootIdentity": legacy_root_identity,
        "quiescenceReceiptId": quiescence_receipt_id,
        "snapshotId": snapshot_id,
        "snapshotRevision": snapshot_revision,
        "entryCount": entry_count,
        "byteCount": byte_count,
        "receiptVersion": receipt_version,
    }


def _cutover_request_identity(
    *,
    store_id: str,
    prior_epoch: int,
    prior_fence_id: str | None,
    prior_fence_revision: int,
    expected_legacy_root_identity: str,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
    request_version: int,
) -> dict[str, object]:
    return {
        "storeId": store_id,
        "priorEpoch": prior_epoch,
        "priorFenceId": prior_fence_id,
        "priorFenceRevision": prior_fence_revision,
        "expectedLegacyRootIdentity": expected_legacy_root_identity,
        "namespaceId": namespace_id,
        "minimumRuntimeVersion": minimum_runtime_version,
        "minimumRuntimeProtocolEpoch": minimum_runtime_protocol_epoch,
        "requestVersion": request_version,
    }


def _root_switch_identity(
    *,
    request_id: str,
    store_id: str,
    prior_epoch: int,
    next_epoch: int,
    legacy_root_identity: str,
    fenced_root_identity: str,
    namespace_id: str,
    quiescence_receipt_id: str,
    snapshot_receipt_id: str,
    switch_authority: str,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "requestId": request_id,
        "storeId": store_id,
        "priorEpoch": prior_epoch,
        "nextEpoch": next_epoch,
        "legacyRootIdentity": legacy_root_identity,
        "fencedRootIdentity": fenced_root_identity,
        "namespaceId": namespace_id,
        "quiescenceReceiptId": quiescence_receipt_id,
        "snapshotReceiptId": snapshot_receipt_id,
        "switchAuthority": switch_authority,
        "receiptVersion": receipt_version,
    }


def _cutover_failure_identity(
    *,
    request_id: str,
    evidence_ref: str,
    barrier: str,
    code: str,
    operator_action: str,
    failure_version: int,
) -> dict[str, object]:
    return {
        "requestId": request_id,
        "evidenceRef": evidence_ref,
        "barrier": barrier,
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


def _require_component(value: str, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or _SAFE_COMPONENT.fullmatch(value) is None
        or value in {".", ".."}
    ):
        raise ValueError(f"{name} is invalid")


def _require_ordered_sha256_values(
    values: tuple[str, ...],
    *,
    name: str,
) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} must be uniquely ordered")
    for value in values:
        _require_sha256(value, name=name)


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


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{name} must be an array of strings")
    return tuple(cast(list[str], value))


__all__ = [
    "PackageEpochCutoverCoordinationPort",
    "PackageEpochCutoverQuiescenceReceiptV1",
    "PackageEpochCutoverSnapshotPort",
    "PackageEpochCutoverSnapshotReceiptV1",
    "PackagePosixEpochCutoverError",
    "PackagePosixEpochCutoverFailureV1",
    "PackagePosixEpochCutoverOwner",
    "PackagePosixEpochCutoverRequestV1",
    "PackagePosixEpochCutoverResultV1",
    "PackagePosixEpochRootSwitchReceiptV1",
]
