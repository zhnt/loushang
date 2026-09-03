"""Dark PLC9B4b retention handoff records, journal, and coordinator."""

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
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitAdmissionPort,
    PackageCommitAdmissionReceiptV1,
    PackageCommitAdmissionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinReceiptV1,
)

PACKAGE_DESIRED_STATE_COMMIT_REQUEST_VERSION = 1
PACKAGE_DESIRED_STATE_COMMIT_RECEIPT_VERSION = 1
PACKAGE_DESIRED_STATE_COMMIT_FAILURE_VERSION = 1
PACKAGE_DESIRED_STATE_COMMIT_RESULT_VERSION = 1
PACKAGE_RETENTION_HANDOFF_REQUEST_VERSION = 1
PACKAGE_DEPENDENCY_PIN_REQUEST_VERSION = 1
PACKAGE_DEPENDENCY_PIN_RECEIPT_VERSION = 1
PACKAGE_RETENTION_HANDOFF_RECEIPT_VERSION = 1
PACKAGE_RETENTION_HANDOFF_FAILURE_VERSION = 1
PACKAGE_RETENTION_HANDOFF_RESULT_VERSION = 1
PACKAGE_RETENTION_HANDOFF_RECORD_VERSION = 1

PackageDesiredStateCommitDisposition = Literal["committed", "rejected"]
PackageDependencyPinState = Literal["acquired", "aborted", "settled"]
PackageRetentionHandoffState = Literal[
    "opened",
    "dependency_pinned",
    "desired_committed",
    "settled",
    "aborted",
]
PackageRetentionHandoffFailurePhase = Literal[
    "none",
    "opened",
    "dependency_pinned",
    "desired_committed",
]
PackageRetentionHandoffCode = Literal[
    "ok",
    "package_retention_handoff_interrupted",
    "package_desired_revision_conflict",
    "package_retention_handoff_stale",
]
PackageRetentionHandoffDisposition = Literal[
    "settled",
    "retryable_failure",
    "rejected",
]
PackageRetentionHandoffRecordKind = Literal["handoff", "handoff_attempt"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class PackageRetentionHandoffError(RuntimeError):
    """Fail-closed journal or coordinator refusal with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageDesiredStateCommitRequestV1:
    """Opaque desired command identity bound to one admitted committed set."""

    desired_request_id: str
    command_id: str
    command_fingerprint: str
    expected_inventory_revision: int
    operation_id: str
    operation_fingerprint: str
    request_fingerprint: str
    attempt_epoch: int
    product_id: str
    scope_id: str
    installation_id: str
    plugin_id: str
    committed_set_id: str
    root_ref: PluginRevisionRefV1
    request_version: int = PACKAGE_DESIRED_STATE_COMMIT_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.desired_request_id, "desired commit request id"),
            (self.command_fingerprint, "desired command fingerprint"),
            (self.operation_fingerprint, "Package operation fingerprint"),
            (self.request_fingerprint, "Package request fingerprint"),
            (self.committed_set_id, "committed Package set id"),
        ):
            _require_sha256(value, name=name)
        for value, name in (
            (self.command_id, "desired command identity"),
            (self.operation_id, "Package operation identity"),
            (self.product_id, "Product identity"),
            (self.scope_id, "scope identity"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
        ):
            _require_safe_id(value, name=name)
        _require_nonnegative(
            self.expected_inventory_revision,
            name="expected desired inventory revision",
        )
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        if not isinstance(self.root_ref, PluginRevisionRefV1):
            raise TypeError("Desired commit requires a Plugin revision ref")
        if (
            self.root_ref.installation_id != self.installation_id
            or self.root_ref.plugin_id != self.plugin_id
        ):
            raise ValueError("Desired commit root identity changed")
        if self.request_version != PACKAGE_DESIRED_STATE_COMMIT_REQUEST_VERSION:
            raise ValueError("Unsupported Package desired-state commit request")
        if self.desired_request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package desired-state commit request id does not match")

    @classmethod
    def create(
        cls,
        admission_request: PackageCommitAdmissionRequestV1,
        *,
        command_id: str,
        command_fingerprint: str,
        expected_inventory_revision: int,
    ) -> PackageDesiredStateCommitRequestV1:
        if not isinstance(admission_request, PackageCommitAdmissionRequestV1):
            raise TypeError("Package commit admission request is required")
        publication = admission_request.publication_receipt
        if publication is None:
            raise ValueError("Desired commit requires a Package publication receipt")
        root_ref = publication.committed_set.root_ref
        values = _desired_request_identity(
            command_id=command_id,
            command_fingerprint=command_fingerprint,
            expected_inventory_revision=expected_inventory_revision,
            operation_id=admission_request.operation_id,
            operation_fingerprint=admission_request.operation_fingerprint,
            request_fingerprint=admission_request.request_fingerprint,
            attempt_epoch=publication.attempt_epoch,
            product_id=admission_request.product_id,
            scope_id=admission_request.scope_id,
            installation_id=admission_request.installation_id,
            plugin_id=admission_request.plugin_id,
            committed_set_id=admission_request.committed_set_id,
            root_ref=root_ref,
            request_version=PACKAGE_DESIRED_STATE_COMMIT_REQUEST_VERSION,
        )
        return cls(
            desired_request_id=_fingerprint(values),
            command_id=command_id,
            command_fingerprint=command_fingerprint,
            expected_inventory_revision=expected_inventory_revision,
            operation_id=admission_request.operation_id,
            operation_fingerprint=admission_request.operation_fingerprint,
            request_fingerprint=admission_request.request_fingerprint,
            attempt_epoch=publication.attempt_epoch,
            product_id=admission_request.product_id,
            scope_id=admission_request.scope_id,
            installation_id=admission_request.installation_id,
            plugin_id=admission_request.plugin_id,
            committed_set_id=admission_request.committed_set_id,
            root_ref=root_ref,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _desired_request_identity(
            command_id=self.command_id,
            command_fingerprint=self.command_fingerprint,
            expected_inventory_revision=self.expected_inventory_revision,
            operation_id=self.operation_id,
            operation_fingerprint=self.operation_fingerprint,
            request_fingerprint=self.request_fingerprint,
            attempt_epoch=self.attempt_epoch,
            product_id=self.product_id,
            scope_id=self.scope_id,
            installation_id=self.installation_id,
            plugin_id=self.plugin_id,
            committed_set_id=self.committed_set_id,
            root_ref=self.root_ref,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"desiredRequestId": self.desired_request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageDesiredStateCommitRequestV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "commandFingerprint",
                "commandId",
                "committedSetId",
                "desiredRequestId",
                "expectedInventoryRevision",
                "installationId",
                "operationFingerprint",
                "operationId",
                "pluginId",
                "productId",
                "requestFingerprint",
                "requestVersion",
                "rootRef",
                "scopeId",
            },
            name="Package desired-state commit request",
        )
        return cls(
            desired_request_id=_wire_string(
                document["desiredRequestId"], name="desired request id"
            ),
            command_id=_wire_string(document["commandId"], name="command id"),
            command_fingerprint=_wire_string(
                document["commandFingerprint"], name="command fingerprint"
            ),
            expected_inventory_revision=_wire_int(
                document["expectedInventoryRevision"],
                name="expected inventory revision",
            ),
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
            ),
            operation_fingerprint=_wire_string(
                document["operationFingerprint"], name="operation fingerprint"
            ),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            product_id=_wire_string(document["productId"], name="Product identity"),
            scope_id=_wire_string(document["scopeId"], name="scope identity"),
            installation_id=_wire_string(
                document["installationId"], name="Installation identity"
            ),
            plugin_id=_wire_string(document["pluginId"], name="Plugin identity"),
            committed_set_id=_wire_string(
                document["committedSetId"], name="committed set id"
            ),
            root_ref=PluginRevisionRefV1.from_dict(document["rootRef"]),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageDesiredStateCommitReceiptV1:
    receipt_id: str
    request: PackageDesiredStateCommitRequestV1
    inventory_revision: int
    owner_identity: str
    owner_revision: int
    receipt_version: int = PACKAGE_DESIRED_STATE_COMMIT_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="desired commit receipt id")
        if not isinstance(self.request, PackageDesiredStateCommitRequestV1):
            raise TypeError("Package desired-state commit request is required")
        if self.inventory_revision != self.request.expected_inventory_revision + 1:
            raise ValueError("Desired commit receipt does not prove the expected CAS")
        _require_safe_id(self.owner_identity, name="desired owner identity")
        _require_positive(self.owner_revision, name="desired owner revision")
        if self.receipt_version != PACKAGE_DESIRED_STATE_COMMIT_RECEIPT_VERSION:
            raise ValueError("Unsupported Package desired-state commit receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package desired-state commit receipt id does not match")

    @classmethod
    def create(
        cls,
        request: PackageDesiredStateCommitRequestV1,
        *,
        owner_identity: str,
        owner_revision: int,
    ) -> PackageDesiredStateCommitReceiptV1:
        values = _desired_receipt_identity(
            request=request,
            inventory_revision=request.expected_inventory_revision + 1,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
            receipt_version=PACKAGE_DESIRED_STATE_COMMIT_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=request,
            inventory_revision=request.expected_inventory_revision + 1,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _desired_receipt_identity(
            request=self.request,
            inventory_revision=self.inventory_revision,
            owner_identity=self.owner_identity,
            owner_revision=self.owner_revision,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageDesiredStateCommitReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "inventoryRevision",
                "ownerIdentity",
                "ownerRevision",
                "receiptId",
                "receiptVersion",
                "request",
            },
            name="Package desired-state commit receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            request=PackageDesiredStateCommitRequestV1.from_dict(document["request"]),
            inventory_revision=_wire_int(
                document["inventoryRevision"], name="inventory revision"
            ),
            owner_identity=_wire_string(
                document["ownerIdentity"], name="owner identity"
            ),
            owner_revision=_wire_int(document["ownerRevision"], name="owner revision"),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageDesiredStateCommitFailureV1:
    failure_id: str
    request: PackageDesiredStateCommitRequestV1
    observed_inventory_revision: int
    owner_identity: str
    owner_revision: int
    code: Literal["package_desired_revision_conflict"] = (
        "package_desired_revision_conflict"
    )
    failure_version: int = PACKAGE_DESIRED_STATE_COMMIT_FAILURE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.failure_id, name="desired commit failure id")
        if not isinstance(self.request, PackageDesiredStateCommitRequestV1):
            raise TypeError("Package desired-state commit request is required")
        _require_nonnegative(
            self.observed_inventory_revision,
            name="observed desired inventory revision",
        )
        if self.observed_inventory_revision == self.request.expected_inventory_revision:
            raise ValueError("Desired revision conflict requires a different head")
        _require_safe_id(self.owner_identity, name="desired owner identity")
        _require_positive(self.owner_revision, name="desired owner revision")
        if self.code != "package_desired_revision_conflict":
            raise ValueError("Unsupported Package desired-state commit failure")
        if self.failure_version != PACKAGE_DESIRED_STATE_COMMIT_FAILURE_VERSION:
            raise ValueError("Unsupported Package desired-state commit failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package desired-state commit failure id does not match")

    @classmethod
    def conflict(
        cls,
        request: PackageDesiredStateCommitRequestV1,
        *,
        observed_inventory_revision: int,
        owner_identity: str,
        owner_revision: int,
    ) -> PackageDesiredStateCommitFailureV1:
        values = _desired_failure_identity(
            request=request,
            observed_inventory_revision=observed_inventory_revision,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
            code="package_desired_revision_conflict",
            failure_version=PACKAGE_DESIRED_STATE_COMMIT_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            request=request,
            observed_inventory_revision=observed_inventory_revision,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _desired_failure_identity(
            request=self.request,
            observed_inventory_revision=self.observed_inventory_revision,
            owner_identity=self.owner_identity,
            owner_revision=self.owner_revision,
            code=self.code,
            failure_version=self.failure_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageDesiredStateCommitFailureV1:
        document = _exact_dict(
            value,
            fields={
                "code",
                "failureId",
                "failureVersion",
                "observedInventoryRevision",
                "ownerIdentity",
                "ownerRevision",
                "request",
            },
            name="Package desired-state commit failure",
        )
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            request=PackageDesiredStateCommitRequestV1.from_dict(document["request"]),
            observed_inventory_revision=_wire_int(
                document["observedInventoryRevision"],
                name="observed inventory revision",
            ),
            owner_identity=_wire_string(
                document["ownerIdentity"], name="owner identity"
            ),
            owner_revision=_wire_int(document["ownerRevision"], name="owner revision"),
            code=cast(
                Literal["package_desired_revision_conflict"],
                _wire_string(document["code"], name="failure code"),
            ),
            failure_version=_wire_int(
                document["failureVersion"], name="failure version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageDesiredStateCommitResultV1:
    desired_request_id: str
    disposition: PackageDesiredStateCommitDisposition
    receipt: PackageDesiredStateCommitReceiptV1 | None
    failure: PackageDesiredStateCommitFailureV1 | None
    result_version: int = PACKAGE_DESIRED_STATE_COMMIT_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.desired_request_id, name="desired commit request id")
        if self.disposition == "committed":
            if self.receipt is None or self.failure is not None:
                raise ValueError("Committed desired-state result is inconsistent")
            request_id = self.receipt.request.desired_request_id
        elif self.disposition == "rejected":
            if self.receipt is not None or self.failure is None:
                raise ValueError("Rejected desired-state result is inconsistent")
            request_id = self.failure.request.desired_request_id
        else:
            raise ValueError("Unsupported desired-state commit disposition")
        if request_id != self.desired_request_id:
            raise ValueError("Desired-state result request changed")
        if self.result_version != PACKAGE_DESIRED_STATE_COMMIT_RESULT_VERSION:
            raise ValueError("Unsupported Package desired-state commit result")

    @classmethod
    def committed(
        cls,
        request: PackageDesiredStateCommitRequestV1,
        *,
        owner_identity: str,
        owner_revision: int,
    ) -> PackageDesiredStateCommitResultV1:
        return cls(
            desired_request_id=request.desired_request_id,
            disposition="committed",
            receipt=PackageDesiredStateCommitReceiptV1.create(
                request,
                owner_identity=owner_identity,
                owner_revision=owner_revision,
            ),
            failure=None,
        )

    @classmethod
    def rejected(
        cls,
        request: PackageDesiredStateCommitRequestV1,
        *,
        observed_inventory_revision: int,
        owner_identity: str,
        owner_revision: int,
    ) -> PackageDesiredStateCommitResultV1:
        return cls(
            desired_request_id=request.desired_request_id,
            disposition="rejected",
            receipt=None,
            failure=PackageDesiredStateCommitFailureV1.conflict(
                request,
                observed_inventory_revision=observed_inventory_revision,
                owner_identity=owner_identity,
                owner_revision=owner_revision,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "desiredRequestId": self.desired_request_id,
            "disposition": self.disposition,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDesiredStateCommitResultV1:
        document = _exact_dict(
            value,
            fields={
                "desiredRequestId",
                "disposition",
                "failure",
                "receipt",
                "resultVersion",
            },
            name="Package desired-state commit result",
        )
        return cls(
            desired_request_id=_wire_string(
                document["desiredRequestId"], name="desired request id"
            ),
            disposition=cast(
                PackageDesiredStateCommitDisposition,
                _wire_string(document["disposition"], name="disposition"),
            ),
            receipt=(
                None
                if document["receipt"] is None
                else PackageDesiredStateCommitReceiptV1.from_dict(document["receipt"])
            ),
            failure=(
                None
                if document["failure"] is None
                else PackageDesiredStateCommitFailureV1.from_dict(document["failure"])
            ),
            result_version=_wire_int(document["resultVersion"], name="result version"),
        )


class PackageDesiredStateCommitPort(Protocol):
    """Narrow expected-revision CAS owner; it receives no retention capability."""

    def commit(
        self,
        request: PackageDesiredStateCommitRequestV1,
    ) -> PackageDesiredStateCommitResultV1: ...


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffRequestV1:
    """Exact admitted-set handoff input with the still-live transaction pin."""

    handoff_id: str
    admission_request: PackageCommitAdmissionRequestV1
    admission_receipt: PackageCommitAdmissionReceiptV1
    transaction_pin_receipt: PackageTransactionPinReceiptV1
    desired_request: PackageDesiredStateCommitRequestV1
    request_version: int = PACKAGE_RETENTION_HANDOFF_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.handoff_id, name="retention handoff identity")
        if not isinstance(self.admission_request, PackageCommitAdmissionRequestV1):
            raise TypeError("Package commit admission request is required")
        if not isinstance(self.admission_receipt, PackageCommitAdmissionReceiptV1):
            raise TypeError("Package commit admission receipt is required")
        if not isinstance(
            self.transaction_pin_receipt,
            PackageTransactionPinReceiptV1,
        ):
            raise TypeError("Package transaction pin receipt is required")
        if not isinstance(self.desired_request, PackageDesiredStateCommitRequestV1):
            raise TypeError("Package desired-state commit request is required")
        publication = self.admission_request.publication_receipt
        if publication is None:
            raise ValueError("Retention handoff requires a publication receipt")
        expected_admission = PackageCommitAdmissionReceiptV1.create(
            self.admission_request,
            publication,
        )
        if self.admission_receipt != expected_admission:
            raise ValueError("Retention handoff admission receipt changed")
        committed = publication.committed_set
        pin = self.transaction_pin_receipt
        desired = self.desired_request
        if (
            not isinstance(self.admission_request.claimed_root_ref, PluginRevisionRefV1)
            or self.admission_request.claimed_root_ref != committed.root_ref
            or self.admission_receipt.root_ref != committed.root_ref
            or pin.state != "acquired"
            or pin.receipt_id != publication.transaction_pin_receipt_id
            or pin.receipt_id != self.admission_receipt.transaction_pin_receipt_id
            or pin.pin_request.operation_id != publication.operation_id
            or pin.pin_request.attempt_epoch != publication.attempt_epoch
            or pin.pin_request.request_fingerprint != publication.request_fingerprint
            or pin.pin_request.classification_fingerprint
            != publication.classification_fingerprint
            or pin.pin_request.prepublication_graph_digest
            != committed.prepublication_graph_digest
            or desired.operation_id != publication.operation_id
            or desired.operation_fingerprint != publication.operation_fingerprint
            or desired.request_fingerprint != publication.request_fingerprint
            or desired.attempt_epoch != publication.attempt_epoch
            or desired.product_id != publication.product_id
            or desired.scope_id != publication.scope_id
            or desired.installation_id != publication.installation_id
            or desired.plugin_id != publication.plugin_id
            or desired.committed_set_id != committed.set_id
            or desired.root_ref != committed.root_ref
        ):
            raise ValueError("Retention handoff context changed")
        if self.request_version != PACKAGE_RETENTION_HANDOFF_REQUEST_VERSION:
            raise ValueError("Unsupported Package retention handoff request")
        if self.handoff_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package retention handoff identity does not match")

    @classmethod
    def create(
        cls,
        *,
        admission_request: PackageCommitAdmissionRequestV1,
        admission_receipt: PackageCommitAdmissionReceiptV1,
        transaction_pin_receipt: PackageTransactionPinReceiptV1,
        desired_request: PackageDesiredStateCommitRequestV1,
    ) -> PackageRetentionHandoffRequestV1:
        values = _handoff_request_identity(
            admission_request=admission_request,
            admission_receipt=admission_receipt,
            transaction_pin_receipt=transaction_pin_receipt,
            desired_request=desired_request,
            request_version=PACKAGE_RETENTION_HANDOFF_REQUEST_VERSION,
        )
        return cls(
            handoff_id=_fingerprint(values),
            admission_request=admission_request,
            admission_receipt=admission_receipt,
            transaction_pin_receipt=transaction_pin_receipt,
            desired_request=desired_request,
        )

    @property
    def operation_id(self) -> str:
        return self.admission_request.operation_id

    @property
    def attempt_epoch(self) -> int:
        return self.desired_request.attempt_epoch

    @property
    def dependency_pin_request(self) -> PackageDependencyPinRequestV1:
        return PackageDependencyPinRequestV1.create(self)

    def _identity_dict(self) -> dict[str, object]:
        return _handoff_request_identity(
            admission_request=self.admission_request,
            admission_receipt=self.admission_receipt,
            transaction_pin_receipt=self.transaction_pin_receipt,
            desired_request=self.desired_request,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"handoffId": self.handoff_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageRetentionHandoffRequestV1:
        document = _exact_dict(
            value,
            fields={
                "admissionReceipt",
                "admissionRequest",
                "desiredRequest",
                "handoffId",
                "requestVersion",
                "transactionPinReceipt",
            },
            name="Package retention handoff request",
        )
        return cls(
            handoff_id=_wire_string(document["handoffId"], name="handoff id"),
            admission_request=PackageCommitAdmissionRequestV1.from_dict(
                document["admissionRequest"]
            ),
            admission_receipt=PackageCommitAdmissionReceiptV1.from_dict(
                document["admissionReceipt"]
            ),
            transaction_pin_receipt=PackageTransactionPinReceiptV1.from_dict(
                document["transactionPinReceipt"]
            ),
            desired_request=PackageDesiredStateCommitRequestV1.from_dict(
                document["desiredRequest"]
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageDependencyPinRequestV1:
    """Exact root/dependency refs retained before the desired-state CAS."""

    pin_request_id: str
    handoff_id: str
    operation_id: str
    attempt_epoch: int
    admission_id: str
    publication_receipt_id: str
    committed_set_id: str
    transaction_pin_receipt_id: str
    pin_set_id: str
    root_ref: PluginRevisionRefV1
    dependency_refs: tuple[VerifiedArtifactRefV1, ...]
    request_version: int = PACKAGE_DEPENDENCY_PIN_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.pin_request_id, "dependency pin request id"),
            (self.handoff_id, "retention handoff identity"),
            (self.admission_id, "commit admission receipt id"),
            (self.publication_receipt_id, "Package publication receipt id"),
            (self.committed_set_id, "committed Package set id"),
            (self.transaction_pin_receipt_id, "transaction pin receipt id"),
            (self.pin_set_id, "dependency pin set id"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.operation_id, name="Package operation identity")
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        if not isinstance(self.root_ref, PluginRevisionRefV1):
            raise TypeError("Dependency pin request requires a Plugin root ref")
        if not all(
            isinstance(item, VerifiedArtifactRefV1) for item in self.dependency_refs
        ):
            raise TypeError("Dependency pin request contains an invalid dependency ref")
        if self.dependency_refs != tuple(
            sorted(self.dependency_refs, key=lambda item: item.ref_id)
        ):
            raise ValueError("Dependency refs must be in canonical order")
        if len({item.ref_id for item in self.dependency_refs}) != len(
            self.dependency_refs
        ):
            raise ValueError("Dependency refs must be unique")
        if self.pin_set_id != _dependency_pin_set_id(
            self.root_ref,
            self.dependency_refs,
        ):
            raise ValueError("Dependency pin set id does not match")
        if self.request_version != PACKAGE_DEPENDENCY_PIN_REQUEST_VERSION:
            raise ValueError("Unsupported Package dependency pin request")
        if self.pin_request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package dependency pin request id does not match")

    @classmethod
    def create(
        cls,
        handoff: PackageRetentionHandoffRequestV1,
    ) -> PackageDependencyPinRequestV1:
        if not isinstance(handoff, PackageRetentionHandoffRequestV1):
            raise TypeError("Package retention handoff request is required")
        publication = handoff.admission_request.publication_receipt
        assert publication is not None
        committed = publication.committed_set
        pin_set_id = _dependency_pin_set_id(
            committed.root_ref,
            committed.dependency_refs,
        )
        values = _dependency_pin_request_identity(
            handoff_id=handoff.handoff_id,
            operation_id=publication.operation_id,
            attempt_epoch=publication.attempt_epoch,
            admission_id=handoff.admission_receipt.admission_id,
            publication_receipt_id=publication.receipt_id,
            committed_set_id=committed.set_id,
            transaction_pin_receipt_id=handoff.transaction_pin_receipt.receipt_id,
            pin_set_id=pin_set_id,
            root_ref=committed.root_ref,
            dependency_refs=committed.dependency_refs,
            request_version=PACKAGE_DEPENDENCY_PIN_REQUEST_VERSION,
        )
        return cls(
            pin_request_id=_fingerprint(values),
            handoff_id=handoff.handoff_id,
            operation_id=publication.operation_id,
            attempt_epoch=publication.attempt_epoch,
            admission_id=handoff.admission_receipt.admission_id,
            publication_receipt_id=publication.receipt_id,
            committed_set_id=committed.set_id,
            transaction_pin_receipt_id=handoff.transaction_pin_receipt.receipt_id,
            pin_set_id=pin_set_id,
            root_ref=committed.root_ref,
            dependency_refs=committed.dependency_refs,
        )

    @property
    def target_ref_ids(self) -> tuple[str, ...]:
        return (self.root_ref.ref_id,) + tuple(
            item.ref_id for item in self.dependency_refs
        )

    def _identity_dict(self) -> dict[str, object]:
        return _dependency_pin_request_identity(
            handoff_id=self.handoff_id,
            operation_id=self.operation_id,
            attempt_epoch=self.attempt_epoch,
            admission_id=self.admission_id,
            publication_receipt_id=self.publication_receipt_id,
            committed_set_id=self.committed_set_id,
            transaction_pin_receipt_id=self.transaction_pin_receipt_id,
            pin_set_id=self.pin_set_id,
            root_ref=self.root_ref,
            dependency_refs=self.dependency_refs,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"pinRequestId": self.pin_request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyPinRequestV1:
        document = _exact_dict(
            value,
            fields={
                "admissionId",
                "attemptEpoch",
                "committedSetId",
                "dependencyRefs",
                "handoffId",
                "operationId",
                "pinRequestId",
                "pinSetId",
                "publicationReceiptId",
                "requestVersion",
                "rootRef",
                "transactionPinReceiptId",
            },
            name="Package dependency pin request",
        )
        return cls(
            pin_request_id=_wire_string(
                document["pinRequestId"], name="pin request id"
            ),
            handoff_id=_wire_string(document["handoffId"], name="handoff id"),
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            admission_id=_wire_string(document["admissionId"], name="admission id"),
            publication_receipt_id=_wire_string(
                document["publicationReceiptId"], name="publication receipt id"
            ),
            committed_set_id=_wire_string(
                document["committedSetId"], name="committed set id"
            ),
            transaction_pin_receipt_id=_wire_string(
                document["transactionPinReceiptId"], name="transaction pin receipt id"
            ),
            pin_set_id=_wire_string(document["pinSetId"], name="pin set id"),
            root_ref=PluginRevisionRefV1.from_dict(document["rootRef"]),
            dependency_refs=tuple(
                VerifiedArtifactRefV1.from_dict(item)
                for item in _wire_list(
                    document["dependencyRefs"], name="dependency refs"
                )
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageDependencyPinReceiptV1:
    """Retention-owner proof of the no-zero-pin handoff invariant."""

    receipt_id: str
    request: PackageDependencyPinRequestV1
    pin_ids: tuple[str, ...]
    owner_identity: str
    owner_revision: int
    lease_revision: int
    state: PackageDependencyPinState
    dependency_pins_live: bool
    transaction_pin_receipt: PackageTransactionPinReceiptV1
    prior_receipt_id: str | None
    desired_receipt_id: str | None
    transition_evidence_ref: str | None
    receipt_version: int = PACKAGE_DEPENDENCY_PIN_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="dependency pin receipt id")
        if not isinstance(self.request, PackageDependencyPinRequestV1):
            raise TypeError("Package dependency pin request is required")
        if len(self.pin_ids) != len(self.request.target_ref_ids):
            raise ValueError("Dependency pin receipt does not cover the exact set")
        if not self.pin_ids or any(
            _SHA256.fullmatch(item) is None for item in self.pin_ids
        ):
            raise ValueError("Dependency pin identities must be lowercase SHA-256")
        if len(set(self.pin_ids)) != len(self.pin_ids):
            raise ValueError("Dependency pin identities must be unique")
        _require_safe_id(self.owner_identity, name="retention owner identity")
        _require_positive(self.owner_revision, name="retention owner revision")
        _require_positive(self.lease_revision, name="retention lease revision")
        if not isinstance(
            self.transaction_pin_receipt,
            PackageTransactionPinReceiptV1,
        ):
            raise TypeError("Package transaction pin receipt is required")
        transaction = self.transaction_pin_receipt
        if (
            transaction.pin_request.operation_id != self.request.operation_id
            or transaction.pin_request.attempt_epoch != self.request.attempt_epoch
        ):
            raise ValueError("Dependency retention transaction context changed")
        if self.state == "acquired":
            if (
                not self.dependency_pins_live
                or transaction.state != "acquired"
                or transaction.receipt_id != self.request.transaction_pin_receipt_id
                or self.prior_receipt_id is not None
                or self.desired_receipt_id is not None
                or self.transition_evidence_ref is not None
            ):
                raise ValueError("Acquired dependency pin receipt is inconsistent")
        elif self.state == "aborted":
            if (
                self.dependency_pins_live
                or transaction.state != "acquired"
                or transaction.receipt_id != self.request.transaction_pin_receipt_id
                or self.prior_receipt_id is None
                or self.desired_receipt_id is not None
                or self.transition_evidence_ref is None
            ):
                raise ValueError("Aborted dependency pin receipt is inconsistent")
        elif self.state == "settled":
            if (
                not self.dependency_pins_live
                or transaction.state != "released"
                or transaction.prior_receipt_id
                != self.request.transaction_pin_receipt_id
                or self.prior_receipt_id is None
                or self.desired_receipt_id is None
                or self.transition_evidence_ref != self.desired_receipt_id
            ):
                raise ValueError("Settled dependency pin receipt is inconsistent")
        else:
            raise ValueError("Unsupported Package dependency pin state")
        for value, name in (
            (self.prior_receipt_id, "prior dependency pin receipt id"),
            (self.desired_receipt_id, "desired commit receipt id"),
            (self.transition_evidence_ref, "retention transition evidence"),
        ):
            if value is not None:
                _require_sha256(value, name=name)
        if self.receipt_version != PACKAGE_DEPENDENCY_PIN_RECEIPT_VERSION:
            raise ValueError("Unsupported Package dependency pin receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package dependency pin receipt id does not match")

    @classmethod
    def acquire(
        cls,
        request: PackageDependencyPinRequestV1,
        *,
        pin_ids: tuple[str, ...],
        owner_identity: str,
        owner_revision: int,
        lease_revision: int,
        transaction_pin_receipt: PackageTransactionPinReceiptV1,
    ) -> PackageDependencyPinReceiptV1:
        values = _dependency_pin_receipt_identity(
            request=request,
            pin_ids=pin_ids,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
            lease_revision=lease_revision,
            state="acquired",
            dependency_pins_live=True,
            transaction_pin_receipt=transaction_pin_receipt,
            prior_receipt_id=None,
            desired_receipt_id=None,
            transition_evidence_ref=None,
            receipt_version=PACKAGE_DEPENDENCY_PIN_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=request,
            pin_ids=pin_ids,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
            lease_revision=lease_revision,
            state="acquired",
            dependency_pins_live=True,
            transaction_pin_receipt=transaction_pin_receipt,
            prior_receipt_id=None,
            desired_receipt_id=None,
            transition_evidence_ref=None,
        )

    @classmethod
    def abort(
        cls,
        prior: PackageDependencyPinReceiptV1,
        failure: PackageDesiredStateCommitFailureV1,
        *,
        owner_revision: int,
        lease_revision: int,
    ) -> PackageDependencyPinReceiptV1:
        _require_acquired_dependency_receipt(prior)
        if not isinstance(failure, PackageDesiredStateCommitFailureV1):
            raise TypeError("Package desired-state commit failure is required")
        if (
            owner_revision <= prior.owner_revision
            or lease_revision <= prior.lease_revision
        ):
            raise ValueError("Dependency retention revisions must advance")
        values = _dependency_pin_receipt_identity(
            request=prior.request,
            pin_ids=prior.pin_ids,
            owner_identity=prior.owner_identity,
            owner_revision=owner_revision,
            lease_revision=lease_revision,
            state="aborted",
            dependency_pins_live=False,
            transaction_pin_receipt=prior.transaction_pin_receipt,
            prior_receipt_id=prior.receipt_id,
            desired_receipt_id=None,
            transition_evidence_ref=failure.failure_id,
            receipt_version=PACKAGE_DEPENDENCY_PIN_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=prior.request,
            pin_ids=prior.pin_ids,
            owner_identity=prior.owner_identity,
            owner_revision=owner_revision,
            lease_revision=lease_revision,
            state="aborted",
            dependency_pins_live=False,
            transaction_pin_receipt=prior.transaction_pin_receipt,
            prior_receipt_id=prior.receipt_id,
            desired_receipt_id=None,
            transition_evidence_ref=failure.failure_id,
        )

    @classmethod
    def settle(
        cls,
        prior: PackageDependencyPinReceiptV1,
        desired: PackageDesiredStateCommitReceiptV1,
        transaction_release: PackageTransactionPinReceiptV1,
        *,
        owner_revision: int,
        lease_revision: int,
    ) -> PackageDependencyPinReceiptV1:
        _require_acquired_dependency_receipt(prior)
        if not isinstance(desired, PackageDesiredStateCommitReceiptV1):
            raise TypeError("Package desired-state commit receipt is required")
        if (
            owner_revision <= prior.owner_revision
            or lease_revision <= prior.lease_revision
        ):
            raise ValueError("Dependency retention revisions must advance")
        if desired.request.operation_id != prior.request.operation_id:
            raise ValueError("Desired receipt operation changed during settlement")
        if (
            not isinstance(transaction_release, PackageTransactionPinReceiptV1)
            or transaction_release.state != "released"
            or transaction_release.prior_receipt_id
            != prior.transaction_pin_receipt.receipt_id
        ):
            raise ValueError("Settlement requires the exact transaction pin release")
        values = _dependency_pin_receipt_identity(
            request=prior.request,
            pin_ids=prior.pin_ids,
            owner_identity=prior.owner_identity,
            owner_revision=owner_revision,
            lease_revision=lease_revision,
            state="settled",
            dependency_pins_live=True,
            transaction_pin_receipt=transaction_release,
            prior_receipt_id=prior.receipt_id,
            desired_receipt_id=desired.receipt_id,
            transition_evidence_ref=desired.receipt_id,
            receipt_version=PACKAGE_DEPENDENCY_PIN_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=prior.request,
            pin_ids=prior.pin_ids,
            owner_identity=prior.owner_identity,
            owner_revision=owner_revision,
            lease_revision=lease_revision,
            state="settled",
            dependency_pins_live=True,
            transaction_pin_receipt=transaction_release,
            prior_receipt_id=prior.receipt_id,
            desired_receipt_id=desired.receipt_id,
            transition_evidence_ref=desired.receipt_id,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _dependency_pin_receipt_identity(
            request=self.request,
            pin_ids=self.pin_ids,
            owner_identity=self.owner_identity,
            owner_revision=self.owner_revision,
            lease_revision=self.lease_revision,
            state=self.state,
            dependency_pins_live=self.dependency_pins_live,
            transaction_pin_receipt=self.transaction_pin_receipt,
            prior_receipt_id=self.prior_receipt_id,
            desired_receipt_id=self.desired_receipt_id,
            transition_evidence_ref=self.transition_evidence_ref,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyPinReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "dependencyPinsLive",
                "desiredReceiptId",
                "leaseRevision",
                "ownerIdentity",
                "ownerRevision",
                "pinIds",
                "priorReceiptId",
                "receiptId",
                "receiptVersion",
                "request",
                "state",
                "transactionPinReceipt",
                "transitionEvidenceRef",
            },
            name="Package dependency pin receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            request=PackageDependencyPinRequestV1.from_dict(document["request"]),
            pin_ids=tuple(
                _wire_string(item, name="pin id")
                for item in _wire_list(document["pinIds"], name="pin ids")
            ),
            owner_identity=_wire_string(
                document["ownerIdentity"], name="owner identity"
            ),
            owner_revision=_wire_int(document["ownerRevision"], name="owner revision"),
            lease_revision=_wire_int(document["leaseRevision"], name="lease revision"),
            state=cast(
                PackageDependencyPinState,
                _wire_string(document["state"], name="pin state"),
            ),
            dependency_pins_live=_wire_bool(
                document["dependencyPinsLive"], name="dependency pin liveness"
            ),
            transaction_pin_receipt=PackageTransactionPinReceiptV1.from_dict(
                document["transactionPinReceipt"]
            ),
            prior_receipt_id=_wire_optional_string(
                document["priorReceiptId"], name="prior receipt id"
            ),
            desired_receipt_id=_wire_optional_string(
                document["desiredReceiptId"], name="desired receipt id"
            ),
            transition_evidence_ref=_wire_optional_string(
                document["transitionEvidenceRef"], name="transition evidence ref"
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


class PackageRetentionSettlementPort(Protocol):
    """Sole owner of dependency pins and atomic transaction-pin settlement."""

    def acquire(
        self,
        request: PackageDependencyPinRequestV1,
        *,
        transaction_pin_receipt: PackageTransactionPinReceiptV1,
    ) -> PackageDependencyPinReceiptV1: ...

    def abort(
        self,
        receipt: PackageDependencyPinReceiptV1,
        *,
        failure: PackageDesiredStateCommitFailureV1,
    ) -> PackageDependencyPinReceiptV1: ...

    def settle(
        self,
        receipt: PackageDependencyPinReceiptV1,
        *,
        desired_receipt: PackageDesiredStateCommitReceiptV1,
    ) -> PackageDependencyPinReceiptV1: ...


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffReceiptV1:
    """Monotonic local saga receipt; external owner receipts remain authoritative."""

    receipt_id: str
    request: PackageRetentionHandoffRequestV1
    state: PackageRetentionHandoffState
    handoff_revision: int
    prior_receipt_id: str | None
    dependency_pin_receipt: PackageDependencyPinReceiptV1 | None
    desired_receipt: PackageDesiredStateCommitReceiptV1 | None
    desired_failure: PackageDesiredStateCommitFailureV1 | None
    receipt_version: int = PACKAGE_RETENTION_HANDOFF_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="retention handoff receipt id")
        if not isinstance(self.request, PackageRetentionHandoffRequestV1):
            raise TypeError("Package retention handoff request is required")
        _require_positive(self.handoff_revision, name="retention handoff revision")
        if self.prior_receipt_id is not None:
            _require_sha256(
                self.prior_receipt_id,
                name="prior retention handoff receipt id",
            )
        dependency = self.dependency_pin_receipt
        desired = self.desired_receipt
        failure = self.desired_failure
        if self.state == "opened":
            if (
                self.handoff_revision != 1
                or self.prior_receipt_id is not None
                or dependency is not None
                or desired is not None
                or failure is not None
            ):
                raise ValueError("Opened retention handoff receipt is inconsistent")
        elif self.state == "dependency_pinned":
            if (
                self.prior_receipt_id is None
                or dependency is None
                or dependency.state != "acquired"
                or desired is not None
                or failure is not None
            ):
                raise ValueError("Dependency-pinned handoff receipt is inconsistent")
        elif self.state == "desired_committed":
            if (
                self.prior_receipt_id is None
                or dependency is None
                or dependency.state != "acquired"
                or desired is None
                or failure is not None
            ):
                raise ValueError("Desired-committed handoff receipt is inconsistent")
        elif self.state == "settled":
            if (
                self.prior_receipt_id is None
                or dependency is None
                or dependency.state != "settled"
                or desired is None
                or dependency.desired_receipt_id != desired.receipt_id
                or failure is not None
            ):
                raise ValueError("Settled retention handoff receipt is inconsistent")
        elif self.state == "aborted":
            if (
                self.prior_receipt_id is None
                or dependency is None
                or dependency.state != "aborted"
                or desired is not None
                or failure is None
                or dependency.transition_evidence_ref != failure.failure_id
            ):
                raise ValueError("Aborted retention handoff receipt is inconsistent")
        else:
            raise ValueError("Unsupported Package retention handoff state")
        if (
            dependency is not None
            and dependency.request != self.request.dependency_pin_request
        ):
            raise ValueError("Retention handoff dependency pin request changed")
        if desired is not None and desired.request != self.request.desired_request:
            raise ValueError("Retention handoff desired receipt changed")
        if failure is not None and failure.request != self.request.desired_request:
            raise ValueError("Retention handoff desired failure changed")
        if self.receipt_version != PACKAGE_RETENTION_HANDOFF_RECEIPT_VERSION:
            raise ValueError("Unsupported Package retention handoff receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package retention handoff receipt id does not match")

    @classmethod
    def open(
        cls,
        request: PackageRetentionHandoffRequestV1,
    ) -> PackageRetentionHandoffReceiptV1:
        values = _handoff_receipt_identity(
            request=request,
            state="opened",
            handoff_revision=1,
            prior_receipt_id=None,
            dependency_pin_receipt=None,
            desired_receipt=None,
            desired_failure=None,
            receipt_version=PACKAGE_RETENTION_HANDOFF_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=request,
            state="opened",
            handoff_revision=1,
            prior_receipt_id=None,
            dependency_pin_receipt=None,
            desired_receipt=None,
            desired_failure=None,
        )

    @classmethod
    def dependency_pinned(
        cls,
        prior: PackageRetentionHandoffReceiptV1,
        dependency_receipt: PackageDependencyPinReceiptV1,
    ) -> PackageRetentionHandoffReceiptV1:
        _require_handoff_state(prior, "opened")
        if not _valid_acquired_dependency_receipt(prior.request, dependency_receipt):
            raise ValueError("Dependency-pinned retention evidence changed")
        return cls._advance(
            prior,
            state="dependency_pinned",
            dependency_pin_receipt=dependency_receipt,
            desired_receipt=None,
            desired_failure=None,
        )

    @classmethod
    def desired_committed(
        cls,
        prior: PackageRetentionHandoffReceiptV1,
        desired_receipt: PackageDesiredStateCommitReceiptV1,
    ) -> PackageRetentionHandoffReceiptV1:
        _require_handoff_state(prior, "dependency_pinned")
        assert prior.dependency_pin_receipt is not None
        if desired_receipt.request != prior.request.desired_request:
            raise ValueError("Desired-committed retention evidence changed")
        return cls._advance(
            prior,
            state="desired_committed",
            dependency_pin_receipt=prior.dependency_pin_receipt,
            desired_receipt=desired_receipt,
            desired_failure=None,
        )

    @classmethod
    def settled(
        cls,
        prior: PackageRetentionHandoffReceiptV1,
        dependency_receipt: PackageDependencyPinReceiptV1,
    ) -> PackageRetentionHandoffReceiptV1:
        _require_handoff_state(prior, "desired_committed")
        assert prior.dependency_pin_receipt is not None
        assert prior.desired_receipt is not None
        if not _valid_settled_dependency_receipt(
            prior.dependency_pin_receipt,
            prior.desired_receipt,
            dependency_receipt,
        ):
            raise ValueError("Settled retention evidence changed")
        return cls._advance(
            prior,
            state="settled",
            dependency_pin_receipt=dependency_receipt,
            desired_receipt=prior.desired_receipt,
            desired_failure=None,
        )

    @classmethod
    def aborted(
        cls,
        prior: PackageRetentionHandoffReceiptV1,
        dependency_receipt: PackageDependencyPinReceiptV1,
        desired_failure: PackageDesiredStateCommitFailureV1,
    ) -> PackageRetentionHandoffReceiptV1:
        _require_handoff_state(prior, "dependency_pinned")
        assert prior.dependency_pin_receipt is not None
        if not _valid_aborted_dependency_receipt(
            prior.dependency_pin_receipt,
            desired_failure,
            dependency_receipt,
        ):
            raise ValueError("Aborted retention evidence changed")
        return cls._advance(
            prior,
            state="aborted",
            dependency_pin_receipt=dependency_receipt,
            desired_receipt=None,
            desired_failure=desired_failure,
        )

    @classmethod
    def _advance(
        cls,
        prior: PackageRetentionHandoffReceiptV1,
        *,
        state: PackageRetentionHandoffState,
        dependency_pin_receipt: PackageDependencyPinReceiptV1 | None,
        desired_receipt: PackageDesiredStateCommitReceiptV1 | None,
        desired_failure: PackageDesiredStateCommitFailureV1 | None,
    ) -> PackageRetentionHandoffReceiptV1:
        values = _handoff_receipt_identity(
            request=prior.request,
            state=state,
            handoff_revision=prior.handoff_revision + 1,
            prior_receipt_id=prior.receipt_id,
            dependency_pin_receipt=dependency_pin_receipt,
            desired_receipt=desired_receipt,
            desired_failure=desired_failure,
            receipt_version=PACKAGE_RETENTION_HANDOFF_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request=prior.request,
            state=state,
            handoff_revision=prior.handoff_revision + 1,
            prior_receipt_id=prior.receipt_id,
            dependency_pin_receipt=dependency_pin_receipt,
            desired_receipt=desired_receipt,
            desired_failure=desired_failure,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _handoff_receipt_identity(
            request=self.request,
            state=self.state,
            handoff_revision=self.handoff_revision,
            prior_receipt_id=self.prior_receipt_id,
            dependency_pin_receipt=self.dependency_pin_receipt,
            desired_receipt=self.desired_receipt,
            desired_failure=self.desired_failure,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageRetentionHandoffReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "dependencyPinReceipt",
                "desiredFailure",
                "desiredReceipt",
                "handoffRevision",
                "priorReceiptId",
                "receiptId",
                "receiptVersion",
                "request",
                "state",
            },
            name="Package retention handoff receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            request=PackageRetentionHandoffRequestV1.from_dict(document["request"]),
            state=cast(
                PackageRetentionHandoffState,
                _wire_string(document["state"], name="handoff state"),
            ),
            handoff_revision=_wire_int(
                document["handoffRevision"], name="handoff revision"
            ),
            prior_receipt_id=_wire_optional_string(
                document["priorReceiptId"], name="prior receipt id"
            ),
            dependency_pin_receipt=(
                None
                if document["dependencyPinReceipt"] is None
                else PackageDependencyPinReceiptV1.from_dict(
                    document["dependencyPinReceipt"]
                )
            ),
            desired_receipt=(
                None
                if document["desiredReceipt"] is None
                else PackageDesiredStateCommitReceiptV1.from_dict(
                    document["desiredReceipt"]
                )
            ),
            desired_failure=(
                None
                if document["desiredFailure"] is None
                else PackageDesiredStateCommitFailureV1.from_dict(
                    document["desiredFailure"]
                )
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffFailureV1:
    failure_id: str
    handoff_id: str
    handoff_receipt_id: str | None
    attempt_epoch: int
    phase: PackageRetentionHandoffFailurePhase
    code: PackageRetentionHandoffCode
    retryable: bool
    retry_domain: Literal["none", "handoff"]
    operator_action: Literal["none", "retry"]
    evidence_ref: str
    failure_version: int = PACKAGE_RETENTION_HANDOFF_FAILURE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.failure_id, "retention handoff failure id"),
            (self.handoff_id, "retention handoff identity"),
            (self.evidence_ref, "retention handoff failure evidence"),
        ):
            _require_sha256(value, name=name)
        if self.handoff_receipt_id is not None:
            _require_sha256(
                self.handoff_receipt_id,
                name="retention handoff receipt id",
            )
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        if self.phase not in {
            "none",
            "opened",
            "dependency_pinned",
            "desired_committed",
        }:
            raise ValueError("Unsupported Package retention handoff failure phase")
        expected = {
            "package_retention_handoff_interrupted": (True, "handoff", "retry"),
            "package_desired_revision_conflict": (False, "none", "none"),
            "package_retention_handoff_stale": (False, "none", "none"),
        }
        if (
            self.code not in expected
            or (
                self.retryable,
                self.retry_domain,
                self.operator_action,
            )
            != expected[self.code]
        ):
            raise ValueError("Retention handoff failure policy changed")
        if self.failure_version != PACKAGE_RETENTION_HANDOFF_FAILURE_VERSION:
            raise ValueError("Unsupported Package retention handoff failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package retention handoff failure id does not match")

    @classmethod
    def interrupted(
        cls,
        receipt: PackageRetentionHandoffReceiptV1,
    ) -> PackageRetentionHandoffFailureV1:
        return cls._create(
            request=receipt.request,
            handoff_receipt_id=receipt.receipt_id,
            phase=cast(PackageRetentionHandoffFailurePhase, receipt.state),
            code="package_retention_handoff_interrupted",
            evidence_ref=receipt.receipt_id,
        )

    @classmethod
    def desired_conflict(
        cls,
        receipt: PackageRetentionHandoffReceiptV1,
        failure: PackageDesiredStateCommitFailureV1,
    ) -> PackageRetentionHandoffFailureV1:
        return cls._create(
            request=receipt.request,
            handoff_receipt_id=(
                receipt.prior_receipt_id
                if receipt.state == "aborted"
                else receipt.receipt_id
            ),
            phase="dependency_pinned",
            code="package_desired_revision_conflict",
            evidence_ref=failure.failure_id,
        )

    @classmethod
    def stale(
        cls,
        request: PackageRetentionHandoffRequestV1,
        receipt: PackageRetentionHandoffReceiptV1 | None,
    ) -> PackageRetentionHandoffFailureV1:
        return cls._create(
            request=request,
            handoff_receipt_id=(None if receipt is None else receipt.receipt_id),
            phase=(
                "none"
                if receipt is None
                else cast(PackageRetentionHandoffFailurePhase, receipt.state)
            ),
            code="package_retention_handoff_stale",
            evidence_ref=(
                request.handoff_id if receipt is None else receipt.receipt_id
            ),
        )

    @classmethod
    def _create(
        cls,
        *,
        request: PackageRetentionHandoffRequestV1,
        handoff_receipt_id: str | None,
        phase: PackageRetentionHandoffFailurePhase,
        code: PackageRetentionHandoffCode,
        evidence_ref: str,
    ) -> PackageRetentionHandoffFailureV1:
        retryable = code == "package_retention_handoff_interrupted"
        values = _handoff_failure_identity(
            handoff_id=request.handoff_id,
            handoff_receipt_id=handoff_receipt_id,
            attempt_epoch=request.attempt_epoch,
            phase=phase,
            code=code,
            retryable=retryable,
            retry_domain="handoff" if retryable else "none",
            operator_action="retry" if retryable else "none",
            evidence_ref=evidence_ref,
            failure_version=PACKAGE_RETENTION_HANDOFF_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            handoff_id=request.handoff_id,
            handoff_receipt_id=handoff_receipt_id,
            attempt_epoch=request.attempt_epoch,
            phase=phase,
            code=code,
            retryable=retryable,
            retry_domain="handoff" if retryable else "none",
            operator_action="retry" if retryable else "none",
            evidence_ref=evidence_ref,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _handoff_failure_identity(
            handoff_id=self.handoff_id,
            handoff_receipt_id=self.handoff_receipt_id,
            attempt_epoch=self.attempt_epoch,
            phase=self.phase,
            code=self.code,
            retryable=self.retryable,
            retry_domain=self.retry_domain,
            operator_action=self.operator_action,
            evidence_ref=self.evidence_ref,
            failure_version=self.failure_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageRetentionHandoffFailureV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "code",
                "evidenceRef",
                "failureId",
                "failureVersion",
                "handoffId",
                "handoffReceiptId",
                "operatorAction",
                "phase",
                "retryDomain",
                "retryable",
            },
            name="Package retention handoff failure",
        )
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            handoff_id=_wire_string(document["handoffId"], name="handoff id"),
            handoff_receipt_id=_wire_optional_string(
                document["handoffReceiptId"], name="handoff receipt id"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            phase=cast(
                PackageRetentionHandoffFailurePhase,
                _wire_string(document["phase"], name="failure phase"),
            ),
            code=cast(
                PackageRetentionHandoffCode,
                _wire_string(document["code"], name="failure code"),
            ),
            retryable=_wire_bool(document["retryable"], name="retryability"),
            retry_domain=cast(
                Literal["none", "handoff"],
                _wire_string(document["retryDomain"], name="retry domain"),
            ),
            operator_action=cast(
                Literal["none", "retry"],
                _wire_string(document["operatorAction"], name="operator action"),
            ),
            evidence_ref=_wire_string(document["evidenceRef"], name="evidence ref"),
            failure_version=_wire_int(
                document["failureVersion"], name="failure version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffResultV1:
    handoff_id: str
    disposition: PackageRetentionHandoffDisposition
    code: PackageRetentionHandoffCode
    receipt: PackageRetentionHandoffReceiptV1 | None
    failure: PackageRetentionHandoffFailureV1 | None
    result_version: int = PACKAGE_RETENTION_HANDOFF_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.handoff_id, name="retention handoff identity")
        if self.disposition == "settled":
            if (
                self.code != "ok"
                or self.receipt is None
                or self.receipt.state != "settled"
                or self.failure is not None
            ):
                raise ValueError("Settled retention handoff result is inconsistent")
        elif self.disposition == "retryable_failure":
            if (
                self.code != "package_retention_handoff_interrupted"
                or self.receipt is None
                or self.receipt.state in {"settled", "aborted"}
                or self.failure is None
                or not self.failure.retryable
            ):
                raise ValueError("Retryable retention handoff result is inconsistent")
        elif self.disposition == "rejected":
            if (
                self.code
                not in {
                    "package_desired_revision_conflict",
                    "package_retention_handoff_stale",
                }
                or self.failure is None
                or self.failure.retryable
            ):
                raise ValueError("Rejected retention handoff result is inconsistent")
        else:
            raise ValueError("Unsupported retention handoff disposition")
        if (
            self.receipt is not None
            and self.receipt.request.handoff_id != self.handoff_id
        ):
            raise ValueError("Retention handoff result receipt changed")
        if self.failure is not None and self.failure.handoff_id != self.handoff_id:
            raise ValueError("Retention handoff result failure changed")
        if self.result_version != PACKAGE_RETENTION_HANDOFF_RESULT_VERSION:
            raise ValueError("Unsupported Package retention handoff result")

    @classmethod
    def settled(
        cls,
        receipt: PackageRetentionHandoffReceiptV1,
    ) -> PackageRetentionHandoffResultV1:
        return cls(
            handoff_id=receipt.request.handoff_id,
            disposition="settled",
            code="ok",
            receipt=receipt,
            failure=None,
        )

    @classmethod
    def interrupted(
        cls,
        receipt: PackageRetentionHandoffReceiptV1,
        failure: PackageRetentionHandoffFailureV1,
    ) -> PackageRetentionHandoffResultV1:
        return cls(
            handoff_id=receipt.request.handoff_id,
            disposition="retryable_failure",
            code="package_retention_handoff_interrupted",
            receipt=receipt,
            failure=failure,
        )

    @classmethod
    def desired_conflict(
        cls,
        receipt: PackageRetentionHandoffReceiptV1,
        failure: PackageRetentionHandoffFailureV1,
    ) -> PackageRetentionHandoffResultV1:
        return cls(
            handoff_id=receipt.request.handoff_id,
            disposition="rejected",
            code="package_desired_revision_conflict",
            receipt=receipt,
            failure=failure,
        )

    @classmethod
    def stale(
        cls,
        request: PackageRetentionHandoffRequestV1,
        receipt: PackageRetentionHandoffReceiptV1 | None,
    ) -> PackageRetentionHandoffResultV1:
        return cls(
            handoff_id=request.handoff_id,
            disposition="rejected",
            code="package_retention_handoff_stale",
            receipt=receipt,
            failure=PackageRetentionHandoffFailureV1.stale(request, receipt),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "disposition": self.disposition,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "handoffId": self.handoff_id,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageRetentionHandoffResultV1:
        document = _exact_dict(
            value,
            fields={
                "code",
                "disposition",
                "failure",
                "handoffId",
                "receipt",
                "resultVersion",
            },
            name="Package retention handoff result",
        )
        return cls(
            handoff_id=_wire_string(document["handoffId"], name="handoff id"),
            disposition=cast(
                PackageRetentionHandoffDisposition,
                _wire_string(document["disposition"], name="disposition"),
            ),
            code=cast(
                PackageRetentionHandoffCode,
                _wire_string(document["code"], name="result code"),
            ),
            receipt=(
                None
                if document["receipt"] is None
                else PackageRetentionHandoffReceiptV1.from_dict(document["receipt"])
            ),
            failure=(
                None
                if document["failure"] is None
                else PackageRetentionHandoffFailureV1.from_dict(document["failure"])
            ),
            result_version=_wire_int(document["resultVersion"], name="result version"),
        )


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffRecordV1:
    record_revision: int
    record_kind: PackageRetentionHandoffRecordKind
    prior_handoff_revision: int
    receipt: PackageRetentionHandoffReceiptV1 | None
    failure: PackageRetentionHandoffFailureV1 | None
    record_version: int = PACKAGE_RETENTION_HANDOFF_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.record_revision, name="handoff record revision")
        _require_nonnegative(
            self.prior_handoff_revision,
            name="prior handoff revision",
        )
        if self.record_kind == "handoff":
            if self.receipt is None or self.failure is not None:
                raise ValueError("Handoff record must contain one receipt")
            expected_prior = self.receipt.handoff_revision - 1
            if self.prior_handoff_revision != expected_prior:
                raise ValueError("Handoff record prior revision changed")
        elif self.record_kind == "handoff_attempt":
            if self.receipt is not None or self.failure is None:
                raise ValueError("Handoff attempt record must contain one failure")
            if not self.failure.retryable:
                raise ValueError("Only retryable handoff attempts are journaled")
        else:
            raise ValueError("Unsupported Package retention handoff record kind")
        if self.record_version != PACKAGE_RETENTION_HANDOFF_RECORD_VERSION:
            raise ValueError("Unsupported Package retention handoff record")

    @property
    def handoff_id(self) -> str:
        if self.receipt is not None:
            return self.receipt.request.handoff_id
        assert self.failure is not None
        return self.failure.handoff_id

    def to_dict(self) -> dict[str, object]:
        return {
            "failure": None if self.failure is None else self.failure.to_dict(),
            "handoffId": self.handoff_id,
            "priorHandoffRevision": self.prior_handoff_revision,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recordKind": self.record_kind,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageRetentionHandoffRecordV1:
        document = _exact_dict(
            value,
            fields={
                "failure",
                "handoffId",
                "priorHandoffRevision",
                "receipt",
                "recordKind",
                "recordRevision",
                "recordVersion",
            },
            name="Package retention handoff record",
        )
        record = cls(
            record_revision=_wire_int(
                document["recordRevision"], name="record revision"
            ),
            record_kind=cast(
                PackageRetentionHandoffRecordKind,
                _wire_string(document["recordKind"], name="record kind"),
            ),
            prior_handoff_revision=_wire_int(
                document["priorHandoffRevision"], name="prior handoff revision"
            ),
            receipt=(
                None
                if document["receipt"] is None
                else PackageRetentionHandoffReceiptV1.from_dict(document["receipt"])
            ),
            failure=(
                None
                if document["failure"] is None
                else PackageRetentionHandoffFailureV1.from_dict(document["failure"])
            ),
            record_version=_wire_int(document["recordVersion"], name="record version"),
        )
        if document["handoffId"] != record.handoff_id:
            raise ValueError("Package retention handoff record projection changed")
        return record


def _encode_handoff_record(
    record: PackageRetentionHandoffRecordV1,
) -> dict[str, object]:
    if not isinstance(record, PackageRetentionHandoffRecordV1):
        raise TypeError("Package retention handoff record is required")
    return record.to_dict()


def _decode_handoff_record(value: object) -> PackageRetentionHandoffRecordV1:
    try:
        return PackageRetentionHandoffRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package retention handoff record is invalid",
            code="invalid_package_retention_handoff_record",
        ) from exc


PACKAGE_RETENTION_HANDOFF_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_handoff_record,
    decoder=_decode_handoff_record,
)


class PackageRetentionHandoffJournal:
    """Durable monotonic handoff CAS with separate retry-attempt records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def open(
        self,
        request: PackageRetentionHandoffRequestV1,
    ) -> PackageRetentionHandoffReceiptV1:
        if not isinstance(request, PackageRetentionHandoffRequestV1):
            raise TypeError("Package retention handoff request is required")
        with self._exclusive():
            records = self._load_unlocked()
            current = _current_handoff(records, request.handoff_id)
            if current is not None:
                if current.request != request:
                    raise self._error(
                        "Package retention handoff request changed",
                        code="package_retention_handoff_stale",
                    )
                return current
            for record in records:
                receipt = record.receipt
                if receipt is None:
                    continue
                existing = receipt.request
                if (
                    existing.desired_request.command_id
                    == request.desired_request.command_id
                    or existing.desired_request.desired_request_id
                    == request.desired_request.desired_request_id
                    or existing.admission_request.admission_request_id
                    == request.admission_request.admission_request_id
                ):
                    raise self._error(
                        "Package retention handoff identity was reused",
                        code="package_retention_handoff_stale",
                    )
            opened = PackageRetentionHandoffReceiptV1.open(request)
            self._append_unlocked(
                records,
                PackageRetentionHandoffRecordV1(
                    record_revision=len(records) + 1,
                    record_kind="handoff",
                    prior_handoff_revision=0,
                    receipt=opened,
                    failure=None,
                ),
            )
            return opened

    def append(
        self,
        receipt: PackageRetentionHandoffReceiptV1,
    ) -> PackageRetentionHandoffReceiptV1:
        if not isinstance(receipt, PackageRetentionHandoffReceiptV1):
            raise TypeError("Package retention handoff receipt is required")
        with self._exclusive():
            records = self._load_unlocked()
            chain = tuple(
                record.receipt
                for record in records
                if record.handoff_id == receipt.request.handoff_id
                and record.receipt is not None
            )
            if not chain:
                raise self._error(
                    "Package retention handoff has not been opened",
                    code="package_retention_handoff_stale",
                )
            else:
                current = chain[-1]
                if receipt in chain:
                    return current
                if current.request != receipt.request:
                    raise self._error(
                        "Package retention handoff request changed",
                        code="package_retention_handoff_stale",
                    )
                try:
                    _validate_handoff_successor(current, receipt)
                except ValueError as exc:
                    raise self._error(
                        "Package retention handoff receipt is stale",
                        code="package_retention_handoff_stale",
                    ) from exc
            record = PackageRetentionHandoffRecordV1(
                record_revision=len(records) + 1,
                record_kind="handoff",
                prior_handoff_revision=receipt.handoff_revision - 1,
                receipt=receipt,
                failure=None,
            )
            self._append_unlocked(records, record)
            return receipt

    def record_failure(
        self,
        receipt: PackageRetentionHandoffReceiptV1,
        failure: PackageRetentionHandoffFailureV1,
    ) -> bool:
        if not isinstance(receipt, PackageRetentionHandoffReceiptV1):
            raise TypeError("Package retention handoff receipt is required")
        if not isinstance(failure, PackageRetentionHandoffFailureV1):
            raise TypeError("Package retention handoff failure is required")
        if (
            not failure.retryable
            or failure.handoff_id != receipt.request.handoff_id
            or failure.handoff_receipt_id != receipt.receipt_id
            or failure.phase != receipt.state
        ):
            raise ValueError("Package retention handoff failure context changed")
        with self._exclusive():
            records = self._load_unlocked()
            current = _current_handoff(records, receipt.request.handoff_id)
            if current != receipt:
                return False
            if any(record.failure == failure for record in records):
                return False
            self._append_unlocked(
                records,
                PackageRetentionHandoffRecordV1(
                    record_revision=len(records) + 1,
                    record_kind="handoff_attempt",
                    prior_handoff_revision=receipt.handoff_revision,
                    receipt=None,
                    failure=failure,
                ),
            )
            return True

    def current(self, handoff_id: str) -> PackageRetentionHandoffReceiptV1 | None:
        _require_sha256(handoff_id, name="retention handoff identity")
        with self._exclusive():
            return _current_handoff(self._load_unlocked(), handoff_id)

    def records(self) -> tuple[PackageRetentionHandoffRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _append_unlocked(
        self,
        records: tuple[PackageRetentionHandoffRecordV1, ...],
        record: PackageRetentionHandoffRecordV1,
    ) -> None:
        if record.record_revision != len(records) + 1:
            raise self._error(
                "Package retention handoff journal revision changed",
                code="package_retention_handoff_stale",
            )
        append_jsonl_record(
            self._path,
            record,
            record_codec=PACKAGE_RETENTION_HANDOFF_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PackageRetentionHandoffRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            _assert_no_duplicate_json_keys(self._path)
            snapshot: JsonlSnapshot[None, PackageRetentionHandoffRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_RETENTION_HANDOFF_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
        except (JournalFileError, OSError, UnicodeError, ValueError) as exc:
            raise self._error(
                "Package retention handoff journal cannot be decoded",
                code=(
                    exc.code
                    if isinstance(exc, JournalFileError)
                    and exc.code
                    in {
                        "invalid_package_retention_handoff_record",
                        "unsupported_package_retention_handoff_record_version",
                    }
                    else "package_retention_handoff_journal_corrupt"
                ),
            ) from exc
        records = snapshot.records
        try:
            _validate_handoff_records(records)
        except ValueError as exc:
            raise self._error(
                "Package retention handoff journal history is invalid",
                code="package_retention_handoff_journal_corrupt",
            ) from exc
        return records

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(self, message: str, *, code: str) -> PackageRetentionHandoffError:
        return PackageRetentionHandoffError(message, code=code, path=self._path)


class PackageRetentionHandoffOwner:
    """Lock-free saga across admission, retention, and desired-state owners."""

    def __init__(
        self,
        *,
        journal: PackageRetentionHandoffJournal,
        admission: PackageCommitAdmissionPort,
        retention: PackageRetentionSettlementPort,
        desired_state: PackageDesiredStateCommitPort,
    ) -> None:
        if not isinstance(journal, PackageRetentionHandoffJournal):
            raise TypeError("Package retention handoff journal is required")
        if not callable(getattr(admission, "admit", None)):
            raise TypeError("Package commit admission owner is required")
        if not all(
            callable(getattr(retention, method, None))
            for method in ("acquire", "abort", "settle")
        ):
            raise TypeError("Package retention settlement owner is required")
        if not callable(getattr(desired_state, "commit", None)):
            raise TypeError("Package desired-state commit owner is required")
        self._journal = journal
        self._admission = admission
        self._retention = retention
        self._desired_state = desired_state

    def execute(
        self,
        request: PackageRetentionHandoffRequestV1,
        *,
        expected_receipt: PackageRetentionHandoffReceiptV1 | None = None,
    ) -> PackageRetentionHandoffResultV1:
        if not isinstance(request, PackageRetentionHandoffRequestV1):
            raise TypeError("Package retention handoff request is required")
        if expected_receipt is not None and not isinstance(
            expected_receipt,
            PackageRetentionHandoffReceiptV1,
        ):
            raise TypeError("Expected Package retention handoff receipt is invalid")

        current = self._journal.current(request.handoff_id)
        if expected_receipt is not None and current != expected_receipt:
            return PackageRetentionHandoffResultV1.stale(request, current)
        terminal = self._terminal_result(current)
        if terminal is not None:
            return terminal

        if current is None:
            admission = self._admission.admit(request.admission_request)
            if (
                admission.disposition != "admitted"
                or admission.receipt != request.admission_receipt
            ):
                current = self._journal.current(request.handoff_id)
                if current is None or current.request != request:
                    return PackageRetentionHandoffResultV1.stale(request, current)
            else:
                current = self._journal.open(request)
        elif current.request != request:
            return PackageRetentionHandoffResultV1.stale(request, current)

        while True:
            terminal = self._terminal_result(current)
            if terminal is not None:
                return terminal
            if current.state == "opened":
                try:
                    dependency = self._retention.acquire(
                        request.dependency_pin_request,
                        transaction_pin_receipt=request.transaction_pin_receipt,
                    )
                except Exception:
                    return self._interrupted(current)
                if not _valid_acquired_dependency_receipt(request, dependency):
                    advanced = self._journal.current(request.handoff_id)
                    if advanced == current or (
                        advanced is not None and advanced.request != request
                    ):
                        return PackageRetentionHandoffResultV1.stale(request, advanced)
                    assert advanced is not None
                    current = advanced
                    continue
                current = self._journal.append(
                    PackageRetentionHandoffReceiptV1.dependency_pinned(
                        current,
                        dependency,
                    )
                )
                continue

            if current.state == "dependency_pinned":
                assert current.dependency_pin_receipt is not None
                dependency_receipt = current.dependency_pin_receipt
                try:
                    desired_result = self._desired_state.commit(request.desired_request)
                except Exception:
                    return self._interrupted(current)
                if (
                    not isinstance(desired_result, PackageDesiredStateCommitResultV1)
                    or desired_result.desired_request_id
                    != request.desired_request.desired_request_id
                ):
                    advanced = self._journal.current(request.handoff_id)
                    if advanced == current or (
                        advanced is not None and advanced.request != request
                    ):
                        return PackageRetentionHandoffResultV1.stale(request, advanced)
                    assert advanced is not None
                    current = advanced
                    continue
                if desired_result.disposition == "rejected":
                    failure = desired_result.failure
                    if failure is None or failure.request != request.desired_request:
                        return PackageRetentionHandoffResultV1.stale(request, current)
                    result_failure = PackageRetentionHandoffFailureV1.desired_conflict(
                        current,
                        failure,
                    )
                    try:
                        aborted_dependency = self._retention.abort(
                            dependency_receipt,
                            failure=failure,
                        )
                    except Exception:
                        return self._interrupted(current)
                    if not _valid_aborted_dependency_receipt(
                        dependency_receipt,
                        failure,
                        aborted_dependency,
                    ):
                        advanced = self._journal.current(request.handoff_id)
                        if advanced == current or (
                            advanced is not None and advanced.request != request
                        ):
                            return PackageRetentionHandoffResultV1.stale(
                                request,
                                advanced,
                            )
                        assert advanced is not None
                        current = advanced
                        continue
                    current = self._journal.append(
                        PackageRetentionHandoffReceiptV1.aborted(
                            current,
                            aborted_dependency,
                            failure,
                        )
                    )
                    terminal = self._terminal_result(current)
                    if terminal is not None:
                        return terminal
                    return PackageRetentionHandoffResultV1.desired_conflict(
                        current,
                        result_failure,
                    )
                desired_receipt = desired_result.receipt
                if (
                    desired_receipt is None
                    or desired_receipt.request != request.desired_request
                ):
                    advanced = self._journal.current(request.handoff_id)
                    if advanced == current or (
                        advanced is not None and advanced.request != request
                    ):
                        return PackageRetentionHandoffResultV1.stale(request, advanced)
                    assert advanced is not None
                    current = advanced
                    continue
                current = self._journal.append(
                    PackageRetentionHandoffReceiptV1.desired_committed(
                        current,
                        desired_receipt,
                    )
                )
                continue

            if current.state == "desired_committed":
                assert current.dependency_pin_receipt is not None
                assert current.desired_receipt is not None
                try:
                    settled_dependency = self._retention.settle(
                        current.dependency_pin_receipt,
                        desired_receipt=current.desired_receipt,
                    )
                except Exception:
                    return self._interrupted(current)
                if not _valid_settled_dependency_receipt(
                    current.dependency_pin_receipt,
                    current.desired_receipt,
                    settled_dependency,
                ):
                    advanced = self._journal.current(request.handoff_id)
                    if advanced == current or (
                        advanced is not None and advanced.request != request
                    ):
                        return PackageRetentionHandoffResultV1.stale(request, advanced)
                    assert advanced is not None
                    current = advanced
                    continue
                current = self._journal.append(
                    PackageRetentionHandoffReceiptV1.settled(
                        current,
                        settled_dependency,
                    )
                )
                continue

            raise PackageRetentionHandoffError(
                "Package retention handoff reached an unsupported state",
                code="package_retention_handoff_stale",
                path=self._journal.path,
            )

    def _interrupted(
        self,
        receipt: PackageRetentionHandoffReceiptV1,
    ) -> PackageRetentionHandoffResultV1:
        failure = PackageRetentionHandoffFailureV1.interrupted(receipt)
        self._journal.record_failure(receipt, failure)
        current = self._journal.current(receipt.request.handoff_id)
        terminal = self._terminal_result(current)
        if terminal is not None:
            return terminal
        if current != receipt:
            return PackageRetentionHandoffResultV1.stale(receipt.request, current)
        return PackageRetentionHandoffResultV1.interrupted(receipt, failure)

    @staticmethod
    def _terminal_result(
        receipt: PackageRetentionHandoffReceiptV1 | None,
    ) -> PackageRetentionHandoffResultV1 | None:
        if receipt is None:
            return None
        if receipt.state == "settled":
            return PackageRetentionHandoffResultV1.settled(receipt)
        if receipt.state == "aborted":
            assert receipt.desired_failure is not None
            return PackageRetentionHandoffResultV1.desired_conflict(
                receipt,
                PackageRetentionHandoffFailureV1.desired_conflict(
                    receipt,
                    receipt.desired_failure,
                ),
            )
        return None


def _desired_request_identity(
    *,
    command_id: str,
    command_fingerprint: str,
    expected_inventory_revision: int,
    operation_id: str,
    operation_fingerprint: str,
    request_fingerprint: str,
    attempt_epoch: int,
    product_id: str,
    scope_id: str,
    installation_id: str,
    plugin_id: str,
    committed_set_id: str,
    root_ref: PluginRevisionRefV1,
    request_version: int,
) -> dict[str, object]:
    return {
        "attemptEpoch": attempt_epoch,
        "commandFingerprint": command_fingerprint,
        "commandId": command_id,
        "committedSetId": committed_set_id,
        "expectedInventoryRevision": expected_inventory_revision,
        "installationId": installation_id,
        "operationFingerprint": operation_fingerprint,
        "operationId": operation_id,
        "pluginId": plugin_id,
        "productId": product_id,
        "requestFingerprint": request_fingerprint,
        "requestVersion": request_version,
        "rootRef": root_ref.to_dict(),
        "scopeId": scope_id,
    }


def _desired_receipt_identity(
    *,
    request: PackageDesiredStateCommitRequestV1,
    inventory_revision: int,
    owner_identity: str,
    owner_revision: int,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "inventoryRevision": inventory_revision,
        "ownerIdentity": owner_identity,
        "ownerRevision": owner_revision,
        "receiptVersion": receipt_version,
        "request": request.to_dict(),
    }


def _desired_failure_identity(
    *,
    request: PackageDesiredStateCommitRequestV1,
    observed_inventory_revision: int,
    owner_identity: str,
    owner_revision: int,
    code: str,
    failure_version: int,
) -> dict[str, object]:
    return {
        "code": code,
        "failureVersion": failure_version,
        "observedInventoryRevision": observed_inventory_revision,
        "ownerIdentity": owner_identity,
        "ownerRevision": owner_revision,
        "request": request.to_dict(),
    }


def _handoff_request_identity(
    *,
    admission_request: PackageCommitAdmissionRequestV1,
    admission_receipt: PackageCommitAdmissionReceiptV1,
    transaction_pin_receipt: PackageTransactionPinReceiptV1,
    desired_request: PackageDesiredStateCommitRequestV1,
    request_version: int,
) -> dict[str, object]:
    return {
        "admissionReceipt": admission_receipt.to_dict(),
        "admissionRequest": admission_request.to_dict(),
        "desiredRequest": desired_request.to_dict(),
        "requestVersion": request_version,
        "transactionPinReceipt": transaction_pin_receipt.to_dict(),
    }


def _dependency_pin_set_id(
    root_ref: PluginRevisionRefV1,
    dependency_refs: tuple[VerifiedArtifactRefV1, ...],
) -> str:
    return _fingerprint(
        {
            "dependencyRefs": [item.to_dict() for item in dependency_refs],
            "rootRef": root_ref.to_dict(),
        }
    )


def _dependency_pin_request_identity(
    *,
    handoff_id: str,
    operation_id: str,
    attempt_epoch: int,
    admission_id: str,
    publication_receipt_id: str,
    committed_set_id: str,
    transaction_pin_receipt_id: str,
    pin_set_id: str,
    root_ref: PluginRevisionRefV1,
    dependency_refs: tuple[VerifiedArtifactRefV1, ...],
    request_version: int,
) -> dict[str, object]:
    return {
        "admissionId": admission_id,
        "attemptEpoch": attempt_epoch,
        "committedSetId": committed_set_id,
        "dependencyRefs": [item.to_dict() for item in dependency_refs],
        "handoffId": handoff_id,
        "operationId": operation_id,
        "pinSetId": pin_set_id,
        "publicationReceiptId": publication_receipt_id,
        "requestVersion": request_version,
        "rootRef": root_ref.to_dict(),
        "transactionPinReceiptId": transaction_pin_receipt_id,
    }


def _dependency_pin_receipt_identity(
    *,
    request: PackageDependencyPinRequestV1,
    pin_ids: tuple[str, ...],
    owner_identity: str,
    owner_revision: int,
    lease_revision: int,
    state: PackageDependencyPinState,
    dependency_pins_live: bool,
    transaction_pin_receipt: PackageTransactionPinReceiptV1,
    prior_receipt_id: str | None,
    desired_receipt_id: str | None,
    transition_evidence_ref: str | None,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "dependencyPinsLive": dependency_pins_live,
        "desiredReceiptId": desired_receipt_id,
        "leaseRevision": lease_revision,
        "ownerIdentity": owner_identity,
        "ownerRevision": owner_revision,
        "pinIds": list(pin_ids),
        "priorReceiptId": prior_receipt_id,
        "receiptVersion": receipt_version,
        "request": request.to_dict(),
        "state": state,
        "transactionPinReceipt": transaction_pin_receipt.to_dict(),
        "transitionEvidenceRef": transition_evidence_ref,
    }


def _handoff_receipt_identity(
    *,
    request: PackageRetentionHandoffRequestV1,
    state: PackageRetentionHandoffState,
    handoff_revision: int,
    prior_receipt_id: str | None,
    dependency_pin_receipt: PackageDependencyPinReceiptV1 | None,
    desired_receipt: PackageDesiredStateCommitReceiptV1 | None,
    desired_failure: PackageDesiredStateCommitFailureV1 | None,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "dependencyPinReceipt": (
            None if dependency_pin_receipt is None else dependency_pin_receipt.to_dict()
        ),
        "desiredFailure": (
            None if desired_failure is None else desired_failure.to_dict()
        ),
        "desiredReceipt": (
            None if desired_receipt is None else desired_receipt.to_dict()
        ),
        "handoffRevision": handoff_revision,
        "priorReceiptId": prior_receipt_id,
        "receiptVersion": receipt_version,
        "request": request.to_dict(),
        "state": state,
    }


def _handoff_failure_identity(
    *,
    handoff_id: str,
    handoff_receipt_id: str | None,
    attempt_epoch: int,
    phase: PackageRetentionHandoffFailurePhase,
    code: PackageRetentionHandoffCode,
    retryable: bool,
    retry_domain: str,
    operator_action: str,
    evidence_ref: str,
    failure_version: int,
) -> dict[str, object]:
    return {
        "attemptEpoch": attempt_epoch,
        "code": code,
        "evidenceRef": evidence_ref,
        "failureVersion": failure_version,
        "handoffId": handoff_id,
        "handoffReceiptId": handoff_receipt_id,
        "operatorAction": operator_action,
        "phase": phase,
        "retryDomain": retry_domain,
        "retryable": retryable,
    }


def _require_acquired_dependency_receipt(
    receipt: PackageDependencyPinReceiptV1,
) -> None:
    if not isinstance(receipt, PackageDependencyPinReceiptV1):
        raise TypeError("Prior Package dependency pin receipt is required")
    if receipt.state != "acquired":
        raise ValueError("Package dependency pins are already terminal")


def _require_handoff_state(
    receipt: PackageRetentionHandoffReceiptV1,
    expected: PackageRetentionHandoffState,
) -> None:
    if not isinstance(receipt, PackageRetentionHandoffReceiptV1):
        raise TypeError("Prior Package retention handoff receipt is required")
    if receipt.state != expected:
        raise ValueError("Package retention handoff phase changed")


def _validate_handoff_successor(
    prior: PackageRetentionHandoffReceiptV1,
    successor: PackageRetentionHandoffReceiptV1,
) -> None:
    if (
        successor.request != prior.request
        or successor.handoff_revision != prior.handoff_revision + 1
        or successor.prior_receipt_id != prior.receipt_id
    ):
        raise ValueError("Package retention handoff CAS changed")
    if prior.state == "opened" and successor.state == "dependency_pinned":
        assert successor.dependency_pin_receipt is not None
        expected = PackageRetentionHandoffReceiptV1.dependency_pinned(
            prior,
            successor.dependency_pin_receipt,
        )
    elif prior.state == "dependency_pinned" and successor.state == "desired_committed":
        assert successor.desired_receipt is not None
        expected = PackageRetentionHandoffReceiptV1.desired_committed(
            prior,
            successor.desired_receipt,
        )
    elif prior.state == "dependency_pinned" and successor.state == "aborted":
        assert successor.dependency_pin_receipt is not None
        assert successor.desired_failure is not None
        expected = PackageRetentionHandoffReceiptV1.aborted(
            prior,
            successor.dependency_pin_receipt,
            successor.desired_failure,
        )
    elif prior.state == "desired_committed" and successor.state == "settled":
        assert successor.dependency_pin_receipt is not None
        expected = PackageRetentionHandoffReceiptV1.settled(
            prior,
            successor.dependency_pin_receipt,
        )
    else:
        raise ValueError("Illegal Package retention handoff transition")
    if successor != expected:
        raise ValueError("Package retention handoff successor evidence changed")


def _validate_handoff_records(
    records: tuple[PackageRetentionHandoffRecordV1, ...],
) -> None:
    current: dict[str, PackageRetentionHandoffReceiptV1] = {}
    command_owners: dict[str, str] = {}
    desired_request_owners: dict[str, str] = {}
    admission_owners: dict[str, str] = {}
    failures: set[str] = set()
    for index, record in enumerate(records, start=1):
        if record.record_revision != index:
            raise ValueError("Package retention handoff record revisions are not dense")
        if record.record_kind == "handoff":
            assert record.receipt is not None
            receipt = record.receipt
            prior = current.get(record.handoff_id)
            if prior is None:
                if receipt.state != "opened":
                    raise ValueError("Package retention handoff does not start opened")
                request = receipt.request
                identities = (
                    (
                        command_owners,
                        request.desired_request.command_id,
                    ),
                    (
                        desired_request_owners,
                        request.desired_request.desired_request_id,
                    ),
                    (
                        admission_owners,
                        request.admission_request.admission_request_id,
                    ),
                )
                for owners, identity in identities:
                    owner = owners.get(identity)
                    if owner is not None and owner != request.handoff_id:
                        raise ValueError(
                            "Package retention handoff identity was reused"
                        )
                    owners[identity] = request.handoff_id
            else:
                _validate_handoff_successor(prior, receipt)
            current[record.handoff_id] = receipt
        else:
            assert record.failure is not None
            failure = record.failure
            prior = current.get(record.handoff_id)
            if (
                prior is None
                or record.prior_handoff_revision != prior.handoff_revision
                or failure.handoff_receipt_id != prior.receipt_id
                or failure.phase != prior.state
                or failure.failure_id in failures
            ):
                raise ValueError("Package retention handoff attempt changed")
            failures.add(failure.failure_id)


def _current_handoff(
    records: tuple[PackageRetentionHandoffRecordV1, ...],
    handoff_id: str,
) -> PackageRetentionHandoffReceiptV1 | None:
    receipts = tuple(
        record.receipt
        for record in records
        if record.handoff_id == handoff_id and record.receipt is not None
    )
    return receipts[-1] if receipts else None


def _valid_acquired_dependency_receipt(
    handoff: PackageRetentionHandoffRequestV1,
    receipt: object,
) -> bool:
    return (
        isinstance(receipt, PackageDependencyPinReceiptV1)
        and receipt.state == "acquired"
        and receipt.request == handoff.dependency_pin_request
        and receipt.transaction_pin_receipt == handoff.transaction_pin_receipt
        and receipt.dependency_pins_live
    )


def _valid_aborted_dependency_receipt(
    prior: PackageDependencyPinReceiptV1,
    failure: PackageDesiredStateCommitFailureV1,
    receipt: object,
) -> bool:
    return (
        isinstance(receipt, PackageDependencyPinReceiptV1)
        and receipt.state == "aborted"
        and receipt.request == prior.request
        and receipt.pin_ids == prior.pin_ids
        and receipt.owner_identity == prior.owner_identity
        and receipt.owner_revision > prior.owner_revision
        and receipt.lease_revision > prior.lease_revision
        and receipt.prior_receipt_id == prior.receipt_id
        and receipt.transaction_pin_receipt == prior.transaction_pin_receipt
        and receipt.transition_evidence_ref == failure.failure_id
        and not receipt.dependency_pins_live
    )


def _valid_settled_dependency_receipt(
    prior: PackageDependencyPinReceiptV1,
    desired: PackageDesiredStateCommitReceiptV1,
    receipt: object,
) -> bool:
    return (
        isinstance(receipt, PackageDependencyPinReceiptV1)
        and receipt.state == "settled"
        and receipt.request == prior.request
        and receipt.pin_ids == prior.pin_ids
        and receipt.owner_identity == prior.owner_identity
        and receipt.owner_revision > prior.owner_revision
        and receipt.lease_revision > prior.lease_revision
        and receipt.prior_receipt_id == prior.receipt_id
        and receipt.desired_receipt_id == desired.receipt_id
        and receipt.transaction_pin_receipt.state == "released"
        and receipt.transaction_pin_receipt.prior_receipt_id
        == prior.transaction_pin_receipt.receipt_id
        and receipt.dependency_pins_live
    )


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be positive")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _exact_dict(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} does not match its versioned schema")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _wire_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package retention handoff has duplicate JSON keys")
        document[key] = value
    return document


__all__ = [
    "PACKAGE_RETENTION_HANDOFF_JOURNAL_CODEC",
    "PackageDependencyPinReceiptV1",
    "PackageDependencyPinRequestV1",
    "PackageDesiredStateCommitFailureV1",
    "PackageDesiredStateCommitPort",
    "PackageDesiredStateCommitReceiptV1",
    "PackageDesiredStateCommitRequestV1",
    "PackageDesiredStateCommitResultV1",
    "PackageRetentionHandoffError",
    "PackageRetentionHandoffFailureV1",
    "PackageRetentionHandoffJournal",
    "PackageRetentionHandoffOwner",
    "PackageRetentionHandoffReceiptV1",
    "PackageRetentionHandoffRecordV1",
    "PackageRetentionHandoffRequestV1",
    "PackageRetentionHandoffResultV1",
    "PackageRetentionSettlementPort",
]
