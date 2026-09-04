"""Durable exclusive-epoch journal for supervised local Worker attempts."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)

from .contracts import WorkerLaunchIdentityV1

WORKER_ATTEMPT_RECORD_VERSION = 1
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")

WorkerAttemptPhase = Literal[
    "claimed",
    "launching",
    "handshaking",
    "healthy",
    "draining",
    "stopped",
    "failed",
    "fenced",
]

_TERMINAL_PHASES = frozenset({"stopped", "failed", "fenced"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "claimed": frozenset({"launching", "failed", "fenced"}),
    "launching": frozenset({"handshaking", "failed", "fenced"}),
    "handshaking": frozenset({"healthy", "failed", "fenced"}),
    "healthy": frozenset({"draining", "failed", "fenced"}),
    "draining": frozenset({"stopped", "failed", "fenced"}),
    "stopped": frozenset(),
    "failed": frozenset(),
    "fenced": frozenset(),
}


class WorkerSupervisorJournalError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class WorkerAttemptRecordV1:
    supervisor_key: str
    identity_fingerprint: str
    attempt_id: str
    supervisor_epoch: int
    phase: WorkerAttemptPhase
    record_revision: int
    prior_attempt_revision: int
    restart_ordinal: int
    failure_code: str | None = None
    record_version: int = WORKER_ATTEMPT_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.supervisor_key, name="Worker supervisor key")
        _require_sha256(
            self.identity_fingerprint,
            name="Worker identity fingerprint",
        )
        _require_hex(self.attempt_id, length=32, name="Worker attempt id")
        _require_positive_integer(self.supervisor_epoch, name="supervisor epoch")
        if self.phase not in _TRANSITIONS:
            raise ValueError("Unsupported Worker attempt phase")
        _require_positive_integer(self.record_revision, name="record revision")
        _require_nonnegative_integer(
            self.prior_attempt_revision,
            name="prior attempt revision",
        )
        _require_positive_integer(self.restart_ordinal, name="restart ordinal")
        if self.failure_code is not None:
            _require_identifier(self.failure_code, name="Worker failure code")
        if self.phase in {"failed", "fenced"} and self.failure_code is None:
            raise ValueError("Failed/fenced Worker attempts require a failure code")
        if self.phase not in {"failed", "fenced"} and self.failure_code is not None:
            raise ValueError("Healthy Worker phases cannot carry a failure code")
        if (
            type(self.record_version) is not int
            or self.record_version != WORKER_ATTEMPT_RECORD_VERSION
        ):
            raise ValueError("Unsupported Worker attempt record version")

    @property
    def terminal(self) -> bool:
        return self.phase in _TERMINAL_PHASES

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "failureCode": self.failure_code,
            "identityFingerprint": self.identity_fingerprint,
            "phase": self.phase,
            "priorAttemptRevision": self.prior_attempt_revision,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "restartOrdinal": self.restart_ordinal,
            "supervisorEpoch": self.supervisor_epoch,
            "supervisorKey": self.supervisor_key,
        }

    @classmethod
    def from_dict(cls, value: object) -> WorkerAttemptRecordV1:
        if not isinstance(value, dict) or set(value) != {
            "attemptId",
            "failureCode",
            "identityFingerprint",
            "phase",
            "priorAttemptRevision",
            "recordRevision",
            "recordVersion",
            "restartOrdinal",
            "supervisorEpoch",
            "supervisorKey",
        }:
            raise ValueError("Worker attempt record fields are invalid")
        return cls(
            supervisor_key=_require_string(
                value["supervisorKey"], name="Worker supervisor key"
            ),
            identity_fingerprint=_require_string(
                value["identityFingerprint"],
                name="Worker identity fingerprint",
            ),
            attempt_id=_require_string(value["attemptId"], name="Worker attempt id"),
            supervisor_epoch=_require_integer(
                value["supervisorEpoch"], name="supervisor epoch"
            ),
            phase=cast(WorkerAttemptPhase, value["phase"]),
            record_revision=_require_integer(
                value["recordRevision"], name="record revision"
            ),
            prior_attempt_revision=_require_integer(
                value["priorAttemptRevision"], name="prior attempt revision"
            ),
            restart_ordinal=_require_integer(
                value["restartOrdinal"], name="restart ordinal"
            ),
            failure_code=(
                None
                if value["failureCode"] is None
                else _require_string(value["failureCode"], name="Worker failure code")
            ),
            record_version=_require_integer(
                value["recordVersion"], name="record version"
            ),
        )


def _encode_record(record: WorkerAttemptRecordV1) -> dict[str, object]:
    if not isinstance(record, WorkerAttemptRecordV1):
        raise TypeError("Worker attempt journal requires typed records")
    return record.to_dict()


def _decode_record(value: object) -> WorkerAttemptRecordV1:
    try:
        return WorkerAttemptRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Worker attempt journal record is invalid",
            code="invalid_worker_attempt_record",
        ) from exc


WORKER_ATTEMPT_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class WorkerSupervisorJournal:
    """One durable CAS authority for attempts sharing a Product/domain key."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def claim(
        self,
        identity: WorkerLaunchIdentityV1,
        *,
        max_attempts: int,
    ) -> WorkerAttemptRecordV1:
        if not isinstance(identity, WorkerLaunchIdentityV1):
            raise TypeError("Worker supervisor claim requires a launch identity")
        _require_positive_integer(max_attempts, name="Worker restart budget")
        key = _supervisor_key(identity)
        with self._exclusive():
            records = self._load_unlocked()
            prior_attempt = _latest_for_attempt(records, identity.attempt_id)
            if prior_attempt is not None:
                if (
                    prior_attempt.supervisor_key != key
                    or prior_attempt.identity_fingerprint != identity.fingerprint
                ):
                    raise self._error(
                        "Worker attempt identity was reused for changed input",
                        code="worker_attempt_identity_conflict",
                    )
                raise self._error(
                    "Worker attempt id was already durably claimed",
                    code="worker_attempt_already_claimed",
                )
            current = _latest_for_key(records, key)
            if current is not None and not current.terminal:
                raise self._error(
                    "Prior Worker attempt is not durably settled",
                    code="worker_prior_attempt_unsettled",
                )
            expected_epoch = 1 if current is None else current.supervisor_epoch + 1
            if identity.supervisor_epoch != expected_epoch:
                raise self._error(
                    "Worker supervisor epoch is stale or non-contiguous",
                    code="worker_supervisor_epoch_stale",
                )
            claimed = tuple(
                record
                for record in records
                if record.supervisor_key == key and record.phase == "claimed"
            )
            if len(claimed) >= max_attempts:
                raise self._error(
                    "Worker restart budget is exhausted",
                    code="worker_restart_budget_exhausted",
                )
            record = WorkerAttemptRecordV1(
                supervisor_key=key,
                identity_fingerprint=identity.fingerprint,
                attempt_id=identity.attempt_id,
                supervisor_epoch=identity.supervisor_epoch,
                phase="claimed",
                record_revision=len(records) + 1,
                prior_attempt_revision=0,
                restart_ordinal=len(claimed) + 1,
            )
            self._append_unlocked(record)
            return record

    def transition(
        self,
        attempt_id: str,
        *,
        expected_phase: WorkerAttemptPhase,
        next_phase: WorkerAttemptPhase,
        expected_record_revision: int,
        expected_supervisor_epoch: int,
        failure_code: str | None = None,
    ) -> WorkerAttemptRecordV1:
        if next_phase not in _TRANSITIONS.get(expected_phase, frozenset()):
            raise self._error(
                "Worker attempt phase transition is invalid",
                code="worker_attempt_phase_invalid",
            )
        with self._exclusive():
            records = self._load_unlocked()
            current = _latest_for_attempt(records, attempt_id)
            if current is None:
                raise self._error(
                    "Worker attempt does not exist",
                    code="worker_attempt_not_found",
                )
            if (
                current.phase != expected_phase
                or current.record_revision != expected_record_revision
                or current.supervisor_epoch != expected_supervisor_epoch
            ):
                raise self._error(
                    "Worker attempt compare-and-swap failed",
                    code="worker_attempt_cas_conflict",
                )
            record = WorkerAttemptRecordV1(
                supervisor_key=current.supervisor_key,
                identity_fingerprint=current.identity_fingerprint,
                attempt_id=current.attempt_id,
                supervisor_epoch=current.supervisor_epoch,
                phase=next_phase,
                record_revision=len(records) + 1,
                prior_attempt_revision=current.record_revision,
                restart_ordinal=current.restart_ordinal,
                failure_code=failure_code,
            )
            self._append_unlocked(record)
            return record

    def status(self, attempt_id: str) -> WorkerAttemptRecordV1 | None:
        with self._exclusive():
            return _latest_for_attempt(self._load_unlocked(), attempt_id)

    def incomplete(self) -> tuple[WorkerAttemptRecordV1, ...]:
        with self._exclusive():
            current_by_key: dict[str, WorkerAttemptRecordV1] = {}
            for record in self._load_unlocked():
                current_by_key[record.supervisor_key] = record
            return tuple(
                sorted(
                    (
                        record
                        for record in current_by_key.values()
                        if not record.terminal
                    ),
                    key=lambda record: record.supervisor_key,
                )
            )

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _append_unlocked(self, record: WorkerAttemptRecordV1) -> None:
        append_jsonl_record(
            self._path,
            record,
            record_codec=WORKER_ATTEMPT_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[WorkerAttemptRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, WorkerAttemptRecordV1] = load_jsonl(
                self._path,
                record_codec=WORKER_ATTEMPT_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            _assert_no_duplicate_json_keys(self._path)
            if any(
                record.record_revision != ordinal
                for ordinal, record in enumerate(records, start=1)
            ):
                raise ValueError("Worker journal revisions are not contiguous")
            _validate_history(records)
            return records
        except (
            JournalCodecError,
            JournalFileError,
            OSError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise self._error(
                "Worker supervisor journal is corrupt",
                code="worker_supervisor_journal_corrupt",
            ) from exc

    def _error(self, message: str, *, code: str) -> WorkerSupervisorJournalError:
        return WorkerSupervisorJournalError(message, code=code, path=self._path)


def _supervisor_key(identity: WorkerLaunchIdentityV1) -> str:
    body = json.dumps(
        {
            "contributionId": identity.contribution_id,
            "domain": "loushang.worker-supervisor-key/v1",
            "ownerGeneration": identity.owner_generation,
            "ownerId": identity.owner_id,
            "pluginId": identity.plugin_id,
            "pluginRevisionDigest": identity.plugin_revision_digest,
            "productId": identity.product_id,
            "scopeId": identity.scope_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(body).hexdigest()


def _latest_for_key(
    records: tuple[WorkerAttemptRecordV1, ...],
    key: str,
) -> WorkerAttemptRecordV1 | None:
    return next(
        (record for record in reversed(records) if record.supervisor_key == key),
        None,
    )


def _latest_for_attempt(
    records: tuple[WorkerAttemptRecordV1, ...],
    attempt_id: str,
) -> WorkerAttemptRecordV1 | None:
    return next(
        (record for record in reversed(records) if record.attempt_id == attempt_id),
        None,
    )


def _validate_history(records: tuple[WorkerAttemptRecordV1, ...]) -> None:
    current: dict[str, WorkerAttemptRecordV1] = {}
    current_by_key: dict[str, WorkerAttemptRecordV1] = {}
    for record in records:
        previous = current.get(record.attempt_id)
        if previous is None:
            if record.phase != "claimed" or record.prior_attempt_revision != 0:
                raise ValueError("Worker attempt history does not begin at claimed")
            prior_key_attempt = current_by_key.get(record.supervisor_key)
            if prior_key_attempt is None:
                if record.supervisor_epoch != 1 or record.restart_ordinal != 1:
                    raise ValueError(
                        "Worker attempt history does not begin at epoch one"
                    )
            elif (
                not prior_key_attempt.terminal
                or record.supervisor_epoch != prior_key_attempt.supervisor_epoch + 1
                or record.restart_ordinal != prior_key_attempt.restart_ordinal + 1
            ):
                raise ValueError("Worker attempt history crosses an invalid epoch")
        elif (
            record.supervisor_key != previous.supervisor_key
            or record.identity_fingerprint != previous.identity_fingerprint
            or record.supervisor_epoch != previous.supervisor_epoch
            or record.restart_ordinal != previous.restart_ordinal
            or record.prior_attempt_revision != previous.record_revision
            or record.phase not in _TRANSITIONS[previous.phase]
        ):
            raise ValueError("Worker attempt history transition is invalid")
        current[record.attempt_id] = record
        current_by_key[record.supervisor_key] = record


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            seen: set[str] = set()
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in seen:
                    raise ValueError("Worker journal contains a duplicate JSON key")
                seen.add(key)
                result[key] = value
            return result

        json.loads(line, object_pairs_hook=unique)


def _require_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _require_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _require_nonempty(value: object, *, name: str) -> str:
    result = _require_string(value, name=name).strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _require_identifier(value: object, *, name: str) -> str:
    result = _require_nonempty(value, name=name)
    if result != value or len(result) > 128 or not _IDENTIFIER.fullmatch(result):
        raise ValueError(f"{name} must be a bounded identifier")
    return result


def _require_hex(value: object, *, length: int, name: str) -> str:
    result = _require_nonempty(value, name=name)
    if len(result) != length or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{name} must be lowercase hexadecimal")
    return result


def _require_sha256(value: object, *, name: str) -> str:
    return _require_hex(value, length=64, name=name)


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    result = _require_integer(value, name=name)
    if result < 0:
        raise ValueError(f"{name} must not be negative")
    return result


def _require_positive_integer(value: object, *, name: str) -> int:
    result = _require_nonnegative_integer(value, name=name)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


__all__ = [
    "WORKER_ATTEMPT_JOURNAL_CODEC",
    "WORKER_ATTEMPT_RECORD_VERSION",
    "WorkerAttemptPhase",
    "WorkerAttemptRecordV1",
    "WorkerSupervisorJournal",
    "WorkerSupervisorJournalError",
]
