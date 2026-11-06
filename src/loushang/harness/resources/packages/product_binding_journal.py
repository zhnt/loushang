"""Private persistence mechanics for separate Product admission binding logs.

Each concrete journal retains its record codec, identity, errors and admission
policy. This module does not select a Package decision or combine journal files.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JournalRecordCodec,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecyclePinnedAdoptionRequestV1,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleStagingAdoptionRequestV1,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_READ_ONLY_LOAD_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)
_Decision = (
    PackageLifecyclePinnedAdoptionRequestV1
    | PackageLifecycleRebindRequestV1
    | PackageLifecycleStagingAdoptionRequestV1
)


class _BindingRecord(Protocol):
    @property
    def record_revision(self) -> int: ...


class _DecisionBindingRecord(_BindingRecord, Protocol):
    @property
    def decision(self) -> _Decision: ...

    @property
    def admission(self) -> PackageEpochRuntimeAdmissionReceiptV1: ...


_RecordT = TypeVar("_RecordT", bound=_BindingRecord)
_DecisionRecordT = TypeVar("_DecisionRecordT", bound=_DecisionBindingRecord)
_DecisionT = TypeVar("_DecisionT", bound=_Decision)


class _ProductBindingJournal(Generic[_RecordT]):
    _codec: JournalRecordCodec[_RecordT]
    _label: str
    _corrupt_code: str

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def _record_key(self, record: _RecordT) -> str:
        raise NotImplementedError

    def _error(self, message: str, *, code: str) -> Exception:
        raise NotImplementedError

    def _append_record(self, record: _RecordT) -> None:
        append_jsonl_record(
            self._path,
            record,
            record_codec=self._codec,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _read_only_records(self) -> tuple[_RecordT, ...]:
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            return self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[_RecordT, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, _RecordT] = load_jsonl(
                self._path,
                record_codec=self._codec,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=load_policy or self._load_policy,
            )
            records = snapshot.records
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if line:
                    json.loads(line, object_pairs_hook=self._unique_json_object)
            if any(
                record.record_revision != revision
                for revision, record in enumerate(records, start=1)
            ) or len({self._record_key(record) for record in records}) != len(records):
                raise ValueError(f"{self._label} history changed")
            return records
        except (
            JournalCodecError,
            JournalFileError,
            OSError,
            UnicodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise self._error(
                f"{self._label} journal is corrupt", code=self._corrupt_code
            ) from exc

    def _unique_json_object(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{self._label} contains duplicate JSON keys")
            result[key] = value
        return result


class _ProductDecisionBindingJournal(
    _ProductBindingJournal[_DecisionRecordT], Generic[_DecisionRecordT, _DecisionT]
):
    _decision_type: type[_DecisionT]
    _record_type: Callable[..., _DecisionRecordT]
    _query_label: str
    _invalid_code: str
    _conflict_code: str
    _match_snapshot: bool = True
    _match_full_receipt: bool = False

    def _record_key(self, record: _DecisionRecordT) -> str:
        return record.decision.decision_id

    def _bind_decision(
        self, decision: _DecisionT, admission: PackageEpochRuntimeAdmissionReceiptV1
    ) -> _DecisionRecordT:
        if not isinstance(decision, self._decision_type) or not isinstance(
            admission, PackageEpochRuntimeAdmissionReceiptV1
        ):
            raise TypeError(f"Exact {self._label} evidence is required")
        if (
            decision.new_runtime_admission_request_id
            != admission.request.admission_request_id
            or (
                self._match_snapshot
                and decision.lease_snapshot_id != admission.lease_snapshot_id
            )
        ):
            raise self._error(
                f"{self._label} changed decision", code=self._invalid_code
            )
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            records = self._load_unlocked()
            existing = next(
                (
                    record
                    for record in records
                    if record.decision.decision_id == decision.decision_id
                ),
                None,
            )
            if existing is not None:
                if existing.decision == decision and (
                    existing.admission == admission
                    if self._match_full_receipt
                    else existing.admission.request == admission.request
                ):
                    return existing
                raise self._error(
                    f"{self._label} changed for fixed decision",
                    code=self._conflict_code,
                )
            record = self._record_type(
                record_revision=len(records) + 1,
                decision=decision,
                admission=admission,
            )
            self._append_record(record)
            return record

    def _read_decision(self, decision_id: str) -> _DecisionRecordT | None:
        if not isinstance(decision_id, str) or _SHA256.fullmatch(decision_id) is None:
            raise ValueError(f"{self._query_label} decision id is invalid")
        records = self._read_only_records()
        return next(
            (
                record
                for record in records
                if record.decision.decision_id == decision_id
            ),
            None,
        )

    def _read_operation(self, operation_id: str) -> tuple[_DecisionRecordT, ...]:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError(f"{self._query_label} operation id is invalid")
        return tuple(
            record
            for record in self._read_only_records()
            if record.decision.operation_id == operation_id
        )
