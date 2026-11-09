"""Receipt values and history codecs over existing Journal and Worker facts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Self, TypeVar, cast

from loushang.harness.journal import (
    JournalCodecError,
    JournalLoadPolicy,
    JournalRecordCodec,
    decode_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import CodingWorkerSegmentedHistoryV1
from ..product_activation import ProductWorkerActivationReceiptV1
from ._base_codec import _BaseWireMethods, _unchanged

_MAX_RECEIPTS = 4096
_MAX_RECEIPT_SEGMENT_BYTES = 32 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_PATH = Path("worker-activation-receipts.jsonl")
_STRICT_LOAD = JournalLoadPolicy(partial_tail="raise", create_lock=False)


class _ReceiptRecordMethods:
    __slots__ = ()

    journal_revision: int
    scope_id: str
    opt_in_decision_digest: str
    receipt: ProductWorkerActivationReceiptV1
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or not isinstance(self.scope_id, str)
            or not self.scope_id
            or not isinstance(self.opt_in_decision_digest, str)
            or len(self.opt_in_decision_digest) != 64
            or not isinstance(self.receipt, ProductWorkerActivationReceiptV1)
            or self.receipt.issue_sequence != self.journal_revision
            or self.record_version != 1
            or self.record_digest != self._fingerprint()
        ):
            raise ValueError("Coding Worker receipt record is invalid")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        scope_id: str,
        opt_in_decision_digest: str,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> Self:
        values = {
            "journalRevision": journal_revision,
            "optInDecisionDigest": opt_in_decision_digest,
            "receipt": receipt.to_dict(),
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cast(Callable[..., Self], cls)(
            journal_revision=journal_revision,
            scope_id=scope_id,
            opt_in_decision_digest=opt_in_decision_digest,
            receipt=receipt,
            record_digest=sha256(canonical_json_bytes(values)).hexdigest(),
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "journalRevision": self.journal_revision,
            "optInDecisionDigest": self.opt_in_decision_digest,
            "receipt": self.receipt.to_dict(),
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
        }

    def _fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        fields = {
            "journalRevision",
            "optInDecisionDigest",
            "receipt",
            "recordDigest",
            "recordVersion",
            "scopeId",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError("Coding Worker receipt record shape is invalid")
        return cast(Callable[..., Self], cls)(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            opt_in_decision_digest=value["optInDecisionDigest"],
            receipt=ProductWorkerActivationReceiptV1.from_dict(value["receipt"]),
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


_ReceiptT = TypeVar("_ReceiptT", bound=_ReceiptRecordMethods)


def decode_receipt_history(
    raw: bytes,
    *,
    path: Path,
    scope_id: str,
    load_policy: JournalLoadPolicy,
    record_codec: JournalRecordCodec[_ReceiptT],
    error_type: type[RuntimeError],
    max_receipts: int,
    max_segment_bytes: int,
    first_revision: int = 1,
) -> tuple[_ReceiptT, ...]:
    """Replay one Product scope's receipt history across platform journals."""

    if len(raw) > max_segment_bytes:
        raise error_type("coding_worker_receipt_capacity")
    records: tuple[_ReceiptT, ...] = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=record_codec,
        load_policy=load_policy,
    ).records
    if len(records) > max_receipts:
        raise error_type("coding_worker_receipt_capacity")
    seen_receipts: set[str] = set()
    for revision, record in enumerate(records, first_revision):
        if (
            record.journal_revision != revision
            or record.scope_id != scope_id
            or record.receipt.fingerprint in seen_receipts
        ):
            raise error_type("coding_worker_receipt_corrupt")
        seen_receipts.add(record.receipt.fingerprint)
    return records


def receipt_line(record: _ReceiptRecordMethods) -> bytes:
    return (
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def parse_receipt_segment(
    raw: bytes,
    *,
    scope_id: str,
    first_revision: int,
    record_codec: JournalRecordCodec[_ReceiptT],
    error_type: type[RuntimeError],
    max_receipts: int,
    max_segment_bytes: int,
) -> tuple[_ReceiptT, ...]:
    if type(raw) is not bytes:
        raise ValueError("Coding Worker receipt V2 segment is invalid")
    try:
        records = decode_receipt_history(
            raw,
            path=_SOURCE_PATH,
            scope_id=scope_id,
            load_policy=_STRICT_LOAD,
            first_revision=first_revision,
            record_codec=record_codec,
            error_type=error_type,
            max_receipts=max_receipts,
            max_segment_bytes=max_segment_bytes,
        )
    except (
        error_type,
        JournalCodecError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ValueError("Coding Worker receipt V2 segment is invalid") from exc
    lines = raw.splitlines(keepends=True)
    if len(lines) != len(records) or any(
        line != receipt_line(record)
        for line, record in zip(lines, records, strict=True)
    ):
        raise ValueError("Coding Worker receipt V2 segment encoding changed")
    return records


class _ReceiptReplayFields:
    __slots__ = ()

    last_issue_sequence: int
    retained_records: tuple[_ReceiptRecordMethods, ...]
    receipt_fingerprints: frozenset[str]


class _ReceiptBaseMethods(_BaseWireMethods):
    __slots__ = ()

    _wire_label = "Coding Worker receipt V2 semantic base"
    _wire_lists = ("retiredReceiptFingerprints",)

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField("retired_receipt_fingerprints", encoder=list, decoder=tuple),
        )

    scope_id: str
    first_retained_generation: int
    last_issue_sequence: int
    retired_sealed_digest: str
    retired_receipt_fingerprints: tuple[str, ...]
    version: int = 2

    _replay_type: ClassVar[type[_ReceiptReplayFields]]

    @staticmethod
    def _decode_segment(
        raw: bytes,
        *,
        scope_id: str,
        first_revision: int,
    ) -> tuple[_ReceiptRecordMethods, ...]:
        """Concrete bindings provide only the original pure bytes codec."""
        raise NotImplementedError

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

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
    ) -> Self:
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
            records = cls._decode_segment(
                raw, scope_id=scope_id, first_revision=sequence + 1
            )
            for record in records:
                if record.receipt.fingerprint in fingerprints:
                    raise ValueError("Coding Worker receipt V2 fingerprint repeated")
                fingerprints.add(record.receipt.fingerprint)
            sequence += len(records)
            if sequence != seal.last_revision:
                raise ValueError("Coding Worker receipt V2 source revision changed")
        return cast(Callable[..., Self], cls)(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            last_issue_sequence=sequence,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            retired_receipt_fingerprints=tuple(sorted(fingerprints)),
        )

    def replay_retained(self, segments: tuple[bytes, ...]) -> _ReceiptReplayFields:
        if type(segments) is not tuple or not segments:
            raise ValueError("Coding Worker receipt V2 retained segments are invalid")
        sequence = self.last_issue_sequence
        fingerprints = set(self.retired_receipt_fingerprints)
        retained: list[_ReceiptRecordMethods] = []
        for raw in segments:
            records = self._decode_segment(
                raw, scope_id=self.scope_id, first_revision=sequence + 1
            )
            for record in records:
                if record.receipt.fingerprint in fingerprints:
                    raise ValueError("Coding Worker receipt V2 fingerprint repeated")
                fingerprints.add(record.receipt.fingerprint)
            retained.extend(records)
            sequence += len(records)
        return cast(Callable[..., _ReceiptReplayFields], self._replay_type)(
            last_issue_sequence=sequence,
            retained_records=tuple(retained),
            receipt_fingerprints=frozenset(fingerprints),
        )
