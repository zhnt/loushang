"""Typed Windows Worker receipt sequence and tombstones at a cutover boundary.

This projection preserves historical allow joins. It does not commit a
Product cutover, replace the receipt journal, or authorize source deletion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._product_worker_canary import CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_policy import coding_worker_session_scope_id
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerReceiptSemanticBaseV1:
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    last_issue_sequence: int
    retired_receipt_fingerprints: tuple[str, ...]
    record_digest: str
    version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or type(self.last_issue_sequence) is not int
            or self.last_issue_sequence < 0
            or type(self.retired_receipt_fingerprints) is not tuple
            or any(
                type(item) is not str or _DIGEST.fullmatch(item) is None
                for item in self.retired_receipt_fingerprints
            )
            or self.retired_receipt_fingerprints
            != tuple(sorted(set(self.retired_receipt_fingerprints)))
            or len(self.retired_receipt_fingerprints) != self.last_issue_sequence
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker receipt semantic base is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "lastIssueSequence": self.last_issue_sequence,
            "retiredReceiptFingerprints": list(self.retired_receipt_fingerprints),
            "scopeId": self.scope_id,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
            "version": self.version,
        }

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Windows Worker receipt semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerReceiptSemanticBaseV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Windows Worker receipt semantic base is invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "lastIssueSequence",
                    "retiredReceiptFingerprints",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                    "recordDigest",
                    "version",
                }
                or type(value["retiredReceiptFingerprints"]) is not list
            ):
                raise ValueError("Windows Worker receipt semantic base is invalid")
            base = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                last_issue_sequence=value["lastIssueSequence"],
                retired_receipt_fingerprints=tuple(value["retiredReceiptFingerprints"]),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Windows Worker receipt semantic base is invalid")
            return base
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Worker receipt semantic base is invalid") from exc

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerReceiptSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker receipt preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        records = recovery.receipt_records
        if records and not any(
            item.name == "worker-activation-receipts.jsonl" for item in source.files
        ):
            raise ValueError("Windows Worker receipt source is absent")
        if any(
            type(item) is not CodingWorkerOptInDecisionV1
            for item in recovery.opt_in_decisions
        ):
            raise ValueError("Windows Worker receipt opt-in history is invalid")
        decisions = {item.decision_digest: item for item in recovery.opt_in_decisions}
        if len(decisions) != len(recovery.opt_in_decisions):
            raise ValueError("Windows Worker receipt opt-in history is invalid")
        fingerprints: set[str] = set()
        for sequence, record in enumerate(records, 1):
            if type(record) is not CodingWorkerReceiptRecordV1:
                raise ValueError("Windows Worker receipt history is invalid")
            receipt = record.receipt
            policy = receipt.policy
            decision = decisions.get(record.opt_in_decision_digest)
            if (
                record.journal_revision != sequence
                or record.scope_id != source.scope_id
                or receipt.fingerprint in fingerprints
                or policy.product_id != "coding"
                or policy.product_scope_id
                != coding_worker_session_scope_id(policy.session_id)
                or policy.native_profile_id
                != CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID
                or decision is None
                or decision.action != "allow"
                or decision.opt_in is None
                or decision.plugin_id != policy.plugin_id
                or decision.opt_in.contribution_id != policy.contribution_id
                or decision.opt_in.artifact_digest != policy.plugin_revision_digest
                or decision.opt_in.native_platform != "windows-amd64"
                or policy.effective_required
                != (policy.declared_required or decision.opt_in.require_worker)
                or decision.generation != policy.owner_selection_generation
                or decision.kill_switch_generation != policy.kill_switch_generation
            ):
                raise ValueError("Windows Worker receipt history is invalid")
            fingerprints.add(receipt.fingerprint)
        unsigned = {
            "lastIssueSequence": len(records),
            "retiredReceiptFingerprints": sorted(fingerprints),
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            last_issue_sequence=len(records),
            retired_receipt_fingerprints=tuple(sorted(fingerprints)),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def replay(
        self, records: tuple[CodingWorkerReceiptRecordV1, ...]
    ) -> CodingWindowsWorkerReceiptReplayV1:
        if type(records) is not tuple:
            raise ValueError("Windows Worker receipt retained replay is invalid")
        fingerprints = set(self.retired_receipt_fingerprints)
        for sequence, record in enumerate(records, self.last_issue_sequence + 1):
            if type(record) is not CodingWorkerReceiptRecordV1:
                raise ValueError("Windows Worker receipt retained replay is invalid")
            if (
                record.journal_revision != sequence
                or record.scope_id != self.scope_id
                or record.receipt.fingerprint in fingerprints
            ):
                raise ValueError("Windows Worker receipt retained replay is invalid")
            fingerprints.add(record.receipt.fingerprint)
        return CodingWindowsWorkerReceiptReplayV1(
            last_issue_sequence=self.last_issue_sequence + len(records),
            retained_records=records,
            receipt_fingerprints=frozenset(fingerprints),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerReceiptReplayV1:
    last_issue_sequence: int
    retained_records: tuple[CodingWorkerReceiptRecordV1, ...]
    receipt_fingerprints: frozenset[str]


__all__ = [
    "CodingWindowsWorkerReceiptReplayV1",
    "CodingWindowsWorkerReceiptSemanticBaseV1",
]
