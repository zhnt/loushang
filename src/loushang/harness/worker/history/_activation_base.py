"""Typed C5 retained replay over the original activation-state model."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import CodingWorkerSegmentedHistoryV1
from ..activation_state_journal import (
    _MAX_JOURNAL_BYTES,
    _MAX_REVISIONS,
    _canonical_json_bytes,
    _StateRecord,
)
from ._activation import fold_activation_attempt_history
from ._base_codec import _BASE_ERRORS, _BaseWireMethods, _unchanged

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class _ActivationReplayFields:
    __slots__ = ()

    last_record: _StateRecord
    retired_attempt_ids: frozenset[str]


class _ActivationBaseMethods(_BaseWireMethods):
    __slots__ = ()

    _wire_label = "Coding Worker C5 V2 semantic base"
    _wire_lists = ("retiredAttemptIds",)
    _wire_errors = (*_BASE_ERRORS, RecursionError)

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "last_record",
                encoder=_StateRecord.to_dict,
                decoder=_StateRecord.from_dict,
            ),
            RecordField("retired_attempt_ids", encoder=list, decoder=tuple),
        )

    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    last_record: _StateRecord
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    _replay_type: ClassVar[type[_ActivationReplayFields]]

    def __post_init__(self) -> None:
        if type(self.last_record) is not _StateRecord:
            raise ValueError("Coding Worker C5 V2 semantic base is invalid")
        try:
            validated_record = _StateRecord.from_dict(self.last_record.to_dict())
            attempts = cast(
                dict[str, dict[str, object]], validated_record.document["attempts"]
            )
            current_ids = tuple(
                cast(str, attempt["attemptId"]) for attempt in attempts.values()
            )
        except (KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError("Coding Worker C5 V2 semantic base is invalid") from exc
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 1
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < self.first_retained_generation
            or validated_record != self.last_record
            or self.last_record.journal_revision != self.cutoff_revision
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or len(set(current_ids)) != len(current_ids)
            or bool(set(current_ids) & set(self.retired_attempt_ids))
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker C5 V2 semantic base is invalid")

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
    ) -> Self:
        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker C5 V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-activation-state"
            or type(first_retained_generation) is not int
            or not 1 <= first_retained_generation <= manifest.active_generation
            or len(history.segments) != manifest.active_generation + 1
        ):
            raise ValueError("Coding Worker C5 V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        records: list[_StateRecord] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker C5 V2 source changed")
            records.extend(_parse_c5_segment(raw, first_revision=len(records) + 1))
            if len(records) != seal.last_revision:
                raise ValueError("Coding Worker C5 V2 source revision changed")
        try:
            retired_ids = fold_activation_attempt_history(tuple(records))
        except ValueError as exc:
            raise ValueError("Coding Worker C5 V2 source is invalid") from exc
        return cast(Callable[..., Self], cls)(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=retired[-1].last_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            last_record=records[-1],
            retired_attempt_ids=tuple(sorted(retired_ids)),
        )

    def replay_retained(self, segments: tuple[bytes, ...]) -> _ActivationReplayFields:
        if type(segments) is not tuple or not segments:
            raise ValueError("Coding Worker C5 V2 retained segments are invalid")
        revision = self.cutoff_revision
        records: list[_StateRecord] = []
        for raw in segments:
            segment = _parse_c5_segment(raw, first_revision=revision + 1)
            records.extend(segment)
            revision += len(segment)
        try:
            retired_ids = fold_activation_attempt_history(
                tuple(records),
                previous_record=self.last_record,
                retired_attempt_ids=frozenset(self.retired_attempt_ids),
            )
        except ValueError as exc:
            raise ValueError("Coding Worker C5 V2 retained replay is invalid") from exc
        return cast(Callable[..., _ActivationReplayFields], self._replay_type)(
            last_record=self.last_record if not records else records[-1],
            retired_attempt_ids=retired_ids,
        )


def _parse_c5_segment(raw: bytes, *, first_revision: int) -> tuple[_StateRecord, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_JOURNAL_BYTES:
        raise ValueError("Coding Worker C5 V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_REVISIONS:
        raise ValueError("Coding Worker C5 V2 segment exceeds capacity")
    records: list[_StateRecord] = []
    try:
        for revision, line in enumerate(lines, first_revision):
            record = _StateRecord.from_dict(json.loads(line))
            if (
                record.journal_revision != revision
                or line != _canonical_json_bytes(record.to_dict()) + b"\n"
            ):
                raise ValueError("Coding Worker C5 V2 segment changed")
            records.append(record)
    except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker C5 V2 segment is invalid") from exc
    return tuple(records)
