"""Dark transaction-pin contracts and owner-side evidence for PLC9B3e."""

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
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    PackageClosureArtifactRole,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_TRANSACTION_PIN_TARGET_VERSION = 1
PACKAGE_TRANSACTION_PIN_REQUEST_VERSION = 1
PACKAGE_TRANSACTION_PIN_RECEIPT_VERSION = 1
PACKAGE_TRANSACTION_PIN_RECORD_VERSION = 1

PackageTransactionPinState = Literal["acquired", "released", "transferred"]
PackageTransactionPinKind = Literal["package_transaction"]

_TERMINAL_PIN_STATES = frozenset({"released", "transferred"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


@dataclass(frozen=True, slots=True)
class PackageTransactionPinTargetV1:
    """Credential-free identity of one quarantined verified closure node."""

    target_id: str
    node_id: str
    role: PackageClosureArtifactRole
    distribution: str
    version: str
    artifact_digest: str
    extraction_tree_digest: str
    wheel_evidence_fingerprint: str
    target_version: int = PACKAGE_TRANSACTION_PIN_TARGET_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.target_id, name="transaction pin target id")
        _require_safe_id(self.node_id, name="transaction pin node identity")
        if self.role not in {"root", "dependency"}:
            raise ValueError("Unsupported transaction pin target role")
        if self.distribution != _canonical_distribution(self.distribution):
            raise ValueError("Transaction pin distribution must be canonical")
        _require_nonempty(self.version, name="transaction pin version")
        for value, name in (
            (self.artifact_digest, "transaction pin artifact digest"),
            (self.extraction_tree_digest, "transaction pin tree digest"),
            (self.wheel_evidence_fingerprint, "wheel evidence fingerprint"),
        ):
            _require_sha256(value, name=name)
        if self.target_version != PACKAGE_TRANSACTION_PIN_TARGET_VERSION:
            raise ValueError("Unsupported Package transaction pin target")
        if self.target_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package transaction pin target id does not match")

    @classmethod
    def from_plan_node(
        cls,
        node: VerifiedClosurePlanNodeV2,
    ) -> PackageTransactionPinTargetV1:
        if not isinstance(node, VerifiedClosurePlanNodeV2):
            raise TypeError("Verified closure plan node is required")
        values = {
            "artifactDigest": node.artifact_digest,
            "distribution": node.distribution,
            "extractionTreeDigest": node.extraction_tree_digest,
            "nodeId": node.node_id,
            "role": node.role,
            "targetVersion": PACKAGE_TRANSACTION_PIN_TARGET_VERSION,
            "version": node.version,
            "wheelEvidenceFingerprint": node.wheel_evidence_fingerprint,
        }
        return cls(
            target_id=_fingerprint(values),
            node_id=node.node_id,
            role=node.role,
            distribution=node.distribution,
            version=node.version,
            artifact_digest=node.artifact_digest,
            extraction_tree_digest=node.extraction_tree_digest,
            wheel_evidence_fingerprint=node.wheel_evidence_fingerprint,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "artifactDigest": self.artifact_digest,
            "distribution": self.distribution,
            "extractionTreeDigest": self.extraction_tree_digest,
            "nodeId": self.node_id,
            "role": self.role,
            "targetVersion": self.target_version,
            "version": self.version,
            "wheelEvidenceFingerprint": self.wheel_evidence_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        return {"targetId": self.target_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageTransactionPinTargetV1:
        document = _exact_dict(
            value,
            fields={
                "artifactDigest",
                "distribution",
                "extractionTreeDigest",
                "nodeId",
                "role",
                "targetId",
                "targetVersion",
                "version",
                "wheelEvidenceFingerprint",
            },
            name="Package transaction pin target",
        )
        return cls(
            target_id=_wire_string(document["targetId"], name="target id"),
            node_id=_wire_string(document["nodeId"], name="node id"),
            role=cast(
                PackageClosureArtifactRole,
                _wire_string(document["role"], name="target role"),
            ),
            distribution=_wire_string(document["distribution"], name="distribution"),
            version=_wire_string(document["version"], name="version"),
            artifact_digest=_wire_string(
                document["artifactDigest"], name="artifact digest"
            ),
            extraction_tree_digest=_wire_string(
                document["extractionTreeDigest"], name="tree digest"
            ),
            wheel_evidence_fingerprint=_wire_string(
                document["wheelEvidenceFingerprint"],
                name="wheel evidence fingerprint",
            ),
            target_version=_wire_int(document["targetVersion"], name="target version"),
        )


@dataclass(frozen=True, slots=True)
class PackageTransactionPinRequestV1:
    """Exact graph-wide request sent to the narrow retention-pin owner."""

    pin_request_id: str
    operation_id: str
    attempt_epoch: int
    request_fingerprint: str
    classification_fingerprint: str
    verified_plan_fingerprint: str
    prepublication_graph_digest: str
    recovery_identity: str
    root_target_id: str
    targets: tuple[PackageTransactionPinTargetV1, ...]
    pin_kind: PackageTransactionPinKind = "package_transaction"
    pin_request_version: int = PACKAGE_TRANSACTION_PIN_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.pin_request_id, name="transaction pin request id")
        _require_safe_id(self.operation_id, name="transaction pin operation identity")
        _require_positive(self.attempt_epoch, name="transaction pin attempt epoch")
        for value, name in (
            (self.request_fingerprint, "Package request fingerprint"),
            (self.classification_fingerprint, "classification fingerprint"),
            (self.verified_plan_fingerprint, "verified plan fingerprint"),
            (self.prepublication_graph_digest, "prepublication graph digest"),
            (self.root_target_id, "root transaction pin target id"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.recovery_identity, name="pin recovery identity")
        if not self.targets or self.targets != tuple(
            sorted(self.targets, key=lambda target: target.node_id)
        ):
            raise ValueError("Transaction pin targets must be canonical")
        if len({target.node_id for target in self.targets}) != len(self.targets):
            raise ValueError("Transaction pin target nodes must be unique")
        if len({target.target_id for target in self.targets}) != len(self.targets):
            raise ValueError("Transaction pin target ids must be unique")
        if len({target.distribution for target in self.targets}) != len(self.targets):
            raise ValueError("Transaction pin distributions must be unique")
        roots = tuple(target for target in self.targets if target.role == "root")
        if len(roots) != 1 or roots[0].target_id != self.root_target_id:
            raise ValueError("Transaction pin request has no exact root target")
        if self.pin_kind != "package_transaction":
            raise ValueError("Unsupported Package transaction pin kind")
        if self.pin_request_version != PACKAGE_TRANSACTION_PIN_REQUEST_VERSION:
            raise ValueError("Unsupported Package transaction pin request")
        if self.pin_request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package transaction pin request id does not match")

    @classmethod
    def create(
        cls,
        plan: VerifiedClosurePlanV2,
        *,
        request_fingerprint: str,
        classification_fingerprint: str,
        recovery_identity: str,
    ) -> PackageTransactionPinRequestV1:
        if not isinstance(plan, VerifiedClosurePlanV2):
            raise TypeError("Verified closure plan is required")
        targets = tuple(
            PackageTransactionPinTargetV1.from_plan_node(node) for node in plan.nodes
        )
        root_target = next(
            target
            for target in targets
            if target.node_id == plan.root_node_id and target.role == "root"
        )
        values = {
            "attemptEpoch": plan.attempt_epoch,
            "classificationFingerprint": classification_fingerprint,
            "operationId": plan.operation_id,
            "pinKind": "package_transaction",
            "pinRequestVersion": PACKAGE_TRANSACTION_PIN_REQUEST_VERSION,
            "prepublicationGraphDigest": plan.graph_digest,
            "recoveryIdentity": recovery_identity,
            "requestFingerprint": request_fingerprint,
            "rootTargetId": root_target.target_id,
            "targets": [target.to_dict() for target in targets],
            "verifiedPlanFingerprint": plan.fingerprint,
        }
        return cls(
            pin_request_id=_fingerprint(values),
            operation_id=plan.operation_id,
            attempt_epoch=plan.attempt_epoch,
            request_fingerprint=request_fingerprint,
            classification_fingerprint=classification_fingerprint,
            verified_plan_fingerprint=plan.fingerprint,
            prepublication_graph_digest=plan.graph_digest,
            recovery_identity=recovery_identity,
            root_target_id=root_target.target_id,
            targets=targets,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "classificationFingerprint": self.classification_fingerprint,
            "operationId": self.operation_id,
            "pinKind": self.pin_kind,
            "pinRequestVersion": self.pin_request_version,
            "prepublicationGraphDigest": self.prepublication_graph_digest,
            "recoveryIdentity": self.recovery_identity,
            "requestFingerprint": self.request_fingerprint,
            "rootTargetId": self.root_target_id,
            "targets": [target.to_dict() for target in self.targets],
            "verifiedPlanFingerprint": self.verified_plan_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        return {"pinRequestId": self.pin_request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageTransactionPinRequestV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "classificationFingerprint",
                "operationId",
                "pinKind",
                "pinRequestId",
                "pinRequestVersion",
                "prepublicationGraphDigest",
                "recoveryIdentity",
                "requestFingerprint",
                "rootTargetId",
                "targets",
                "verifiedPlanFingerprint",
            },
            name="Package transaction pin request",
        )
        targets = _wire_list(document["targets"], name="transaction pin targets")
        return cls(
            pin_request_id=_wire_string(
                document["pinRequestId"], name="pin request id"
            ),
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            classification_fingerprint=_wire_string(
                document["classificationFingerprint"],
                name="classification fingerprint",
            ),
            verified_plan_fingerprint=_wire_string(
                document["verifiedPlanFingerprint"],
                name="verified plan fingerprint",
            ),
            prepublication_graph_digest=_wire_string(
                document["prepublicationGraphDigest"],
                name="prepublication graph digest",
            ),
            recovery_identity=_wire_string(
                document["recoveryIdentity"], name="recovery identity"
            ),
            root_target_id=_wire_string(
                document["rootTargetId"], name="root target id"
            ),
            targets=tuple(
                PackageTransactionPinTargetV1.from_dict(item) for item in targets
            ),
            pin_kind=cast(
                PackageTransactionPinKind,
                _wire_string(document["pinKind"], name="pin kind"),
            ),
            pin_request_version=_wire_int(
                document["pinRequestVersion"], name="pin request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageTransactionPinReceiptV1:
    """Retention-owner fact for one acquired, released, or transferred pin."""

    receipt_id: str
    pin_request: PackageTransactionPinRequestV1
    pin_id: str
    owner_identity: str
    owner_revision: int
    lease_id: str
    lease_revision: int
    state: PackageTransactionPinState
    prior_receipt_id: str | None
    transition_evidence_ref: str | None
    receipt_version: int = PACKAGE_TRANSACTION_PIN_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="transaction pin receipt id")
        if not isinstance(self.pin_request, PackageTransactionPinRequestV1):
            raise TypeError("Package transaction pin request is required")
        _require_sha256(self.pin_id, name="transaction pin id")
        _require_safe_id(self.owner_identity, name="retention owner identity")
        _require_positive(self.owner_revision, name="retention owner revision")
        _require_safe_id(self.lease_id, name="transaction pin lease identity")
        _require_positive(self.lease_revision, name="transaction pin lease revision")
        if self.state == "acquired":
            if self.prior_receipt_id is not None or (
                self.transition_evidence_ref is not None
            ):
                raise ValueError("Acquired transaction pin cannot have a predecessor")
        elif self.state in _TERMINAL_PIN_STATES:
            if self.prior_receipt_id is None:
                raise ValueError("Terminal transaction pin requires a predecessor")
            _require_sha256(
                self.prior_receipt_id,
                name="prior transaction pin receipt id",
            )
            if self.transition_evidence_ref is None:
                raise ValueError(
                    "Terminal transaction pin requires transition evidence"
                )
            _require_sha256(
                self.transition_evidence_ref,
                name="transaction pin transition evidence",
            )
        else:
            raise ValueError("Unsupported Package transaction pin state")
        if self.receipt_version != PACKAGE_TRANSACTION_PIN_RECEIPT_VERSION:
            raise ValueError("Unsupported Package transaction pin receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package transaction pin receipt id does not match")

    @classmethod
    def acquire(
        cls,
        request: PackageTransactionPinRequestV1,
        *,
        pin_id: str,
        owner_identity: str,
        owner_revision: int,
        lease_id: str,
        lease_revision: int,
    ) -> PackageTransactionPinReceiptV1:
        if not isinstance(request, PackageTransactionPinRequestV1):
            raise TypeError("Package transaction pin request is required")
        values = _receipt_identity_dict(
            pin_request=request,
            pin_id=pin_id,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
            lease_id=lease_id,
            lease_revision=lease_revision,
            state="acquired",
            prior_receipt_id=None,
            transition_evidence_ref=None,
            receipt_version=PACKAGE_TRANSACTION_PIN_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            pin_request=request,
            pin_id=pin_id,
            owner_identity=owner_identity,
            owner_revision=owner_revision,
            lease_id=lease_id,
            lease_revision=lease_revision,
            state="acquired",
            prior_receipt_id=None,
            transition_evidence_ref=None,
        )

    @classmethod
    def transition(
        cls,
        prior: PackageTransactionPinReceiptV1,
        *,
        state: Literal["released", "transferred"],
        owner_revision: int,
        lease_revision: int,
        transition_evidence_ref: str,
    ) -> PackageTransactionPinReceiptV1:
        if not isinstance(prior, PackageTransactionPinReceiptV1):
            raise TypeError("Prior Package transaction pin receipt is required")
        if prior.state != "acquired":
            raise ValueError("Package transaction pin is already terminal")
        if state not in _TERMINAL_PIN_STATES:
            raise ValueError("Unsupported Package transaction pin transition")
        if owner_revision <= prior.owner_revision:
            raise ValueError("Transaction pin owner revision must advance")
        if lease_revision <= prior.lease_revision:
            raise ValueError("Transaction pin lease revision must advance")
        values = _receipt_identity_dict(
            pin_request=prior.pin_request,
            pin_id=prior.pin_id,
            owner_identity=prior.owner_identity,
            owner_revision=owner_revision,
            lease_id=prior.lease_id,
            lease_revision=lease_revision,
            state=state,
            prior_receipt_id=prior.receipt_id,
            transition_evidence_ref=transition_evidence_ref,
            receipt_version=PACKAGE_TRANSACTION_PIN_RECEIPT_VERSION,
        )
        return cls(
            receipt_id=_fingerprint(values),
            pin_request=prior.pin_request,
            pin_id=prior.pin_id,
            owner_identity=prior.owner_identity,
            owner_revision=owner_revision,
            lease_id=prior.lease_id,
            lease_revision=lease_revision,
            state=state,
            prior_receipt_id=prior.receipt_id,
            transition_evidence_ref=transition_evidence_ref,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _receipt_identity_dict(
            pin_request=self.pin_request,
            pin_id=self.pin_id,
            owner_identity=self.owner_identity,
            owner_revision=self.owner_revision,
            lease_id=self.lease_id,
            lease_revision=self.lease_revision,
            state=self.state,
            prior_receipt_id=self.prior_receipt_id,
            transition_evidence_ref=self.transition_evidence_ref,
            receipt_version=self.receipt_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageTransactionPinReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "leaseId",
                "leaseRevision",
                "ownerIdentity",
                "ownerRevision",
                "pinId",
                "pinRequest",
                "priorReceiptId",
                "receiptId",
                "receiptVersion",
                "state",
                "transitionEvidenceRef",
            },
            name="Package transaction pin receipt",
        )
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            pin_request=PackageTransactionPinRequestV1.from_dict(
                document["pinRequest"]
            ),
            pin_id=_wire_string(document["pinId"], name="pin id"),
            owner_identity=_wire_string(
                document["ownerIdentity"], name="owner identity"
            ),
            owner_revision=_wire_int(document["ownerRevision"], name="owner revision"),
            lease_id=_wire_string(document["leaseId"], name="lease id"),
            lease_revision=_wire_int(document["leaseRevision"], name="lease revision"),
            state=cast(
                PackageTransactionPinState,
                _wire_string(document["state"], name="pin state"),
            ),
            prior_receipt_id=_wire_optional_string(
                document["priorReceiptId"], name="prior receipt id"
            ),
            transition_evidence_ref=_wire_optional_string(
                document["transitionEvidenceRef"],
                name="transition evidence ref",
            ),
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


class PackageTransactionPinPort(Protocol):
    """Narrow external owner; receives no path, candidate, or store capability."""

    def acquire(
        self,
        request: PackageTransactionPinRequestV1,
    ) -> PackageTransactionPinReceiptV1: ...

    def release(
        self,
        receipt: PackageTransactionPinReceiptV1,
        *,
        transition_evidence_ref: str,
    ) -> PackageTransactionPinReceiptV1: ...


class PackageTransactionPinJournalError(RuntimeError):
    """Fail-closed transaction-pin journal refusal."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageTransactionPinRecordV1:
    record_revision: int
    prior_pin_revision: int
    receipt: PackageTransactionPinReceiptV1
    record_version: int = PACKAGE_TRANSACTION_PIN_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.record_revision, name="transaction pin record revision")
        _require_nonnegative(
            self.prior_pin_revision,
            name="prior transaction pin revision",
        )
        if not isinstance(self.receipt, PackageTransactionPinReceiptV1):
            raise TypeError("Package transaction pin receipt is required")
        if self.record_version != PACKAGE_TRANSACTION_PIN_RECORD_VERSION:
            raise ValueError("Unsupported Package transaction pin record")

    @property
    def operation_id(self) -> str:
        return self.receipt.pin_request.operation_id

    @property
    def attempt_epoch(self) -> int:
        return self.receipt.pin_request.attempt_epoch

    @property
    def pin_request_id(self) -> str:
        return self.receipt.pin_request.pin_request_id

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "operationId": self.operation_id,
            "pinRequestId": self.pin_request_id,
            "priorPinRevision": self.prior_pin_revision,
            "receipt": self.receipt.to_dict(),
            "receiptId": self.receipt.receipt_id,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "state": self.receipt.state,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageTransactionPinRecordV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "operationId",
                "pinRequestId",
                "priorPinRevision",
                "receipt",
                "receiptId",
                "recordRevision",
                "recordVersion",
                "state",
            },
            name="Package transaction pin record",
        )
        record = cls(
            record_revision=_wire_int(
                document["recordRevision"], name="record revision"
            ),
            prior_pin_revision=_wire_int(
                document["priorPinRevision"], name="prior pin revision"
            ),
            receipt=PackageTransactionPinReceiptV1.from_dict(document["receipt"]),
            record_version=_wire_int(document["recordVersion"], name="record version"),
        )
        if (
            document["attemptEpoch"] != record.attempt_epoch
            or document["operationId"] != record.operation_id
            or document["pinRequestId"] != record.pin_request_id
            or document["receiptId"] != record.receipt.receipt_id
            or document["state"] != record.receipt.state
        ):
            raise ValueError("Package transaction pin record projection changed")
        return record


def _encode_record(record: PackageTransactionPinRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageTransactionPinRecordV1):
        raise TypeError("Package transaction pin record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageTransactionPinRecordV1:
    try:
        return PackageTransactionPinRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package transaction pin record is invalid",
            code="invalid_package_transaction_pin_record",
        ) from exc


PACKAGE_TRANSACTION_PIN_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageTransactionPinJournal:
    """Record one exact acquired pin and at most one terminal transition."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        receipt: PackageTransactionPinReceiptV1,
    ) -> PackageTransactionPinReceiptV1:
        if not isinstance(receipt, PackageTransactionPinReceiptV1):
            raise TypeError("Package transaction pin receipt is required")
        with self._exclusive():
            records = self._load_unlocked()
            operation_records = tuple(
                record
                for record in records
                if record.operation_id == receipt.pin_request.operation_id
            )
            latest = operation_records[-1] if operation_records else None
            if latest is None:
                if receipt.state != "acquired":
                    raise self._error(
                        "Package transaction pin transition has no acquisition",
                        code="package_operation_phase_conflict",
                    )
            else:
                if latest.receipt == receipt:
                    return receipt
                if latest.pin_request_id != receipt.pin_request.pin_request_id or (
                    latest.receipt.pin_request != receipt.pin_request
                ):
                    raise self._error(
                        "Package transaction pin request identity changed",
                        code="package_operation_identity_conflict",
                    )
                if latest.receipt.state != "acquired" or receipt.state == "acquired":
                    raise self._error(
                        "Package transaction pin cannot transition again",
                        code="package_operation_phase_conflict",
                    )
                try:
                    _require_receipt_transition(latest.receipt, receipt)
                except ValueError as exc:
                    raise self._error(
                        "Package transaction pin transition changed",
                        code="package_operation_identity_conflict",
                    ) from exc
            record = PackageTransactionPinRecordV1(
                record_revision=len(records) + 1,
                prior_pin_revision=(0 if latest is None else latest.record_revision),
                receipt=receipt,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=PACKAGE_TRANSACTION_PIN_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return receipt

    def current(
        self,
        *,
        operation_id: str,
        pin_request_id: str,
    ) -> PackageTransactionPinReceiptV1 | None:
        _require_safe_id(operation_id, name="transaction pin operation identity")
        _require_sha256(pin_request_id, name="transaction pin request id")
        with self._exclusive():
            matching = tuple(
                record.receipt
                for record in self._load_unlocked()
                if record.operation_id == operation_id
                and record.pin_request_id == pin_request_id
            )
            return matching[-1] if matching else None

    def records(self) -> tuple[PackageTransactionPinRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[PackageTransactionPinRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageTransactionPinRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_TRANSACTION_PIN_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            _assert_no_duplicate_json_keys(self._path)
            _validate_records(records)
            return records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Package transaction pin journal is corrupt",
                code="package_transaction_pin_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(
        self,
        message: str,
        *,
        code: str,
    ) -> PackageTransactionPinJournalError:
        return PackageTransactionPinJournalError(
            message,
            code=code,
            path=self._path,
        )


def _validate_records(records: tuple[PackageTransactionPinRecordV1, ...]) -> None:
    latest: dict[str, PackageTransactionPinRecordV1] = {}
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package transaction pin revisions are not contiguous")
        prior = latest.get(record.operation_id)
        if record.prior_pin_revision != (0 if prior is None else prior.record_revision):
            raise ValueError("Package transaction pin predecessor changed")
        if prior is None:
            if record.receipt.state != "acquired":
                raise ValueError("Package transaction pin begins after acquisition")
        else:
            if prior.pin_request_id != record.pin_request_id or (
                prior.receipt.pin_request != record.receipt.pin_request
            ):
                raise ValueError("Package transaction pin request changed")
            if prior.receipt.state != "acquired":
                raise ValueError("Package transaction pin has multiple transitions")
            _require_receipt_transition(prior.receipt, record.receipt)
        latest[record.operation_id] = record


def _require_receipt_transition(
    prior: PackageTransactionPinReceiptV1,
    current: PackageTransactionPinReceiptV1,
) -> None:
    if prior.state != "acquired" or current.state not in _TERMINAL_PIN_STATES:
        raise ValueError("Package transaction pin transition is invalid")
    if (
        current.prior_receipt_id != prior.receipt_id
        or current.pin_request != prior.pin_request
        or current.pin_id != prior.pin_id
        or current.owner_identity != prior.owner_identity
        or current.lease_id != prior.lease_id
        or current.owner_revision <= prior.owner_revision
        or current.lease_revision <= prior.lease_revision
    ):
        raise ValueError("Package transaction pin transition facts changed")


def _receipt_identity_dict(
    *,
    pin_request: PackageTransactionPinRequestV1,
    pin_id: str,
    owner_identity: str,
    owner_revision: int,
    lease_id: str,
    lease_revision: int,
    state: PackageTransactionPinState,
    prior_receipt_id: str | None,
    transition_evidence_ref: str | None,
    receipt_version: int,
) -> dict[str, object]:
    return {
        "leaseId": lease_id,
        "leaseRevision": lease_revision,
        "ownerIdentity": owner_identity,
        "ownerRevision": owner_revision,
        "pinId": pin_id,
        "pinRequest": pin_request.to_dict(),
        "priorReceiptId": prior_receipt_id,
        "receiptVersion": receipt_version,
        "state": state,
        "transitionEvidenceRef": transition_evidence_ref,
    }


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _canonical_distribution(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Package distribution name must be a string")
    result = re.sub(r"[-_.]+", "-", value.strip()).lower()
    if not result or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result) is None:
        raise ValueError("Package distribution name is invalid")
    return result


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")


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
            raise ValueError("Package transaction pin has duplicate JSON keys")
        document[key] = value
    return document


__all__ = [
    "PACKAGE_TRANSACTION_PIN_JOURNAL_CODEC",
    "PackageTransactionPinJournal",
    "PackageTransactionPinJournalError",
    "PackageTransactionPinPort",
    "PackageTransactionPinReceiptV1",
    "PackageTransactionPinRecordV1",
    "PackageTransactionPinRequestV1",
    "PackageTransactionPinTargetV1",
]
