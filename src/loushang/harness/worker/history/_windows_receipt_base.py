"""Source-bound Windows receipt semantics over existing history records."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Protocol, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._base_codec import _SourceBoundBaseWireMethods
from loushang.harness.worker.history._opt_in import _OptInDecisionMethods
from loushang.harness.worker.history._receipts import _ReceiptRecordMethods
from loushang.harness.worker.history._windows_semantic_contracts import (
    _DIGEST,
    _RecoveryFacts,
    _SourceFacts,
)


class _ReceiptOptInFacts(Protocol):
    @property
    def contribution_id(self) -> str: ...
    @property
    def artifact_digest(self) -> str: ...
    @property
    def native_platform(self) -> str: ...
    @property
    def require_worker(self) -> bool: ...


class _WindowsReceiptBaseMethods(_SourceBoundBaseWireMethods):
    __slots__ = ()
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    last_issue_sequence: int
    retired_receipt_fingerprints: tuple[str, ...]
    record_digest: str
    version: int
    _decision_type: ClassVar[type[_OptInDecisionMethods]]
    _record_type: ClassVar[type[_ReceiptRecordMethods]]
    _replay_type: ClassVar[Callable[..., object]]
    _product_id: ClassVar[str]
    _native_profile_id: ClassVar[str]
    _native_platform: ClassVar[str]

    @staticmethod
    def _session_scope_id(session_id: str) -> str:
        """Pure Product scope policy supplied by the concrete value facade."""
        raise NotImplementedError

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

    @classmethod
    def _from_source_read(cls, source: _SourceFacts, recovery: _RecoveryFacts) -> Self:
        records = recovery.receipt_records
        if records and not any(
            item.name == "worker-activation-receipts.jsonl" for item in source.files
        ):
            raise ValueError("Windows Worker receipt source is absent")
        if any(
            type(item) is not cls._decision_type for item in recovery.opt_in_decisions
        ):
            raise ValueError("Windows Worker receipt opt-in history is invalid")
        decisions = {item.decision_digest: item for item in recovery.opt_in_decisions}
        if len(decisions) != len(recovery.opt_in_decisions):
            raise ValueError("Windows Worker receipt opt-in history is invalid")
        fingerprints: set[str] = set()
        for sequence, record in enumerate(records, 1):
            if type(record) is not cls._record_type:
                raise ValueError("Windows Worker receipt history is invalid")
            receipt = record.receipt
            policy = receipt.policy
            decision = decisions.get(record.opt_in_decision_digest)
            if (
                record.journal_revision != sequence
                or record.scope_id != source.scope_id
                or receipt.fingerprint in fingerprints
                or policy.product_id != cls._product_id
                or policy.product_scope_id != cls._session_scope_id(policy.session_id)
                or policy.native_profile_id != cls._native_profile_id
                or decision is None
                or decision.action != "allow"
                or decision.opt_in is None
                or decision.plugin_id != policy.plugin_id
                or cast(_ReceiptOptInFacts, decision.opt_in).contribution_id
                != policy.contribution_id
                or cast(_ReceiptOptInFacts, decision.opt_in).artifact_digest
                != policy.plugin_revision_digest
                or cast(_ReceiptOptInFacts, decision.opt_in).native_platform
                != cls._native_platform
                or policy.effective_required
                != (
                    policy.declared_required
                    or cast(_ReceiptOptInFacts, decision.opt_in).require_worker
                )
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
        return cast(Callable[..., Self], cls)(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            last_issue_sequence=len(records),
            retired_receipt_fingerprints=tuple(sorted(fingerprints)),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _replay_retained(self, records: tuple[_ReceiptRecordMethods, ...]) -> object:
        if type(records) is not tuple:
            raise ValueError("Windows Worker receipt retained replay is invalid")
        fingerprints = set(self.retired_receipt_fingerprints)
        for sequence, record in enumerate(records, self.last_issue_sequence + 1):
            if type(record) is not self._record_type:
                raise ValueError("Windows Worker receipt retained replay is invalid")
            if (
                record.journal_revision != sequence
                or record.scope_id != self.scope_id
                or record.receipt.fingerprint in fingerprints
            ):
                raise ValueError("Windows Worker receipt retained replay is invalid")
            fingerprints.add(record.receipt.fingerprint)
        return self._replay_type(
            last_issue_sequence=self.last_issue_sequence + len(records),
            retained_records=records,
            receipt_fingerprints=frozenset(fingerprints),
        )
