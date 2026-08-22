from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
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
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentSnapshotV1,
    PluginRetirementIntentV1,
    PluginRetirementRecordCodecError,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec

PLUGIN_OWNER_RETIREMENT_TARGET_VERSION = 1
PLUGIN_OWNER_RETIREMENT_PLAN_VERSION = 1
PLUGIN_OWNER_RETIREMENT_OUTCOME_VERSION = 1
PLUGIN_RETIREMENT_SET_EVENT_VERSION = 1

PluginOwnerRetirementDisposition = Literal[
    "succeeded",
    "retryable_failure",
    "terminal_failure",
]
PluginRetirementSetEventKind = Literal[
    "opened",
    "plan_committed",
    "outcome_recorded",
]
PluginRetirementSetState = Literal[
    "collecting",
    "retiring",
    "succeeded",
    "retryable_failure",
    "terminal_failure",
]

_OUTCOME_DISPOSITIONS = frozenset(
    {"succeeded", "retryable_failure", "terminal_failure"}
)
_RESULT_CODE_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-:"
)


class PluginRetirementSetRecordCodecError(JournalCodecError):
    """Strict owner-retirement aggregate record decoding failure."""


class PluginRetirementSetError(RuntimeError):
    """Fail-closed owner-retirement aggregate error with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class PluginRetirementIntentSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginRetirementIntentSnapshotV1: ...


@dataclass(frozen=True, slots=True)
class PluginOwnerRetirementTargetV1:
    target_id: str
    owner_reference: str
    owner_generation_reference: str
    retirement_handle: str
    contribution_ids: tuple[str, ...]
    target_version: int = PLUGIN_OWNER_RETIREMENT_TARGET_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.target_id, name="owner retirement target id")
        for value, name in (
            (self.owner_reference, "owner reference"),
            (self.owner_generation_reference, "owner generation reference"),
            (self.retirement_handle, "owner retirement handle"),
        ):
            _require_nonempty(value, name=name)
        _require_sorted_unique_nonempty_strings(
            self.contribution_ids,
            name="owner retirement contribution ids",
            allow_empty=False,
        )
        _require_version(
            self.target_version,
            expected=PLUGIN_OWNER_RETIREMENT_TARGET_VERSION,
        )
        if self.target_id != owner_retirement_target_id(
            owner_reference=self.owner_reference,
            owner_generation_reference=self.owner_generation_reference,
            retirement_handle=self.retirement_handle,
            contribution_ids=self.contribution_ids,
        ):
            raise ValueError("Owner retirement target id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        owner_reference: str,
        owner_generation_reference: str,
        retirement_handle: str,
        contribution_ids: tuple[str, ...],
    ) -> PluginOwnerRetirementTargetV1:
        return cls(
            target_id=owner_retirement_target_id(
                owner_reference=owner_reference,
                owner_generation_reference=owner_generation_reference,
                retirement_handle=retirement_handle,
                contribution_ids=contribution_ids,
            ),
            owner_reference=owner_reference,
            owner_generation_reference=owner_generation_reference,
            retirement_handle=retirement_handle,
            contribution_ids=contribution_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contributionIds": list(self.contribution_ids),
            "ownerGenerationReference": self.owner_generation_reference,
            "ownerReference": self.owner_reference,
            "retirementHandle": self.retirement_handle,
            "targetId": self.target_id,
            "targetVersion": self.target_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginOwnerRetirementTargetV1:
        document = _wire_object(value, name="Plugin owner retirement target")
        _wire_exact_fields(
            document,
            keys={
                "contributionIds",
                "ownerGenerationReference",
                "ownerReference",
                "retirementHandle",
                "targetId",
                "targetVersion",
            },
            name="Plugin owner retirement target",
        )
        _wire_version(
            document.get("targetVersion"),
            expected=PLUGIN_OWNER_RETIREMENT_TARGET_VERSION,
        )
        try:
            return cls(
                target_id=_wire_string(document["targetId"], name="target id"),
                owner_reference=_wire_string(
                    document["ownerReference"], name="owner reference"
                ),
                owner_generation_reference=_wire_string(
                    document["ownerGenerationReference"],
                    name="owner generation reference",
                ),
                retirement_handle=_wire_string(
                    document["retirementHandle"], name="retirement handle"
                ),
                contribution_ids=_wire_string_tuple(
                    document["contributionIds"], name="contribution ids"
                ),
                target_version=PLUGIN_OWNER_RETIREMENT_TARGET_VERSION,
            )
        except PluginRetirementSetRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginOwnerRetirementPlanV1:
    plan_id: str
    retirement_id: str
    owner_closure_reference: str
    targets: tuple[PluginOwnerRetirementTargetV1, ...]
    plan_version: int = PLUGIN_OWNER_RETIREMENT_PLAN_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.plan_id, name="owner retirement plan id")
        _require_sha256(self.retirement_id, name="retirement id")
        _require_nonempty(
            self.owner_closure_reference,
            name="owner closure reference",
        )
        if self.targets != tuple(sorted(self.targets, key=lambda item: item.target_id)):
            raise ValueError("Owner retirement targets must be sorted by target id")
        target_ids = tuple(target.target_id for target in self.targets)
        owner_generations = tuple(
            (target.owner_reference, target.owner_generation_reference)
            for target in self.targets
        )
        handles = tuple(target.retirement_handle for target in self.targets)
        contribution_ids = tuple(
            contribution_id
            for target in self.targets
            for contribution_id in target.contribution_ids
        )
        for values, name in (
            (target_ids, "owner retirement target ids"),
            (owner_generations, "owner generation pairs"),
            (handles, "owner retirement handles"),
            (contribution_ids, "owner retirement contribution ids"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        _require_version(
            self.plan_version,
            expected=PLUGIN_OWNER_RETIREMENT_PLAN_VERSION,
        )
        if self.plan_id != owner_retirement_plan_id(
            retirement_id=self.retirement_id,
            owner_closure_reference=self.owner_closure_reference,
            targets=self.targets,
        ):
            raise ValueError("Owner retirement plan id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        retirement_id: str,
        owner_closure_reference: str,
        targets: tuple[PluginOwnerRetirementTargetV1, ...],
    ) -> PluginOwnerRetirementPlanV1:
        return cls(
            plan_id=owner_retirement_plan_id(
                retirement_id=retirement_id,
                owner_closure_reference=owner_closure_reference,
                targets=targets,
            ),
            retirement_id=retirement_id,
            owner_closure_reference=owner_closure_reference,
            targets=targets,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ownerClosureReference": self.owner_closure_reference,
            "planId": self.plan_id,
            "planVersion": self.plan_version,
            "retirementId": self.retirement_id,
            "targets": [target.to_dict() for target in self.targets],
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginOwnerRetirementPlanV1:
        document = _wire_object(value, name="Plugin owner retirement plan")
        _wire_exact_fields(
            document,
            keys={
                "ownerClosureReference",
                "planId",
                "planVersion",
                "retirementId",
                "targets",
            },
            name="Plugin owner retirement plan",
        )
        _wire_version(
            document.get("planVersion"),
            expected=PLUGIN_OWNER_RETIREMENT_PLAN_VERSION,
        )
        try:
            targets_value = document["targets"]
            if not isinstance(targets_value, list):
                raise ValueError("Owner retirement targets must be a JSON array")
            return cls(
                plan_id=_wire_string(document["planId"], name="plan id"),
                retirement_id=_wire_string(
                    document["retirementId"], name="retirement id"
                ),
                owner_closure_reference=_wire_string(
                    document["ownerClosureReference"],
                    name="owner closure reference",
                ),
                targets=tuple(
                    PluginOwnerRetirementTargetV1.from_dict(target)
                    for target in targets_value
                ),
                plan_version=PLUGIN_OWNER_RETIREMENT_PLAN_VERSION,
            )
        except PluginRetirementSetRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginOwnerRetirementOutcomeV1:
    retirement_id: str
    target_id: str
    operation_id: str
    idempotency_key: str
    attempt: int
    disposition: PluginOwnerRetirementDisposition
    result_code: str
    owner_outcome_reference: str
    outcome_version: int = PLUGIN_OWNER_RETIREMENT_OUTCOME_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.retirement_id, name="retirement id")
        _require_sha256(self.target_id, name="owner retirement target id")
        for value, name in (
            (self.operation_id, "owner retirement operation id"),
            (self.idempotency_key, "owner retirement idempotency key"),
            (self.owner_outcome_reference, "owner outcome reference"),
        ):
            _require_nonempty(value, name=name)
        _require_positive_integer(self.attempt, name="owner retirement attempt")
        if self.disposition not in _OUTCOME_DISPOSITIONS:
            raise ValueError("Unsupported owner retirement outcome disposition")
        _require_result_code(self.result_code)
        _require_version(
            self.outcome_version,
            expected=PLUGIN_OWNER_RETIREMENT_OUTCOME_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "disposition": self.disposition,
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "outcomeVersion": self.outcome_version,
            "ownerOutcomeReference": self.owner_outcome_reference,
            "resultCode": self.result_code,
            "retirementId": self.retirement_id,
            "targetId": self.target_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginOwnerRetirementOutcomeV1:
        document = _wire_object(value, name="Plugin owner retirement outcome")
        _wire_exact_fields(
            document,
            keys={
                "attempt",
                "disposition",
                "idempotencyKey",
                "operationId",
                "outcomeVersion",
                "ownerOutcomeReference",
                "resultCode",
                "retirementId",
                "targetId",
            },
            name="Plugin owner retirement outcome",
        )
        _wire_version(
            document.get("outcomeVersion"),
            expected=PLUGIN_OWNER_RETIREMENT_OUTCOME_VERSION,
        )
        try:
            disposition = _wire_string(
                document["disposition"],
                name="owner retirement outcome disposition",
            )
            if disposition not in _OUTCOME_DISPOSITIONS:
                raise ValueError("Unsupported owner retirement outcome disposition")
            return cls(
                retirement_id=_wire_string(
                    document["retirementId"], name="retirement id"
                ),
                target_id=_wire_string(document["targetId"], name="target id"),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                attempt=_wire_integer(document["attempt"], name="attempt"),
                disposition=cast(PluginOwnerRetirementDisposition, disposition),
                result_code=_wire_string(
                    document["resultCode"], name="result code"
                ),
                owner_outcome_reference=_wire_string(
                    document["ownerOutcomeReference"],
                    name="owner outcome reference",
                ),
                outcome_version=PLUGIN_OWNER_RETIREMENT_OUTCOME_VERSION,
            )
        except PluginRetirementSetRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginRetirementSetEventV1:
    journal_revision: int
    event_kind: PluginRetirementSetEventKind
    intent: PluginRetirementIntentV1 | None
    plan: PluginOwnerRetirementPlanV1 | None
    outcome: PluginOwnerRetirementOutcomeV1 | None
    record_version: int = PLUGIN_RETIREMENT_SET_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        if self.event_kind not in {"opened", "plan_committed", "outcome_recorded"}:
            raise ValueError("Unsupported Plugin retirement set event kind")
        _require_version(
            self.record_version,
            expected=PLUGIN_RETIREMENT_SET_EVENT_VERSION,
        )
        expected = {
            "opened": (True, False, False),
            "plan_committed": (False, True, False),
            "outcome_recorded": (False, False, True),
        }[self.event_kind]
        actual = (
            self.intent is not None,
            self.plan is not None,
            self.outcome is not None,
        )
        if actual != expected:
            raise ValueError("Plugin retirement set payload does not match event kind")

    @property
    def retirement_id(self) -> str:
        if self.intent is not None:
            return self.intent.retirement_id
        if self.plan is not None:
            return self.plan.retirement_id
        if self.outcome is None:
            raise AssertionError("Retirement set event payload is missing")
        return self.outcome.retirement_id

    @classmethod
    def opened(
        cls, *, journal_revision: int, intent: PluginRetirementIntentV1
    ) -> PluginRetirementSetEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="opened",
            intent=intent,
            plan=None,
            outcome=None,
        )

    @classmethod
    def plan_committed(
        cls, *, journal_revision: int, plan: PluginOwnerRetirementPlanV1
    ) -> PluginRetirementSetEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="plan_committed",
            intent=None,
            plan=plan,
            outcome=None,
        )

    @classmethod
    def outcome_recorded(
        cls, *, journal_revision: int, outcome: PluginOwnerRetirementOutcomeV1
    ) -> PluginRetirementSetEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="outcome_recorded",
            intent=None,
            plan=None,
            outcome=outcome,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "eventKind": self.event_kind,
            "intent": None if self.intent is None else self.intent.to_dict(),
            "journalRevision": self.journal_revision,
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
            "plan": None if self.plan is None else self.plan.to_dict(),
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginRetirementSetEventV1:
        document = _wire_object(value, name="Plugin retirement set event")
        _wire_exact_fields(
            document,
            keys={
                "eventKind",
                "intent",
                "journalRevision",
                "outcome",
                "plan",
                "recordVersion",
            },
            name="Plugin retirement set event",
        )
        _wire_version(
            document.get("recordVersion"),
            expected=PLUGIN_RETIREMENT_SET_EVENT_VERSION,
        )
        try:
            event_kind = _wire_string(
                document["eventKind"], name="retirement set event kind"
            )
            if event_kind not in {"opened", "plan_committed", "outcome_recorded"}:
                raise ValueError("Unsupported Plugin retirement set event kind")
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                event_kind=cast(PluginRetirementSetEventKind, event_kind),
                intent=(
                    None
                    if document["intent"] is None
                    else PluginRetirementIntentV1.from_dict(document["intent"])
                ),
                plan=(
                    None
                    if document["plan"] is None
                    else PluginOwnerRetirementPlanV1.from_dict(document["plan"])
                ),
                outcome=(
                    None
                    if document["outcome"] is None
                    else PluginOwnerRetirementOutcomeV1.from_dict(
                        document["outcome"]
                    )
                ),
                record_version=PLUGIN_RETIREMENT_SET_EVENT_VERSION,
            )
        except PluginRetirementSetRecordCodecError:
            raise
        except (PluginRetirementRecordCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


PLUGIN_RETIREMENT_SET_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginRetirementSetEventV1.to_dict,
    decoder=PluginRetirementSetEventV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginRetirementSetSnapshotV1:
    intent: PluginRetirementIntentV1
    plan: PluginOwnerRetirementPlanV1 | None
    latest_outcomes: tuple[PluginOwnerRetirementOutcomeV1, ...]
    state: PluginRetirementSetState

    def __post_init__(self) -> None:
        if self.plan is not None and self.plan.retirement_id != self.intent.retirement_id:
            raise ValueError("Retirement set plan does not match intent")
        if self.plan is None and self.latest_outcomes:
            raise ValueError("Retirement set outcomes require a sealed plan")
        if self.latest_outcomes != tuple(
            sorted(self.latest_outcomes, key=lambda outcome: outcome.target_id)
        ):
            raise ValueError("Retirement set outcomes must be sorted by target id")
        if len({outcome.target_id for outcome in self.latest_outcomes}) != len(
            self.latest_outcomes
        ):
            raise ValueError("Retirement set outcomes must be unique by target")
        target_ids = (
            frozenset()
            if self.plan is None
            else frozenset(target.target_id for target in self.plan.targets)
        )
        if any(
            outcome.retirement_id != self.intent.retirement_id
            or outcome.target_id not in target_ids
            for outcome in self.latest_outcomes
        ):
            raise ValueError("Retirement set outcome does not match its plan")
        if self.state != _derive_state(self.plan, self.latest_outcomes):
            raise ValueError("Retirement set state does not match evidence")


@dataclass(frozen=True, slots=True)
class PluginRetirementSetInventorySnapshotV1:
    journal_revision: int
    sets: tuple[PluginRetirementSetSnapshotV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.journal_revision, int)
            or isinstance(self.journal_revision, bool)
            or self.journal_revision < 0
        ):
            raise ValueError("Retirement set journal revision must be non-negative")
        if self.sets != tuple(
            sorted(self.sets, key=lambda item: item.intent.retirement_id)
        ):
            raise ValueError("Retirement sets must be sorted by retirement id")
        if len({item.intent.retirement_id for item in self.sets}) != len(self.sets):
            raise ValueError("Retirement sets must be unique")

    def retirement_set(
        self, retirement_id: str
    ) -> PluginRetirementSetSnapshotV1 | None:
        for item in self.sets:
            if item.intent.retirement_id == retirement_id:
                return item
        return None


@dataclass(slots=True)
class _MutableRetirementSet:
    intent: PluginRetirementIntentV1
    plan: PluginOwnerRetirementPlanV1 | None
    outcomes: list[PluginOwnerRetirementOutcomeV1]
    latest_by_target: dict[str, PluginOwnerRetirementOutcomeV1]


@dataclass(slots=True)
class _ReplayedRetirementSets:
    events: tuple[PluginRetirementSetEventV1, ...]
    sets: dict[str, _MutableRetirementSet]
    outcome_by_operation: dict[
        tuple[str, str, str], PluginOwnerRetirementOutcomeV1
    ]
    outcome_by_idempotency: dict[
        tuple[str, str, str], PluginOwnerRetirementOutcomeV1
    ]


class PluginRetirementSetLedger:
    """Durable, inert exact-owner retirement result aggregate."""

    def __init__(
        self,
        path: str | Path,
        *,
        retirement_intents: PluginRetirementIntentSourcePort,
    ) -> None:
        self._path = Path(path)
        self._retirement_intents = retirement_intents
        if self._path.resolve() == retirement_intents.path.resolve():
            raise ValueError("Retirement intent and set journals must be distinct")
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def open_set(
        self, intent: PluginRetirementIntentV1
    ) -> PluginRetirementSetSnapshotV1:
        if not isinstance(intent, PluginRetirementIntentV1):
            raise TypeError("Plugin retirement intent is required")
        source = self._source_intents().get(intent.retirement_id)
        if source != intent:
            raise _corrupt(
                self._path,
                "Retirement set intent is not present in the intent journal",
            )
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            existing = replayed.sets.get(intent.retirement_id)
            if existing is not None:
                if existing.intent != intent:
                    raise _conflict(self._path, "Retirement set intent was reused")
                return _snapshot_set(existing)
            event = PluginRetirementSetEventV1.opened(
                journal_revision=len(replayed.events) + 1,
                intent=intent,
            )
            self._append_unlocked(event)
            return PluginRetirementSetSnapshotV1(
                intent=intent,
                plan=None,
                latest_outcomes=(),
                state="collecting",
            )

    def commit_plan(
        self,
        plan: PluginOwnerRetirementPlanV1,
    ) -> PluginRetirementSetSnapshotV1:
        if not isinstance(plan, PluginOwnerRetirementPlanV1):
            raise TypeError("Plugin owner retirement plan is required")
        source = self._source_intents().get(plan.retirement_id)
        if source is None:
            raise _corrupt(
                self._path,
                "Retirement plan is not present in the intent journal",
            )
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            current = replayed.sets.get(plan.retirement_id)
            if current is None:
                raise _transition_error(
                    self._path, "Retirement set must be opened before plan commit"
                )
            if current.intent != source:
                raise _corrupt(
                    self._path,
                    "Retirement set contradicts the retirement intent journal",
                )
            if current.plan is not None:
                if current.plan != plan:
                    raise _conflict(self._path, "Retirement plan was replaced")
                return _snapshot_set(current)
            event = PluginRetirementSetEventV1.plan_committed(
                journal_revision=len(replayed.events) + 1,
                plan=plan,
            )
            self._append_unlocked(event)
            return PluginRetirementSetSnapshotV1(
                intent=current.intent,
                plan=plan,
                latest_outcomes=(),
                state="succeeded" if not plan.targets else "retiring",
            )

    def record_outcome(
        self,
        outcome: PluginOwnerRetirementOutcomeV1,
    ) -> PluginRetirementSetSnapshotV1:
        if not isinstance(outcome, PluginOwnerRetirementOutcomeV1):
            raise TypeError("Plugin owner retirement outcome is required")
        source = self._source_intents().get(outcome.retirement_id)
        if source is None:
            raise _corrupt(
                self._path,
                "Retirement outcome is not present in the intent journal",
            )
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            repeated = self._repeat_outcome(replayed, outcome)
            if repeated is not None:
                repeated_set = replayed.sets[repeated.retirement_id]
                if repeated_set.intent != source:
                    raise _corrupt(
                        self._path,
                        "Retirement set contradicts the retirement intent journal",
                    )
                return _snapshot_set(repeated_set)
            current_set = replayed.sets.get(outcome.retirement_id)
            if current_set is None or current_set.plan is None:
                raise _transition_error(
                    self._path,
                    "Owner retirement outcome requires a sealed plan",
                )
            if current_set.intent != source:
                raise _corrupt(
                    self._path,
                    "Retirement set contradicts the retirement intent journal",
                )
            if outcome.target_id not in {
                target.target_id for target in current_set.plan.targets
            }:
                raise _transition_error(
                    self._path,
                    "Owner retirement outcome target is not in the sealed plan",
                )
            previous = current_set.latest_by_target.get(outcome.target_id)
            expected_attempt = 1 if previous is None else previous.attempt + 1
            if outcome.attempt != expected_attempt:
                raise _transition_error(
                    self._path,
                    "Owner retirement outcome attempt is not contiguous",
                )
            if previous is not None and previous.disposition != "retryable_failure":
                raise _transition_error(
                    self._path,
                    "Terminal owner retirement outcome cannot be retried",
                )
            event = PluginRetirementSetEventV1.outcome_recorded(
                journal_revision=len(replayed.events) + 1,
                outcome=outcome,
            )
            self._append_unlocked(event)
            latest = dict(current_set.latest_by_target)
            latest[outcome.target_id] = outcome
            latest_outcomes = tuple(
                sorted(latest.values(), key=lambda item: item.target_id)
            )
            return PluginRetirementSetSnapshotV1(
                intent=current_set.intent,
                plan=current_set.plan,
                latest_outcomes=latest_outcomes,
                state=_derive_state(current_set.plan, latest_outcomes),
            )

    def snapshot(self) -> PluginRetirementSetInventorySnapshotV1:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        self._validate_intent_sources(replayed)
        return PluginRetirementSetInventorySnapshotV1(
            journal_revision=len(replayed.events),
            sets=tuple(
                sorted(
                    (_snapshot_set(item) for item in replayed.sets.values()),
                    key=lambda item: item.intent.retirement_id,
                )
            ),
        )

    def events(self) -> tuple[PluginRetirementSetEventV1, ...]:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        self._validate_intent_sources(replayed)
        return replayed.events

    def _repeat_outcome(
        self,
        replayed: _ReplayedRetirementSets,
        outcome: PluginOwnerRetirementOutcomeV1,
    ) -> PluginOwnerRetirementOutcomeV1 | None:
        idempotency_identity = (
            outcome.retirement_id,
            outcome.target_id,
            outcome.idempotency_key,
        )
        by_idempotency = replayed.outcome_by_idempotency.get(
            idempotency_identity
        )
        if by_idempotency is not None:
            if by_idempotency != outcome:
                raise _conflict(
                    self._path, "Owner retirement idempotency key was reused"
                )
            return by_idempotency
        operation_identity = (
            outcome.retirement_id,
            outcome.target_id,
            outcome.operation_id,
        )
        by_operation = replayed.outcome_by_operation.get(operation_identity)
        if by_operation is not None:
            if by_operation != outcome:
                raise _conflict(
                    self._path, "Owner retirement operation id was reused"
                )
            return by_operation
        return None

    def _load_and_replay_unlocked(self) -> _ReplayedRetirementSets:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginRetirementSetEventV1] = load_jsonl(
                self._path,
                record_codec=PLUGIN_RETIREMENT_SET_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
        except JournalFileError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "invalid_plugin_retirement_set_record",
                    "unsupported_plugin_retirement_set_record_version",
                }
                else "plugin_retirement_set_journal_corrupt"
            )
            raise PluginRetirementSetError(
                "Plugin retirement set journal cannot be decoded",
                code=code,
                path=self._path,
            ) from exc
        return _replay(snapshot.records, path=self._path)

    def _validate_intent_sources(self, replayed: _ReplayedRetirementSets) -> None:
        sources = self._source_intents()
        for retirement_id, current in replayed.sets.items():
            if sources.get(retirement_id) != current.intent:
                raise _corrupt(
                    self._path,
                    "Retirement set contradicts the retirement intent journal",
                )

    def _source_intents(self) -> dict[str, PluginRetirementIntentV1]:
        return {
            intent.retirement_id: intent
            for intent in self._retirement_intents.snapshot().intents
        }

    def _append_unlocked(self, event: PluginRetirementSetEventV1) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_RETIREMENT_SET_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )


def owner_retirement_target_id(
    *,
    owner_reference: str,
    owner_generation_reference: str,
    retirement_handle: str,
    contribution_ids: tuple[str, ...],
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "contributionIds": list(contribution_ids),
            "ownerGenerationReference": owner_generation_reference,
            "ownerReference": owner_reference,
            "retirementHandle": retirement_handle,
        }
    )
    return sha256(b"plugin-owner-retirement-target-v1\0" + payload).hexdigest()


def owner_retirement_plan_id(
    *,
    retirement_id: str,
    owner_closure_reference: str,
    targets: tuple[PluginOwnerRetirementTargetV1, ...],
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "ownerClosureReference": owner_closure_reference,
            "retirementId": retirement_id,
            "targets": [target.to_dict() for target in targets],
        }
    )
    return sha256(b"plugin-owner-retirement-plan-v1\0" + payload).hexdigest()


def _empty_replay() -> _ReplayedRetirementSets:
    return _ReplayedRetirementSets(
        events=(),
        sets={},
        outcome_by_operation={},
        outcome_by_idempotency={},
    )


def _replay(
    events: tuple[PluginRetirementSetEventV1, ...],
    *,
    path: Path,
) -> _ReplayedRetirementSets:
    replayed = _empty_replay()
    for expected_revision, event in enumerate(events, start=1):
        if event.journal_revision != expected_revision:
            raise _corrupt(path, "Retirement set journal revision is not contiguous")
        retirement_id = event.retirement_id
        current = replayed.sets.get(retirement_id)
        if event.event_kind == "opened":
            if event.intent is None:
                raise _corrupt(path, "Retirement set open intent is missing")
            if current is not None:
                raise _corrupt(path, "Retirement set was opened twice")
            replayed.sets[retirement_id] = _MutableRetirementSet(
                intent=event.intent,
                plan=None,
                outcomes=[],
                latest_by_target={},
            )
            continue
        if current is None:
            raise _corrupt(path, "Retirement set event precedes open")
        if event.event_kind == "plan_committed":
            if event.plan is None:
                raise _corrupt(path, "Retirement set plan is missing")
            if current.plan is not None or current.outcomes:
                raise _corrupt(path, "Retirement set plan is not contiguous")
            current.plan = event.plan
            continue
        outcome = event.outcome
        if outcome is None or current.plan is None:
            raise _corrupt(path, "Retirement outcome precedes its plan")
        if outcome.target_id not in {
            target.target_id for target in current.plan.targets
        }:
            raise _corrupt(path, "Retirement outcome target is outside its plan")
        operation_identity = (
            outcome.retirement_id,
            outcome.target_id,
            outcome.operation_id,
        )
        idempotency_identity = (
            outcome.retirement_id,
            outcome.target_id,
            outcome.idempotency_key,
        )
        if operation_identity in replayed.outcome_by_operation:
            raise _corrupt(path, "Owner retirement operation id is duplicated")
        if idempotency_identity in replayed.outcome_by_idempotency:
            raise _corrupt(path, "Owner retirement idempotency key is duplicated")
        previous = current.latest_by_target.get(outcome.target_id)
        expected_attempt = 1 if previous is None else previous.attempt + 1
        if outcome.attempt != expected_attempt:
            raise _corrupt(path, "Owner retirement attempt is not contiguous")
        if previous is not None and previous.disposition != "retryable_failure":
            raise _corrupt(path, "Terminal owner retirement outcome was retried")
        current.outcomes.append(outcome)
        current.latest_by_target[outcome.target_id] = outcome
        replayed.outcome_by_operation[operation_identity] = outcome
        replayed.outcome_by_idempotency[idempotency_identity] = outcome
    replayed.events = events
    return replayed


def _snapshot_set(current: _MutableRetirementSet) -> PluginRetirementSetSnapshotV1:
    latest = tuple(
        sorted(current.latest_by_target.values(), key=lambda item: item.target_id)
    )
    return PluginRetirementSetSnapshotV1(
        intent=current.intent,
        plan=current.plan,
        latest_outcomes=latest,
        state=_derive_state(current.plan, latest),
    )


def _derive_state(
    plan: PluginOwnerRetirementPlanV1 | None,
    latest_outcomes: tuple[PluginOwnerRetirementOutcomeV1, ...],
) -> PluginRetirementSetState:
    if plan is None:
        return "collecting"
    if any(
        outcome.disposition == "terminal_failure" for outcome in latest_outcomes
    ):
        return "terminal_failure"
    if any(
        outcome.disposition == "retryable_failure" for outcome in latest_outcomes
    ):
        return "retryable_failure"
    succeeded = {
        outcome.target_id
        for outcome in latest_outcomes
        if outcome.disposition == "succeeded"
    }
    if succeeded == {target.target_id for target in plan.targets}:
        return "succeeded"
    return "retiring"


def _wire_object(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _invalid_record(str(exc)) from exc


def _wire_exact_fields(
    value: dict[str, object], *, keys: set[str], name: str
) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _invalid_record(
            f"{name} fields do not match; missing={missing!r}, unknown={unknown!r}"
        )


def _wire_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise PluginRetirementSetRecordCodecError(
            "Unsupported Plugin retirement set record version",
            code="unsupported_plugin_retirement_set_record_version",
        )


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return tuple(_wire_string(item, name=name) for item in value)


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_positive_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_sorted_unique_nonempty_strings(
    values: tuple[str, ...], *, name: str, allow_empty: bool
) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{name} must not be empty")
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{name} must contain non-empty strings")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{name} must be sorted and unique")


def _require_result_code(value: str) -> None:
    _require_nonempty(value, name="owner retirement result code")
    if len(value) > 128 or any(
        character not in _RESULT_CODE_CHARACTERS for character in value
    ):
        raise ValueError("Owner retirement result code is not structural")


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin retirement set record version")


def _invalid_record(message: str) -> PluginRetirementSetRecordCodecError:
    return PluginRetirementSetRecordCodecError(
        message,
        code="invalid_plugin_retirement_set_record",
    )


def _conflict(path: Path, message: str) -> PluginRetirementSetError:
    return PluginRetirementSetError(
        message,
        code="plugin_retirement_set_conflict",
        path=path,
    )


def _transition_error(path: Path, message: str) -> PluginRetirementSetError:
    return PluginRetirementSetError(
        message,
        code="invalid_plugin_retirement_set_transition",
        path=path,
    )


def _corrupt(path: Path, message: str) -> PluginRetirementSetError:
    return PluginRetirementSetError(
        message,
        code="plugin_retirement_set_journal_corrupt",
        path=path,
    )


__all__ = [
    "PLUGIN_OWNER_RETIREMENT_OUTCOME_VERSION",
    "PLUGIN_OWNER_RETIREMENT_PLAN_VERSION",
    "PLUGIN_OWNER_RETIREMENT_TARGET_VERSION",
    "PLUGIN_RETIREMENT_SET_EVENT_CODEC",
    "PLUGIN_RETIREMENT_SET_EVENT_VERSION",
    "PluginOwnerRetirementDisposition",
    "PluginOwnerRetirementOutcomeV1",
    "PluginOwnerRetirementPlanV1",
    "PluginOwnerRetirementTargetV1",
    "PluginRetirementIntentSourcePort",
    "PluginRetirementSetError",
    "PluginRetirementSetEventKind",
    "PluginRetirementSetEventV1",
    "PluginRetirementSetInventorySnapshotV1",
    "PluginRetirementSetLedger",
    "PluginRetirementSetRecordCodecError",
    "PluginRetirementSetSnapshotV1",
    "PluginRetirementSetState",
    "owner_retirement_plan_id",
    "owner_retirement_target_id",
]
