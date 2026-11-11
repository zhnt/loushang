"""Source-bound Windows opt in semantics over existing history records."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._base_codec import _SourceBoundBaseWireMethods
from loushang.harness.worker.history._opt_in import (
    _OPAQUE,
    _OptInDecisionMethods,
    fold_opt_in_events,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _DIGEST,
    _RecoveryFacts,
    _SourceFacts,
)


class _WindowsOptInBaseMethods(_SourceBoundBaseWireMethods):
    __slots__ = ()
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    cutoff_revision: int
    latest_decisions: tuple[_OptInDecisionMethods, ...]
    retired_operation_ids: tuple[str, ...]
    record_digest: str
    version: int
    _decision_type: ClassVar[type[_OptInDecisionMethods]]
    _error_type: ClassVar[type[RuntimeError]]
    _replay_type: ClassVar[Callable[..., object]]

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
                type(item) is not self._decision_type
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

    @classmethod
    def _from_source_read(cls, source: _SourceFacts, recovery: _RecoveryFacts) -> Self:
        events = recovery.opt_in_decisions
        if events and not any(
            item.name == "worker-opt-in.jsonl" for item in source.files
        ):
            raise ValueError("Windows Worker opt-in source is absent")
        try:
            latest, operations = fold_opt_in_events(
                events, scope_id=source.scope_id, error_type=cls._error_type
            )
        except cls._error_type as exc:
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
        return cast(Callable[..., Self], cls)(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            cutoff_revision=len(events),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            retired_operation_ids=tuple(sorted(operations)),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _replay_retained(self, events: tuple[_OptInDecisionMethods, ...]) -> object:
        if type(events) is not tuple:
            raise ValueError("Windows Worker opt-in retained replay is invalid")
        try:
            latest, operations = fold_opt_in_events(
                events,
                scope_id=self.scope_id,
                start_revision=self.cutoff_revision + 1,
                initial_latest={item.plugin_id: item for item in self.latest_decisions},
                initial_operations=frozenset(self.retired_operation_ids),
                error_type=self._error_type,
            )
        except self._error_type as exc:
            raise ValueError(
                "Windows Worker opt-in retained replay is invalid"
            ) from exc
        return self._replay_type(
            last_revision=self.cutoff_revision + len(events),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            operation_ids=frozenset(operations),
        )
