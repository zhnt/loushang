"""Versioned Work references to Product-authorized Transcript records.

The codec is private to this bridge. Paths and read authority never come from
Work payloads. Readable records and complete handoffs are not Goal acceptance.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from loushang.harness.transcript.source_reader import (
    TranscriptSourceBatch,
    TranscriptSourceReader,
    TranscriptSourceRecord,
)
from loushang.harnesswork.event_log import EventLogEntry
from loushang.harnesswork.recording import WorkRecording, project_work_recording
from loushang.harnesswork.types import WorkEventFact

CONTRACT_KEY = "_harnesswork_transcript"
REFERENCE_KIND = "WorkTranscriptReferenced"
HANDOFF_KIND = "WorkTranscriptHandoffCompleted"


class WorkTranscriptError(ValueError):
    """A source contract or its recorded handoff cannot be verified."""


class WorkTranscriptExpired(WorkTranscriptError):
    """The frozen Product retention deadline has elapsed."""


def _text(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise WorkTranscriptError("expected a nonempty source identifier")
    return value


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise WorkTranscriptError("invalid source fields")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise WorkTranscriptError("unsupported source version")
    return dict(value)


def _deadline(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value))
    except ValueError as error:
        raise WorkTranscriptError("invalid source retention deadline") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise WorkTranscriptError("retention deadline requires timezone")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class WorkTranscriptSource:
    reader: TranscriptSourceReader
    binding_id: str
    store_identity: str
    conversation_id: str
    retained_until: datetime

    @classmethod
    async def bind(
        cls,
        reader: TranscriptSourceReader,
        *,
        binding_id: str,
        retained_until: datetime,
    ) -> WorkTranscriptSource:
        _text(binding_id)
        deadline = _deadline(retained_until.isoformat())
        if deadline <= datetime.now(UTC):
            raise WorkTranscriptExpired("retention_expired")
        batch = await reader.inspect_identity()
        return cls(
            reader, binding_id, batch.store_identity, batch.conversation_id, deadline
        )

    def check(self) -> None:
        if datetime.now(UTC) >= self.retained_until:
            raise WorkTranscriptExpired("retention_expired")

    def identity(self) -> dict[str, object]:
        return dict(
            version=1,
            binding_id=self.binding_id,
            store_identity=self.store_identity,
            conversation_id=self.conversation_id,
        )

    def contract(self, handoffs: Sequence[Mapping[str, object]]) -> dict[str, object]:
        self.check()
        result = {
            **self.identity(),
            "retained_until": self.retained_until.isoformat(),
            "handoff": "committed_messages",
            "handoffs": [dict(item) for item in handoffs],
        }
        _contract(result)
        return result

    async def read(self, record_ids: Sequence[str]) -> TranscriptSourceBatch:
        self.check()
        batch = await self.reader.read(record_ids)
        self.check()
        if (
            batch.store_identity != self.store_identity
            or batch.conversation_id != self.conversation_id
        ):
            raise WorkTranscriptError("source identity changed")
        return batch

    async def report(
        self,
        record_events: Mapping[str, str],
        *,
        handoff_id: str,
        publish: Callable[[WorkEventFact], object],
        cancelled: Callable[[], bool],
    ) -> None:
        record_events = dict(record_events)
        if not record_events:
            raise WorkTranscriptError(
                "prompt returned without committed message records"
            )
        if cancelled():
            return
        batch = await self.read(tuple(record_events))
        for source in batch.records:
            if cancelled():
                return
            publish(
                WorkEventFact(
                    kind=REFERENCE_KIND,
                    source_event_ref=record_events[source.record.record_id],
                    payload={
                        "transcript_source": {
                            **self.identity(),
                            "handoff_id": handoff_id,
                            "record_id": source.record.record_id,
                            "branch_digest": source.branch_digest,
                        }
                    },
                )
            )
        if not cancelled():
            publish(
                WorkEventFact(
                    kind=HANDOFF_KIND,
                    payload={
                        "handoff": {
                            **self.identity(),
                            "handoff_id": handoff_id,
                            "record_ids": list(record_events),
                        }
                    },
                )
            )


_IDENTITY_KEYS = {"version", "binding_id", "store_identity", "conversation_id"}


def _contract(raw: object) -> dict[str, object]:
    contract = _object(raw, _IDENTITY_KEYS | {"retained_until", "handoff", "handoffs"})
    for key in _IDENTITY_KEYS - {"version"}:
        _text(contract[key])
    _deadline(contract["retained_until"])
    groups = contract["handoffs"]
    if (
        contract["handoff"] != "committed_messages"
        or type(groups) is not list
        or not groups
    ):
        raise WorkTranscriptError("invalid expected handoffs")
    seen = set()
    for group in groups:
        if type(group) is not dict or set(group) != {
            "handoff_id",
            "step_id",
            "step_index",
            "prompt_index",
        }:
            raise WorkTranscriptError("invalid expected handoff")
        key = _text(group["handoff_id"])
        index, prompt = group["step_index"], group["prompt_index"]
        if (
            type(prompt) is not int
            or prompt < 0
            or (index is not None and (type(index) is not int or index < 0))
            or (group["step_id"] is not None and not _text(group["step_id"]))
            or key != f"{index if index is not None else 0}:{prompt}"
            or key in seen
        ):
            raise WorkTranscriptError("invalid or repeated expected handoff")
        seen.add(key)
    return contract


@dataclass(frozen=True)
class WorkTranscriptReference:
    handoff_id: str
    record_id: str
    branch_digest: str


@dataclass(frozen=True)
class WorkTranscriptHandoffs:
    references: tuple[WorkTranscriptReference, ...]
    missing_handoffs: tuple[str, ...]
    binding_id: str
    store_identity: str
    conversation_id: str
    retained_until: datetime

    @property
    def complete(self) -> bool:
        return not self.missing_handoffs


@dataclass(frozen=True)
class WorkTranscriptResolution:
    handoffs: WorkTranscriptHandoffs
    records: tuple[TranscriptSourceRecord, ...]
    bytes_read: int
    ancestors_hashed: int


def project_work_transcript(
    recording: WorkRecording, entries: Sequence[EventLogEntry]
) -> WorkTranscriptHandoffs | None:
    """Decode only the supplied owner's confirmed prefix; never read a cache past ACK.

    For cold history obtain ``recording`` via ``project_work_recording`` after
    stopping its writer and opening a fresh backend. This is not write recovery.
    """
    selected = [
        e
        for e in entries
        if e.run_id == recording.run.run_id
        and e.sequence <= recording.observed_sequence
    ]
    loaded = project_work_recording(selected, recording.run.run_id)
    if (
        loaded is None
        or loaded.observed_sequence != recording.observed_sequence
        or loaded.source_event_id != recording.source_event_id
        or loaded.contract != recording.contract
        or loaded.run.operation_id != recording.run.operation_id
        or loaded.run.session_id != recording.run.session_id
    ):
        raise WorkTranscriptError("entries differ from confirmed Work prefix")
    payload = selected[0].payload.get("payload")
    if not isinstance(payload, Mapping) or CONTRACT_KEY not in payload:
        if any(
            e.payload.get("kind") in {REFERENCE_KIND, HANDOFF_KIND} for e in selected
        ):
            raise WorkTranscriptError("source facts without admission contract")
        return None
    contract = _contract(payload[CONTRACT_KEY])
    if (
        contract["conversation_id"] != recording.run.session_id
        or recording.contract is None
    ):
        raise WorkTranscriptError(
            "source admission differs from Work session or recording"
        )
    expected = {
        _text(group["handoff_id"])
        for group in cast(list[dict[str, object]], contract["handoffs"])
    }
    references = []
    groups: dict[str, dict[str, str]] = {key: {} for key in expected}
    completed: set[str] = set()
    for entry in selected[1:]:
        kind = entry.payload.get("kind")
        if kind not in {REFERENCE_KIND, HANDOFF_KIND}:
            continue
        nested = entry.payload.get("payload")
        field = "transcript_source" if kind == REFERENCE_KIND else "handoff"
        if not isinstance(nested, Mapping) or set(nested) != {field}:
            raise WorkTranscriptError(
                "source facts must have only their nested payload"
            )
        fields = (
            {"record_id", "branch_digest"} if kind == REFERENCE_KIND else {"record_ids"}
        )
        raw = _object(nested[field], _IDENTITY_KEYS | {"handoff_id"} | fields)
        if any(raw[key] != contract[key] for key in _IDENTITY_KEYS):
            raise WorkTranscriptError("fact source differs from admission")
        group = _text(raw["handoff_id"])
        if group not in expected or group in completed:
            raise WorkTranscriptError("unknown or already completed handoff")
        if kind == REFERENCE_KIND:
            record_id, digest = _text(raw["record_id"]), _text(raw["branch_digest"])
            if (
                record_id in groups[group]
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise WorkTranscriptError("duplicate reference or invalid digest")
            groups[group][record_id] = digest
            references.append(WorkTranscriptReference(group, record_id, digest))
        else:
            ids = raw["record_ids"]
            if (
                type(ids) is not list
                or not ids
                or any(type(i) is not str for i in ids)
                or len(set(ids)) != len(ids)
                or set(ids) != set(groups[group])
            ):
                raise WorkTranscriptError("handoff completion differs from references")
            completed.add(group)
    return WorkTranscriptHandoffs(
        tuple(references),
        tuple(sorted(expected - completed)),
        _text(contract["binding_id"]),
        _text(contract["store_identity"]),
        _text(contract["conversation_id"]),
        _deadline(contract["retained_until"]),
    )


async def resolve_work_transcript(
    recording: WorkRecording,
    entries: Sequence[EventLogEntry],
    *,
    source: WorkTranscriptSource,
) -> WorkTranscriptResolution:
    projection = project_work_transcript(recording, entries)
    if projection is None:
        raise WorkTranscriptError("Work has no Transcript source contract")
    if (
        projection.binding_id != source.binding_id
        or projection.store_identity != source.store_identity
        or projection.conversation_id != source.conversation_id
        or projection.retained_until != source.retained_until
    ):
        raise WorkTranscriptError("reader binding differs from frozen Product contract")
    batch = await source.read(tuple(ref.record_id for ref in projection.references))
    actual = {item.record.record_id: item for item in batch.records}
    for ref in projection.references:
        if actual[ref.record_id].branch_digest != ref.branch_digest:
            raise WorkTranscriptError("source branch digest changed")
    return WorkTranscriptResolution(
        projection, batch.records, batch.bytes_read, batch.ancestors_hashed
    )


__all__ = [
    "WorkTranscriptError",
    "WorkTranscriptExpired",
    "WorkTranscriptHandoffs",
    "WorkTranscriptReference",
    "WorkTranscriptResolution",
    "WorkTranscriptSource",
    "project_work_transcript",
    "resolve_work_transcript",
]
