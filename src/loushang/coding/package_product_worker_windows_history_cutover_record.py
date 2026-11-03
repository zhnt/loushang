"""Canonical Windows Worker Product history-cutover record, without authority.

The record names one persisted checkpoint and its six semantic bases. It is
inert until a separate Product owner can atomically switch every reader and
writer and publish it under runtime quiescence and the GC write gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_windows_base_files import (
    WINDOWS_WORKER_BASE_FILES,
    WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
)
from .package_product_worker_windows_persisted_bases import (
    CodingWindowsWorkerPersistedBasesV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 4096
_BASE_KEYS = tuple(key for key, _ in WINDOWS_WORKER_BASE_FILES)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryCutoverRecordV1:
    scope_id: str
    store_id: str
    checkpoint_digest: str
    source_snapshot_digest: str
    base_digests: tuple[tuple[str, str], ...]
    record_digest: str
    cutover_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not 0 < len(self.scope_id) <= 128
            or type(self.store_id) is not str
            or not 0 < len(self.store_id) <= 128
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.checkpoint_digest,
                    self.source_snapshot_digest,
                    self.record_digest,
                )
            )
            or type(self.base_digests) is not tuple
            or any(
                type(item) is not tuple or len(item) != 2 for item in self.base_digests
            )
            or tuple(key for key, _ in self.base_digests) != _BASE_KEYS
            or any(
                type(digest) is not str or _DIGEST.fullmatch(digest) is None
                for _, digest in self.base_digests
            )
            or type(self.cutover_version) is not int
            or self.cutover_version != 1
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history cutover record is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "baseDigests": [list(item) for item in self.base_digests],
            "checkpointDigest": self.checkpoint_digest,
            "cutoverVersion": self.cutover_version,
            "scopeId": self.scope_id,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
        }

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )
        if len(raw) > _MAX_BYTES:
            raise ValueError("Windows Worker history cutover record exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerHistoryCutoverRecordV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise ValueError("Windows Worker history cutover record is invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "baseDigests",
                    "checkpointDigest",
                    "cutoverVersion",
                    "recordDigest",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                }
                or type(value["baseDigests"]) is not list
                or any(type(item) is not list for item in value["baseDigests"])
            ):
                raise ValueError("Windows Worker history cutover record is invalid")
            record = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                checkpoint_digest=value["checkpointDigest"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                base_digests=tuple(tuple(item) for item in value["baseDigests"]),
                record_digest=value["recordDigest"],
                cutover_version=value["cutoverVersion"],
            )
            if record.to_bytes() != raw:
                raise ValueError("Windows Worker history cutover record is invalid")
            return record
        except (KeyError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
            raise ValueError(
                "Windows Worker history cutover record is invalid"
            ) from exc

    @classmethod
    def from_persisted_bases(
        cls, persisted: CodingWindowsWorkerPersistedBasesV1
    ) -> CodingWindowsWorkerHistoryCutoverRecordV1:
        if type(persisted) is not CodingWindowsWorkerPersistedBasesV1:
            raise ValueError("Windows Worker persisted cutover bases are invalid")
        checkpoint = persisted.checkpoint
        source = checkpoint.source_snapshot
        unsigned = {
            "baseDigests": [list(item) for item in checkpoint.base_digests],
            "checkpointDigest": checkpoint.record_digest,
            "cutoverVersion": 1,
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            checkpoint_digest=checkpoint.record_digest,
            source_snapshot_digest=source.snapshot_digest,
            base_digests=checkpoint.base_digests,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def require_persisted_bases(
        self, persisted: CodingWindowsWorkerPersistedBasesV1
    ) -> None:
        if self != self.from_persisted_bases(persisted):
            raise ValueError("Windows Worker history cutover bases changed")


__all__ = [
    "WINDOWS_WORKER_HISTORY_CUTOVER_NAME",
    "CodingWindowsWorkerHistoryCutoverRecordV1",
]
