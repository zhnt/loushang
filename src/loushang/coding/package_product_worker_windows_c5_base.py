"""Typed Windows Worker C5 state and attempt tombstones at a cutover boundary.

This source-bound projection cannot commit a Product cutover, replace the C5
journal, or authorize source deletion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.activation_state_journal import (
    _canonical_json_bytes,
    _StateRecord,
)

from .package_product_worker_activation_history import (
    _fold_coding_worker_activation_attempt_history,
    project_coding_worker_retained_attempts,
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
class CodingWindowsWorkerC5SemanticBaseV1:
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    owner_present: bool
    cutoff_revision: int
    last_record: _StateRecord | None
    retired_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

    @property
    def known_attempt_ids(self) -> frozenset[str]:
        """Include settled attempts still present in the final C5 state."""

        current = (
            ()
            if self.last_record is None
            else tuple(
                cast(str, attempt["attemptId"])
                for attempt in cast(
                    dict[str, dict[str, object]],
                    self.last_record.document["attempts"],
                ).values()
            )
        )
        return frozenset((*self.retired_attempt_ids, *current))

    def __post_init__(self) -> None:
        try:
            validated = (
                None
                if self.last_record is None
                else _StateRecord.from_dict(self.last_record.to_dict())
            )
            current_ids = (
                ()
                if validated is None
                else tuple(
                    cast(str, attempt["attemptId"])
                    for attempt in cast(
                        dict[str, dict[str, object]],
                        validated.document["attempts"],
                    ).values()
                )
            )
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 semantic base is invalid") from exc
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or type(self.owner_present) is not bool
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < 0
            or (self.last_record is None) != (self.cutoff_revision == 0)
            or (self.last_record is not None and not self.owner_present)
            or validated != self.last_record
            or (
                validated is not None
                and validated.journal_revision != self.cutoff_revision
            )
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or len(current_ids) != len(set(current_ids))
            or bool(set(current_ids) & set(self.retired_attempt_ids))
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker C5 semantic base is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "cutoffRevision": self.cutoff_revision,
            "lastRecord": (
                None if self.last_record is None else self.last_record.to_dict()
            ),
            "ownerPresent": self.owner_present,
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
            raise ValueError("Windows Worker C5 semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerC5SemanticBaseV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Windows Worker C5 semantic base is invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "cutoffRevision",
                    "lastRecord",
                    "ownerPresent",
                    "retiredAttemptIds",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                    "recordDigest",
                    "version",
                }
                or type(value["retiredAttemptIds"]) is not list
            ):
                raise ValueError("Windows Worker C5 semantic base is invalid")
            base = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                owner_present=value["ownerPresent"],
                cutoff_revision=value["cutoffRevision"],
                last_record=(
                    None
                    if value["lastRecord"] is None
                    else _StateRecord.from_dict(value["lastRecord"])
                ),
                retired_attempt_ids=tuple(value["retiredAttemptIds"]),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Windows Worker C5 semantic base is invalid")
            return base
        except (KeyError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 semantic base is invalid") from exc

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerC5SemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker C5 preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        records = recovery.activation_state_records
        names = {item.name for item in source.files}
        if records and "worker-activation-state.jsonl" not in names:
            raise ValueError("Windows Worker C5 source is absent")
        if any(type(item) is not _StateRecord for item in records):
            raise ValueError("Windows Worker C5 history is invalid")
        if records:
            by_name = {item.name: item for item in source.files}
            lines = tuple(
                _canonical_json_bytes(item.to_dict()) + b"\n" for item in records
            )
            journal_bytes = b"".join(lines)
            journal = by_name["worker-activation-state.jsonl"]
            if (
                journal.size != len(journal_bytes)
                or journal.sha256_digest != sha256(journal_bytes).hexdigest()
            ):
                raise ValueError("Windows Worker C5 source changed")
            prefix_digest = sha256()
            prefix_size = 0
            for revision, line in enumerate(lines, 1):
                prefix_digest.update(line)
                prefix_size += len(line)
                head = by_name.get(f"worker-activation-state.h{revision:08d}.json")
                expected_head = canonical_json_bytes(
                    {
                        "byteCount": prefix_size,
                        "digest": prefix_digest.hexdigest(),
                        "revision": revision,
                        "version": 1,
                    }
                )
                if (
                    head is None
                    or head.size != len(expected_head)
                    or head.sha256_digest != sha256(expected_head).hexdigest()
                ):
                    raise ValueError("Windows Worker C5 source changed")
        try:
            if (
                recovery.activation_state_revision != len(records)
                or (bool(records) and not recovery.activation_state_owner_present)
                or recovery.retained_activation_attempts
                != project_coding_worker_retained_attempts(records)
                or any(
                    item.journal_revision != revision
                    or f"worker-activation-state.h{revision:08d}.json" not in names
                    for revision, item in enumerate(records, 1)
                )
            ):
                raise ValueError("Windows Worker C5 history changed")
            retired = _fold_coding_worker_activation_attempt_history(records)
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 history is invalid") from exc
        last = None if not records else records[-1]
        unsigned = {
            "cutoffRevision": len(records),
            "lastRecord": None if last is None else last.to_dict(),
            "ownerPresent": recovery.activation_state_owner_present,
            "retiredAttemptIds": sorted(retired),
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            owner_present=recovery.activation_state_owner_present,
            cutoff_revision=len(records),
            last_record=last,
            retired_attempt_ids=tuple(sorted(retired)),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def replay(
        self, records: tuple[_StateRecord, ...]
    ) -> CodingWindowsWorkerC5ReplayV1:
        if type(records) is not tuple:
            raise ValueError("Windows Worker C5 retained replay is invalid")
        for revision, item in enumerate(records, self.cutoff_revision + 1):
            if type(item) is not _StateRecord or item.journal_revision != revision:
                raise ValueError("Windows Worker C5 retained replay is invalid")
        try:
            retired = _fold_coding_worker_activation_attempt_history(
                records,
                previous_record=self.last_record,
                retired_attempt_ids=frozenset(self.retired_attempt_ids),
            )
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 retained replay is invalid") from exc
        return CodingWindowsWorkerC5ReplayV1(
            last_record=self.last_record if not records else records[-1],
            retired_attempt_ids=retired,
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerC5ReplayV1:
    last_record: _StateRecord | None
    retired_attempt_ids: frozenset[str]


__all__ = ["CodingWindowsWorkerC5ReplayV1", "CodingWindowsWorkerC5SemanticBaseV1"]
