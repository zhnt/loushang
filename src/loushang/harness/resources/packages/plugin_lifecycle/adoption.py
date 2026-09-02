"""Dark PLC9B4c4a protocol for authenticated legacy Package adoption.

The coordinator owns no filesystem, network, credential, Desired, binding,
Instance, enablement, or publication capability.  It binds one already-opened
B transaction to the current epoch and to a complete observation of immutable
legacy state, then accepts only an exact committed publication receipt while
the fence and legacy observation remain unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceReadPort,
    PackageEpochFenceReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)

PACKAGE_LEGACY_STATE_EVIDENCE_VERSION = 1
PACKAGE_LEGACY_ADOPTION_REQUEST_VERSION = 1
PACKAGE_LEGACY_ADOPTION_TRANSACTION_RESULT_VERSION = 1
PACKAGE_LEGACY_ADOPTION_RECEIPT_VERSION = 1
PACKAGE_LEGACY_ADOPTION_FAILURE_VERSION = 1
PACKAGE_LEGACY_ADOPTION_RESULT_VERSION = 1

PackageLegacyAdoptionDisposition = Literal[
    "adopted",
    "rejected",
    "retryable_failure",
]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_CODE = re.compile(r"package_[a-z0-9_]{1,95}\Z")
_COORDINATOR_FAILURE_CODES = frozenset(
    {
        "package_operation_identity_conflict",
        "package_runtime_epoch_unsupported",
    }
)


@dataclass(frozen=True, slots=True)
class PackageLegacyStateEvidenceV1:
    """Complete credential-free observation of the immutable legacy namespace."""

    evidence_id: str
    store_id: str
    legacy_root_identity: str
    state_digest: str
    entry_count: int
    byte_count: int
    covered_domains: tuple[str, ...] = PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    evidence_version: int = PACKAGE_LEGACY_STATE_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.evidence_id, name="legacy state evidence identity")
        _require_safe_id(self.store_id, name="Package store identity")
        _require_sha256(
            self.legacy_root_identity,
            name="legacy Package root identity",
        )
        _require_sha256(self.state_digest, name="legacy Package state digest")
        _require_non_negative(self.entry_count, name="legacy state entry count")
        _require_non_negative(self.byte_count, name="legacy state byte count")
        if self.covered_domains != PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Legacy Package state domains are incomplete")
        if self.evidence_version != PACKAGE_LEGACY_STATE_EVIDENCE_VERSION:
            raise ValueError("Unsupported legacy Package state evidence")
        if self.evidence_id != _fingerprint(self._identity_dict()):
            raise ValueError("Legacy Package state evidence does not match")

    @classmethod
    def create(
        cls,
        *,
        store_id: str,
        legacy_root_identity: str,
        state_digest: str,
        entry_count: int,
        byte_count: int,
    ) -> PackageLegacyStateEvidenceV1:
        values = _legacy_state_identity(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            state_digest=state_digest,
            entry_count=entry_count,
            byte_count=byte_count,
            covered_domains=PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
            evidence_version=PACKAGE_LEGACY_STATE_EVIDENCE_VERSION,
        )
        return cls(
            evidence_id=_fingerprint(values),
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            state_digest=state_digest,
            entry_count=entry_count,
            byte_count=byte_count,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _legacy_state_identity(
            store_id=self.store_id,
            legacy_root_identity=self.legacy_root_identity,
            state_digest=self.state_digest,
            entry_count=self.entry_count,
            byte_count=self.byte_count,
            covered_domains=self.covered_domains,
            evidence_version=self.evidence_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"evidenceId": self.evidence_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyStateEvidenceV1:
        document = _wire_object(
            value,
            expected={
                "byteCount",
                "coveredDomains",
                "entryCount",
                "evidenceId",
                "evidenceVersion",
                "legacyRootIdentity",
                "stateDigest",
                "storeId",
            },
            name="legacy Package state evidence",
        )
        return cls(
            evidence_id=_wire_string(document["evidenceId"], name="evidence id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            legacy_root_identity=_wire_string(
                document["legacyRootIdentity"],
                name="legacy root identity",
            ),
            state_digest=_wire_string(
                document["stateDigest"],
                name="state digest",
            ),
            entry_count=_wire_int(document["entryCount"], name="entry count"),
            byte_count=_wire_int(document["byteCount"], name="byte count"),
            covered_domains=_wire_string_tuple(
                document["coveredDomains"],
                name="covered domains",
            ),
            evidence_version=_wire_int(
                document["evidenceVersion"],
                name="evidence version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLegacyAdoptionRequestV1:
    """Pathless binding of one B transaction to exact legacy/fence evidence."""

    request_id: str
    store_id: str
    current_fence_id: str
    current_fence_revision: int
    current_epoch: int
    current_root_identity: str
    legacy_state_evidence_id: str
    legacy_root_identity: str
    legacy_state_digest: str
    legacy_entry_count: int
    legacy_byte_count: int
    operation_id: str
    transaction_request_fingerprint: str
    expected_classification_fingerprint: str
    expected_attempt_epoch: int
    product_id: str
    scope_id: str
    installation_id: str
    plugin_id: str
    request_version: int = PACKAGE_LEGACY_ADOPTION_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.request_id, name="legacy adoption request identity")
        _require_safe_id(self.store_id, name="Package store identity")
        for value, name in (
            (self.current_fence_id, "current Package fence identity"),
            (self.current_root_identity, "current Package root identity"),
            (self.legacy_state_evidence_id, "legacy state evidence identity"),
            (self.legacy_root_identity, "legacy Package root identity"),
            (self.legacy_state_digest, "legacy Package state digest"),
            (
                self.transaction_request_fingerprint,
                "Package transaction request fingerprint",
            ),
            (
                self.expected_classification_fingerprint,
                "Package classification fingerprint",
            ),
        ):
            _require_sha256(value, name=name)
        _require_positive(self.current_fence_revision, name="current fence revision")
        _require_positive(self.current_epoch, name="current Package epoch")
        _require_non_negative(self.legacy_entry_count, name="legacy entry count")
        _require_non_negative(self.legacy_byte_count, name="legacy byte count")
        _require_positive(self.expected_attempt_epoch, name="expected attempt epoch")
        for value, name in (
            (self.operation_id, "Package operation identity"),
            (self.product_id, "Product identity"),
            (self.scope_id, "scope identity"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
        ):
            _require_safe_id(value, name=name)
        if self.request_version != PACKAGE_LEGACY_ADOPTION_REQUEST_VERSION:
            raise ValueError("Unsupported legacy Package adoption request")
        if self.request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Legacy Package adoption request does not match")

    @classmethod
    def create(
        cls,
        *,
        current_fence: PackageEpochFenceReceiptV1,
        legacy_state: PackageLegacyStateEvidenceV1,
        operation_id: str,
        transaction_request_fingerprint: str,
        expected_classification_fingerprint: str,
        expected_attempt_epoch: int,
        product_id: str,
        scope_id: str,
        installation_id: str,
        plugin_id: str,
    ) -> PackageLegacyAdoptionRequestV1:
        if not isinstance(current_fence, PackageEpochFenceReceiptV1):
            raise TypeError("Current Package epoch fence is required")
        if not isinstance(legacy_state, PackageLegacyStateEvidenceV1):
            raise TypeError("Legacy Package state evidence is required")
        if (
            current_fence.store_id != legacy_state.store_id
            or current_fence.request.legacy_root_identity
            != legacy_state.legacy_root_identity
        ):
            raise ValueError("Legacy adoption authority changed")
        values = _adoption_request_identity(
            store_id=current_fence.store_id,
            current_fence_id=current_fence.fence_id,
            current_fence_revision=current_fence.fence_revision,
            current_epoch=current_fence.epoch,
            current_root_identity=current_fence.fenced_root_identity,
            legacy_state_evidence_id=legacy_state.evidence_id,
            legacy_root_identity=legacy_state.legacy_root_identity,
            legacy_state_digest=legacy_state.state_digest,
            legacy_entry_count=legacy_state.entry_count,
            legacy_byte_count=legacy_state.byte_count,
            operation_id=operation_id,
            transaction_request_fingerprint=transaction_request_fingerprint,
            expected_classification_fingerprint=expected_classification_fingerprint,
            expected_attempt_epoch=expected_attempt_epoch,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
            request_version=PACKAGE_LEGACY_ADOPTION_REQUEST_VERSION,
        )
        return cls(
            request_id=_fingerprint(values),
            store_id=current_fence.store_id,
            current_fence_id=current_fence.fence_id,
            current_fence_revision=current_fence.fence_revision,
            current_epoch=current_fence.epoch,
            current_root_identity=current_fence.fenced_root_identity,
            legacy_state_evidence_id=legacy_state.evidence_id,
            legacy_root_identity=legacy_state.legacy_root_identity,
            legacy_state_digest=legacy_state.state_digest,
            legacy_entry_count=legacy_state.entry_count,
            legacy_byte_count=legacy_state.byte_count,
            operation_id=operation_id,
            transaction_request_fingerprint=transaction_request_fingerprint,
            expected_classification_fingerprint=expected_classification_fingerprint,
            expected_attempt_epoch=expected_attempt_epoch,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
        )

    def matches_legacy_state(self, evidence: PackageLegacyStateEvidenceV1) -> bool:
        return isinstance(evidence, PackageLegacyStateEvidenceV1) and (
            evidence.evidence_id == self.legacy_state_evidence_id
            and evidence.store_id == self.store_id
            and evidence.legacy_root_identity == self.legacy_root_identity
            and evidence.state_digest == self.legacy_state_digest
            and evidence.entry_count == self.legacy_entry_count
            and evidence.byte_count == self.legacy_byte_count
            and evidence.covered_domains == PACKAGE_PRE_B_SNAPSHOT_DOMAINS
        )

    def _identity_dict(self) -> dict[str, object]:
        return _adoption_request_identity(
            store_id=self.store_id,
            current_fence_id=self.current_fence_id,
            current_fence_revision=self.current_fence_revision,
            current_epoch=self.current_epoch,
            current_root_identity=self.current_root_identity,
            legacy_state_evidence_id=self.legacy_state_evidence_id,
            legacy_root_identity=self.legacy_root_identity,
            legacy_state_digest=self.legacy_state_digest,
            legacy_entry_count=self.legacy_entry_count,
            legacy_byte_count=self.legacy_byte_count,
            operation_id=self.operation_id,
            transaction_request_fingerprint=self.transaction_request_fingerprint,
            expected_classification_fingerprint=(
                self.expected_classification_fingerprint
            ),
            expected_attempt_epoch=self.expected_attempt_epoch,
            product_id=self.product_id,
            scope_id=self.scope_id,
            installation_id=self.installation_id,
            plugin_id=self.plugin_id,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"requestId": self.request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyAdoptionRequestV1:
        document = _wire_object(
            value,
            expected={"requestId", *_ADOPTION_REQUEST_WIRE_KEYS},
            name="legacy Package adoption request",
        )
        return cls(
            request_id=_wire_string(document["requestId"], name="request id"),
            store_id=_wire_string(document["storeId"], name="store id"),
            current_fence_id=_wire_string(
                document["currentFenceId"],
                name="current fence id",
            ),
            current_fence_revision=_wire_int(
                document["currentFenceRevision"],
                name="current fence revision",
            ),
            current_epoch=_wire_int(document["currentEpoch"], name="current epoch"),
            current_root_identity=_wire_string(
                document["currentRootIdentity"],
                name="current root identity",
            ),
            legacy_state_evidence_id=_wire_string(
                document["legacyStateEvidenceId"],
                name="legacy state evidence id",
            ),
            legacy_root_identity=_wire_string(
                document["legacyRootIdentity"],
                name="legacy root identity",
            ),
            legacy_state_digest=_wire_string(
                document["legacyStateDigest"],
                name="legacy state digest",
            ),
            legacy_entry_count=_wire_int(
                document["legacyEntryCount"],
                name="legacy entry count",
            ),
            legacy_byte_count=_wire_int(
                document["legacyByteCount"],
                name="legacy byte count",
            ),
            operation_id=_wire_string(
                document["operationId"],
                name="operation id",
            ),
            transaction_request_fingerprint=_wire_string(
                document["transactionRequestFingerprint"],
                name="transaction request fingerprint",
            ),
            expected_classification_fingerprint=_wire_string(
                document["expectedClassificationFingerprint"],
                name="expected classification fingerprint",
            ),
            expected_attempt_epoch=_wire_int(
                document["expectedAttemptEpoch"],
                name="expected attempt epoch",
            ),
            product_id=_wire_string(document["productId"], name="product id"),
            scope_id=_wire_string(document["scopeId"], name="scope id"),
            installation_id=_wire_string(
                document["installationId"],
                name="installation id",
            ),
            plugin_id=_wire_string(document["pluginId"], name="plugin id"),
            request_version=_wire_int(
                document["requestVersion"],
                name="request version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLegacyAdoptionTransactionResultV1:
    """Narrow result returned by the future complete B transaction adapter."""

    adoption_request_id: str
    status: PackageLifecycleStatusV1
    publication: PackagePublicationReceiptV1 | None
    result_version: int = PACKAGE_LEGACY_ADOPTION_TRANSACTION_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.adoption_request_id, name="adoption request identity")
        if not isinstance(self.status, PackageLifecycleStatusV1):
            raise TypeError("Package transaction status is required")
        if self.status.disposition == "committed":
            if not isinstance(self.publication, PackagePublicationReceiptV1):
                raise ValueError("Committed adoption transaction requires publication")
            if not _publication_matches_status(self.publication, self.status):
                raise ValueError("Adoption publication does not match transaction")
        elif self.status.disposition in {
            "cancelled",
            "rejected",
            "retryable_failure",
        }:
            if self.publication is not None or self.status.failure is None:
                raise ValueError("Failed adoption transaction is inconsistent")
        else:
            raise ValueError("Adoption transaction must be committed or failed")
        if self.result_version != PACKAGE_LEGACY_ADOPTION_TRANSACTION_RESULT_VERSION:
            raise ValueError("Unsupported legacy adoption transaction result")

    def to_dict(self) -> dict[str, object]:
        return {
            "adoptionRequestId": self.adoption_request_id,
            "publication": (
                None if self.publication is None else self.publication.to_dict()
            ),
            "resultVersion": self.result_version,
            "status": self.status.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyAdoptionTransactionResultV1:
        document = _wire_object(
            value,
            expected={
                "adoptionRequestId",
                "publication",
                "resultVersion",
                "status",
            },
            name="legacy adoption transaction result",
        )
        publication = document["publication"]
        return cls(
            adoption_request_id=_wire_string(
                document["adoptionRequestId"],
                name="adoption request id",
            ),
            status=PackageLifecycleStatusV1.from_dict(document["status"]),
            publication=(
                None
                if publication is None
                else PackagePublicationReceiptV1.from_dict(publication)
            ),
            result_version=_wire_int(
                document["resultVersion"],
                name="result version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLegacyAdoptionReceiptV1:
    """Pathless proof of adoption through one exact committed B transaction."""

    receipt_id: str
    request_id: str
    legacy_state_evidence_id: str
    publication: PackagePublicationReceiptV1
    receipt_version: int = PACKAGE_LEGACY_ADOPTION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="legacy adoption receipt identity")
        _require_sha256(self.request_id, name="legacy adoption request identity")
        _require_sha256(
            self.legacy_state_evidence_id,
            name="legacy state evidence identity",
        )
        if not isinstance(self.publication, PackagePublicationReceiptV1):
            raise TypeError("Package publication receipt is required")
        if self.receipt_version != PACKAGE_LEGACY_ADOPTION_RECEIPT_VERSION:
            raise ValueError("Unsupported legacy Package adoption receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Legacy Package adoption receipt does not match")

    @classmethod
    def create(
        cls,
        request: PackageLegacyAdoptionRequestV1,
        publication: PackagePublicationReceiptV1,
    ) -> PackageLegacyAdoptionReceiptV1:
        if not isinstance(request, PackageLegacyAdoptionRequestV1):
            raise TypeError("Legacy Package adoption request is required")
        if not isinstance(publication, PackagePublicationReceiptV1):
            raise TypeError("Package publication receipt is required")
        if not _publication_matches_request(publication, request):
            raise ValueError("Package publication does not match adoption request")
        values = _adoption_receipt_identity(
            request_id=request.request_id,
            legacy_state_evidence_id=request.legacy_state_evidence_id,
            publication=publication,
            receipt_version=PACKAGE_LEGACY_ADOPTION_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            request_id=request.request_id,
            legacy_state_evidence_id=request.legacy_state_evidence_id,
            publication=publication,
        )

    def matches(self, request: PackageLegacyAdoptionRequestV1) -> bool:
        return (
            isinstance(request, PackageLegacyAdoptionRequestV1)
            and self.request_id == request.request_id
            and self.legacy_state_evidence_id == request.legacy_state_evidence_id
            and _publication_matches_request(self.publication, request)
        )

    def _identity_dict(self) -> dict[str, object]:
        return _adoption_receipt_identity(
            request_id=self.request_id,
            legacy_state_evidence_id=self.legacy_state_evidence_id,
            publication=self.publication,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyAdoptionReceiptV1:
        document = _wire_object(
            value,
            expected={
                "legacyStateEvidenceId",
                "publication",
                "receiptId",
                "receiptVersion",
                "requestId",
            },
            name="legacy Package adoption receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            request_id=_wire_string(document["requestId"], name="request id"),
            legacy_state_evidence_id=_wire_string(
                document["legacyStateEvidenceId"],
                name="legacy state evidence id",
            ),
            publication=PackagePublicationReceiptV1.from_dict(
                document["publication"]
            ),
            receipt_version=_wire_int(
                document["receiptVersion"],
                name="receipt version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLegacyAdoptionFailureV1:
    failure_id: str
    request_id: str
    operation_id: str
    code: str
    stage: PackageLifecyclePhase
    retryable: bool
    evidence_ref: str
    transaction_failure: PackageLifecycleFailureV1 | None = None
    failure_version: int = PACKAGE_LEGACY_ADOPTION_FAILURE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.failure_id, name="legacy adoption failure identity")
        _require_sha256(self.request_id, name="legacy adoption request identity")
        _require_safe_id(self.operation_id, name="Package operation identity")
        if _SAFE_CODE.fullmatch(self.code) is None:
            raise ValueError("Legacy adoption failure code is invalid")
        if not isinstance(self.stage, str):
            raise TypeError("Legacy adoption failure stage is invalid")
        if type(self.retryable) is not bool:
            raise TypeError("Legacy adoption retryability must be boolean")
        _require_sha256(self.evidence_ref, name="adoption failure evidence")
        if self.transaction_failure is None:
            if (
                self.code not in _COORDINATOR_FAILURE_CODES
                or self.stage != "classified"
                or self.retryable
            ):
                raise ValueError("Coordinator adoption failure is inconsistent")
        elif (
            not isinstance(self.transaction_failure, PackageLifecycleFailureV1)
            or self.transaction_failure.operation_id != self.operation_id
            or self.transaction_failure.code != self.code
            or self.transaction_failure.stage != self.stage
            or self.transaction_failure.retryable != self.retryable
            or self.transaction_failure.evidence_ref != self.evidence_ref
        ):
            raise ValueError("Transaction adoption failure is inconsistent")
        if self.failure_version != PACKAGE_LEGACY_ADOPTION_FAILURE_VERSION:
            raise ValueError("Unsupported legacy Package adoption failure")
        if self.failure_id != _fingerprint(self._identity_dict()):
            raise ValueError("Legacy Package adoption failure does not match")

    @classmethod
    def for_request(
        cls,
        request: PackageLegacyAdoptionRequestV1,
        *,
        code: Literal[
            "package_operation_identity_conflict",
            "package_runtime_epoch_unsupported",
        ],
        evidence_ref: str,
    ) -> PackageLegacyAdoptionFailureV1:
        values = _adoption_failure_identity(
            request_id=request.request_id,
            operation_id=request.operation_id,
            code=code,
            stage="classified",
            retryable=False,
            evidence_ref=evidence_ref,
            transaction_failure=None,
            failure_version=PACKAGE_LEGACY_ADOPTION_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            request_id=request.request_id,
            operation_id=request.operation_id,
            code=code,
            stage="classified",
            retryable=False,
            evidence_ref=evidence_ref,
        )

    @classmethod
    def from_status(
        cls,
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> PackageLegacyAdoptionFailureV1:
        if (
            status.failure is None
            or status.operation_id != request.operation_id
            or status.request_fingerprint
            != request.transaction_request_fingerprint
            or status.attempt_epoch != request.expected_attempt_epoch
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.classification.evidence_ref
            != request.expected_classification_fingerprint
        ):
            raise ValueError("Failed Package transaction does not match adoption")
        failure = status.failure
        values = _adoption_failure_identity(
            request_id=request.request_id,
            operation_id=request.operation_id,
            code=failure.code,
            stage=failure.stage,
            retryable=failure.retryable,
            evidence_ref=failure.evidence_ref,
            transaction_failure=failure,
            failure_version=PACKAGE_LEGACY_ADOPTION_FAILURE_VERSION,
        )
        return cls(
            failure_id=_fingerprint(values),
            request_id=request.request_id,
            operation_id=request.operation_id,
            code=failure.code,
            stage=failure.stage,
            retryable=failure.retryable,
            evidence_ref=failure.evidence_ref,
            transaction_failure=failure,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _adoption_failure_identity(
            request_id=self.request_id,
            operation_id=self.operation_id,
            code=self.code,
            stage=self.stage,
            retryable=self.retryable,
            evidence_ref=self.evidence_ref,
            transaction_failure=self.transaction_failure,
            failure_version=self.failure_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"failureId": self.failure_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyAdoptionFailureV1:
        document = _wire_object(
            value,
            expected={
                "code",
                "evidenceRef",
                "failureId",
                "failureVersion",
                "operationId",
                "requestId",
                "retryable",
                "stage",
                "transactionFailure",
            },
            name="legacy Package adoption failure",
        )
        transaction = document["transactionFailure"]
        return cls(
            failure_id=_wire_string(document["failureId"], name="failure id"),
            request_id=_wire_string(document["requestId"], name="request id"),
            operation_id=_wire_string(
                document["operationId"],
                name="operation id",
            ),
            code=_wire_string(document["code"], name="failure code"),
            stage=cast(
                PackageLifecyclePhase,
                _wire_string(document["stage"], name="failure stage"),
            ),
            retryable=_wire_bool(document["retryable"], name="retryable"),
            evidence_ref=_wire_string(
                document["evidenceRef"],
                name="evidence ref",
            ),
            transaction_failure=(
                None
                if transaction is None
                else PackageLifecycleFailureV1.from_dict(transaction)
            ),
            failure_version=_wire_int(
                document["failureVersion"],
                name="failure version",
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLegacyAdoptionResultV1:
    request_id: str
    disposition: PackageLegacyAdoptionDisposition
    code: str
    receipt: PackageLegacyAdoptionReceiptV1 | None
    failure: PackageLegacyAdoptionFailureV1 | None
    result_version: int = PACKAGE_LEGACY_ADOPTION_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.request_id, name="legacy adoption request identity")
        if self.disposition == "adopted":
            if self.code != "ok" or self.receipt is None or self.failure is not None:
                raise ValueError("Adopted Package result is inconsistent")
            if self.receipt.request_id != self.request_id:
                raise ValueError("Adoption result request changed")
        elif self.disposition in {"rejected", "retryable_failure"}:
            if (
                self.receipt is not None
                or self.failure is None
                or self.failure.request_id != self.request_id
                or self.code != self.failure.code
                or (self.disposition == "retryable_failure")
                != self.failure.retryable
            ):
                raise ValueError("Failed Package adoption result is inconsistent")
        else:
            raise ValueError("Unsupported legacy Package adoption disposition")
        if self.result_version != PACKAGE_LEGACY_ADOPTION_RESULT_VERSION:
            raise ValueError("Unsupported legacy Package adoption result")

    @classmethod
    def adopted(
        cls,
        request: PackageLegacyAdoptionRequestV1,
        publication: PackagePublicationReceiptV1,
    ) -> PackageLegacyAdoptionResultV1:
        return cls(
            request_id=request.request_id,
            disposition="adopted",
            code="ok",
            receipt=PackageLegacyAdoptionReceiptV1.create(request, publication),
            failure=None,
        )

    @classmethod
    def rejected(
        cls,
        request: PackageLegacyAdoptionRequestV1,
        failure: PackageLegacyAdoptionFailureV1,
    ) -> PackageLegacyAdoptionResultV1:
        if failure.request_id != request.request_id:
            raise ValueError("Adoption failure request changed")
        return cls(
            request_id=request.request_id,
            disposition=("retryable_failure" if failure.retryable else "rejected"),
            code=failure.code,
            receipt=None,
            failure=failure,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "disposition": self.disposition,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "requestId": self.request_id,
            "resultVersion": self.result_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLegacyAdoptionResultV1:
        document = _wire_object(
            value,
            expected={
                "code",
                "disposition",
                "failure",
                "receipt",
                "requestId",
                "resultVersion",
            },
            name="legacy Package adoption result",
        )
        receipt = document["receipt"]
        failure = document["failure"]
        return cls(
            request_id=_wire_string(document["requestId"], name="request id"),
            disposition=cast(
                PackageLegacyAdoptionDisposition,
                _wire_string(document["disposition"], name="disposition"),
            ),
            code=_wire_string(document["code"], name="code"),
            receipt=(
                None
                if receipt is None
                else PackageLegacyAdoptionReceiptV1.from_dict(receipt)
            ),
            failure=(
                None
                if failure is None
                else PackageLegacyAdoptionFailureV1.from_dict(failure)
            ),
            result_version=_wire_int(
                document["resultVersion"],
                name="result version",
            ),
        )


class PackageLegacyStateEvidencePort(Protocol):
    def observe(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
    ) -> PackageLegacyStateEvidenceV1: ...


class PackageLegacyAdoptionTransactionPort(Protocol):
    def adopt(
        self,
        request: PackageLegacyAdoptionRequestV1,
    ) -> PackageLegacyAdoptionTransactionResultV1: ...


class PackageLegacyAdoptionOwner:
    """Read-only coordinator around one separately-owned complete B transaction."""

    def __init__(
        self,
        *,
        store_id: str,
        fences: PackageEpochFenceReadPort,
        legacy_state: PackageLegacyStateEvidencePort,
        transaction: PackageLegacyAdoptionTransactionPort,
    ) -> None:
        _require_safe_id(store_id, name="Package store identity")
        for owner, method, name in (
            (fences, "current", "epoch fence reader"),
            (legacy_state, "observe", "legacy state evidence owner"),
            (transaction, "adopt", "adoption transaction owner"),
        ):
            if not callable(getattr(owner, method, None)):
                raise TypeError(f"Package {name} is required")
        self._store_id = store_id
        self._fences = fences
        self._legacy_state = legacy_state
        self._transaction = transaction

    def adopt(
        self,
        request: PackageLegacyAdoptionRequestV1,
    ) -> PackageLegacyAdoptionResultV1:
        if not isinstance(request, PackageLegacyAdoptionRequestV1):
            raise TypeError("Legacy Package adoption request is required")
        if request.store_id != self._store_id or not self._fence_matches(request):
            return self._coordinator_failure(
                request,
                code="package_runtime_epoch_unsupported",
                evidence_ref=request.current_fence_id,
            )
        before = self._legacy_state.observe(
            store_id=request.store_id,
            legacy_root_identity=request.legacy_root_identity,
        )
        if not request.matches_legacy_state(before):
            return self._coordinator_failure(
                request,
                code="package_operation_identity_conflict",
                evidence_ref=request.legacy_state_evidence_id,
            )
        transaction = self._transaction.adopt(request)
        after = self._legacy_state.observe(
            store_id=request.store_id,
            legacy_root_identity=request.legacy_root_identity,
        )
        if after != before or not request.matches_legacy_state(after):
            return self._coordinator_failure(
                request,
                code="package_operation_identity_conflict",
                evidence_ref=before.evidence_id,
            )
        if not self._fence_matches(request):
            return self._coordinator_failure(
                request,
                code="package_runtime_epoch_unsupported",
                evidence_ref=request.current_fence_id,
            )
        if not isinstance(
            transaction,
            PackageLegacyAdoptionTransactionResultV1,
        ) or not _transaction_matches_request(transaction, request):
            return self._coordinator_failure(
                request,
                code="package_operation_identity_conflict",
                evidence_ref=request.request_id,
            )
        if transaction.status.failure is not None:
            return PackageLegacyAdoptionResultV1.rejected(
                request,
                PackageLegacyAdoptionFailureV1.from_status(
                    request,
                    transaction.status,
                ),
            )
        assert transaction.publication is not None
        return PackageLegacyAdoptionResultV1.adopted(
            request,
            transaction.publication,
        )

    def _fence_matches(self, request: PackageLegacyAdoptionRequestV1) -> bool:
        current = self._fences.current(self._store_id)
        return isinstance(current, PackageEpochFenceReceiptV1) and (
            current.store_id == request.store_id
            and current.fence_id == request.current_fence_id
            and current.fence_revision == request.current_fence_revision
            and current.epoch == request.current_epoch
            and current.fenced_root_identity == request.current_root_identity
            and current.request.legacy_root_identity
            == request.legacy_root_identity
        )

    @staticmethod
    def _coordinator_failure(
        request: PackageLegacyAdoptionRequestV1,
        *,
        code: Literal[
            "package_operation_identity_conflict",
            "package_runtime_epoch_unsupported",
        ],
        evidence_ref: str,
    ) -> PackageLegacyAdoptionResultV1:
        return PackageLegacyAdoptionResultV1.rejected(
            request,
            PackageLegacyAdoptionFailureV1.for_request(
                request,
                code=code,
                evidence_ref=evidence_ref,
            ),
        )


def _publication_matches_status(
    publication: PackagePublicationReceiptV1,
    status: PackageLifecycleStatusV1,
) -> bool:
    return (
        publication.operation_id == status.operation_id
        and publication.request_fingerprint == status.request_fingerprint
        and publication.attempt_epoch == status.attempt_epoch
        and publication.commit_status_revision == status.journal_revision
    )


def _publication_matches_request(
    publication: PackagePublicationReceiptV1,
    request: PackageLegacyAdoptionRequestV1,
) -> bool:
    return (
        publication.operation_id == request.operation_id
        and publication.request_fingerprint
        == request.transaction_request_fingerprint
        and publication.classification_fingerprint
        == request.expected_classification_fingerprint
        and publication.attempt_epoch == request.expected_attempt_epoch
        and publication.product_id == request.product_id
        and publication.scope_id == request.scope_id
        and publication.installation_id == request.installation_id
        and publication.plugin_id == request.plugin_id
    )


def _transaction_matches_request(
    transaction: PackageLegacyAdoptionTransactionResultV1,
    request: PackageLegacyAdoptionRequestV1,
) -> bool:
    status = transaction.status
    if (
        transaction.adoption_request_id != request.request_id
        or status.operation_id != request.operation_id
        or status.request_fingerprint != request.transaction_request_fingerprint
        or status.attempt_epoch != request.expected_attempt_epoch
        or status.classification is None
        or status.classification.decision != "plugin_bound"
        or status.classification.evidence_ref
        != request.expected_classification_fingerprint
    ):
        return False
    if transaction.publication is None:
        return status.failure is not None
    return _publication_matches_request(transaction.publication, request)


_ADOPTION_REQUEST_WIRE_KEYS = {
    "currentEpoch",
    "currentFenceId",
    "currentFenceRevision",
    "currentRootIdentity",
    "expectedAttemptEpoch",
    "expectedClassificationFingerprint",
    "installationId",
    "legacyByteCount",
    "legacyEntryCount",
    "legacyRootIdentity",
    "legacyStateDigest",
    "legacyStateEvidenceId",
    "operationId",
    "pluginId",
    "productId",
    "requestVersion",
    "scopeId",
    "storeId",
    "transactionRequestFingerprint",
}


def _legacy_state_identity(
    *,
    store_id: str,
    legacy_root_identity: str,
    state_digest: str,
    entry_count: int,
    byte_count: int,
    covered_domains: tuple[str, ...],
    evidence_version: int,
) -> dict[str, object]:
    return {
        "byteCount": byte_count,
        "coveredDomains": list(covered_domains),
        "entryCount": entry_count,
        "evidenceVersion": evidence_version,
        "legacyRootIdentity": legacy_root_identity,
        "stateDigest": state_digest,
        "storeId": store_id,
    }


def _adoption_request_identity(
    *,
    store_id: str,
    current_fence_id: str,
    current_fence_revision: int,
    current_epoch: int,
    current_root_identity: str,
    legacy_state_evidence_id: str,
    legacy_root_identity: str,
    legacy_state_digest: str,
    legacy_entry_count: int,
    legacy_byte_count: int,
    operation_id: str,
    transaction_request_fingerprint: str,
    expected_classification_fingerprint: str,
    expected_attempt_epoch: int,
    product_id: str,
    scope_id: str,
    installation_id: str,
    plugin_id: str,
    request_version: int,
) -> dict[str, object]:
    return {
        "currentEpoch": current_epoch,
        "currentFenceId": current_fence_id,
        "currentFenceRevision": current_fence_revision,
        "currentRootIdentity": current_root_identity,
        "expectedAttemptEpoch": expected_attempt_epoch,
        "expectedClassificationFingerprint": expected_classification_fingerprint,
        "installationId": installation_id,
        "legacyByteCount": legacy_byte_count,
        "legacyEntryCount": legacy_entry_count,
        "legacyRootIdentity": legacy_root_identity,
        "legacyStateDigest": legacy_state_digest,
        "legacyStateEvidenceId": legacy_state_evidence_id,
        "operationId": operation_id,
        "pluginId": plugin_id,
        "productId": product_id,
        "requestVersion": request_version,
        "scopeId": scope_id,
        "storeId": store_id,
        "transactionRequestFingerprint": transaction_request_fingerprint,
    }


def _adoption_receipt_identity(
    *,
    request_id: str,
    legacy_state_evidence_id: str,
    publication: PackagePublicationReceiptV1,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "legacyStateEvidenceId": legacy_state_evidence_id,
        "publication": publication.to_dict(),
        "receiptVersion": receipt_version,
        "requestId": request_id,
    }


def _adoption_failure_identity(
    *,
    request_id: str,
    operation_id: str,
    code: str,
    stage: PackageLifecyclePhase,
    retryable: bool,
    evidence_ref: str,
    transaction_failure: PackageLifecycleFailureV1 | None,
    failure_version: int,
) -> dict[str, object]:
    return {
        "code": code,
        "evidenceRef": evidence_ref,
        "failureVersion": failure_version,
        "operationId": operation_id,
        "requestId": request_id,
        "retryable": retryable,
        "stage": stage,
        "transactionFailure": (
            None if transaction_failure is None else transaction_failure.to_dict()
        ),
    }


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _wire_object(
    value: object,
    *,
    expected: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{name} does not match its versioned schema")
    return cast(dict[str, object], value)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be boolean")
    return value


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{name} must be an array of strings")
    return tuple(value)


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_positive(value: int, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative(value: int, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = ()
