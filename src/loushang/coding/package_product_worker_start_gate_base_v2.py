"""Typed Start Gate state at a V2 Worker history boundary.

Checkpoint tombstones select retired attempts. The base scope identifies the
Product owner; gate records retain their individual Session scopes. Product-wide
closure must prove retired attempts have no native or recovery references.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_start_gate_journal import (
    _MAX_BYTES,
    _MAX_EVENTS,
    CodingWorkerStartGateRecordV1,
    _fold_start_gate_records,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerStartGateSemanticBaseV2:
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    current_records: tuple[CodingWorkerStartGateRecordV1, ...]
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 1
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < self.first_retained_generation
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.current_records) is not tuple
            or any(
                type(item) is not CodingWorkerStartGateRecordV1
                or item.journal_revision > self.cutoff_revision
                for item in self.current_records
            )
            or tuple(item.attempt_id for item in self.current_records)
            != tuple(sorted({item.attempt_id for item in self.current_records}))
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or any(
                item.attempt_id in self.retired_attempt_ids
                for item in self.current_records
            )
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker Start Gate V2 semantic base is invalid")

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {
                "currentRecords": [item.to_dict() for item in self.current_records],
                "cutoffRevision": self.cutoff_revision,
                "firstRetainedGeneration": self.first_retained_generation,
                "retiredAttemptIds": list(self.retired_attempt_ids),
                "retiredSealedDigest": self.retired_sealed_digest,
                "scopeId": self.scope_id,
                "version": self.version,
            }
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker Start Gate V2 base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerStartGateSemanticBaseV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker Start Gate V2 base bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "currentRecords",
                    "cutoffRevision",
                    "firstRetainedGeneration",
                    "retiredAttemptIds",
                    "retiredSealedDigest",
                    "scopeId",
                    "version",
                }
                or type(value["currentRecords"]) is not list
                or type(value["retiredAttemptIds"]) is not list
            ):
                raise ValueError("Coding Worker Start Gate V2 base fields changed")
            base = cls(
                scope_id=value["scopeId"],
                first_retained_generation=value["firstRetainedGeneration"],
                cutoff_revision=value["cutoffRevision"],
                retired_sealed_digest=value["retiredSealedDigest"],
                current_records=tuple(
                    CodingWorkerStartGateRecordV1.from_dict(item)
                    for item in value["currentRecords"]
                ),
                retired_attempt_ids=tuple(value["retiredAttemptIds"]),
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Coding Worker Start Gate V2 base encoding changed")
            return base
        except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker Start Gate V2 base bytes are invalid"
            ) from exc

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
        retired_attempt_ids: tuple[str, ...],
    ) -> CodingWorkerStartGateSemanticBaseV2:
        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker Start Gate V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-start-gates"
            or type(first_retained_generation) is not int
            or not 1 <= first_retained_generation <= manifest.active_generation
            or len(history.segments) != manifest.active_generation + 1
            or type(retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in retired_attempt_ids
            )
            or retired_attempt_ids != tuple(sorted(set(retired_attempt_ids)))
        ):
            raise ValueError("Coding Worker Start Gate V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        records: list[CodingWorkerStartGateRecordV1] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker Start Gate V2 source changed")
            records.extend(
                _parse_start_gate_segment(raw, first_revision=len(records) + 1)
            )
            if len(records) != seal.last_revision:
                raise ValueError("Coding Worker Start Gate V2 source revision changed")
        try:
            latest = _fold_start_gate_records(tuple(records))
        except ValueError as exc:
            raise ValueError("Coding Worker Start Gate V2 source is invalid") from exc
        return cls(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=retired[-1].last_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            current_records=tuple(
                latest[key] for key in sorted(latest) if key not in retired_attempt_ids
            ),
            retired_attempt_ids=retired_attempt_ids,
        )

    def replay_retained(
        self, segments: tuple[bytes, ...]
    ) -> CodingWorkerStartGateReplayV2:
        if type(segments) is not tuple or not segments:
            raise ValueError(
                "Coding Worker Start Gate V2 retained segments are invalid"
            )
        revision = self.cutoff_revision
        records: list[CodingWorkerStartGateRecordV1] = []
        for raw in segments:
            segment = _parse_start_gate_segment(raw, first_revision=revision + 1)
            records.extend(segment)
            revision += len(segment)
        try:
            latest = _fold_start_gate_records(
                tuple(records),
                initial_latest={item.attempt_id: item for item in self.current_records},
                retired_attempt_ids=frozenset(self.retired_attempt_ids),
            )
        except ValueError as exc:
            raise ValueError(
                "Coding Worker Start Gate V2 retained replay is invalid"
            ) from exc
        return CodingWorkerStartGateReplayV2(
            last_revision=revision,
            current_records=tuple(latest[key] for key in sorted(latest)),
            retired_attempt_ids=frozenset(self.retired_attempt_ids),
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerStartGateReplayV2:
    last_revision: int
    current_records: tuple[CodingWorkerStartGateRecordV1, ...]
    retired_attempt_ids: frozenset[str]


def _parse_start_gate_segment(
    raw: bytes, *, first_revision: int
) -> tuple[CodingWorkerStartGateRecordV1, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        raise ValueError("Coding Worker Start Gate V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_EVENTS:
        raise ValueError("Coding Worker Start Gate V2 segment exceeds capacity")
    records: list[CodingWorkerStartGateRecordV1] = []
    try:
        for revision, line in enumerate(lines, first_revision):
            record = CodingWorkerStartGateRecordV1.from_dict(json.loads(line))
            if (
                record.journal_revision != revision
                or line != canonical_json_bytes(record.to_dict()) + b"\n"
            ):
                raise ValueError("Coding Worker Start Gate V2 segment changed")
            records.append(record)
    except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker Start Gate V2 segment is invalid") from exc
    return tuple(records)


__all__ = ["CodingWorkerStartGateReplayV2", "CodingWorkerStartGateSemanticBaseV2"]
