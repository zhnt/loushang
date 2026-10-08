"""Exact V2 source-deletion debt bound to one committed Product owner index.

The ledger allows a V2 reader to tolerate only named retired segments being
absent. Its presence does not by itself delete a file or authorize Package GC.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerV2DeletionLedger:
    scope_id: str
    store_id: str
    owner_index_digest: str
    retired_seals: tuple[tuple[str, int, int, int, int, str], ...]
    record_digest: str
    version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.owner_index_digest) is not str
            or _DIGEST.fullmatch(self.owner_index_digest) is None
            or type(self.retired_seals) is not tuple
            or not self.retired_seals
            or any(
                type(item) is not tuple
                or len(item) != 6
                or type(item[0]) is not str
                or type(item[1]) is not int
                or item[1] < 0
                or type(item[2]) is not int
                or item[2] < 1
                or type(item[3]) is not int
                or item[3] < item[2]
                or type(item[4]) is not int
                or item[4] < 1
                or type(item[5]) is not str
                or _DIGEST.fullmatch(item[5]) is None
                for item in self.retired_seals
            )
            or len({(stem, generation) for stem, generation, *_ in self.retired_seals})
            != len(self.retired_seals)
            or type(self.version) is not int
            or self.version != 2
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker V2 deletion ledger is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "ownerIndexDigest": self.owner_index_digest,
            "retiredSeals": [list(item) for item in self.retired_seals],
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "version": self.version,
        }

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )
        if len(raw) > _MAX_BYTES:
            raise ValueError("Coding Worker V2 deletion ledger exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerV2DeletionLedger:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise ValueError("Coding Worker V2 deletion ledger bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "ownerIndexDigest",
                    "recordDigest",
                    "retiredSeals",
                    "scopeId",
                    "storeId",
                    "version",
                }
                or type(value["retiredSeals"]) is not list
            ):
                raise ValueError("Coding Worker V2 deletion ledger fields changed")
            ledger = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                owner_index_digest=value["ownerIndexDigest"],
                retired_seals=tuple(
                    tuple(item) if type(item) is list else item
                    for item in value["retiredSeals"]
                ),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if ledger.to_bytes() != raw:
                raise ValueError("Coding Worker V2 deletion ledger encoding changed")
            return ledger
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker V2 deletion ledger bytes are invalid"
            ) from exc

    @classmethod
    def from_prepared(
        cls, prepared: CodingWorkerPreparedProductCutoverV2
    ) -> CodingWorkerV2DeletionLedger:
        if type(prepared) is not CodingWorkerPreparedProductCutoverV2:
            raise ValueError("Coding Worker V2 deletion requires typed Product index")
        index = prepared.index
        retired = tuple(
            (
                stream.stem,
                seal.generation,
                seal.first_revision,
                seal.last_revision,
                seal.byte_count,
                seal.digest,
            )
            for stream in prepared.streams
            for seal in stream.retired_sealed
        )
        unsigned = {
            "ownerIndexDigest": sha256(index.to_bytes()).hexdigest(),
            "retiredSeals": [list(item) for item in retired],
            "scopeId": index.scope_id,
            "storeId": index.store_id,
            "version": 2,
        }
        return cls(
            scope_id=index.scope_id,
            store_id=index.store_id,
            owner_index_digest=sha256(index.to_bytes()).hexdigest(),
            retired_seals=retired,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


__all__ = ["CodingWorkerV2DeletionLedger"]
