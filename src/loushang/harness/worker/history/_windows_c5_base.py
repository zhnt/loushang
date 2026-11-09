"""Source-bound Windows c5 semantics over existing history records."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.activation_state_journal import (
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.history._activation import (
    _RetainedAttemptFields,
    fold_activation_attempt_history,
    project_retained_attempts,
)
from loushang.harness.worker.history._base_codec import _SourceBoundBaseWireMethods
from loushang.harness.worker.history._windows_semantic_contracts import (
    _ATTEMPT,
    _DIGEST,
    _RecoveryFacts,
    _SourceFacts,
)


class _WindowsC5BaseMethods(_SourceBoundBaseWireMethods):
    __slots__ = ()
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    owner_present: bool
    cutoff_revision: int
    last_record: _StateRecord | None
    retired_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int
    _replay_type: ClassVar[Callable[..., object]]
    _retained_attempt_type: ClassVar[type[_RetainedAttemptFields]]

    @property
    def known_attempt_ids(self) -> frozenset[str]:
        """Include settled attempts still present in the final C5 state."""

        current = (
            ()
            if self.last_record is None
            else tuple(
                cast(str, attempt["attemptId"])
                for attempt in cast(
                    dict[str, dict[str, object]],
                    self.last_record.document["attempts"],
                ).values()
            )
        )
        return frozenset((*self.retired_attempt_ids, *current))

    def __post_init__(self) -> None:
        try:
            validated = (
                None
                if self.last_record is None
                else _StateRecord.from_dict(self.last_record.to_dict())
            )
            current_ids = (
                ()
                if validated is None
                else tuple(
                    cast(str, attempt["attemptId"])
                    for attempt in cast(
                        dict[str, dict[str, object]],
                        validated.document["attempts"],
                    ).values()
                )
            )
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 semantic base is invalid") from exc
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or type(self.owner_present) is not bool
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < 0
            or (self.last_record is None) != (self.cutoff_revision == 0)
            or (self.last_record is not None and not self.owner_present)
            or validated != self.last_record
            or (
                validated is not None
                and validated.journal_revision != self.cutoff_revision
            )
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or len(current_ids) != len(set(current_ids))
            or bool(set(current_ids) & set(self.retired_attempt_ids))
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker C5 semantic base is invalid")

    @classmethod
    def _from_source_read(cls, source: _SourceFacts, recovery: _RecoveryFacts) -> Self:
        records = recovery.activation_state_records
        names = {item.name for item in source.files}
        if records and "worker-activation-state.jsonl" not in names:
            raise ValueError("Windows Worker C5 source is absent")
        if any(type(item) is not _StateRecord for item in records):
            raise ValueError("Windows Worker C5 history is invalid")
        if records:
            by_name = {item.name: item for item in source.files}
            lines = tuple(
                _canonical_json_bytes(item.to_dict()) + b"\n" for item in records
            )
            journal_bytes = b"".join(lines)
            journal = by_name["worker-activation-state.jsonl"]
            if (
                journal.size != len(journal_bytes)
                or journal.sha256_digest != sha256(journal_bytes).hexdigest()
            ):
                raise ValueError("Windows Worker C5 source changed")
            prefix_digest = sha256()
            prefix_size = 0
            for revision, line in enumerate(lines, 1):
                prefix_digest.update(line)
                prefix_size += len(line)
                head = by_name.get(f"worker-activation-state.h{revision:08d}.json")
                expected_head = canonical_json_bytes(
                    {
                        "byteCount": prefix_size,
                        "digest": prefix_digest.hexdigest(),
                        "revision": revision,
                        "version": 1,
                    }
                )
                if (
                    head is None
                    or head.size != len(expected_head)
                    or head.sha256_digest != sha256(expected_head).hexdigest()
                ):
                    raise ValueError("Windows Worker C5 source changed")
        try:
            if (
                recovery.activation_state_revision != len(records)
                or (bool(records) and not recovery.activation_state_owner_present)
                or recovery.retained_activation_attempts
                != project_retained_attempts(
                    records, record_type=cls._retained_attempt_type
                )
                or any(
                    item.journal_revision != revision
                    or f"worker-activation-state.h{revision:08d}.json" not in names
                    for revision, item in enumerate(records, 1)
                )
            ):
                raise ValueError("Windows Worker C5 history changed")
            retired = fold_activation_attempt_history(records)
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 history is invalid") from exc
        last = None if not records else records[-1]
        unsigned = {
            "cutoffRevision": len(records),
            "lastRecord": None if last is None else last.to_dict(),
            "ownerPresent": recovery.activation_state_owner_present,
            "retiredAttemptIds": sorted(retired),
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cast(Callable[..., Self], cls)(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            owner_present=recovery.activation_state_owner_present,
            cutoff_revision=len(records),
            last_record=last,
            retired_attempt_ids=tuple(sorted(retired)),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _replay_retained(self, records: tuple[_StateRecord, ...]) -> object:
        if type(records) is not tuple:
            raise ValueError("Windows Worker C5 retained replay is invalid")
        for revision, item in enumerate(records, self.cutoff_revision + 1):
            if type(item) is not _StateRecord or item.journal_revision != revision:
                raise ValueError("Windows Worker C5 retained replay is invalid")
        try:
            retired = fold_activation_attempt_history(
                records,
                previous_record=self.last_record,
                retired_attempt_ids=frozenset(self.retired_attempt_ids),
            )
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Windows Worker C5 retained replay is invalid") from exc
        return self._replay_type(
            last_record=self.last_record if not records else records[-1],
            retired_attempt_ids=retired,
        )
