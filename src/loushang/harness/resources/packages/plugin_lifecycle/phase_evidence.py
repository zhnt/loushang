"""Durable typed evidence receipts for PLC9B artifact phases."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

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
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    BoundedAcquisitionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)

PACKAGE_ARTIFACT_EVIDENCE_RECORD_VERSION = 1

PackageArtifactEvidenceKind = Literal["bounded_acquisition", "verified_wheel"]
PackageArtifactEvidence = BoundedAcquisitionReceiptV1 | VerifiedWheelArtifactV1


class PackageArtifactEvidenceJournalError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageArtifactEvidenceRecordV1:
    record_revision: int
    prior_evidence_revision: int
    request_fingerprint: str
    evidence: PackageArtifactEvidence
    record_version: int = PACKAGE_ARTIFACT_EVIDENCE_RECORD_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.record_revision, int) or self.record_revision < 1:
            raise ValueError("Evidence record revision must be positive")
        if (
            not isinstance(self.prior_evidence_revision, int)
            or self.prior_evidence_revision < 0
        ):
            raise ValueError("Prior evidence revision must be non-negative")
        if (
            not isinstance(self.request_fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint) is None
        ):
            raise ValueError("Evidence request fingerprint must be SHA-256")
        if not isinstance(
            self.evidence,
            BoundedAcquisitionReceiptV1 | VerifiedWheelArtifactV1,
        ):
            raise TypeError("Typed Package artifact evidence is required")
        if self.record_version != PACKAGE_ARTIFACT_EVIDENCE_RECORD_VERSION:
            raise ValueError("Unsupported Package artifact evidence record")

    @property
    def operation_id(self) -> str:
        return self.evidence.operation_id

    @property
    def attempt_epoch(self) -> int:
        return self.evidence.attempt_epoch

    @property
    def node_id(self) -> str:
        return self.evidence.node_id

    @property
    def evidence_kind(self) -> PackageArtifactEvidenceKind:
        if isinstance(self.evidence, BoundedAcquisitionReceiptV1):
            return "bounded_acquisition"
        return "verified_wheel"

    @property
    def phase(self) -> Literal["acquired", "extracted"]:
        if self.evidence_kind == "bounded_acquisition":
            return "acquired"
        return "extracted"

    @property
    def evidence_ref(self) -> str:
        return self.evidence.fingerprint

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "evidence": self.evidence.to_dict(),
            "evidenceKind": self.evidence_kind,
            "evidenceRef": self.evidence_ref,
            "nodeId": self.node_id,
            "operationId": self.operation_id,
            "phase": self.phase,
            "priorEvidenceRevision": self.prior_evidence_revision,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "requestFingerprint": self.request_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageArtifactEvidenceRecordV1:
        if not isinstance(value, dict):
            raise TypeError("Package artifact evidence record must be an object")
        fields = {
            "attemptEpoch",
            "evidence",
            "evidenceKind",
            "evidenceRef",
            "nodeId",
            "operationId",
            "phase",
            "priorEvidenceRevision",
            "recordRevision",
            "recordVersion",
            "requestFingerprint",
        }
        if set(value) != fields:
            raise ValueError("Package artifact evidence record schema changed")
        kind = value["evidenceKind"]
        if kind == "bounded_acquisition":
            evidence: PackageArtifactEvidence = BoundedAcquisitionReceiptV1.from_dict(
                value["evidence"]
            )
            expected_phase = "acquired"
        elif kind == "verified_wheel":
            evidence = VerifiedWheelArtifactV1.from_dict(value["evidence"])
            expected_phase = "extracted"
        else:
            raise ValueError("Unsupported Package artifact evidence kind")
        record = cls(
            record_revision=_wire_int(
                value["recordRevision"], name="evidence record revision"
            ),
            prior_evidence_revision=_wire_int(
                value["priorEvidenceRevision"], name="prior evidence revision"
            ),
            request_fingerprint=_wire_string(
                value["requestFingerprint"], name="request fingerprint"
            ),
            evidence=evidence,
            record_version=_wire_int(
                value["recordVersion"], name="evidence record version"
            ),
        )
        if (
            value["operationId"] != record.operation_id
            or value["attemptEpoch"] != record.attempt_epoch
            or value["nodeId"] != record.node_id
            or value["phase"] != expected_phase
            or value["evidenceRef"] != record.evidence_ref
        ):
            raise ValueError("Package artifact evidence projection changed")
        return record


def _encode_record(record: PackageArtifactEvidenceRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageArtifactEvidenceRecordV1):
        raise TypeError("Package artifact evidence record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageArtifactEvidenceRecordV1:
    try:
        return PackageArtifactEvidenceRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package artifact evidence record is invalid",
            code="invalid_package_artifact_evidence_record",
        ) from exc


PACKAGE_ARTIFACT_EVIDENCE_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageArtifactEvidenceJournal:
    """Append-once evidence per operation, attempt, node, and proved phase."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        *,
        request_fingerprint: str,
        evidence: PackageArtifactEvidence,
    ) -> PackageArtifactEvidenceRecordV1:
        if not isinstance(
            evidence,
            BoundedAcquisitionReceiptV1 | VerifiedWheelArtifactV1,
        ):
            raise TypeError("Typed Package artifact evidence is required")
        with self._exclusive():
            records = self._load_unlocked()
            matching = tuple(
                record
                for record in records
                if (
                    record.operation_id,
                    record.attempt_epoch,
                    record.node_id,
                    record.evidence_kind,
                )
                == (
                    evidence.operation_id,
                    evidence.attempt_epoch,
                    evidence.node_id,
                    (
                        "bounded_acquisition"
                        if isinstance(evidence, BoundedAcquisitionReceiptV1)
                        else "verified_wheel"
                    ),
                )
            )
            if matching:
                existing = matching[-1]
                if (
                    existing.request_fingerprint == request_fingerprint
                    and existing.evidence == evidence
                ):
                    return existing
                raise self._error(
                    "Package artifact evidence identity conflict",
                    code="package_operation_identity_conflict",
                )
            prior = _last_attempt_evidence_revision(
                records,
                operation_id=evidence.operation_id,
                attempt_epoch=evidence.attempt_epoch,
                node_id=evidence.node_id,
            )
            if isinstance(evidence, VerifiedWheelArtifactV1):
                acquired = self._find_in(
                    records,
                    operation_id=evidence.operation_id,
                    attempt_epoch=evidence.attempt_epoch,
                    node_id=evidence.node_id,
                    kind="bounded_acquisition",
                )
                if acquired is None:
                    raise self._error(
                        "Verified wheel evidence has no acquired parent",
                        code="package_operation_phase_conflict",
                    )
                _require_verified_parent(
                    acquired,
                    request_fingerprint=request_fingerprint,
                    evidence=evidence,
                    error=lambda: self._error(
                        "Verified wheel evidence changed its acquired parent",
                        code="package_operation_identity_conflict",
                    ),
                )
            record = PackageArtifactEvidenceRecordV1(
                record_revision=len(records) + 1,
                prior_evidence_revision=prior,
                request_fingerprint=request_fingerprint,
                evidence=evidence,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=PACKAGE_ARTIFACT_EVIDENCE_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return record

    def find(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
        node_id: str,
        kind: PackageArtifactEvidenceKind,
    ) -> PackageArtifactEvidenceRecordV1 | None:
        with self._exclusive():
            return self._find_in(
                self._load_unlocked(),
                operation_id=operation_id,
                attempt_epoch=attempt_epoch,
                node_id=node_id,
                kind=kind,
            )

    def records(self) -> tuple[PackageArtifactEvidenceRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _find_in(
        self,
        records: tuple[PackageArtifactEvidenceRecordV1, ...],
        *,
        operation_id: str,
        attempt_epoch: int,
        node_id: str,
        kind: PackageArtifactEvidenceKind,
    ) -> PackageArtifactEvidenceRecordV1 | None:
        return next(
            (
                record
                for record in reversed(records)
                if (
                    record.operation_id == operation_id
                    and record.attempt_epoch == attempt_epoch
                    and record.node_id == node_id
                    and record.evidence_kind == kind
                )
            ),
            None,
        )

    def _load_unlocked(self) -> tuple[PackageArtifactEvidenceRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageArtifactEvidenceRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_ARTIFACT_EVIDENCE_JOURNAL_CODEC,
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
                "Package artifact evidence journal is corrupt",
                code="package_artifact_evidence_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(self, message: str, *, code: str) -> PackageArtifactEvidenceJournalError:
        return PackageArtifactEvidenceJournalError(message, code=code, path=self._path)


def _validate_records(records: tuple[PackageArtifactEvidenceRecordV1, ...]) -> None:
    latest: dict[tuple[str, int, str], int] = {}
    seen: set[tuple[str, int, str, str]] = set()
    acquired_by_key: dict[tuple[str, int, str], PackageArtifactEvidenceRecordV1] = {}
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package artifact evidence revisions are not contiguous")
        key = (record.operation_id, record.attempt_epoch, record.node_id)
        if record.prior_evidence_revision != latest.get(key, 0):
            raise ValueError("Package artifact evidence CAS predecessor changed")
        unique = (*key, record.evidence_kind)
        if unique in seen:
            raise ValueError("Package artifact phase evidence was appended twice")
        if (
            record.evidence_kind == "verified_wheel"
            and (
                *key,
                "bounded_acquisition",
            )
            not in seen
        ):
            raise ValueError("Verified wheel evidence precedes acquisition evidence")
        if record.evidence_kind == "bounded_acquisition":
            acquired_by_key[key] = record
        else:
            evidence = record.evidence
            if not isinstance(evidence, VerifiedWheelArtifactV1):
                raise ValueError("Verified wheel evidence kind changed")
            _require_verified_parent(
                acquired_by_key[key],
                request_fingerprint=record.request_fingerprint,
                evidence=evidence,
                error=lambda: ValueError(
                    "Verified wheel evidence changed its acquired parent"
                ),
            )
        latest[key] = record.record_revision
        seen.add(unique)


def _last_attempt_evidence_revision(
    records: tuple[PackageArtifactEvidenceRecordV1, ...],
    *,
    operation_id: str,
    attempt_epoch: int,
    node_id: str,
) -> int:
    for record in reversed(records):
        if (
            record.operation_id == operation_id
            and record.attempt_epoch == attempt_epoch
            and record.node_id == node_id
        ):
            return record.record_revision
    return 0


def _require_verified_parent(
    acquired_record: PackageArtifactEvidenceRecordV1,
    *,
    request_fingerprint: str,
    evidence: VerifiedWheelArtifactV1,
    error: Callable[[], Exception],
) -> None:
    acquired = acquired_record.evidence
    if not isinstance(acquired, BoundedAcquisitionReceiptV1):
        raise error()
    if (
        acquired_record.request_fingerprint != request_fingerprint
        or evidence.artifact_digest != acquired.actual_byte_digest
        or evidence.artifact_size != acquired.actual_byte_count
    ):
        raise error()


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package artifact evidence contains duplicate JSON keys")
        document[key] = value
    return document


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "PACKAGE_ARTIFACT_EVIDENCE_JOURNAL_CODEC",
    "PackageArtifactEvidenceJournal",
    "PackageArtifactEvidenceJournalError",
    "PackageArtifactEvidenceRecordV1",
]
