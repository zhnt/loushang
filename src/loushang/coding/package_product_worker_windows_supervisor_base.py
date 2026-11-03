"""Typed Windows Worker Supervisor state and tombstones at a cutover boundary.

This source-bound projection cannot commit a Product cutover, replace the
Supervisor journal, or authorize history deletion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.journal import (
    _TRANSITIONS,
    WorkerAttemptRecordV1,
    _validate_history,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerSupervisorSemanticBaseV1:
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    cutoff_revision: int
    latest_attempts: tuple[WorkerAttemptRecordV1, ...]
    retired_attempt_ids: tuple[str, ...]
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
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < 0
            or type(self.latest_attempts) is not tuple
            or any(
                type(item) is not WorkerAttemptRecordV1
                or item.record_revision > self.cutoff_revision
                for item in self.latest_attempts
            )
            or tuple(item.attempt_id for item in self.latest_attempts)
            != tuple(sorted({item.attempt_id for item in self.latest_attempts}))
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or any(
                item.attempt_id not in self.retired_attempt_ids
                for item in self.latest_attempts
            )
            or bool(self.latest_attempts) != bool(self.cutoff_revision)
            or (
                self.cutoff_revision > 0
                and max(item.record_revision for item in self.latest_attempts)
                != self.cutoff_revision
            )
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker Supervisor semantic base is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "cutoffRevision": self.cutoff_revision,
            "latestAttempts": [item.to_dict() for item in self.latest_attempts],
            "retiredAttemptIds": list(self.retired_attempt_ids),
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
            raise ValueError("Windows Worker Supervisor semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerSupervisorSemanticBaseV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Windows Worker Supervisor semantic base is invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "cutoffRevision",
                    "latestAttempts",
                    "retiredAttemptIds",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                    "recordDigest",
                    "version",
                }
                or type(value["latestAttempts"]) is not list
                or type(value["retiredAttemptIds"]) is not list
            ):
                raise ValueError("Windows Worker Supervisor semantic base is invalid")
            base = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                cutoff_revision=value["cutoffRevision"],
                latest_attempts=tuple(
                    WorkerAttemptRecordV1.from_dict(item)
                    for item in value["latestAttempts"]
                ),
                retired_attempt_ids=tuple(value["retiredAttemptIds"]),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Windows Worker Supervisor semantic base is invalid")
            return base
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError(
                "Windows Worker Supervisor semantic base is invalid"
            ) from exc

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerSupervisorSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker Supervisor preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        records = semantic.offline_recovery.supervisor_records
        if records and not any(
            item.name == "worker-supervisor.jsonl" for item in source.files
        ):
            raise ValueError("Windows Worker Supervisor source is absent")
        if any(type(item) is not WorkerAttemptRecordV1 for item in records):
            raise ValueError("Windows Worker Supervisor history is invalid")
        try:
            if any(
                item.record_revision != revision
                for revision, item in enumerate(records, 1)
            ):
                raise ValueError("Windows Worker Supervisor history is not contiguous")
            _validate_history(records)
        except ValueError as exc:
            raise ValueError("Windows Worker Supervisor history is invalid") from exc
        latest: dict[str, WorkerAttemptRecordV1] = {}
        for item in records:
            latest[item.attempt_id] = item
        attempts = tuple(latest[key] for key in sorted(latest))
        retired = tuple(sorted(latest))
        unsigned = {
            "cutoffRevision": len(records),
            "latestAttempts": [item.to_dict() for item in attempts],
            "retiredAttemptIds": list(retired),
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            cutoff_revision=len(records),
            latest_attempts=attempts,
            retired_attempt_ids=retired,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def replay(
        self, records: tuple[WorkerAttemptRecordV1, ...]
    ) -> CodingWindowsWorkerSupervisorReplayV1:
        if type(records) is not tuple:
            raise ValueError("Windows Worker Supervisor retained replay is invalid")
        latest = {item.attempt_id: item for item in self.latest_attempts}
        by_key = {item.supervisor_key: item for item in self.latest_attempts}
        for item in self.latest_attempts:
            current = by_key[item.supervisor_key]
            if item.record_revision > current.record_revision:
                by_key[item.supervisor_key] = item
        retired = set(self.retired_attempt_ids)
        for revision, item in enumerate(records, self.cutoff_revision + 1):
            if (
                type(item) is not WorkerAttemptRecordV1
                or item.record_revision != revision
            ):
                raise ValueError("Windows Worker Supervisor retained replay is invalid")
            previous = latest.get(item.attempt_id)
            if previous is None:
                prior_key = by_key.get(item.supervisor_key)
                if (
                    item.attempt_id in retired
                    or item.phase != "claimed"
                    or item.prior_attempt_revision != 0
                    or (
                        prior_key is None
                        and (item.supervisor_epoch != 1 or item.restart_ordinal != 1)
                    )
                    or (
                        prior_key is not None
                        and (
                            not prior_key.process_settled
                            or item.supervisor_epoch != prior_key.supervisor_epoch + 1
                            or item.restart_ordinal
                            != (
                                1
                                if prior_key.phase == "stopped"
                                else prior_key.restart_ordinal + 1
                            )
                        )
                    )
                ):
                    raise ValueError(
                        "Windows Worker Supervisor retained replay is invalid"
                    )
                retired.add(item.attempt_id)
            elif (
                item.supervisor_key != previous.supervisor_key
                or item.identity_fingerprint != previous.identity_fingerprint
                or item.supervisor_epoch != previous.supervisor_epoch
                or item.restart_ordinal != previous.restart_ordinal
                or item.prior_attempt_revision != previous.record_revision
                or item.phase not in _TRANSITIONS[previous.phase]
                or (
                    item.phase == "process_settled"
                    and item.failure_code != previous.failure_code
                )
            ):
                raise ValueError("Windows Worker Supervisor retained replay is invalid")
            latest[item.attempt_id] = item
            by_key[item.supervisor_key] = item
        return CodingWindowsWorkerSupervisorReplayV1(
            last_revision=self.cutoff_revision + len(records),
            latest_attempts=tuple(latest[key] for key in sorted(latest)),
            attempt_ids=frozenset(retired),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerSupervisorReplayV1:
    last_revision: int
    latest_attempts: tuple[WorkerAttemptRecordV1, ...]
    attempt_ids: frozenset[str]


__all__ = [
    "CodingWindowsWorkerSupervisorReplayV1",
    "CodingWindowsWorkerSupervisorSemanticBaseV1",
]
