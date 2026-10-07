"""Typed receipt sequence and tombstones at a V2 Worker history boundary.

Projection and replay only; cross-stream closure, cutover, and deletion remain
Product responsibilities.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import JournalCodecError, JournalLoadPolicy
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    _decode_coding_worker_receipt_history,
    _linux_receipt_line,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 128 * 1024 * 1024
_SOURCE_PATH = Path("worker-activation-receipts.jsonl")
_STRICT_LOAD = JournalLoadPolicy(partial_tail="raise", create_lock=False)


@dataclass(frozen=True, slots=True)
class CodingWorkerReceiptSemanticBaseV2:
    scope_id: str
    first_retained_generation: int
    last_issue_sequence: int
    retired_sealed_digest: str
    retired_receipt_fingerprints: tuple[str, ...]
    version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 1
            or type(self.last_issue_sequence) is not int
            or self.last_issue_sequence < self.first_retained_generation
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.retired_receipt_fingerprints) is not tuple
            or any(
                type(item) is not str or _DIGEST.fullmatch(item) is None
                for item in self.retired_receipt_fingerprints
            )
            or self.retired_receipt_fingerprints
            != tuple(sorted(set(self.retired_receipt_fingerprints)))
            or len(self.retired_receipt_fingerprints) != self.last_issue_sequence
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker receipt V2 semantic base is invalid")

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {
                "firstRetainedGeneration": self.first_retained_generation,
                "lastIssueSequence": self.last_issue_sequence,
                "retiredReceiptFingerprints": list(self.retired_receipt_fingerprints),
                "retiredSealedDigest": self.retired_sealed_digest,
                "scopeId": self.scope_id,
                "version": self.version,
            }
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker receipt V2 semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerReceiptSemanticBaseV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker receipt V2 semantic base bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "firstRetainedGeneration",
                    "lastIssueSequence",
                    "retiredReceiptFingerprints",
                    "retiredSealedDigest",
                    "scopeId",
                    "version",
                }
                or type(value["retiredReceiptFingerprints"]) is not list
            ):
                raise ValueError(
                    "Coding Worker receipt V2 semantic base fields changed"
                )
            base = cls(
                scope_id=value["scopeId"],
                first_retained_generation=value["firstRetainedGeneration"],
                last_issue_sequence=value["lastIssueSequence"],
                retired_sealed_digest=value["retiredSealedDigest"],
                retired_receipt_fingerprints=tuple(value["retiredReceiptFingerprints"]),
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError(
                    "Coding Worker receipt V2 semantic base encoding changed"
                )
            return base
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker receipt V2 semantic base bytes are invalid"
            ) from exc

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
    ) -> CodingWorkerReceiptSemanticBaseV2:
        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker receipt V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-activation-receipts"
            or type(first_retained_generation) is not int
            or not 1 <= first_retained_generation <= manifest.active_generation
            or len(history.segments) != manifest.active_generation + 1
        ):
            raise ValueError("Coding Worker receipt V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        sequence = 0
        fingerprints: set[str] = set()
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker receipt V2 source changed")
            records = _parse_receipt_segment(
                raw, scope_id=scope_id, first_revision=sequence + 1
            )
            for record in records:
                if record.receipt.fingerprint in fingerprints:
                    raise ValueError("Coding Worker receipt V2 fingerprint repeated")
                fingerprints.add(record.receipt.fingerprint)
            sequence += len(records)
            if sequence != seal.last_revision:
                raise ValueError("Coding Worker receipt V2 source revision changed")
        return cls(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            last_issue_sequence=sequence,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            retired_receipt_fingerprints=tuple(sorted(fingerprints)),
        )

    def replay_retained(
        self, segments: tuple[bytes, ...]
    ) -> CodingWorkerReceiptReplayV2:
        if type(segments) is not tuple or not segments:
            raise ValueError("Coding Worker receipt V2 retained segments are invalid")
        sequence = self.last_issue_sequence
        fingerprints = set(self.retired_receipt_fingerprints)
        retained: list[CodingWorkerReceiptRecordV1] = []
        for raw in segments:
            records = _parse_receipt_segment(
                raw, scope_id=self.scope_id, first_revision=sequence + 1
            )
            for record in records:
                if record.receipt.fingerprint in fingerprints:
                    raise ValueError("Coding Worker receipt V2 fingerprint repeated")
                fingerprints.add(record.receipt.fingerprint)
            retained.extend(records)
            sequence += len(records)
        return CodingWorkerReceiptReplayV2(
            last_issue_sequence=sequence,
            retained_records=tuple(retained),
            receipt_fingerprints=frozenset(fingerprints),
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerReceiptReplayV2:
    last_issue_sequence: int
    retained_records: tuple[CodingWorkerReceiptRecordV1, ...]
    receipt_fingerprints: frozenset[str]


def _parse_receipt_segment(
    raw: bytes, *, scope_id: str, first_revision: int
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    if type(raw) is not bytes:
        raise ValueError("Coding Worker receipt V2 segment is invalid")
    try:
        records = _decode_coding_worker_receipt_history(
            raw,
            path=_SOURCE_PATH,
            scope_id=scope_id,
            load_policy=_STRICT_LOAD,
            first_revision=first_revision,
        )
    except (
        CodingWorkerReceiptError,
        JournalCodecError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ValueError("Coding Worker receipt V2 segment is invalid") from exc
    lines = raw.splitlines(keepends=True)
    if len(lines) != len(records) or any(
        line != _linux_receipt_line(record)
        for line, record in zip(lines, records, strict=True)
    ):
        raise ValueError("Coding Worker receipt V2 segment encoding changed")
    return records


__all__ = ["CodingWorkerReceiptReplayV2", "CodingWorkerReceiptSemanticBaseV2"]
