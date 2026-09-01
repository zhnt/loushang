"""Dark typed staging boundary and adjacent evidence for PLC9B3e."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Protocol

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
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    DependencyClosureNodeV2,
    PackageStableRefV1,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinReceiptV1,
    PackageTransactionPinTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelCandidate,
)

PACKAGE_PLUGIN_ROOT_TARGET_VERSION = 1
PACKAGE_ARTIFACT_STAGING_REQUEST_VERSION = 1
PACKAGE_ARTIFACT_STAGING_RECEIPT_VERSION = 1
PACKAGE_ARTIFACT_STAGING_RECORD_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


@dataclass(frozen=True, slots=True)
class PackagePluginRootTargetV1:
    """Authority-issued logical identity for the one designated Plugin root."""

    target_id: str
    operation_id: str
    request_fingerprint: str
    product_id: str
    scope_id: str
    installation_id: str
    plugin_id: str
    authority_id: str
    authority_revision: str
    target_version: int = PACKAGE_PLUGIN_ROOT_TARGET_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.target_id, name="Plugin root target id")
        for value, name in (
            (self.operation_id, "Package operation identity"),
            (self.product_id, "Product identity"),
            (self.scope_id, "scope identity"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
            (self.authority_id, "Plugin target authority identity"),
            (self.authority_revision, "Plugin target authority revision"),
        ):
            _require_safe_id(value, name=name)
        _require_sha256(self.request_fingerprint, name="request fingerprint")
        if self.target_version != PACKAGE_PLUGIN_ROOT_TARGET_VERSION:
            raise ValueError("Unsupported Package Plugin root target")
        if self.target_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package Plugin root target id does not match")

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
        authority_id: str,
        authority_revision: str,
    ) -> PackagePluginRootTargetV1:
        values = _root_target_identity_dict(
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
            authority_id=authority_id,
            authority_revision=authority_revision,
            target_version=PACKAGE_PLUGIN_ROOT_TARGET_VERSION,
        )
        return cls(
            target_id=_fingerprint(values),
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
            authority_id=authority_id,
            authority_revision=authority_revision,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _root_target_identity_dict(
            operation_id=self.operation_id,
            request_fingerprint=self.request_fingerprint,
            product_id=self.product_id,
            scope_id=self.scope_id,
            installation_id=self.installation_id,
            plugin_id=self.plugin_id,
            authority_id=self.authority_id,
            authority_revision=self.authority_revision,
            target_version=self.target_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"targetId": self.target_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackagePluginRootTargetV1:
        document = _exact_dict(
            value,
            fields={
                "authorityId",
                "authorityRevision",
                "installationId",
                "operationId",
                "pluginId",
                "productId",
                "requestFingerprint",
                "scopeId",
                "targetId",
                "targetVersion",
            },
            name="Package Plugin root target",
        )
        return cls(
            target_id=_wire_string(document["targetId"], name="target id"),
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
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
            authority_id=_wire_string(
                document["authorityId"], name="authority identity"
            ),
            authority_revision=_wire_string(
                document["authorityRevision"], name="authority revision"
            ),
            target_version=_wire_int(document["targetVersion"], name="target version"),
        )


@dataclass(frozen=True, slots=True)
class PackageArtifactStagingRequestV1:
    """One exact pinned plan node offered to its role-specific store owner."""

    staging_request_id: str
    operation_id: str
    attempt_epoch: int
    request_fingerprint: str
    classification_fingerprint: str
    verified_plan_fingerprint: str
    prepublication_graph_digest: str
    pin_receipt_id: str
    recovery_identity: str
    plan_node: VerifiedClosurePlanNodeV2
    root_target: PackagePluginRootTargetV1 | None
    request_version: int = PACKAGE_ARTIFACT_STAGING_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.staging_request_id, name="staging request id")
        _require_safe_id(self.operation_id, name="Package operation identity")
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        for value, name in (
            (self.request_fingerprint, "request fingerprint"),
            (self.classification_fingerprint, "classification fingerprint"),
            (self.verified_plan_fingerprint, "verified plan fingerprint"),
            (self.prepublication_graph_digest, "prepublication graph digest"),
            (self.pin_receipt_id, "transaction pin receipt id"),
        ):
            _require_sha256(value, name=name)
        _require_safe_id(self.recovery_identity, name="recovery identity")
        if not isinstance(self.plan_node, VerifiedClosurePlanNodeV2):
            raise TypeError("Verified closure plan node is required")
        if self.plan_node.role == "root":
            if not isinstance(self.root_target, PackagePluginRootTargetV1):
                raise TypeError("Plugin root staging requires its target identity")
            if (
                self.root_target.operation_id != self.operation_id
                or self.root_target.request_fingerprint != self.request_fingerprint
            ):
                raise ValueError("Plugin root target changed Package operation")
        elif self.root_target is not None:
            raise ValueError("Dependency staging cannot carry a Plugin root target")
        if self.request_version != PACKAGE_ARTIFACT_STAGING_REQUEST_VERSION:
            raise ValueError("Unsupported Package artifact staging request")
        if self.staging_request_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package artifact staging request id does not match")

    @classmethod
    def create(
        cls,
        plan: VerifiedClosurePlanV2,
        *,
        node_id: str,
        request_fingerprint: str,
        classification_fingerprint: str,
        pin_receipt: PackageTransactionPinReceiptV1,
        root_target: PackagePluginRootTargetV1 | None = None,
    ) -> PackageArtifactStagingRequestV1:
        if not isinstance(plan, VerifiedClosurePlanV2):
            raise TypeError("Verified closure plan is required")
        if not isinstance(pin_receipt, PackageTransactionPinReceiptV1):
            raise TypeError("Package transaction pin receipt is required")
        if pin_receipt.state != "acquired":
            raise ValueError("Artifact staging requires an acquired transaction pin")
        node = next((item for item in plan.nodes if item.node_id == node_id), None)
        if node is None:
            raise ValueError("Artifact staging node is outside the verified plan")
        pin_request = pin_receipt.pin_request
        expected_targets = tuple(
            PackageTransactionPinTargetV1.from_plan_node(item) for item in plan.nodes
        )
        if (
            pin_request.operation_id != plan.operation_id
            or pin_request.attempt_epoch > plan.attempt_epoch
            or pin_request.request_fingerprint != request_fingerprint
            or pin_request.classification_fingerprint != classification_fingerprint
            or pin_request.prepublication_graph_digest != plan.graph_digest
            or pin_request.targets != expected_targets
            or pin_request.root_target_id
            != next(
                target.target_id for target in expected_targets if target.role == "root"
            )
        ):
            raise ValueError("Transaction pin does not cover the verified plan")
        if node.role == "root":
            if root_target is None:
                raise TypeError("Plugin root staging requires its target identity")
            if (
                root_target.operation_id != plan.operation_id
                or root_target.request_fingerprint != request_fingerprint
            ):
                raise ValueError("Plugin root target changed Package operation")
        elif root_target is not None:
            raise ValueError("Dependency staging cannot carry a Plugin root target")
        values = _staging_request_identity_dict(
            operation_id=plan.operation_id,
            attempt_epoch=plan.attempt_epoch,
            request_fingerprint=request_fingerprint,
            classification_fingerprint=classification_fingerprint,
            verified_plan_fingerprint=plan.fingerprint,
            prepublication_graph_digest=plan.graph_digest,
            pin_receipt_id=pin_receipt.receipt_id,
            recovery_identity=pin_request.recovery_identity,
            plan_node=node,
            root_target=root_target,
            request_version=PACKAGE_ARTIFACT_STAGING_REQUEST_VERSION,
        )
        return cls(
            staging_request_id=_fingerprint(values),
            operation_id=plan.operation_id,
            attempt_epoch=plan.attempt_epoch,
            request_fingerprint=request_fingerprint,
            classification_fingerprint=classification_fingerprint,
            verified_plan_fingerprint=plan.fingerprint,
            prepublication_graph_digest=plan.graph_digest,
            pin_receipt_id=pin_receipt.receipt_id,
            recovery_identity=pin_request.recovery_identity,
            plan_node=node,
            root_target=root_target,
        )

    @property
    def node_id(self) -> str:
        return self.plan_node.node_id

    def _identity_dict(self) -> dict[str, object]:
        return _staging_request_identity_dict(
            operation_id=self.operation_id,
            attempt_epoch=self.attempt_epoch,
            request_fingerprint=self.request_fingerprint,
            classification_fingerprint=self.classification_fingerprint,
            verified_plan_fingerprint=self.verified_plan_fingerprint,
            prepublication_graph_digest=self.prepublication_graph_digest,
            pin_receipt_id=self.pin_receipt_id,
            recovery_identity=self.recovery_identity,
            plan_node=self.plan_node,
            root_target=self.root_target,
            request_version=self.request_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"stagingRequestId": self.staging_request_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageArtifactStagingRequestV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "classificationFingerprint",
                "operationId",
                "pinReceiptId",
                "planNode",
                "prepublicationGraphDigest",
                "recoveryIdentity",
                "requestFingerprint",
                "requestVersion",
                "rootTarget",
                "stagingRequestId",
                "verifiedPlanFingerprint",
            },
            name="Package artifact staging request",
        )
        raw_target = document["rootTarget"]
        return cls(
            staging_request_id=_wire_string(
                document["stagingRequestId"], name="staging request id"
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
            pin_receipt_id=_wire_string(
                document["pinReceiptId"], name="transaction pin receipt id"
            ),
            recovery_identity=_wire_string(
                document["recoveryIdentity"], name="recovery identity"
            ),
            plan_node=VerifiedClosurePlanNodeV2.from_dict(document["planNode"]),
            root_target=(
                None
                if raw_target is None
                else PackagePluginRootTargetV1.from_dict(raw_target)
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageArtifactStagingReceiptV1:
    """Store-issued typed stable ref that remains owner-private until set commit."""

    receipt_id: str
    staging_request: PackageArtifactStagingRequestV1
    stable_ref: PackageStableRefV1
    receipt_version: int = PACKAGE_ARTIFACT_STAGING_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, name="artifact staging receipt id")
        if not isinstance(self.staging_request, PackageArtifactStagingRequestV1):
            raise TypeError("Package artifact staging request is required")
        if not isinstance(
            self.stable_ref,
            (VerifiedArtifactRefV1, PluginRevisionRefV1),
        ):
            raise TypeError("Typed Package stable ref is required")
        DependencyClosureNodeV2(
            plan_node=self.staging_request.plan_node,
            stable_ref=self.stable_ref,
        )
        target = self.staging_request.root_target
        if isinstance(self.stable_ref, PluginRevisionRefV1):
            assert target is not None
            if (
                self.stable_ref.installation_id != target.installation_id
                or self.stable_ref.plugin_id != target.plugin_id
            ):
                raise ValueError("Staged Plugin revision target identity changed")
        if self.receipt_version != PACKAGE_ARTIFACT_STAGING_RECEIPT_VERSION:
            raise ValueError("Unsupported Package artifact staging receipt")
        if self.receipt_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package artifact staging receipt id does not match")

    @classmethod
    def create(
        cls,
        staging_request: PackageArtifactStagingRequestV1,
        *,
        stable_ref: PackageStableRefV1,
    ) -> PackageArtifactStagingReceiptV1:
        if not isinstance(staging_request, PackageArtifactStagingRequestV1):
            raise TypeError("Package artifact staging request is required")
        kind = _stable_ref_kind(stable_ref)
        values = {
            "receiptVersion": PACKAGE_ARTIFACT_STAGING_RECEIPT_VERSION,
            "stableRef": {"kind": kind, "value": stable_ref.to_dict()},
            "stagingRequest": staging_request.to_dict(),
        }
        return cls(
            receipt_id=_fingerprint(values),
            staging_request=staging_request,
            stable_ref=stable_ref,
        )

    @property
    def operation_id(self) -> str:
        return self.staging_request.operation_id

    @property
    def node_id(self) -> str:
        return self.staging_request.node_id

    def _identity_dict(self) -> dict[str, object]:
        return {
            "receiptVersion": self.receipt_version,
            "stableRef": {
                "kind": _stable_ref_kind(self.stable_ref),
                "value": self.stable_ref.to_dict(),
            },
            "stagingRequest": self.staging_request.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {"receiptId": self.receipt_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageArtifactStagingReceiptV1:
        document = _exact_dict(
            value,
            fields={
                "receiptId",
                "receiptVersion",
                "stableRef",
                "stagingRequest",
            },
            name="Package artifact staging receipt",
        )
        stable_document = _exact_dict(
            document["stableRef"],
            fields={"kind", "value"},
            name="Package staging stable ref",
        )
        kind = _wire_string(stable_document["kind"], name="stable ref kind")
        if kind == "verified_artifact":
            stable_ref: PackageStableRefV1 = VerifiedArtifactRefV1.from_dict(
                stable_document["value"]
            )
        elif kind == "plugin_revision":
            stable_ref = PluginRevisionRefV1.from_dict(stable_document["value"])
        else:
            raise ValueError("Unsupported Package staging stable ref")
        return cls(
            receipt_id=_wire_string(document["receiptId"], name="receipt id"),
            staging_request=PackageArtifactStagingRequestV1.from_dict(
                document["stagingRequest"]
            ),
            stable_ref=stable_ref,
            receipt_version=_wire_int(
                document["receiptVersion"], name="receipt version"
            ),
        )


class PackageDependencyStagingPort(Protocol):
    """Neutral store owner; it can stage only a dependency candidate."""

    def stage_dependency(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1: ...


class PackagePluginRootStagingPort(Protocol):
    """Plugin revision store owner; it can stage only the designated root."""

    def stage_root(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1: ...


class PackageArtifactStagingJournalError(RuntimeError):
    """Fail-closed adjacent staging-evidence journal refusal."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageArtifactStagingRecordV1:
    record_revision: int
    receipt: PackageArtifactStagingReceiptV1
    record_version: int = PACKAGE_ARTIFACT_STAGING_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.record_revision, name="staging record revision")
        if not isinstance(self.receipt, PackageArtifactStagingReceiptV1):
            raise TypeError("Package artifact staging receipt is required")
        if self.record_version != PACKAGE_ARTIFACT_STAGING_RECORD_VERSION:
            raise ValueError("Unsupported Package artifact staging record")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.receipt.staging_request.attempt_epoch,
            "nodeId": self.receipt.node_id,
            "operationId": self.receipt.operation_id,
            "receipt": self.receipt.to_dict(),
            "receiptId": self.receipt.receipt_id,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "stagingRequestId": self.receipt.staging_request.staging_request_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageArtifactStagingRecordV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "nodeId",
                "operationId",
                "receipt",
                "receiptId",
                "recordRevision",
                "recordVersion",
                "stagingRequestId",
            },
            name="Package artifact staging record",
        )
        record = cls(
            record_revision=_wire_int(
                document["recordRevision"], name="record revision"
            ),
            receipt=PackageArtifactStagingReceiptV1.from_dict(document["receipt"]),
            record_version=_wire_int(document["recordVersion"], name="record version"),
        )
        if (
            document["attemptEpoch"] != record.receipt.staging_request.attempt_epoch
            or document["nodeId"] != record.receipt.node_id
            or document["operationId"] != record.receipt.operation_id
            or document["receiptId"] != record.receipt.receipt_id
            or document["stagingRequestId"]
            != record.receipt.staging_request.staging_request_id
        ):
            raise ValueError("Package artifact staging record projection changed")
        return record


