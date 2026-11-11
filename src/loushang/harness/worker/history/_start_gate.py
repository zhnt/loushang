"""Start-gate values and retained sequence checks, without process authority."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import ClassVar, Literal, Self, TypeVar, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import CodingWorkerSegmentedHistoryV1
from ..gated_start import WorkerNativeProcessIdentityV1
from ._base_codec import _BASE_ERRORS, _BaseWireMethods, _unchanged

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")

_MAX_EVENTS = 4096

_MAX_BYTES = 32 * 1024 * 1024

_IDENTITY_FIELDS = {
    "bootId",
    "pid",
    "pidNamespaceDevice",
    "pidNamespaceInode",
    "startTicks",
    "userId",
}


def _identity_dict(identity: WorkerNativeProcessIdentityV1) -> dict[str, object]:
    return {
        "bootId": identity.boot_id,
        "pid": identity.pid,
        "pidNamespaceDevice": identity.pid_namespace_device,
        "pidNamespaceInode": identity.pid_namespace_inode,
        "startTicks": identity.start_ticks,
        "userId": identity.user_id,
    }


def _identity_from_dict(value: object) -> WorkerNativeProcessIdentityV1:
    if type(value) is not dict or set(value) != _IDENTITY_FIELDS:
        raise ValueError("Worker gate native identity fields are invalid")
    return WorkerNativeProcessIdentityV1(
        pid=value["pid"],
        start_ticks=value["startTicks"],
        boot_id=value["bootId"],
        user_id=value["userId"],
        pid_namespace_device=value["pidNamespaceDevice"],
        pid_namespace_inode=value["pidNamespaceInode"],
    )


class _StartGateRecordMethods:
    __slots__ = ()

    journal_revision: int
    phase: Literal["intent", "bound"]
    attempt_id: str
    worker_identity_fingerprint: str
    receipt_fingerprint: str
    policy_fingerprint: str
    scope_id: str
    native_closure_digest: str
    identity: WorkerNativeProcessIdentityV1 | None
    record_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or self.phase not in {"intent", "bound"}
            or type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.worker_identity_fingerprint,
                    self.receipt_fingerprint,
                    self.policy_fingerprint,
                    self.native_closure_digest,
                )
            )
            or type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or (self.phase == "intent") != (self.identity is None)
            or (
                self.identity is not None
                and type(self.identity) is not WorkerNativeProcessIdentityV1
            )
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Worker start gate record is invalid")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
        identity: WorkerNativeProcessIdentityV1 | None,
    ) -> Self:
        unsigned = {
            "attemptId": attempt_id,
            "workerIdentityFingerprint": worker_identity_fingerprint,
            "identity": None if identity is None else _identity_dict(identity),
            "journalRevision": journal_revision,
            "nativeClosureDigest": native_closure_digest,
            "phase": phase,
            "policyFingerprint": policy_fingerprint,
            "receiptFingerprint": receipt_fingerprint,
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cast(Callable[..., Self], cls)(
            journal_revision=journal_revision,
            phase=phase,
            attempt_id=attempt_id,
            worker_identity_fingerprint=worker_identity_fingerprint,
            receipt_fingerprint=receipt_fingerprint,
            policy_fingerprint=policy_fingerprint,
            scope_id=scope_id,
            native_closure_digest=native_closure_digest,
            identity=identity,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "workerIdentityFingerprint": self.worker_identity_fingerprint,
            "identity": None
            if self.identity is None
            else _identity_dict(self.identity),
            "journalRevision": self.journal_revision,
            "nativeClosureDigest": self.native_closure_digest,
            "phase": self.phase,
            "policyFingerprint": self.policy_fingerprint,
            "receiptFingerprint": self.receipt_fingerprint,
            "recordVersion": 1,
            "scopeId": self.scope_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if (
            type(value) is not dict
            or set(value)
            != {
                "attemptId",
                "workerIdentityFingerprint",
                "identity",
                "journalRevision",
                "nativeClosureDigest",
                "phase",
                "policyFingerprint",
                "receiptFingerprint",
                "recordDigest",
                "recordVersion",
                "scopeId",
            }
            or value["recordVersion"] != 1
        ):
            raise ValueError("Worker start gate record fields are invalid")
        identity = value["identity"]
        return cast(Callable[..., Self], cls)(
            journal_revision=value["journalRevision"],
            phase=value["phase"],
            attempt_id=value["attemptId"],
            worker_identity_fingerprint=value["workerIdentityFingerprint"],
            receipt_fingerprint=value["receiptFingerprint"],
            policy_fingerprint=value["policyFingerprint"],
            scope_id=value["scopeId"],
            native_closure_digest=value["nativeClosureDigest"],
            identity=None if identity is None else _identity_from_dict(identity),
            record_digest=value["recordDigest"],
        )


_GateT = TypeVar("_GateT", bound=_StartGateRecordMethods)


def fold_start_gate_records(
    records: tuple[_GateT, ...],
    *,
    initial_latest: Mapping[str, _GateT] | None = None,
    retired_attempt_ids: frozenset[str] = frozenset(),
    scope_id: str | None = None,
) -> dict[str, _GateT]:
    """Validate intent/bound continuity across V1 or a typed V2 boundary."""

    latest = {} if initial_latest is None else dict(initial_latest)
    for record in records:
        if record.attempt_id in retired_attempt_ids or (
            scope_id is not None and record.scope_id != scope_id
        ):
            raise ValueError("Worker gate retired attempt or scope changed")
        previous = latest.get(record.attempt_id)
        if record.phase == "intent":
            if previous is not None:
                raise ValueError("Worker gate attempt repeated")
        elif (
            previous is None
            or previous.phase != "intent"
            or previous.receipt_fingerprint != record.receipt_fingerprint
            or previous.worker_identity_fingerprint
            != record.worker_identity_fingerprint
            or previous.policy_fingerprint != record.policy_fingerprint
            or previous.scope_id != record.scope_id
            or previous.native_closure_digest != record.native_closure_digest
        ):
            raise ValueError("Worker gate binding changed")
        latest[record.attempt_id] = record
    return latest


def parse_start_gate_segment(
    raw: bytes, *, first_revision: int, record_type: type[_GateT]
) -> tuple[_GateT, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        raise ValueError("Coding Worker Start Gate V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_EVENTS:
        raise ValueError("Coding Worker Start Gate V2 segment exceeds capacity")
    records: list[_GateT] = []
    try:
        for revision, line in enumerate(lines, first_revision):
            record = record_type.from_dict(json.loads(line))
            if (
                record.journal_revision != revision
                or line != canonical_json_bytes(record.to_dict()) + b"\n"
            ):
                raise ValueError("Coding Worker Start Gate V2 segment changed")
            records.append(record)
    except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker Start Gate V2 segment is invalid") from exc
    return tuple(records)


class _StartGateReplayFields:
    __slots__ = ()

    last_revision: int
    current_records: tuple[_StartGateRecordMethods, ...]
    retired_attempt_ids: frozenset[str]


class _StartGateBaseMethods(_BaseWireMethods):
    __slots__ = ()

    _wire_label = "Coding Worker Start Gate V2 base"
    _wire_lists = ("currentRecords", "retiredAttemptIds")
    _wire_errors = (*_BASE_ERRORS, RecursionError)

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "current_records",
                encoder=lambda xs: [x.to_dict() for x in xs],
                decoder=lambda xs: tuple(cls._record_type.from_dict(x) for x in xs),
            ),
            RecordField("retired_attempt_ids", encoder=list, decoder=tuple),
        )

    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    current_records: tuple[_StartGateRecordMethods, ...]
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    _record_type: ClassVar[type[_StartGateRecordMethods]]
    _replay_type: ClassVar[type[_StartGateReplayFields]]

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 1
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < self.first_retained_generation
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.current_records) is not tuple
            or any(
                type(item) is not self._record_type
                or item.journal_revision > self.cutoff_revision
                for item in self.current_records
            )
            or tuple(item.attempt_id for item in self.current_records)
            != tuple(sorted({item.attempt_id for item in self.current_records}))
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or any(
                item.attempt_id in self.retired_attempt_ids
                for item in self.current_records
            )
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker Start Gate V2 semantic base is invalid")

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
        retired_attempt_ids: tuple[str, ...],
    ) -> Self:
        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker Start Gate V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-start-gates"
            or type(first_retained_generation) is not int
            or not 1 <= first_retained_generation <= manifest.active_generation
            or len(history.segments) != manifest.active_generation + 1
            or type(retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in retired_attempt_ids
            )
            or retired_attempt_ids != tuple(sorted(set(retired_attempt_ids)))
        ):
            raise ValueError("Coding Worker Start Gate V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        records: list[_StartGateRecordMethods] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker Start Gate V2 source changed")
            records.extend(
                parse_start_gate_segment(
                    raw, first_revision=len(records) + 1, record_type=cls._record_type
                )
            )
            if len(records) != seal.last_revision:
                raise ValueError("Coding Worker Start Gate V2 source revision changed")
        try:
            latest = fold_start_gate_records(tuple(records))
        except ValueError as exc:
            raise ValueError("Coding Worker Start Gate V2 source is invalid") from exc
        return cast(Callable[..., Self], cls)(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=retired[-1].last_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            current_records=tuple(
                latest[key] for key in sorted(latest) if key not in retired_attempt_ids
            ),
            retired_attempt_ids=retired_attempt_ids,
        )

    def replay_retained(self, segments: tuple[bytes, ...]) -> _StartGateReplayFields:
        if type(segments) is not tuple or not segments:
            raise ValueError(
                "Coding Worker Start Gate V2 retained segments are invalid"
            )
        revision = self.cutoff_revision
        records: list[_StartGateRecordMethods] = []
        for raw in segments:
            segment = parse_start_gate_segment(
                raw, first_revision=revision + 1, record_type=self._record_type
            )
            records.extend(segment)
            revision += len(segment)
        try:
            latest = fold_start_gate_records(
                tuple(records),
                initial_latest={item.attempt_id: item for item in self.current_records},
                retired_attempt_ids=frozenset(self.retired_attempt_ids),
            )
        except ValueError as exc:
            raise ValueError(
                "Coding Worker Start Gate V2 retained replay is invalid"
            ) from exc
        return cast(Callable[..., _StartGateReplayFields], self._replay_type)(
            last_revision=revision,
            current_records=tuple(latest[key] for key in sorted(latest)),
            retired_attempt_ids=frozenset(self.retired_attempt_ids),
        )
