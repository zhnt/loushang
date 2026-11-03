"""Typed Supervisor epoch and retry state at a V2 Worker history boundary.

This candidate preserves per-key claim state and non-retired attempts. Product
closure, durable cutover, and source deletion remain separate authorities.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.journal import (
    _TRANSITIONS,
    WorkerAttemptRecordV1,
    _validate_history,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_supervisor_journal import _MAX_BYTES, _MAX_RECORDS

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerSupervisorKeyBaseV2:
    supervisor_key: str
    last_record: WorkerAttemptRecordV1
    last_clean_stop_revision: int
    claims_since_stop: int

    def __post_init__(self) -> None:
        if (
            type(self.supervisor_key) is not str
            or _DIGEST.fullmatch(self.supervisor_key) is None
            or type(self.last_record) is not WorkerAttemptRecordV1
            or self.last_record.supervisor_key != self.supervisor_key
            or type(self.last_clean_stop_revision) is not int
            or not 0
            <= self.last_clean_stop_revision
            <= self.last_record.record_revision
            or type(self.claims_since_stop) is not int
            or self.claims_since_stop
            != (
                0
                if self.last_record.phase == "stopped"
                else self.last_record.restart_ordinal
            )
            or (
                self.last_record.phase == "stopped"
                and self.last_clean_stop_revision != self.last_record.record_revision
            )
        ):
            raise ValueError("Coding Worker Supervisor V2 key state is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "claimsSinceStop": self.claims_since_stop,
            "lastCleanStopRevision": self.last_clean_stop_revision,
            "lastRecord": self.last_record.to_dict(),
            "supervisorKey": self.supervisor_key,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerSupervisorKeyBaseV2:
        if type(value) is not dict or set(value) != {
            "claimsSinceStop",
            "lastCleanStopRevision",
            "lastRecord",
            "supervisorKey",
        }:
            raise ValueError("Coding Worker Supervisor V2 key fields changed")
        return cls(
            supervisor_key=value["supervisorKey"],
            last_record=WorkerAttemptRecordV1.from_dict(value["lastRecord"]),
            last_clean_stop_revision=value["lastCleanStopRevision"],
            claims_since_stop=value["claimsSinceStop"],
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerSupervisorSemanticBaseV2:
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    current_attempts: tuple[WorkerAttemptRecordV1, ...]
    key_states: tuple[CodingWorkerSupervisorKeyBaseV2, ...]
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 0
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < self.first_retained_generation
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.current_attempts) is not tuple
            or any(
                type(item) is not WorkerAttemptRecordV1
                or item.record_revision > self.cutoff_revision
                for item in self.current_attempts
            )
            or tuple(item.attempt_id for item in self.current_attempts)
            != tuple(sorted({item.attempt_id for item in self.current_attempts}))
            or type(self.key_states) is not tuple
            or any(
                type(item) is not CodingWorkerSupervisorKeyBaseV2
                or item.last_record.record_revision > self.cutoff_revision
                for item in self.key_states
            )
            or tuple(item.supervisor_key for item in self.key_states)
            != tuple(sorted({item.supervisor_key for item in self.key_states}))
            or type(self.retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.retired_attempt_ids
            )
            or self.retired_attempt_ids != tuple(sorted(set(self.retired_attempt_ids)))
            or any(
                item.attempt_id in self.retired_attempt_ids
                for item in self.current_attempts
            )
            or type(self.version) is not int
            or self.version != 2
            or (
                self.first_retained_generation == 0
                and (
                    self.cutoff_revision != 0
                    or self.current_attempts
                    or self.key_states
                    or self.retired_attempt_ids
                    or self.retired_sealed_digest
                    != sha256(canonical_json_bytes([])).hexdigest()
                )
            )
        ):
            raise ValueError("Coding Worker Supervisor V2 semantic base is invalid")
        current = {item.attempt_id: item for item in self.current_attempts}
        by_key = {item.supervisor_key: item for item in self.key_states}
        if any(
            item.supervisor_key not in by_key
            or item.supervisor_epoch
            > by_key[item.supervisor_key].last_record.supervisor_epoch
            for item in self.current_attempts
        ) or any(
            (state.last_record.attempt_id in self.retired_attempt_ids)
            != (state.last_record.attempt_id not in current)
            or (
                state.last_record.attempt_id in current
                and current[state.last_record.attempt_id] != state.last_record
            )
            or (
                state.last_record.attempt_id in self.retired_attempt_ids
                and not state.last_record.process_settled
            )
            for state in self.key_states
        ):
            raise ValueError("Coding Worker Supervisor V2 semantic base is invalid")

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {
                "currentAttempts": [item.to_dict() for item in self.current_attempts],
                "cutoffRevision": self.cutoff_revision,
                "firstRetainedGeneration": self.first_retained_generation,
                "keyStates": [item.to_dict() for item in self.key_states],
                "retiredAttemptIds": list(self.retired_attempt_ids),
                "retiredSealedDigest": self.retired_sealed_digest,
                "scopeId": self.scope_id,
                "version": self.version,
            }
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker Supervisor V2 base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerSupervisorSemanticBaseV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker Supervisor V2 base bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "currentAttempts",
                    "cutoffRevision",
                    "firstRetainedGeneration",
                    "keyStates",
                    "retiredAttemptIds",
                    "retiredSealedDigest",
                    "scopeId",
                    "version",
                }
                or type(value["currentAttempts"]) is not list
                or type(value["keyStates"]) is not list
                or type(value["retiredAttemptIds"]) is not list
            ):
                raise ValueError("Coding Worker Supervisor V2 base fields changed")
            base = cls(
                scope_id=value["scopeId"],
                first_retained_generation=value["firstRetainedGeneration"],
                cutoff_revision=value["cutoffRevision"],
                retired_sealed_digest=value["retiredSealedDigest"],
                current_attempts=tuple(
                    WorkerAttemptRecordV1.from_dict(item)
                    for item in value["currentAttempts"]
                ),
                key_states=tuple(
                    CodingWorkerSupervisorKeyBaseV2.from_dict(item)
                    for item in value["keyStates"]
                ),
                retired_attempt_ids=tuple(value["retiredAttemptIds"]),
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError("Coding Worker Supervisor V2 base encoding changed")
            return base
        except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker Supervisor V2 base bytes are invalid"
            ) from exc

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
        retired_attempt_ids: tuple[str, ...],
    ) -> CodingWorkerSupervisorSemanticBaseV2:
        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker Supervisor V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-supervisor"
            or type(first_retained_generation) is not int
            or not 0 <= first_retained_generation <= manifest.active_generation
            or (
                first_retained_generation == 0
                and (manifest.active_generation != 0 or history.active_raw)
            )
            or len(history.segments) != manifest.active_generation + 1
            or type(retired_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in retired_attempt_ids
            )
            or retired_attempt_ids != tuple(sorted(set(retired_attempt_ids)))
        ):
            raise ValueError("Coding Worker Supervisor V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        records: list[WorkerAttemptRecordV1] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker Supervisor V2 source changed")
            records.extend(
                _parse_supervisor_segment(raw, first_revision=len(records) + 1)
            )
            if len(records) != seal.last_revision:
                raise ValueError("Coding Worker Supervisor V2 source revision changed")
        try:
            _validate_history(tuple(records))
        except ValueError as exc:
            raise ValueError("Coding Worker Supervisor V2 source is invalid") from exc
        latest_attempts: dict[str, WorkerAttemptRecordV1] = {}
        latest_keys: dict[str, WorkerAttemptRecordV1] = {}
        last_stops: dict[str, int] = {}
        for record in records:
            latest_attempts[record.attempt_id] = record
            latest_keys[record.supervisor_key] = record
            if record.phase == "stopped":
                last_stops[record.supervisor_key] = record.record_revision
        if any(
            attempt_id not in latest_attempts
            or not latest_attempts[attempt_id].process_settled
            for attempt_id in retired_attempt_ids
        ):
            raise ValueError(
                "Coding Worker Supervisor V2 retired attempt is not settled"
            )
        return cls(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=0 if not retired else retired[-1].last_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            current_attempts=tuple(
                latest_attempts[key]
                for key in sorted(latest_attempts)
                if key not in retired_attempt_ids
            ),
            key_states=tuple(
                CodingWorkerSupervisorKeyBaseV2(
                    supervisor_key=key,
                    last_record=latest_keys[key],
                    last_clean_stop_revision=last_stops.get(key, 0),
                    claims_since_stop=(
                        0
                        if latest_keys[key].phase == "stopped"
                        else latest_keys[key].restart_ordinal
                    ),
                )
                for key in sorted(latest_keys)
            ),
            retired_attempt_ids=retired_attempt_ids,
        )

    def replay_retained(
        self, segments: tuple[bytes, ...]
    ) -> CodingWorkerSupervisorReplayV2:
        if type(segments) is not tuple or not segments:
            raise ValueError(
                "Coding Worker Supervisor V2 retained segments are invalid"
            )
        revision = self.cutoff_revision
        attempts = {item.attempt_id: item for item in self.current_attempts}
        keys = {item.supervisor_key: item for item in self.key_states}
        retired = frozenset(self.retired_attempt_ids)
        for raw in segments:
            records = _parse_supervisor_segment(raw, first_revision=revision + 1)
            for record in records:
                if record.attempt_id in retired:
                    raise ValueError("Coding Worker Supervisor V2 attempt was retired")
                previous = attempts.get(record.attempt_id)
                key_state = keys.get(record.supervisor_key)
                if previous is None:
                    prior = None if key_state is None else key_state.last_record
                    if (
                        record.phase != "claimed"
                        or record.prior_attempt_revision != 0
                        or (
                            prior is None
                            and (
                                record.supervisor_epoch != 1
                                or record.restart_ordinal != 1
                            )
                        )
                        or (
                            prior is not None
                            and (
                                not prior.process_settled
                                or record.supervisor_epoch != prior.supervisor_epoch + 1
                                or record.restart_ordinal
                                != (
                                    1
                                    if prior.phase == "stopped"
                                    else prior.restart_ordinal + 1
                                )
                            )
                        )
                    ):
                        raise ValueError("Coding Worker Supervisor V2 claim is invalid")
                elif (
                    record.supervisor_key != previous.supervisor_key
                    or record.identity_fingerprint != previous.identity_fingerprint
                    or record.supervisor_epoch != previous.supervisor_epoch
                    or record.restart_ordinal != previous.restart_ordinal
                    or record.prior_attempt_revision != previous.record_revision
                    or record.phase not in _TRANSITIONS[previous.phase]
                    or (
                        record.phase == "process_settled"
                        and record.failure_code != previous.failure_code
                    )
                ):
                    raise ValueError(
                        "Coding Worker Supervisor V2 transition is invalid"
                    )
                attempts[record.attempt_id] = record
                keys[record.supervisor_key] = CodingWorkerSupervisorKeyBaseV2(
                    supervisor_key=record.supervisor_key,
                    last_record=record,
                    last_clean_stop_revision=(
                        record.record_revision
                        if record.phase == "stopped"
                        else (
                            0
                            if key_state is None
                            else key_state.last_clean_stop_revision
                        )
                    ),
                    claims_since_stop=(
                        0 if record.phase == "stopped" else record.restart_ordinal
                    ),
                )
            revision += len(records)
        return CodingWorkerSupervisorReplayV2(
            last_revision=revision,
            current_attempts=tuple(attempts[key] for key in sorted(attempts)),
            key_states=tuple(keys[key] for key in sorted(keys)),
            retired_attempt_ids=retired,
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerSupervisorReplayV2:
    last_revision: int
    current_attempts: tuple[WorkerAttemptRecordV1, ...]
    key_states: tuple[CodingWorkerSupervisorKeyBaseV2, ...]
    retired_attempt_ids: frozenset[str]


def _parse_supervisor_segment(
    raw: bytes, *, first_revision: int
) -> tuple[WorkerAttemptRecordV1, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        raise ValueError("Coding Worker Supervisor V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_RECORDS:
        raise ValueError("Coding Worker Supervisor V2 segment exceeds capacity")
    records: list[WorkerAttemptRecordV1] = []
    try:
        for revision, line in enumerate(lines, first_revision):
            record = WorkerAttemptRecordV1.from_dict(json.loads(line))
            canonical = (
                json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode(
                    "utf-8"
                )
                + b"\n"
            )
            if record.record_revision != revision or line != canonical:
                raise ValueError("Coding Worker Supervisor V2 segment changed")
            records.append(record)
    except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker Supervisor V2 segment is invalid") from exc
    return tuple(records)


__all__ = [
    "CodingWorkerSupervisorKeyBaseV2",
    "CodingWorkerSupervisorReplayV2",
    "CodingWorkerSupervisorSemanticBaseV2",
]