def _encode_record(record: PackageArtifactStagingRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageArtifactStagingRecordV1):
        raise TypeError("Package artifact staging record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageArtifactStagingRecordV1:
    try:
        return PackageArtifactStagingRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package artifact staging record is invalid",
            code="invalid_package_artifact_staging_record",
        ) from exc


PACKAGE_ARTIFACT_STAGING_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageArtifactStagingJournal:
    """Record exactly one store-issued receipt for each operation plan node."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        if not isinstance(receipt, PackageArtifactStagingReceiptV1):
            raise TypeError("Package artifact staging receipt is required")
        with self._exclusive():
            records = self._load_unlocked()
            existing = next(
                (
                    record.receipt
                    for record in records
                    if record.receipt.operation_id == receipt.operation_id
                    and record.receipt.node_id == receipt.node_id
                ),
                None,
            )
            if existing is not None:
                if existing == receipt:
                    return existing
                raise self._error(
                    "Package artifact staging identity changed",
                    code="package_operation_identity_conflict",
                )
            record = PackageArtifactStagingRecordV1(
                record_revision=len(records) + 1,
                receipt=receipt,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=PACKAGE_ARTIFACT_STAGING_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return receipt

    def current(
        self,
        *,
        operation_id: str,
        node_id: str,
    ) -> PackageArtifactStagingReceiptV1 | None:
        _require_safe_id(operation_id, name="Package operation identity")
        _require_safe_id(node_id, name="Package node identity")
        with self._exclusive():
            return next(
                (
                    record.receipt
                    for record in self._load_unlocked()
                    if record.receipt.operation_id == operation_id
                    and record.receipt.node_id == node_id
                ),
                None,
            )

    def receipts(
        self,
        operation_id: str,
    ) -> tuple[PackageArtifactStagingReceiptV1, ...]:
        _require_safe_id(operation_id, name="Package operation identity")
        with self._exclusive():
            return tuple(
                sorted(
                    (
                        record.receipt
                        for record in self._load_unlocked()
                        if record.receipt.operation_id == operation_id
                    ),
                    key=lambda receipt: receipt.node_id,
                )
            )

    def records(self) -> tuple[PackageArtifactStagingRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[PackageArtifactStagingRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageArtifactStagingRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_ARTIFACT_STAGING_JOURNAL_CODEC,
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
                "Package artifact staging journal is corrupt",
                code="package_artifact_staging_journal_corrupt",
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
    ) -> PackageArtifactStagingJournalError:
        return PackageArtifactStagingJournalError(
            message,
            code=code,
            path=self._path,
        )


def _validate_records(
    records: tuple[PackageArtifactStagingRecordV1, ...],
) -> None:
    seen: set[tuple[str, str]] = set()
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package artifact staging revisions are not contiguous")
        key = (record.receipt.operation_id, record.receipt.node_id)
        if key in seen:
            raise ValueError("Package artifact staging node was recorded twice")
        seen.add(key)


def _root_target_identity_dict(
    *,
    operation_id: str,
    request_fingerprint: str,
    product_id: str,
    scope_id: str,
    installation_id: str,
    plugin_id: str,
    authority_id: str,
    authority_revision: str,
    target_version: int,
) -> dict[str, object]:
    return {
        "authorityId": authority_id,
        "authorityRevision": authority_revision,
        "installationId": installation_id,
        "operationId": operation_id,
        "pluginId": plugin_id,
        "productId": product_id,
        "requestFingerprint": request_fingerprint,
        "scopeId": scope_id,
        "targetVersion": target_version,
    }


def _staging_request_identity_dict(
    *,
    operation_id: str,
    attempt_epoch: int,
    request_fingerprint: str,
    classification_fingerprint: str,
    verified_plan_fingerprint: str,
    prepublication_graph_digest: str,
    pin_receipt_id: str,
    recovery_identity: str,
    plan_node: VerifiedClosurePlanNodeV2,
    root_target: PackagePluginRootTargetV1 | None,
    request_version: int,
) -> dict[str, object]:
    return {
        "attemptEpoch": attempt_epoch,
        "classificationFingerprint": classification_fingerprint,
        "operationId": operation_id,
        "pinReceiptId": pin_receipt_id,
        "planNode": plan_node.to_dict(),
        "prepublicationGraphDigest": prepublication_graph_digest,
        "recoveryIdentity": recovery_identity,
        "requestFingerprint": request_fingerprint,
        "requestVersion": request_version,
        "rootTarget": None if root_target is None else root_target.to_dict(),
        "verifiedPlanFingerprint": verified_plan_fingerprint,
    }


def _stable_ref_kind(stable_ref: PackageStableRefV1) -> str:
    if isinstance(stable_ref, VerifiedArtifactRefV1):
        return "verified_artifact"
    if isinstance(stable_ref, PluginRevisionRefV1):
        return "plugin_revision"
    raise TypeError("Typed Package stable ref is required")


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


def _exact_dict(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} does not match its versioned schema")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package artifact staging has duplicate JSON keys")
        document[key] = value
    return document


__all__ = [
    "PACKAGE_ARTIFACT_STAGING_JOURNAL_CODEC",
    "PackageArtifactStagingJournal",
    "PackageArtifactStagingJournalError",
    "PackageArtifactStagingReceiptV1",
    "PackageArtifactStagingRecordV1",
    "PackageArtifactStagingRequestV1",
    "PackageDependencyStagingPort",
    "PackagePluginRootStagingPort",
    "PackagePluginRootTargetV1",
]
