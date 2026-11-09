"""Checkpoint values and invariants; publishing authority remains separate."""

from __future__ import annotations

import re
from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._snapshot import CODING_WORKER_HISTORY_STREAM_STEMS, _SnapshotMethods

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _sorted_unique(values: tuple[str, ...]) -> bool:
    return type(values) is tuple and values == tuple(sorted(set(values)))


class _CheckpointMethods:
    __slots__ = ()

    journal_revision: int
    scope_id: str
    store_id: str
    attempt_id: str
    receipt_fingerprint: str
    previous_digest: str
    gc_reservation_revision: int
    backup_topology_revision: str
    stream_snapshots: tuple[_SnapshotMethods, ...]
    new_opt_in_operation_ids: tuple[str, ...]
    new_attempt_ids: tuple[str, ...]
    new_receipt_fingerprints: tuple[str, ...]
    opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...]
    supervisor_epoch_high_water: tuple[tuple[str, int], ...]
    record_digest: str
    record_version: int = 1

    _snapshot_type: ClassVar[type[_SnapshotMethods]]

    @staticmethod
    def _valid_backup_topology_revision(value: str) -> bool:
        """The concrete Product supplies its original namespace predicate."""
        raise NotImplementedError

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.receipt_fingerprint) is not str
            or _DIGEST.fullmatch(self.receipt_fingerprint) is None
            or type(self.previous_digest) is not str
            or (
                self.previous_digest and _DIGEST.fullmatch(self.previous_digest) is None
            )
            or type(self.gc_reservation_revision) is not int
            or self.gc_reservation_revision < 0
            or type(self.backup_topology_revision) is not str
            or not self._valid_backup_topology_revision(self.backup_topology_revision)
            or type(self.stream_snapshots) is not tuple
            or any(
                type(item) is not self._snapshot_type for item in self.stream_snapshots
            )
            or tuple(item.stem for item in self.stream_snapshots)
            != CODING_WORKER_HISTORY_STREAM_STEMS
            or not _sorted_unique(self.new_opt_in_operation_ids)
            or not _sorted_unique(self.new_attempt_ids)
            or not _sorted_unique(self.new_receipt_fingerprints)
            or any(
                type(item) is not str or not item or len(item) > 128
                for item in self.new_opt_in_operation_ids
            )
            or any(_ATTEMPT.fullmatch(item) is None for item in self.new_attempt_ids)
            or any(
                _DIGEST.fullmatch(item) is None
                for item in self.new_receipt_fingerprints
            )
            or type(self.opt_in_generation_high_water) is not tuple
            or self.opt_in_generation_high_water
            != tuple(sorted(self.opt_in_generation_high_water))
            or type(self.supervisor_epoch_high_water) is not tuple
            or self.supervisor_epoch_high_water
            != tuple(sorted(self.supervisor_epoch_high_water))
            or type(self.record_version) is not int
            or self.record_version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker history checkpoint is invalid")
        for (
            plugin_id,
            generation,
            kill_generation,
            action,
            digest,
        ) in self.opt_in_generation_high_water:
            if (
                type(plugin_id) is not str
                or not plugin_id
                or type(generation) is not int
                or generation < 1
                or type(kill_generation) is not int
                or kill_generation < 0
                or action not in {"allow", "revoke"}
                or type(digest) is not str
                or _DIGEST.fullmatch(digest) is None
            ):
                raise ValueError(
                    "Coding Worker checkpoint opt-in high water is invalid"
                )
        if len({item[0] for item in self.opt_in_generation_high_water}) != len(
            self.opt_in_generation_high_water
        ):
            raise ValueError("Coding Worker checkpoint opt-in keys repeat")
        for key, epoch in self.supervisor_epoch_high_water:
            if type(key) is not str or not key or type(epoch) is not int or epoch < 1:
                raise ValueError(
                    "Coding Worker checkpoint Supervisor high water is invalid"
                )
        if len({item[0] for item in self.supervisor_epoch_high_water}) != len(
            self.supervisor_epoch_high_water
        ):
            raise ValueError("Coding Worker checkpoint Supervisor keys repeat")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "backupTopologyRevision": self.backup_topology_revision,
            "gcReservationRevision": self.gc_reservation_revision,
            "journalRevision": self.journal_revision,
            "newAttemptIds": list(self.new_attempt_ids),
            "newOptInOperationIds": list(self.new_opt_in_operation_ids),
            "newReceiptFingerprints": list(self.new_receipt_fingerprints),
            "optInGenerationHighWater": [
                list(item) for item in self.opt_in_generation_high_water
            ],
            "previousDigest": self.previous_digest,
            "receiptFingerprint": self.receipt_fingerprint,
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "streamSnapshots": [item.to_dict() for item in self.stream_snapshots],
            "supervisorEpochHighWater": [
                list(item) for item in self.supervisor_epoch_high_water
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        scope_id: str,
        store_id: str,
        attempt_id: str,
        receipt_fingerprint: str,
        previous_digest: str,
        gc_reservation_revision: int,
        backup_topology_revision: str,
        stream_snapshots: tuple[_SnapshotMethods, ...],
        new_opt_in_operation_ids: tuple[str, ...],
        new_attempt_ids: tuple[str, ...],
        new_receipt_fingerprints: tuple[str, ...],
        opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...],
        supervisor_epoch_high_water: tuple[tuple[str, int], ...],
    ) -> Self:
        unsigned = {
            "attemptId": attempt_id,
            "backupTopologyRevision": backup_topology_revision,
            "gcReservationRevision": gc_reservation_revision,
            "journalRevision": journal_revision,
            "newAttemptIds": list(new_attempt_ids),
            "newOptInOperationIds": list(new_opt_in_operation_ids),
            "newReceiptFingerprints": list(new_receipt_fingerprints),
            "optInGenerationHighWater": [
                list(item) for item in opt_in_generation_high_water
            ],
            "previousDigest": previous_digest,
            "receiptFingerprint": receipt_fingerprint,
            "recordVersion": 1,
            "scopeId": scope_id,
            "storeId": store_id,
            "streamSnapshots": [item.to_dict() for item in stream_snapshots],
            "supervisorEpochHighWater": [
                list(item) for item in supervisor_epoch_high_water
            ],
        }
        return cast(Callable[..., Self], cls)(
            journal_revision=journal_revision,
            scope_id=scope_id,
            store_id=store_id,
            attempt_id=attempt_id,
            receipt_fingerprint=receipt_fingerprint,
            previous_digest=previous_digest,
            gc_reservation_revision=gc_reservation_revision,
            backup_topology_revision=backup_topology_revision,
            stream_snapshots=stream_snapshots,
            new_opt_in_operation_ids=new_opt_in_operation_ids,
            new_attempt_ids=new_attempt_ids,
            new_receipt_fingerprints=new_receipt_fingerprints,
            opt_in_generation_high_water=opt_in_generation_high_water,
            supervisor_epoch_high_water=supervisor_epoch_high_water,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {
            "attemptId",
            "backupTopologyRevision",
            "gcReservationRevision",
            "journalRevision",
            "newAttemptIds",
            "newOptInOperationIds",
            "newReceiptFingerprints",
            "optInGenerationHighWater",
            "previousDigest",
            "receiptFingerprint",
            "recordDigest",
            "recordVersion",
            "scopeId",
            "storeId",
            "streamSnapshots",
            "supervisorEpochHighWater",
        }:
            raise ValueError("Coding Worker checkpoint record shape is invalid")
        for name in (
            "newAttemptIds",
            "newOptInOperationIds",
            "newReceiptFingerprints",
            "optInGenerationHighWater",
            "streamSnapshots",
            "supervisorEpochHighWater",
        ):
            if type(value[name]) is not list:
                raise ValueError("Coding Worker checkpoint list shape is invalid")
        return cast(Callable[..., Self], cls)(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            store_id=value["storeId"],
            attempt_id=value["attemptId"],
            receipt_fingerprint=value["receiptFingerprint"],
            previous_digest=value["previousDigest"],
            gc_reservation_revision=value["gcReservationRevision"],
            backup_topology_revision=value["backupTopologyRevision"],
            stream_snapshots=tuple(
                cls._snapshot_type.from_dict(item) for item in value["streamSnapshots"]
            ),
            new_opt_in_operation_ids=tuple(value["newOptInOperationIds"]),
            new_attempt_ids=tuple(value["newAttemptIds"]),
            new_receipt_fingerprints=tuple(value["newReceiptFingerprints"]),
            opt_in_generation_high_water=tuple(
                tuple(item) for item in value["optInGenerationHighWater"]
            ),
            supervisor_epoch_high_water=tuple(
                tuple(item) for item in value["supervisorEpochHighWater"]
            ),
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


def checkpoint_chain_matches(
    checkpoints: tuple[_CheckpointMethods, ...],
    checkpoint: _CheckpointMethods,
) -> bool:
    """Match a previously type-checked sequence to its original logical owner."""
    return not any(
        item.journal_revision != ordinal
        or item.scope_id != checkpoint.scope_id
        or item.store_id != checkpoint.store_id
        or item.previous_digest
        != ("" if ordinal == 1 else checkpoints[ordinal - 2].record_digest)
        for ordinal, item in enumerate(checkpoints, 1)
    )
