"""Source-bound Windows Worker native provisioning cutover projection.

This typed base preserves old attempt identities and terminal observations.
It cannot commit a Product cutover, authorize cleanup, or delete old files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

from loushang.harness.journal import JournalCodecError
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
    WindowsWorkerProvisioningStateJournalError,
    _canonical,
    _inventory_identity,
    _Record,
    windows_worker_provisioning_settlement_fingerprint,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_PREFIX = "worker-native-provisioning-"
_MAX_BASE_BYTES = 32 * 1024 * 1024


def _name(attempt_id: str) -> str:
    return f"{_PREFIX}{attempt_id}.jsonl"


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerNativeProvisioningRetainedAttemptV1:
    attempt_id: str
    identity: dict[str, object]
    cutoff_revision: int
    last_record: _Record
    phase_history: tuple[str, ...]
    witness_present_history: tuple[bool, ...]
    last_witness_state: str | None
    settlement_fingerprint: str | None

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.last_record) is not _Record
        ):
            raise ValueError(
                "Windows Worker native provisioning base attempt is invalid"
            )
        try:
            name = _name(self.attempt_id)
            identity = _inventory_identity(
                name, _canonical(self.last_record.to_dict()) + b"\n"
            )
            journal = WindowsWorkerProvisioningStateJournal(
                Path.cwd() / name, identity=identity
            )
            validated = journal._decode(self.last_record.to_dict())
            document = validated.document
            witness = document["witness"]
            witness_state = (
                None
                if witness is None
                else cast(str, cast(dict[str, object], witness)["state"])
            )
            fingerprint = (
                windows_worker_provisioning_settlement_fingerprint(document)
                if document["phase"] == "settled"
                else None
            )
        except (
            AttributeError,
            JournalCodecError,
            KeyError,
            TypeError,
            ValueError,
            WindowsWorkerProvisioningStateJournalError,
        ) as exc:
            raise ValueError(
                "Windows Worker native provisioning base attempt is invalid"
            ) from exc
        if (
            type(self.identity) is not dict
            or self.identity != identity
            or type(self.cutoff_revision) is not int
            or not 1 <= self.cutoff_revision <= 256
            or validated != self.last_record
            or validated.revision != self.cutoff_revision
            or type(self.phase_history) is not tuple
            or len(self.phase_history) != self.cutoff_revision
            or any(type(phase) is not str for phase in self.phase_history)
            or self.phase_history[-1] != document["phase"]
            or type(self.witness_present_history) is not tuple
            or len(self.witness_present_history) != self.cutoff_revision
            or any(
                type(present) is not bool for present in self.witness_present_history
            )
            or self.witness_present_history[-1] != (witness is not None)
            or self.last_witness_state != witness_state
            or self.settlement_fingerprint != fingerprint
        ):
            raise ValueError(
                "Windows Worker native provisioning base attempt is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "cutoffRevision": self.cutoff_revision,
            "identity": self.identity,
            "lastRecord": self.last_record.to_dict(),
            "lastWitnessState": self.last_witness_state,
            "phaseHistory": list(self.phase_history),
            "settlementFingerprint": self.settlement_fingerprint,
            "witnessPresentHistory": list(self.witness_present_history),
        }

    @classmethod
    def from_dict(
        cls, value: object
    ) -> CodingWindowsWorkerNativeProvisioningRetainedAttemptV1:
        if (
            type(value) is not dict
            or set(value)
            != {
                "attemptId",
                "cutoffRevision",
                "identity",
                "lastRecord",
                "lastWitnessState",
                "phaseHistory",
                "settlementFingerprint",
                "witnessPresentHistory",
            }
            or type(value["lastRecord"]) is not dict
            or set(value["lastRecord"])
            != {"document", "documentDigest", "journalRevision", "recordVersion"}
            or type(value["lastRecord"]["recordVersion"]) is not int
            or value["lastRecord"]["recordVersion"] != 1
            or type(value["phaseHistory"]) is not list
            or type(value["witnessPresentHistory"]) is not list
        ):
            raise ValueError(
                "Windows Worker native provisioning base attempt is invalid"
            )
        record = value["lastRecord"]
        return cls(
            attempt_id=value["attemptId"],
            identity=value["identity"],
            cutoff_revision=value["cutoffRevision"],
            last_record=_Record(
                revision=record["journalRevision"],
                document=record["document"],
                digest=record["documentDigest"],
            ),
            phase_history=tuple(value["phaseHistory"]),
            witness_present_history=tuple(value["witnessPresentHistory"]),
            last_witness_state=value["lastWitnessState"],
            settlement_fingerprint=value["settlementFingerprint"],
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerNativeProvisioningSemanticBaseV1:
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    retained_attempts: tuple[
        CodingWindowsWorkerNativeProvisioningRetainedAttemptV1, ...
    ]
    attempt_ids: tuple[str, ...]
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
            or type(self.retained_attempts) is not tuple
            or any(
                type(item) is not CodingWindowsWorkerNativeProvisioningRetainedAttemptV1
                for item in self.retained_attempts
            )
            or tuple(item.attempt_id for item in self.retained_attempts)
            != tuple(sorted({item.attempt_id for item in self.retained_attempts}))
            or type(self.attempt_ids) is not tuple
            or self.attempt_ids
            != tuple(item.attempt_id for item in self.retained_attempts)
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError(
                "Windows Worker native provisioning semantic base is invalid"
            )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "attemptIds": list(self.attempt_ids),
            "retainedAttempts": [item.to_dict() for item in self.retained_attempts],
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
            raise ValueError("Windows Worker native provisioning base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(
        cls, raw: bytes
    ) -> CodingWindowsWorkerNativeProvisioningSemanticBaseV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError(
                "Windows Worker native provisioning semantic base is invalid"
            )
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "attemptIds",
                    "retainedAttempts",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                    "recordDigest",
                    "version",
                }
                or type(value["attemptIds"]) is not list
                or type(value["retainedAttempts"]) is not list
            ):
                raise ValueError(
                    "Windows Worker native provisioning semantic base is invalid"
                )
            base = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                retained_attempts=tuple(
                    CodingWindowsWorkerNativeProvisioningRetainedAttemptV1.from_dict(
                        item
                    )
                    for item in value["retainedAttempts"]
                ),
                attempt_ids=tuple(value["attemptIds"]),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError(
                    "Windows Worker native provisioning semantic base is invalid"
                )
            return base
        except (KeyError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
            raise ValueError(
                "Windows Worker native provisioning semantic base is invalid"
            ) from exc

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerNativeProvisioningSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError(
                "Windows Worker native provisioning preparation is invalid"
            )
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        attempts = recovery.native_provisioning_attempts
        if any(
            type(item) is not WindowsWorkerProvisioningAttemptV1 for item in attempts
        ):
            raise ValueError("Windows Worker native provisioning history is invalid")
        by_id = {item.attempt_id: item for item in attempts}
        if len(by_id) != len(attempts):
            raise ValueError("Windows Worker native provisioning history is invalid")
        files = {
            item.name: item for item in source.files if item.name.startswith(_PREFIX)
        }
        expected = {
            name
            for attempt_id in by_id
            for name in (_name(attempt_id), _name(attempt_id) + ".lock")
        }
        if set(files) != expected:
            raise ValueError("Windows Worker native provisioning source is absent")
        recovery_attempts = {item.attempt_id: item for item in recovery.attempts}
        if len(recovery_attempts) != len(recovery.attempts):
            raise ValueError(
                "Windows Worker native provisioning recovery join is invalid"
            )
        retained = []
        for attempt_id, attempt in sorted(by_id.items()):
            name = _name(attempt_id)
            raw = b"".join(
                _canonical(record.to_dict()) + b"\n" for record in attempt.records
            )
            source_file = files[name]
            lock_file = files[name + ".lock"]
            if (
                source_file.size != len(raw)
                or source_file.sha256_digest != sha256(raw).hexdigest()
                or lock_file.size != 1
                or lock_file.sha256_digest != sha256(b"\1").hexdigest()
            ):
                raise ValueError("Windows Worker native provisioning source changed")
            try:
                identity = _inventory_identity(name, raw)
                records, _ = WindowsWorkerProvisioningStateJournal(
                    Path.cwd() / name, identity=identity
                )._decode_raw(raw)
            except (ValueError, WindowsWorkerProvisioningStateJournalError) as exc:
                raise ValueError(
                    "Windows Worker native provisioning history is invalid"
                ) from exc
            observed = recovery_attempts.get(attempt_id)
            if (
                identity != attempt.identity
                or records != attempt.records
                or attempt.state_revision != len(records)
                or attempt.phase != records[-1].document["phase"]
                or attempt.phase_history
                != tuple(record.document["phase"] for record in records)
                or attempt.witness_present_history
                != tuple(record.document["witness"] is not None for record in records)
                or observed is None
                or observed.native_phase != attempt.phase
                or observed.native_revision != attempt.state_revision
                or observed.native_phase_history != attempt.phase_history
                or observed.native_witness_present_history
                != attempt.witness_present_history
                or observed.native_worker_request_fingerprint
                != identity["workerRequestFingerprint"]
                or observed.native_receipt_fingerprint != identity["receiptFingerprint"]
                or observed.native_job_name != identity["jobObjectName"]
            ):
                raise ValueError(
                    "Windows Worker native provisioning recovery join is invalid"
                )
            retained.append(
                CodingWindowsWorkerNativeProvisioningRetainedAttemptV1(
                    attempt_id=attempt_id,
                    identity=identity,
                    cutoff_revision=len(records),
                    last_record=records[-1],
                    phase_history=attempt.phase_history,
                    witness_present_history=attempt.witness_present_history,
                    last_witness_state=attempt.last_witness_state,
                    settlement_fingerprint=attempt.settlement_fingerprint,
                )
            )
        ids = tuple(sorted(by_id))
        unsigned = {
            "attemptIds": list(ids),
            "retainedAttempts": [item.to_dict() for item in retained],
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            retained_attempts=tuple(retained),
            attempt_ids=ids,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


__all__ = [
    "CodingWindowsWorkerNativeProvisioningRetainedAttemptV1",
    "CodingWindowsWorkerNativeProvisioningSemanticBaseV1",
]
