"""Dark PLC9B4a commit closure and read-only admission boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    CommittedPackageSetRefV1,
    PackageStableRefV1,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
    PackageCommittedSetJournalError,
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
    PackageLifecycleJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinJournalError,
    PackageTransactionPinReceiptV1,
)

PACKAGE_PUBLICATION_RECEIPT_VERSION = 1
PACKAGE_COMMIT_ADMISSION_REQUEST_VERSION = 1
PACKAGE_COMMIT_ADMISSION_FAILURE_VERSION = 1
PACKAGE_COMMIT_ADMISSION_RECEIPT_VERSION = 1
PACKAGE_COMMIT_ADMISSION_RESULT_VERSION = 1

PackageCommitAdmissionDisposition = Literal["admitted", "rejected"]
PackageCommitAdmissionCode = Literal["ok", "package_commit_admission_denied"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class PackageCommitEvidenceError(RuntimeError):
    """Fail-closed refusal to close a Package operation without exact evidence."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackagePublicationReceiptV1:
    """Immutable final receipt; contains stable evidence and no reopen authority."""

    receipt_id: str
    operation_id: str
    operation_fingerprint: str
    request_fingerprint: str
    attempt_epoch: int
    product_id: str
    scope_id: str
    installation_id: str
    plugin_id: str
    classification_fingerprint: str
    committed_set: CommittedPackageSetRefV1
    transaction_pin_receipt_id: str
    commit_status_revision: int
    receipt_version: int = PACKAGE_PUBLICATION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="Package publication receipt id")
        _require_safe_id(self.operation_id, name="Package operation identity")
        for value, name in (
            (self.operation_fingerprint, "Package operation fingerprint"),
            (self.request_fingerprint, "Package request fingerprint"),
            (self.classification_fingerprint, "classification fingerprint"),
            (self.transaction_pin_receipt_id, "transaction pin receipt id"),
        ):
            _require_sha256(value, name=name)
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        _require_positive(self.commit_status_revision, name="commit status revision")
        for value, name in (
            (self.product_id, "Product identity"),
            (self.scope_id, "scope identity"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
        ):
            _require_safe_id(value, name=name)
        if not isinstance(self.committed_set, CommittedPackageSetRefV1):
            raise TypeError("Committed Package set ref is required")
        committed = self.committed_set
        if (
            self.operation_fingerprint
            != package_operation_fingerprint(
                self.operation_id,
                self.request_fingerprint,
            )
            or committed.operation_id != self.operation_id
            or committed.attempt_epoch != self.attempt_epoch
            or committed.request_fingerprint != self.request_fingerprint
            or committed.product_id != self.product_id
            or committed.scope_id != self.scope_id
            or committed.installation_id != self.installation_id
            or committed.plugin_id != self.plugin_id
            or committed.classification_fingerprint
            != self.classification_fingerprint
        ):
            raise ValueError("Package publication receipt context changed")
        if self.receipt_version != PACKAGE_PUBLICATION_RECEIPT_VERSION:
            raise ValueError("Unsupported Package publication receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package publication receipt id does not match")

    @classmethod
    def create(
        cls,
        *,
        status: PackageLifecycleStatusV1,
        request: PackageLifecycleRequestV1,
        committed_record: PackageCommittedSetRecordV1,
        pin_receipt: PackageTransactionPinReceiptV1,
    ) -> PackagePublicationReceiptV1:
        _validate_commit_evidence(
            status=status,
            request=request,
            committed_record=committed_record,
            pin_receipt=pin_receipt,
            require_committed=True,
        )
        committed = committed_record.committed_set
        values = _publication_receipt_identity(
            operation_id=status.operation_id,
            operation_fingerprint=package_operation_fingerprint(
                status.operation_id,
                status.request_fingerprint,
            ),
            request_fingerprint=status.request_fingerprint,
            attempt_epoch=status.attempt_epoch,
            product_id=committed.product_id,
            scope_id=committed.scope_id,
            installation_id=committed.installation_id,
            plugin_id=committed.plugin_id,
            classification_fingerprint=committed.classification_fingerprint,
            committed_set=committed,
            transaction_pin_receipt_id=pin_receipt.receipt_id,
            commit_status_revision=status.journal_revision,
            receipt_version=PACKAGE_PUBLICATION_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            operation_id=status.operation_id,
            operation_fingerprint=package_operation_fingerprint(
                status.operation_id,
                status.request_fingerprint,
            ),
            request_fingerprint=status.request_fingerprint,
            attempt_epoch=status.attempt_epoch,
            product_id=committed.product_id,
            scope_id=committed.scope_id,
            installation_id=committed.installation_id,
            plugin_id=committed.plugin_id,
            classification_fingerprint=committed.classification_fingerprint,
            committed_set=committed,
            transaction_pin_receipt_id=pin_receipt.receipt_id,
            commit_status_revision=status.journal_revision,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _publication_receipt_identity(
            operation_id=self.operation_id,
            operation_fingerprint=self.operation_fingerprint,
            request_fingerprint=self.request_fingerprint,
            attempt_epoch=self.attempt_epoch,
            product_id=self.product_id,
            scope_id=self.scope_id,
            installation_id=self.installation_id,
            plugin_id=self.plugin_id,
            classification_fingerprint=self.classification_fingerprint,
            committed_set=self.committed_set,
            transaction_pin_receipt_id=self.transaction_pin_receipt_id,
            commit_status_revision=self.commit_status_revision,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackagePublicationReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "classificationFingerprint",
                "commitStatusRevision",
                "committedSet",
                "installationId",
                "operationFingerprint",
                "operationId",
                "pluginId",
                "productId",
                "receiptId",
                "receiptVersion",
                "requestFingerprint",
                "scopeId",
                "transactionPinReceiptId",
            },
            name="Package publication receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
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
            classification_fingerprint=_wire_string(
                document["classificationFingerprint"],
                name="classification fingerprint",
            ),
            committed_set=CommittedPackageSetRefV1.from_dict(
                document["committedSet"]
            ),
            transaction_pin_receipt_id=_wire_string(
                document["transactionPinReceiptId"],
                name="transaction pin receipt id",
            ),
            commit_status_revision=_wire_int(
                document["commitStatusRevision"], name="commit status revision"
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageCommitAdmissionRequestV1:
    """One self-identifying claim against a durable publication receipt."""

    admission_request_id: str
    operation_id: str
    operation_fingerprint: str
    request_fingerprint: str
    product_id: str
    scope_id: str
    installation_id: str
    plugin_id: str
    claimed_root_ref: PackageStableRefV1
    committed_set_id: str
    closure_lock_digest: str
    publication_receipt: PackagePublicationReceiptV1 | None
    request_version: int = PACKAGE_COMMIT_ADMISSION_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(
            self.admission_request_id,
            name="commit admission request id",
        )
        _require_safe_id(self.operation_id, name="Package operation identity")
        for value, name in (
            (self.operation_fingerprint, "Package operation fingerprint"),
            (self.request_fingerprint, "Package request fingerprint"),
            (self.committed_set_id, "committed Package set id"),
            (self.closure_lock_digest, "closure lock digest"),
        ):
            _require_sha256(value, name=name)
        if self.operation_fingerprint != package_operation_fingerprint(
            self.operation_id,
            self.request_fingerprint,
        ):
            raise ValueError("Commit admission operation fingerprint changed")
        for value, name in (
            (self.product_id, "Product identity"),
            (self.scope_id, "scope identity"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
        ):
            _require_safe_id(value, name=name)
        if not isinstance(
            self.claimed_root_ref,
            (PluginRevisionRefV1, VerifiedArtifactRefV1),
        ):
            raise TypeError("Typed Package stable ref is required")
        if self.publication_receipt is not None and not isinstance(
            self.publication_receipt,
            PackagePublicationReceiptV1,
        ):
            raise TypeError("Package publication receipt is invalid")
        if self.request_version != PACKAGE_COMMIT_ADMISSION_REQUEST_VERSION:
            raise ValueError("Unsupported Package commit admission request")
        if self.admission_request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package commit admission request id does not match")

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        request_fingerprint: str,
        product_id: str,
        scope_id: str,
        installation_id: str,
        plugin_id: str,
        claimed_root_ref: PackageStableRefV1,
        committed_set_id: str,
        closure_lock_digest: str,
        publication_receipt: PackagePublicationReceiptV1 | None,
    ) -> PackageCommitAdmissionRequestV1:
        operation_fingerprint = package_operation_fingerprint(
            operation_id,
            request_fingerprint,
        )
        values = _admission_request_identity(
            operation_id=operation_id,
            operation_fingerprint=operation_fingerprint,
            request_fingerprint=request_fingerprint,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
            claimed_root_ref=claimed_root_ref,
            committed_set_id=committed_set_id,
            closure_lock_digest=closure_lock_digest,
            publication_receipt=publication_receipt,
            request_version=PACKAGE_COMMIT_ADMISSION_REQUEST_VERSION,
        )
        return cls(
            admission_request_id=_fingerprint(values),
            operation_id=operation_id,
            operation_fingerprint=operation_fingerprint,
            request_fingerprint=request_fingerprint,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
            claimed_root_ref=claimed_root_ref,
            committed_set_id=committed_set_id,
            closure_lock_digest=closure_lock_digest,
            publication_receipt=publication_receipt,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _admission_request_identity(
            operation_id=self.operation_id,
            operation_fingerprint=self.operation_fingerprint,
            request_fingerprint=self.request_fingerprint,
            product_id=self.product_id,
            scope_id=self.scope_id,
            installation_id=self.installation_id,
            plugin_id=self.plugin_id,
            claimed_root_ref=self.claimed_root_ref,
            committed_set_id=self.committed_set_id,
            closure_lock_digest=self.closure_lock_digest,
            publication_receipt=self.publication_receipt,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"admissionRequestId": self.admission_request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageCommitAdmissionRequestV1:
        document = _exact_dict(
            value,
            fields={
                "admissionRequestId",
                "claimedRootRef",
                "claimedRootRefKind",
                "closureLockDigest",
                "committedSetId",
                "installationId",
                "operationFingerprint",
                "operationId",
                "pluginId",
                "productId",
                "publicationReceipt",
                "requestFingerprint",
                "requestVersion",
                "scopeId",
            },
            name="Package commit admission request",
        )
        kind = _wire_string(
            document["claimedRootRefKind"],
            name="claimed root ref kind",
        )
        if kind == "plugin_revision":
            claimed_ref: PackageStableRefV1 = PluginRevisionRefV1.from_dict(
                document["claimedRootRef"]
            )
        elif kind == "verified_artifact":
            claimed_ref = VerifiedArtifactRefV1.from_dict(document["claimedRootRef"])
        else:
            raise ValueError("Unsupported claimed Package stable ref kind")
        return cls(
            admission_request_id=_wire_string(
                document["admissionRequestId"], name="admission request id"
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
            product_id=_wire_string(document["productId"], name="Product identity"),
            scope_id=_wire_string(document["scopeId"], name="scope identity"),
            installation_id=_wire_string(
                document["installationId"], name="Installation identity"
            ),
            plugin_id=_wire_string(document["pluginId"], name="Plugin identity"),
            claimed_root_ref=claimed_ref,
            committed_set_id=_wire_string(
                document["committedSetId"], name="committed set id"
            ),
            closure_lock_digest=_wire_string(
                document["closureLockDigest"], name="closure lock digest"
            ),
            publication_receipt=(
                None
                if document["publicationReceipt"] is None
                else PackagePublicationReceiptV1.from_dict(
                    document["publicationReceipt"]
                )
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageCommitAdmissionFailureV1:
    failure_id: str
    admission_request_id: str
    operation_id: str
    evidence_ref: str
    code: Literal["package_commit_admission_denied"] = (
        "package_commit_admission_denied"
    )
    failure_version: int = PACKAGE_COMMIT_ADMISSION_FAILURE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.failure_id, "commit admission failure id"),
            (self.admission_request_id, "commit admission request id"),
            (self.evidence_ref, "commit admission evidence ref"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.operation_id, name="Package operation identity")
        if self.code != "package_commit_admission_denied":
            raise ValueError("Unsupported Package commit admission failure")
        if self.failure_version != PACKAGE_COMMIT_ADMISSION_FAILURE_VERSION:
            raise ValueError("Unsupported Package commit admission failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package commit admission failure id does not match")

    @classmethod
    def deny(
        cls,
        request: PackageCommitAdmissionRequestV1,
    ) -> PackageCommitAdmissionFailureV1:
        values = {
            "admissionRequestId": request.admission_request_id,
            "code": "package_commit_admission_denied",
            "evidenceRef": request.admission_request_id,
            "failureVersion": PACKAGE_COMMIT_ADMISSION_FAILURE_VERSION,
            "operationId": request.operation_id,
        }
        return cls(
            failure_id=_fingerprint(values),
            admission_request_id=request.admission_request_id,
            operation_id=request.operation_id,
            evidence_ref=request.admission_request_id,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "admissionRequestId": self.admission_request_id,
            "code": self.code,
            "evidenceRef": self.evidence_ref,
            "failureVersion": self.failure_version,
            "operationId": self.operation_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageCommitAdmissionFailureV1:
        document = _exact_dict(
            value,
            fields={
                "admissionRequestId",
                "code",
                "evidenceRef",
                "failureId",
                "failureVersion",
                "operationId",
            },
            name="Package commit admission failure",
        )
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            admission_request_id=_wire_string(
                document["admissionRequestId"], name="admission request id"
            ),
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
            ),
            evidence_ref=_wire_string(
                document["evidenceRef"], name="evidence ref"
            ),
            code=cast(
                Literal["package_commit_admission_denied"],
                _wire_string(document["code"], name="failure code"),
            ),
            failure_version=_wire_int(
                document["failureVersion"], name="failure version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageCommitAdmissionReceiptV1:
    """Read-only proof that a root was admitted; never a live store handle."""

    admission_id: str
    admission_request_id: str
    publication_receipt_id: str
    operation_fingerprint: str
    committed_set_id: str
    closure_lock_digest: str
    transaction_pin_receipt_id: str
    root_ref: PluginRevisionRefV1
    receipt_version: int = PACKAGE_COMMIT_ADMISSION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.admission_id, "commit admission receipt id"),
            (self.admission_request_id, "commit admission request id"),
            (self.publication_receipt_id, "Package publication receipt id"),
            (self.operation_fingerprint, "Package operation fingerprint"),
            (self.committed_set_id, "committed Package set id"),
            (self.closure_lock_digest, "closure lock digest"),
            (self.transaction_pin_receipt_id, "transaction pin receipt id"),
        ):
            _require_sha256(value, name=name)
        if not isinstance(self.root_ref, PluginRevisionRefV1):
            raise TypeError("Admitted Plugin revision ref is required")
        if self.receipt_version != PACKAGE_COMMIT_ADMISSION_RECEIPT_VERSION:
            raise ValueError("Unsupported Package commit admission receipt")
        if self.admission_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package commit admission receipt id does not match")

    @classmethod
    def create(
        cls,
        request: PackageCommitAdmissionRequestV1,
        publication: PackagePublicationReceiptV1,
    ) -> PackageCommitAdmissionReceiptV1:
        root_ref = publication.committed_set.root_ref
        values = {
            "admissionRequestId": request.admission_request_id,
            "closureLockDigest": publication.committed_set.closure_lock_digest,
            "committedSetId": publication.committed_set.set_id,
            "operationFingerprint": publication.operation_fingerprint,
            "publicationReceiptId": publication.receipt_id,
            "receiptVersion": PACKAGE_COMMIT_ADMISSION_RECEIPT_VERSION,
            "rootRef": root_ref.to_dict(),
            "transactionPinReceiptId": publication.transaction_pin_receipt_id,
        }
        return cls(
            admission_id=_fingerprint(values),
            admission_request_id=request.admission_request_id,
            publication_receipt_id=publication.receipt_id,
            operation_fingerprint=publication.operation_fingerprint,
            committed_set_id=publication.committed_set.set_id,
            closure_lock_digest=publication.committed_set.closure_lock_digest,
            transaction_pin_receipt_id=publication.transaction_pin_receipt_id,
            root_ref=root_ref,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "admissionRequestId": self.admission_request_id,
            "closureLockDigest": self.closure_lock_digest,
            "committedSetId": self.committed_set_id,
            "operationFingerprint": self.operation_fingerprint,
            "publicationReceiptId": self.publication_receipt_id,
            "receiptVersion": self.receipt_version,
            "rootRef": self.root_ref.to_dict(),
            "transactionPinReceiptId": self.transaction_pin_receipt_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {"admissionId": self.admission_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageCommitAdmissionReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "admissionId",
                "admissionRequestId",
                "closureLockDigest",
                "committedSetId",
                "operationFingerprint",
                "publicationReceiptId",
                "receiptVersion",
                "rootRef",
                "transactionPinReceiptId",
            },
            name="Package commit admission receipt",
        )
        return cls(
            admission_id=_wire_string(document["admissionId"], name="admission id"),
            admission_request_id=_wire_string(
                document["admissionRequestId"], name="admission request id"
            ),
            publication_receipt_id=_wire_string(
                document["publicationReceiptId"], name="publication receipt id"
            ),
            operation_fingerprint=_wire_string(
                document["operationFingerprint"], name="operation fingerprint"
            ),
            committed_set_id=_wire_string(
                document["committedSetId"], name="committed set id"
            ),
            closure_lock_digest=_wire_string(
                document["closureLockDigest"], name="closure lock digest"
            ),
            transaction_pin_receipt_id=_wire_string(
                document["transactionPinReceiptId"], name="transaction pin receipt id"
            ),
            root_ref=PluginRevisionRefV1.from_dict(document["rootRef"]),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageCommitAdmissionResultV1:
    admission_request_id: str
    disposition: PackageCommitAdmissionDisposition
    code: PackageCommitAdmissionCode
    receipt: PackageCommitAdmissionReceiptV1 | None
    failure: PackageCommitAdmissionFailureV1 | None
    result_version: int = PACKAGE_COMMIT_ADMISSION_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.admission_request_id, name="admission request id")
        if self.disposition == "admitted":
            if self.code != "ok" or self.receipt is None or self.failure is not None:
                raise ValueError("Admitted Package result is inconsistent")
            if self.receipt.admission_request_id != self.admission_request_id:
                raise ValueError("Admission result request changed")
        elif self.disposition == "rejected":
            if (
                self.code != "package_commit_admission_denied"
                or self.receipt is not None
                or self.failure is None
            ):
                raise ValueError("Rejected Package result is inconsistent")
            if self.failure.admission_request_id != self.admission_request_id:
                raise ValueError("Admission failure request changed")
        else:
            raise ValueError("Unsupported Package commit admission disposition")
        if self.result_version != PACKAGE_COMMIT_ADMISSION_RESULT_VERSION:
            raise ValueError("Unsupported Package commit admission result")

    @classmethod
    def admitted(
        cls,
        request: PackageCommitAdmissionRequestV1,
        publication: PackagePublicationReceiptV1,
    ) -> PackageCommitAdmissionResultV1:
        return cls(
            admission_request_id=request.admission_request_id,
            disposition="admitted",
            code="ok",
            receipt=PackageCommitAdmissionReceiptV1.create(request, publication),
            failure=None,
        )

    @classmethod
    def rejected(
        cls,
        request: PackageCommitAdmissionRequestV1,
    ) -> PackageCommitAdmissionResultV1:
        return cls(
            admission_request_id=request.admission_request_id,
            disposition="rejected",
            code="package_commit_admission_denied",
            receipt=None,
            failure=PackageCommitAdmissionFailureV1.deny(request),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionRequestId": self.admission_request_id,
            "code": self.code,
            "disposition": self.disposition,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageCommitAdmissionResultV1:
        document = _exact_dict(
            value,
            fields={
                "admissionRequestId",
                "code",
                "disposition",
                "failure",
                "receipt",
                "resultVersion",
            },
            name="Package commit admission result",
        )
        return cls(
            admission_request_id=_wire_string(
                document["admissionRequestId"], name="admission request id"
            ),
            disposition=cast(
                PackageCommitAdmissionDisposition,
                _wire_string(document["disposition"], name="disposition"),
            ),
            code=cast(
                PackageCommitAdmissionCode,
                _wire_string(document["code"], name="admission code"),
            ),
            receipt=(
                None
                if document["receipt"] is None
                else PackageCommitAdmissionReceiptV1.from_dict(document["receipt"])
            ),
            failure=(
                None
                if document["failure"] is None
                else PackageCommitAdmissionFailureV1.from_dict(document["failure"])
            ),
            result_version=_wire_int(
                document["resultVersion"], name="result version"
            ),
        )


class PackageCommitAdmissionPort(Protocol):
    """Read-only selection proof; the port cannot reopen a revision."""

    def admit(
        self,
        request: PackageCommitAdmissionRequestV1,
    ) -> PackageCommitAdmissionResultV1: ...


class PackageCommitLifecycleOwner:
    """Sole writer of the set_published -> committed operation CAS."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        committed_sets: PackageCommittedSetJournal,
        pin_journal: PackageTransactionPinJournal,
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not isinstance(committed_sets, PackageCommittedSetJournal):
            raise TypeError("Package committed-set journal is required")
        if not isinstance(pin_journal, PackageTransactionPinJournal):
            raise TypeError("Package transaction-pin journal is required")
        self._kernel = kernel
        self._committed_sets = committed_sets
        self._pin_journal = pin_journal

    def commit(self, operation_id: str) -> PackagePublicationReceiptV1:
        status, request, committed, pin = self._evidence(operation_id)
        try:
            if status.phase == "set_published" and status.disposition == "active":
                _validate_commit_evidence(
                    status=status,
                    request=request,
                    committed_record=committed,
                    pin_receipt=pin,
                    require_committed=False,
                )
                prior = status
                try:
                    status = self._kernel.advance(
                        operation_id,
                        next_phase="committed",
                        expected_phase="set_published",
                        expected_journal_revision=status.journal_revision,
                        expected_attempt_epoch=status.attempt_epoch,
                    )
                except PackageLifecycleJournalError:
                    winner = self._kernel.status(operation_id)
                    if (
                        winner is None
                        or winner.phase != "committed"
                        or winner.disposition != "committed"
                        or winner.request_fingerprint != prior.request_fingerprint
                        or winner.attempt_epoch != prior.attempt_epoch
                    ):
                        raise
                    status = winner
            return PackagePublicationReceiptV1.create(
                status=status,
                request=request,
                committed_record=committed,
                pin_receipt=pin,
            )
        except (PackageLifecycleJournalError, TypeError, ValueError) as exc:
            raise PackageCommitEvidenceError(
                "Package commit evidence is incomplete or inconsistent",
                code="package_operation_identity_conflict",
            ) from exc

    def _evidence(
        self,
        operation_id: str,
    ) -> tuple[
        PackageLifecycleStatusV1,
        PackageLifecycleRequestV1,
        PackageCommittedSetRecordV1,
        PackageTransactionPinReceiptV1,
    ]:
        try:
            status = self._kernel.status(operation_id)
            request = self._kernel.journal.request(operation_id)
            committed = self._committed_sets.current(operation_id)
            pin = self._pin_journal.current_for_operation(operation_id)
        except (
            PackageLifecycleJournalError,
            PackageCommittedSetJournalError,
            PackageTransactionPinJournalError,
        ) as exc:
            raise PackageCommitEvidenceError(
                "Package commit evidence cannot be read",
                code="package_operation_identity_conflict",
            ) from exc
        if status is None or request is None or committed is None or pin is None:
            raise PackageCommitEvidenceError(
                "Package commit evidence is incomplete",
                code="package_operation_identity_conflict",
            )
        return status, request, committed, pin


class PackageCommitAdmissionOwner:
    """Candidate-free verifier over immutable journals; performs no writes."""

    def __init__(
        self,
        *,
        lifecycle_journal: PackageLifecycleJournal,
        committed_sets: PackageCommittedSetJournal,
        pin_journal: PackageTransactionPinJournal,
    ) -> None:
        if not isinstance(lifecycle_journal, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(committed_sets, PackageCommittedSetJournal):
            raise TypeError("Package committed-set journal is required")
        if not isinstance(pin_journal, PackageTransactionPinJournal):
            raise TypeError("Package transaction-pin journal is required")
        self._lifecycle_journal = lifecycle_journal
        self._committed_sets = committed_sets
        self._pin_journal = pin_journal

    def admit(
        self,
        request: PackageCommitAdmissionRequestV1,
    ) -> PackageCommitAdmissionResultV1:
        if not isinstance(request, PackageCommitAdmissionRequestV1):
            raise TypeError("Package commit admission request is required")
        publication = request.publication_receipt
        if publication is None:
            return PackageCommitAdmissionResultV1.rejected(request)
        try:
            status = self._lifecycle_journal.status(request.operation_id)
            lifecycle_request = self._lifecycle_journal.request(request.operation_id)
            committed = self._committed_sets.current(request.operation_id)
            pin = self._pin_journal.current_for_operation(request.operation_id)
            if (
                status is None
                or lifecycle_request is None
                or committed is None
                or pin is None
            ):
                return PackageCommitAdmissionResultV1.rejected(request)
            expected = PackagePublicationReceiptV1.create(
                status=status,
                request=lifecycle_request,
                committed_record=committed,
                pin_receipt=pin,
            )
        except (
            PackageLifecycleJournalError,
            PackageCommittedSetJournalError,
            PackageTransactionPinJournalError,
            TypeError,
            ValueError,
        ):
            return PackageCommitAdmissionResultV1.rejected(request)
        if not _claim_matches(request, expected):
            return PackageCommitAdmissionResultV1.rejected(request)
        return PackageCommitAdmissionResultV1.admitted(request, expected)


def package_operation_fingerprint(
    operation_id: str,
    request_fingerprint: str,
) -> str:
    _require_safe_id(operation_id, name="Package operation identity")
    _require_sha256(request_fingerprint, name="Package request fingerprint")
    return _fingerprint(
        {
            "operationId": operation_id,
            "requestFingerprint": request_fingerprint,
        }
    )


def _claim_matches(
    request: PackageCommitAdmissionRequestV1,
    expected: PackagePublicationReceiptV1,
) -> bool:
    committed = expected.committed_set
    return bool(
        request.publication_receipt == expected
        and request.operation_id == expected.operation_id
        and request.operation_fingerprint == expected.operation_fingerprint
        and request.request_fingerprint == expected.request_fingerprint
        and request.product_id == expected.product_id
        and request.scope_id == expected.scope_id
        and request.installation_id == expected.installation_id
        and request.plugin_id == expected.plugin_id
        and isinstance(request.claimed_root_ref, PluginRevisionRefV1)
        and request.claimed_root_ref == committed.root_ref
        and request.committed_set_id == committed.set_id
        and request.closure_lock_digest == committed.closure_lock_digest
    )


def _validate_commit_evidence(
    *,
    status: PackageLifecycleStatusV1,
    request: PackageLifecycleRequestV1,
    committed_record: PackageCommittedSetRecordV1,
    pin_receipt: PackageTransactionPinReceiptV1,
    require_committed: bool,
) -> None:
    for value, expected_type, name in (
        (status, PackageLifecycleStatusV1, "Package lifecycle status"),
        (request, PackageLifecycleRequestV1, "Package lifecycle request"),
        (committed_record, PackageCommittedSetRecordV1, "Package committed set"),
        (pin_receipt, PackageTransactionPinReceiptV1, "Package transaction pin"),
    ):
        if not isinstance(value, expected_type):
            raise TypeError(f"{name} is required")
    allowed_status = (
        status.phase == "committed" and status.disposition == "committed"
        if require_committed
        else status.phase == "set_published" and status.disposition == "active"
    )
    committed = committed_record.committed_set
    pin_request = pin_receipt.pin_request
    classification = status.classification
    if (
        not allowed_status
        or classification is None
        or classification.decision != "plugin_bound"
        or status.operation_id != request.operation_id
        or status.request_fingerprint != request.request_fingerprint
        or classification.request_fingerprint != status.request_fingerprint
        or committed_record.operation_id != status.operation_id
        or committed.operation_id != status.operation_id
        or committed.attempt_epoch != status.attempt_epoch
        or committed.request_fingerprint != status.request_fingerprint
        or committed.product_id != request.product_id
        or committed.scope_id != request.scope_id
        or (
            request.requested_plugin_id is not None
            and committed.plugin_id != request.requested_plugin_id
        )
        or committed.classification_fingerprint != classification.evidence_ref
        or committed.closure_lock_digest != committed_record.closure_lock.lock_digest
        or committed.prepublication_graph_digest
        != committed_record.closure_lock.prepublication_graph_digest
        or committed.root_ref
        != next(
            node.stable_ref
            for node in committed_record.closure_lock.nodes
            if node.plan_node.role == "root"
        )
        or pin_receipt.state != "acquired"
        or pin_request.operation_id != status.operation_id
        or pin_request.attempt_epoch > status.attempt_epoch
        or pin_request.request_fingerprint != status.request_fingerprint
        or pin_request.classification_fingerprint != classification.evidence_ref
        or pin_request.prepublication_graph_digest
        != committed.prepublication_graph_digest
        or not _pin_targets_match_lock(pin_receipt, committed_record)
    ):
        raise ValueError("Package commit evidence does not form one exact transaction")


def _pin_targets_match_lock(
    receipt: PackageTransactionPinReceiptV1,
    committed_record: PackageCommittedSetRecordV1,
) -> bool:
    nodes = committed_record.closure_lock.nodes
    targets = receipt.pin_request.targets
    if len(nodes) != len(targets):
        return False
    by_node = {target.node_id: target for target in targets}
    for node in nodes:
        target = by_node.get(node.node_id)
        if target is None or (
            target.role != node.plan_node.role
            or target.distribution != node.plan_node.distribution
            or target.version != node.plan_node.version
            or target.artifact_digest != node.plan_node.artifact_digest
            or target.extraction_tree_digest
            != node.plan_node.extraction_tree_digest
            or target.wheel_evidence_fingerprint
            != node.plan_node.wheel_evidence_fingerprint
        ):
            return False
    root = next(node for node in nodes if node.plan_node.role == "root")
    root_target = by_node[root.node_id]
    return receipt.pin_request.root_target_id == root_target.target_id


def _publication_receipt_identity(
    *,
    operation_id: str,
    operation_fingerprint: str,
    request_fingerprint: str,
    attempt_epoch: int,
    product_id: str,
    scope_id: str,
    installation_id: str,
    plugin_id: str,
    classification_fingerprint: str,
    committed_set: CommittedPackageSetRefV1,
    transaction_pin_receipt_id: str,
    commit_status_revision: int,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "attemptEpoch": attempt_epoch,
        "classificationFingerprint": classification_fingerprint,
        "commitStatusRevision": commit_status_revision,
        "committedSet": committed_set.to_dict(),
        "installationId": installation_id,
        "operationFingerprint": operation_fingerprint,
        "operationId": operation_id,
        "pluginId": plugin_id,
        "productId": product_id,
        "receiptVersion": receipt_version,
        "requestFingerprint": request_fingerprint,
        "scopeId": scope_id,
        "transactionPinReceiptId": transaction_pin_receipt_id,
    }


def _admission_request_identity(
    *,
    operation_id: str,
    operation_fingerprint: str,
    request_fingerprint: str,
    product_id: str,
    scope_id: str,
    installation_id: str,
    plugin_id: str,
    claimed_root_ref: PackageStableRefV1,
    committed_set_id: str,
    closure_lock_digest: str,
    publication_receipt: PackagePublicationReceiptV1 | None,
    request_version: int,
) -> dict[str, object]:
    return {
        "claimedRootRef": claimed_root_ref.to_dict(),
        "claimedRootRefKind": (
            "plugin_revision"
            if isinstance(claimed_root_ref, PluginRevisionRefV1)
            else "verified_artifact"
        ),
        "closureLockDigest": closure_lock_digest,
        "committedSetId": committed_set_id,
        "installationId": installation_id,
        "operationFingerprint": operation_fingerprint,
        "operationId": operation_id,
        "pluginId": plugin_id,
        "productId": product_id,
        "publicationReceipt": (
            None if publication_receipt is None else publication_receipt.to_dict()
        ),
        "requestFingerprint": request_fingerprint,
        "requestVersion": request_version,
        "scopeId": scope_id,
    }


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} does not match its versioned schema")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_positive(value: int, *, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be positive")
