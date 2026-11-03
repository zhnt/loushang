"""Typed C5 state and retired attempt IDs at a V2 Worker history boundary.

This projection preserves CAS state after sealed V1 history is retired. It
does not publish a cutover, infer native absence, or authorize source deletion.
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
    _MAX_JOURNAL_BYTES,
    _MAX_REVISIONS,
    _canonical_json_bytes,
    _StateRecord,
)

from .package_product_worker_activation_history import (
    _fold_coding_worker_activation_attempt_history,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerActivationSemanticBaseV2:
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    last_record: _StateRecord
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    def __post_init__(self) -> None:
        if type(self.last_record) is not _StateRecord:
            raise ValueError("Coding Worker C5 V2 semantic base is invalid")
        try:
            validated_record = _StateRecord.from_dict(self.last_record.to_dict())
            attempts = cast(
                dict[str, dict[str, object]], validated_record.document["attempts"]
            )
            current_ids = tuple(
                cast(str, attempt["attemptId"]) for attempt in attempts.values()
            )
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Coding Worker C5 V2 semantic base is invalid") from exc
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 1
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < self.first_retained_generation
            or validated_record != self.last_record
            or self.last_record.journal_revision != self.cutoff_revision
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or len(set(current_ids)) != len(current_ids)
            or bool(set(current_ids) & set(self.retired_attempt_ids))
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker C5 V2 semantic base is invalid")

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {
                "cutoffRevision": self.cutoff_revision,
                "firstRetainedGeneration": self.first_retained_generation,
                "lastRecord": self.last_record.to_dict(),
                "retiredAttemptIds": list(self.retired_attempt_ids),
                "retiredSealedDigest": self.retired_sealed_digest,
                "scopeId": self.scope_id,
                "version": self.version,
            }
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker C5 V2 semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerActivationSemanticBaseV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker C5 V2 semantic base bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "cutoffRevision",
                    "firstRetainedGeneration",
                    "lastRecord",
                    "retiredAttemptIds",
                    "retiredSealedDigest",
                    "scopeId",
                    "version",
                }
                or type(value["retiredAttemptIds"]) is not list
            ):
                raise ValueError("Coding Worker C5 V2 semantic base fields changed")
            base = cls(
                scope_id=value["scopeId"],
                first_retained_generation=value["firstRetainedGeneration"],
                cutoff_revision=value["cutoffRevision"],
                retired_sealed_digest=value["retiredSealedDigest"],
                last_record=_StateRecord.from_dict(value["lastRecord"]),
                retired_attempt_ids=tuple(value["retiredAttemptIds"]),
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Coding Worker C5 V2 semantic base encoding changed")
            return base
        except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker C5 V2 semantic base bytes are invalid"
            ) from exc

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
    ) -> CodingWorkerActivationSemanticBaseV2:
        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker C5 V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-activation-state"
            or type(first_retained_generation) is not int
            or not 1 <= first_retained_generation <= manifest.active_generation
            or len(history.segments) != manifest.active_generation + 1
        ):
            raise ValueError("Coding Worker C5 V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        records: list[_StateRecord] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker C5 V2 source changed")
            records.extend(_parse_c5_segment(raw, first_revision=len(records) + 1))
            if len(records) != seal.last_revision:
                raise ValueError("Coding Worker C5 V2 source revision changed")
        try:
            retired_ids = _fold_coding_worker_activation_attempt_history(tuple(records))
        except ValueError as exc:
            raise ValueError("Coding Worker C5 V2 source is invalid") from exc
        return cls(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=retired[-1].last_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            last_record=records[-1],
            retired_attempt_ids=tuple(sorted(retired_ids)),
        )

    def replay_retained(
        self, segments: tuple[bytes, ...]
    ) -> CodingWorkerActivationReplayV2:
        if type(segments) is not tuple or not segments:
            raise ValueError("Coding Worker C5 V2 retained segments are invalid")
        revision = self.cutoff_revision
        records: list[_StateRecord] = []
        for raw in segments:
            segment = _parse_c5_segment(raw, first_revision=revision + 1)
            records.extend(segment)
            revision += len(segment)
        try:
            retired_ids = _fold_coding_worker_activation_attempt_history(
                tuple(records),
                previous_record=self.last_record,
                retired_attempt_ids=frozenset(self.retired_attempt_ids),
            )
        except ValueError as exc:
            raise ValueError("Coding Worker C5 V2 retained replay is invalid") from exc
        return CodingWorkerActivationReplayV2(
            last_record=self.last_record if not records else records[-1],
            retired_attempt_ids=retired_ids,
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerActivationReplayV2:
    last_record: _StateRecord
    retired_attempt_ids: frozenset[str]


def _parse_c5_segment(raw: bytes, *, first_revision: int) -> tuple[_StateRecord, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_JOURNAL_BYTES:
        raise ValueError("Coding Worker C5 V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_REVISIONS:
        raise ValueError("Coding Worker C5 V2 segment exceeds capacity")
    records: list[_StateRecord] = []
    try:
        for revision, line in enumerate(lines, first_revision):
            record = _StateRecord.from_dict(json.loads(line))
            if (
                record.journal_revision != revision
                or line != _canonical_json_bytes(record.to_dict()) + b"\n"
            ):
                raise ValueError("Coding Worker C5 V2 segment changed")
            records.append(record)
    except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker C5 V2 segment is invalid") from exc
    return tuple(records)


__all__ = ["CodingWorkerActivationReplayV2", "CodingWorkerActivationSemanticBaseV2"]
