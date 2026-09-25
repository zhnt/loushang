"""Incompatible journal marker that excludes pre-GC reference writers.

An older writer decodes each owner journal before appending.  It cannot decode
this marker, while a current writer must prove that it uses the bound GC gate.
The marker does not consume a logical owner revision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Generic, Literal, TypeVar, cast

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalRecordCodec,
)
from loushang.harness.plugin_management.gc_fence import (
    PluginPackageGcReferenceGatePort,
)

GcWriterJournalKind = Literal["desired", "instance", "package"]
_RecordT = TypeVar("_RecordT")
_MARKER_KIND = "plugin_gc_writer_epoch"
_MINIMUM_WRITER_EPOCH = 2
_MARKER_RECORD_VERSION = 3


class PluginGcWriterEpochError(RuntimeError):
    code = "plugin_package_gc_writer_epoch_unsupported"


@dataclass(frozen=True, slots=True)
class PluginGcWriterEpochSealV1:
    journal_kind: GcWriterJournalKind
    owner_path_digest: str
    gate_path_digest: str

    @classmethod
    def create(
        cls,
        *,
        journal_kind: GcWriterJournalKind,
        owner_path: Path,
        gate: PluginPackageGcReferenceGatePort,
    ) -> PluginGcWriterEpochSealV1:
        gate_path = getattr(gate, "path", None)
        if not isinstance(gate_path, Path):
            raise PluginGcWriterEpochError("GC gate has no durable journal path")
        return cls(
            journal_kind=journal_kind,
            owner_path_digest=_path_digest(owner_path),
            gate_path_digest=_path_digest(gate_path),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "gatePathDigest": self.gate_path_digest,
            "journalKind": self.journal_kind,
            "minimumWriterEpoch": _MINIMUM_WRITER_EPOCH,
            "ownerPathDigest": self.owner_path_digest,
            "recordKind": _MARKER_KIND,
            "recordVersion": _MARKER_RECORD_VERSION,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PluginGcWriterEpochSealV1:
        if (
            set(value)
            != {
                "gatePathDigest",
                "journalKind",
                "minimumWriterEpoch",
                "ownerPathDigest",
                "recordKind",
                "recordVersion",
            }
            or value["recordKind"] != _MARKER_KIND
            or type(value["recordVersion"]) is not int
            or value["recordVersion"] != _MARKER_RECORD_VERSION
            or type(value["minimumWriterEpoch"]) is not int
            or value["minimumWriterEpoch"] != _MINIMUM_WRITER_EPOCH
            or value["journalKind"] not in {"desired", "instance", "package"}
            or not _sha256_digest(value["ownerPathDigest"])
            or not _sha256_digest(value["gatePathDigest"])
        ):
            raise JournalCodecError(
                "Invalid Plugin GC writer epoch marker",
                code="invalid_plugin_gc_writer_epoch_record",
            )
        return cls(
            journal_kind=cast(GcWriterJournalKind, value["journalKind"]),
            owner_path_digest=cast(str, value["ownerPathDigest"]),
            gate_path_digest=cast(str, value["gatePathDigest"]),
        )


@dataclass(frozen=True, slots=True)
class PluginGcWriterEpochRecords(Generic[_RecordT]):
    records: tuple[_RecordT, ...]
    sealed: bool


def gc_writer_epoch_codec(
    base: JournalRecordCodec[_RecordT],
) -> FunctionalJournalRecordCodec[_RecordT | PluginGcWriterEpochSealV1]:
    def encode(record: _RecordT | PluginGcWriterEpochSealV1) -> Mapping[str, object]:
        if isinstance(record, PluginGcWriterEpochSealV1):
            return record.to_dict()
        return base.encode_record(record)

    def decode(
        value: Mapping[str, object],
    ) -> _RecordT | PluginGcWriterEpochSealV1:
        if "recordKind" in value:
            return PluginGcWriterEpochSealV1.from_dict(value)
        return base.decode_record(value)

    return FunctionalJournalRecordCodec(encoder=encode, decoder=decode)


def split_gc_writer_epoch_records(
    records: tuple[_RecordT | PluginGcWriterEpochSealV1, ...],
    *,
    journal_kind: GcWriterJournalKind,
    owner_path: Path,
    gate: PluginPackageGcReferenceGatePort | None,
) -> PluginGcWriterEpochRecords[_RecordT]:
    seal: PluginGcWriterEpochSealV1 | None = None
    ordinary: list[_RecordT] = []
    for record in records:
        if isinstance(record, PluginGcWriterEpochSealV1):
            if seal is not None:
                raise PluginGcWriterEpochError("GC writer epoch marker is duplicated")
            seal = record
        else:
            ordinary.append(record)
    if seal is not None and (
        gate is None
        or seal
        != PluginGcWriterEpochSealV1.create(
            journal_kind=journal_kind,
            owner_path=owner_path,
            gate=gate,
        )
    ):
        raise PluginGcWriterEpochError(
            "GC writer epoch requires the exact reservation journal"
        )
    return PluginGcWriterEpochRecords(records=tuple(ordinary), sealed=seal is not None)


def _path_digest(path: Path) -> str:
    return sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _sha256_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "PluginGcWriterEpochError",
    "PluginGcWriterEpochRecords",
    "PluginGcWriterEpochSealV1",
    "gc_writer_epoch_codec",
    "split_gc_writer_epoch_records",
]
