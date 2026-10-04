"""Segmented Product custody for the durable C5 Worker activation state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loushang.harness.journal import (
    JournalCodecError,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.worker.activation_state_journal import (
    _CODEC,
    _FORMAT,
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_JOURNAL_BYTES as _DEFAULT_MAX_BYTES,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_REVISIONS as _DEFAULT_MAX_REVISIONS,
)
from loushang.harness.worker.product_activation import _ATTEMPT_TRANSITIONS

from .package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)

_STEM = "worker-activation-state"
_MAX_REVISIONS = _DEFAULT_MAX_REVISIONS
_MAX_BYTES = _DEFAULT_MAX_BYTES
_IMMUTABLE_ATTEMPT_FIELDS = (
    "attemptId",
    "bootIdentity",
    "evidenceAuthorityFingerprint",
    "evidenceAuthorityId",
    "hostIdentity",
    "owner",
    "ownerGeneration",
    "policyFingerprint",
    "receiptFingerprint",
    "required",
)


class CodingProductWorkerActivationStateJournal(WorkerActivationStateJournal):
    """Keep every CAS revision across immutable Product-owned generations."""

    def load(self) -> Mapping[str, object] | None:
        with self._bound_journal() as rooted:
            records, _history = self._load_segments(rooted)
            return None if not records else dict(records[-1].document)

    def load_read_only(self) -> Mapping[str, object] | None:
        with self._bound_journal_read_only() as rooted:
            records, _history = self._load_segments(rooted)
            return None if not records else dict(records[-1].document)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Worker activation expected revision is invalid")
        record = _StateRecord.create(document)
        if record.journal_revision != expected_revision + 1:
            raise ValueError("Worker activation state revision must advance by one")
        line = _canonical_json_bytes(record.to_dict()) + b"\n"
        if len(line) > _MAX_BYTES:
            raise WorkerActivationStateJournalError("worker_activation_state_capacity")
        with self._bound_journal() as rooted:
            records, history = self._load_segments(rooted)
            current_revision = 0 if not records else records[-1].journal_revision
            if current_revision != expected_revision:
                return False
            try:
                _validate_attempt_history((*records, record))
            except ValueError as exc:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_history_conflict"
                ) from exc
            active_records = current_revision - history.last_sealed_revision
            if (
                active_records >= _MAX_REVISIONS
                or len(history.active_raw) + len(line) > _MAX_BYTES
            ):
                try:
                    seal_coding_worker_active_segment(
                        rooted,
                        stem=_STEM,
                        stream_id=_STEM,
                        history=history,
                        last_revision=current_revision,
                    )
                except CodingWorkerHistorySegmentError as exc:
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_capacity"
                        if exc.code == "coding_worker_segment_capacity"
                        else "worker_activation_state_corrupt"
                    ) from exc
                generation = history.active_generation + 1
            else:
                generation = history.active_generation
            name = (
                f"{_STEM}.jsonl"
                if generation == 0
                else f"{_STEM}.g{generation:08d}.jsonl"
            )
            append_jsonl_record(
                self.path,
                record,
                record_codec=_CODEC,
                format_profile=_FORMAT,
                durability=self._durability,
                bound_file=rooted.sibling(name),
            )
            return True

    def _load_segments(
        self, rooted: RootedFile
    ) -> tuple[tuple[_StateRecord, ...], CodingWorkerSegmentedHistoryV1]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=_MAX_BYTES,
            )
            records: list[_StateRecord] = []
            for generation, raw in enumerate(history.segments):
                segment = decode_jsonl(
                    raw.decode("utf-8"),
                    target=self.path,
                    record_codec=_CODEC,
                    load_policy=self._load_policy,
                ).records
                lines = raw.splitlines(keepends=True)
                if (
                    len(segment) > _MAX_REVISIONS
                    or len(segment) != len(lines)
                    or any(
                        record.journal_revision != revision
                        or line != _canonical_json_bytes(record.to_dict()) + b"\n"
                        for revision, (record, line) in enumerate(
                            zip(segment, lines, strict=True), len(records) + 1
                        )
                    )
                ):
                    raise ValueError("Worker activation state segment changed")
                records.extend(segment)
                if (
                    history.manifest is not None
                    and generation < history.active_generation
                    and len(records)
                    != history.manifest.sealed[generation].last_revision
                ):
                    raise ValueError("Worker activation state sealed revision changed")
            result = tuple(records)
            _validate_attempt_history(result)
            return result, history
        except (
            CodingWorkerHistorySegmentError,
            JournalCodecError,
            OSError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc


def _validate_attempt_history(records: tuple[_StateRecord, ...]) -> None:
    """A compacted attempt cannot be minted again under another CAS revision."""

    seen_attempt_ids: dict[str, str] = {}
    removed_keys: set[str] = set()
    previous: dict[str, dict[str, object]] = {}
    for record in records:
        current = cast(dict[str, dict[str, object]], record.document["attempts"])
        for key in previous.keys() - current.keys():
            if previous[key]["phase"] != "settled":
                raise ValueError("Unsettled activation attempt was removed")
            removed_keys.add(key)
        for key, attempt in current.items():
            attempt_id = cast(str, attempt["attemptId"])
            prior_key = seen_attempt_ids.get(attempt_id)
            if key in removed_keys or (prior_key is not None and prior_key != key):
                raise ValueError("Activation attempt identity was reused")
            seen_attempt_ids[attempt_id] = key
            prior_attempt = previous.get(key)
            if prior_attempt is not None:
                if any(
                    attempt[field] != prior_attempt[field]
                    for field in _IMMUTABLE_ATTEMPT_FIELDS
                ):
                    raise ValueError("Activation attempt identity changed")
                prior_phase = cast(str, prior_attempt["phase"])
                phase = cast(str, attempt["phase"])
                if (
                    phase != prior_phase
                    and phase not in _ATTEMPT_TRANSITIONS[prior_phase]
                ):
                    raise ValueError("Activation attempt phase regressed")
        previous = current


__all__ = ["CodingProductWorkerActivationStateJournal"]
