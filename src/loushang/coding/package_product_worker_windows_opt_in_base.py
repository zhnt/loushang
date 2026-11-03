"""Typed Windows Worker opt-in base for a future Product history cutover.

This projects a guarded V1 source and can validate later records. It does not
publish a cutover, replace the current journal, or authorize deletion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_opt_in import (
    _OPAQUE,
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
    _fold_opt_in_events,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOptInSemanticBaseV1:
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    cutoff_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    retired_operation_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or _OPAQUE.fullmatch(self.scope_id) is None
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < 0
            or type(self.latest_decisions) is not tuple
            or any(
                type(item) is not CodingWorkerOptInDecisionV1
                or item.scope_id != self.scope_id
                or item.journal_revision > self.cutoff_revision
                for item in self.latest_decisions
            )
            or tuple(item.plugin_id for item in self.latest_decisions)
            != tuple(sorted({item.plugin_id for item in self.latest_decisions}))
            or type(self.retired_operation_ids) is not tuple
            or any(
                type(item) is not str
                or len(item) > 128
                or _OPAQUE.fullmatch(item) is None
                for item in self.retired_operation_ids
            )
            or self.retired_operation_ids
            != tuple(sorted(set(self.retired_operation_ids)))
            or len(self.retired_operation_ids) != self.cutoff_revision
            or bool(self.latest_decisions) != bool(self.cutoff_revision)
            or any(
                item.operation_id not in self.retired_operation_ids
                for item in self.latest_decisions
            )
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker opt-in semantic base is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "cutoffRevision": self.cutoff_revision,
            "latestDecisions": [item.to_dict() for item in self.latest_decisions],
            "retiredOperationIds": list(self.retired_operation_ids),
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
            raise ValueError("Windows Worker opt-in semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerOptInSemanticBaseV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Windows Worker opt-in semantic base is invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "cutoffRevision",
                    "latestDecisions",
                    "retiredOperationIds",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                    "recordDigest",
                    "version",
                }
                or type(value["latestDecisions"]) is not list
                or type(value["retiredOperationIds"]) is not list
            ):
                raise ValueError("Windows Worker opt-in semantic base is invalid")
            base = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                cutoff_revision=value["cutoffRevision"],
                latest_decisions=tuple(
                    CodingWorkerOptInDecisionV1.from_dict(item)
                    for item in value["latestDecisions"]
                ),
                retired_operation_ids=tuple(value["retiredOperationIds"]),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Windows Worker opt-in semantic base is invalid")
            return base
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Worker opt-in semantic base is invalid") from exc

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerOptInSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker opt-in preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        events = semantic.offline_recovery.opt_in_decisions
        if events and not any(
            item.name == "worker-opt-in.jsonl" for item in source.files
        ):
            raise ValueError("Windows Worker opt-in source is absent")
        try:
            latest, operations = _fold_opt_in_events(events, scope_id=source.scope_id)
        except CodingWorkerOptInJournalError as exc:
            raise ValueError("Windows Worker opt-in history is invalid") from exc
        unsigned = {
            "cutoffRevision": len(events),
            "latestDecisions": [latest[key].to_dict() for key in sorted(latest)],
            "retiredOperationIds": sorted(operations),
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            cutoff_revision=len(events),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            retired_operation_ids=tuple(sorted(operations)),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def replay(
        self, events: tuple[CodingWorkerOptInDecisionV1, ...]
    ) -> CodingWindowsWorkerOptInReplayV1:
        if type(events) is not tuple:
            raise ValueError("Windows Worker opt-in retained replay is invalid")
        try:
            latest, operations = _fold_opt_in_events(
                events,
                scope_id=self.scope_id,
                start_revision=self.cutoff_revision + 1,
                initial_latest={item.plugin_id: item for item in self.latest_decisions},
                initial_operations=frozenset(self.retired_operation_ids),
            )
        except CodingWorkerOptInJournalError as exc:
            raise ValueError(
                "Windows Worker opt-in retained replay is invalid"
            ) from exc
        return CodingWindowsWorkerOptInReplayV1(
            last_revision=self.cutoff_revision + len(events),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            operation_ids=frozenset(operations),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOptInReplayV1:
    last_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    operation_ids: frozenset[str]


__all__ = [
    "CodingWindowsWorkerOptInReplayV1",
    "CodingWindowsWorkerOptInSemanticBaseV1",
]
