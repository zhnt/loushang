"""Durable Product anchor for the Worker checkpoint journal's committed tip."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

ANCHOR_NAME = "worker-history-checkpoint-owner.json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 1024


class CodingWorkerCheckpointAnchorError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerCheckpointAnchorV1:
    scope_id: str
    store_id: str
    latest_revision: int
    latest_digest: str
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.latest_revision) is not int
            or self.latest_revision < 0
            or type(self.latest_digest) is not str
            or (
                self.latest_revision == 0
                and self.latest_digest != ""
            )
            or (
                self.latest_revision > 0
                and _DIGEST.fullmatch(self.latest_digest) is None
            )
            or type(self.record_version) is not int
            or self.record_version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker checkpoint anchor is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "latestDigest": self.latest_digest,
            "latestRevision": self.latest_revision,
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        store_id: str,
        latest_revision: int,
        latest_digest: str,
    ) -> CodingWorkerCheckpointAnchorV1:
        unsigned = {
            "latestDigest": latest_digest,
            "latestRevision": latest_revision,
            "recordVersion": 1,
            "scopeId": scope_id,
            "storeId": store_id,
        }
        return cls(
            scope_id=scope_id,
            store_id=store_id,
            latest_revision=latest_revision,
            latest_digest=latest_digest,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerCheckpointAnchorV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise CodingWorkerCheckpointAnchorError("coding_worker_checkpoint_anchor_corrupt")
        try:
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {
                "latestDigest",
                "latestRevision",
                "recordDigest",
                "recordVersion",
                "scopeId",
                "storeId",
            }:
                raise ValueError("Coding Worker checkpoint anchor fields changed")
            anchor = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                latest_revision=value["latestRevision"],
                latest_digest=value["latestDigest"],
                record_digest=value["recordDigest"],
                record_version=value["recordVersion"],
            )
            if anchor.to_bytes() != raw:
                raise ValueError("Coding Worker checkpoint anchor encoding changed")
            return anchor
        except (TypeError, ValueError, UnicodeError) as exc:
            raise CodingWorkerCheckpointAnchorError(
                "coding_worker_checkpoint_anchor_corrupt"
            ) from exc


def read_coding_worker_checkpoint_anchor(
    rooted: RootedFile, *, scope_id: str, store_id: str
) -> CodingWorkerCheckpointAnchorV1 | None:
    try:
        raw = rooted.sibling(ANCHOR_NAME).read_bytes(max_bytes=_MAX_BYTES)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CodingWorkerCheckpointAnchorError(
            "coding_worker_checkpoint_anchor_corrupt"
        ) from exc
    anchor = CodingWorkerCheckpointAnchorV1.from_bytes(raw)
    if anchor.scope_id != scope_id or anchor.store_id != store_id:
        raise CodingWorkerCheckpointAnchorError(
            "coding_worker_checkpoint_anchor_owner_changed"
        )
    return anchor


def write_coding_worker_checkpoint_anchor(
    rooted: RootedFile,
    *,
    expected: CodingWorkerCheckpointAnchorV1 | None,
    current: CodingWorkerCheckpointAnchorV1,
) -> None:
    if expected is not None and (
        expected.scope_id != current.scope_id
        or expected.store_id != current.store_id
        or current.latest_revision < expected.latest_revision
    ):
        raise ValueError("Coding Worker checkpoint anchor transition is invalid")
    target = rooted.sibling(ANCHOR_NAME)
    if expected is None:
        target.create_new(current.to_bytes())
        return
    try:
        old_raw = target.read_bytes(max_bytes=_MAX_BYTES)
    except OSError as exc:
        raise CodingWorkerCheckpointAnchorError(
            "coding_worker_checkpoint_anchor_changed"
        ) from exc
    if old_raw != expected.to_bytes():
        raise CodingWorkerCheckpointAnchorError(
            "coding_worker_checkpoint_anchor_changed"
        )
    target.atomic_write(current.to_bytes())


__all__ = [
    "ANCHOR_NAME",
    "CodingWorkerCheckpointAnchorError",
    "CodingWorkerCheckpointAnchorV1",
    "read_coding_worker_checkpoint_anchor",
    "write_coding_worker_checkpoint_anchor",
]
