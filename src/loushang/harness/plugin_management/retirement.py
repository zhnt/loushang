from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

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
from loushang.harness.plugin_management.journal_codecs import (
    PLUGIN_DESIRED_STATE_JOURNAL_CODEC,
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateTransitionV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import PluginDeclarationCodecError
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PLUGIN_RETIREMENT_INTENT_VERSION = 1
PLUGIN_RETIREMENT_INTENT_RECORD_VERSION = 1

PluginRetirementTrigger = Literal["disable", "remove", "update"]
PluginRetirementMode = Literal["graceful"]


class PluginRetirementRecordCodecError(JournalCodecError):
    """Strict retirement-intent record decoding failure."""


class PluginRetirementError(RuntimeError):
    """Fail-closed retirement-intent journal error with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginRetirementIntentV1:
    retirement_id: str
    trigger: PluginRetirementTrigger
    mode: PluginRetirementMode
    instance_revision_ref: PluginInstanceRevisionRef
    package_revision: PluginPackageRevisionRefV1
    source_transition: PluginDesiredStateJournalTransition
    intent_version: int = PLUGIN_RETIREMENT_INTENT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.retirement_id, name="retirement id")
        if self.mode != "graceful":
            raise ValueError("PLC2-4A retirement mode must be graceful")
        if self.trigger not in {"disable", "remove", "update"}:
            raise ValueError("Unsupported Plugin retirement trigger")
        _require_version(
            self.intent_version,
            expected=PLUGIN_RETIREMENT_INTENT_VERSION,
        )
        subject = _retirement_subject(self.source_transition)
        if subject is None:
            raise ValueError(
                "Plugin retirement intent requires a replaced enabled Instance"
            )
        trigger, instance_revision_ref, package_revision = subject
        if (
            self.trigger != trigger
            or self.instance_revision_ref != instance_revision_ref
            or self.package_revision != package_revision
        ):
            raise ValueError(
                "Plugin retirement intent does not match its source transition"
            )
        if self.retirement_id != retirement_id_for(self.source_transition):
            raise ValueError("Plugin retirement id does not match source transition")

    @property
    def source_operation_id(self) -> str:
        return self.source_transition.mutation.operation_id

    def to_dict(self) -> dict[str, object]:
        return {
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "intentVersion": self.intent_version,
            "mode": self.mode,
            "packageRevision": self.package_revision.to_dict(),
            "retirementId": self.retirement_id,
            "sourceTransition": self.source_transition.to_dict(),
            "trigger": self.trigger,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginRetirementIntentV1:
        document = _wire_object(value, name="Plugin retirement intent")
        _wire_exact_fields(
            document,
            keys={
                "instanceRevisionRef",
                "intentVersion",
                "mode",
                "packageRevision",
                "retirementId",
                "sourceTransition",
                "trigger",
            },
            name="Plugin retirement intent",
        )
        _wire_version(
            document.get("intentVersion"),
            expected=PLUGIN_RETIREMENT_INTENT_VERSION,
        )
        try:
            trigger = _wire_string(
                document["trigger"], name="Plugin retirement trigger"
            )
            mode = _wire_string(document["mode"], name="Plugin retirement mode")
            if trigger not in {"disable", "remove", "update"}:
                raise ValueError("Unsupported Plugin retirement trigger")
            if mode != "graceful":
                raise ValueError("PLC2-4A retirement mode must be graceful")
            source_document = _wire_mapping(
                document["sourceTransition"],
                name="Plugin retirement source transition",
            )
            return cls(
                retirement_id=_wire_string(
                    document["retirementId"], name="retirement id"
                ),
                trigger=cast(PluginRetirementTrigger, trigger),
                mode="graceful",
                instance_revision_ref=_wire_instance_ref(
                    document["instanceRevisionRef"]
                ),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["packageRevision"]
                ),
                source_transition=PLUGIN_DESIRED_STATE_JOURNAL_CODEC.decode_record(
                    source_document
                ),
                intent_version=PLUGIN_RETIREMENT_INTENT_VERSION,
            )
        except PluginRetirementRecordCodecError:
            raise
        except (
            PluginDeclarationCodecError,
            PluginLifecycleCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginRetirementIntentRecordV1:
    journal_revision: int
    intent: PluginRetirementIntentV1
    record_version: int = PLUGIN_RETIREMENT_INTENT_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        _require_version(
            self.record_version,
            expected=PLUGIN_RETIREMENT_INTENT_RECORD_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.to_dict(),
            "journalRevision": self.journal_revision,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginRetirementIntentRecordV1:
        document = _wire_object(value, name="Plugin retirement intent record")
        _wire_exact_fields(
            document,
            keys={"intent", "journalRevision", "recordVersion"},
            name="Plugin retirement intent record",
        )
        _wire_version(
            document.get("recordVersion"),
            expected=PLUGIN_RETIREMENT_INTENT_RECORD_VERSION,
        )
        try:
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                intent=PluginRetirementIntentV1.from_dict(document["intent"]),
                record_version=PLUGIN_RETIREMENT_INTENT_RECORD_VERSION,
            )
        except PluginRetirementRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


PLUGIN_RETIREMENT_INTENT_RECORD_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginRetirementIntentRecordV1.to_dict,
    decoder=PluginRetirementIntentRecordV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginRetirementIntentSnapshotV1:
    journal_revision: int
    intents: tuple[PluginRetirementIntentV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.journal_revision, int)
            or isinstance(self.journal_revision, bool)
            or self.journal_revision < 0
        ):
            raise ValueError("Retirement journal revision must be non-negative")
        if self.journal_revision != len(self.intents):
            raise ValueError("Retirement snapshot revision does not match intents")

    def intent_for_operation(
        self, operation_id: str
    ) -> PluginRetirementIntentV1 | None:
        for intent in self.intents:
            if intent.source_operation_id == operation_id:
                return intent
        return None


@dataclass(slots=True)
class _ReplayedRetirementIntents:
    records: tuple[PluginRetirementIntentRecordV1, ...]
    by_operation: dict[str, PluginRetirementIntentV1]
    by_retirement_id: dict[str, PluginRetirementIntentV1]
    by_instance: dict[PluginInstanceRevisionRef, PluginRetirementIntentV1]


class PluginRetirementIntentLedger:
    """Durable, inert handoff of exact graceful retirement subjects."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def request_for(
        self,
        transition: PluginDesiredStateJournalTransition,
    ) -> PluginRetirementIntentV1 | None:
        if not isinstance(
            transition,
            (PluginDesiredStateTransitionV1, PluginDesiredStateUpdateTransitionV2),
        ):
            raise TypeError("Plugin desired-state transition is required")
        expected = retirement_intent_for_transition(transition)
        if expected is None:
            return None
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            repeated = replayed.by_operation.get(expected.source_operation_id)
            if repeated is not None:
                if repeated != expected:
                    raise _conflict(self._path, "Retirement source operation was reused")
                return repeated
            for candidate, message in (
                (
                    replayed.by_retirement_id.get(expected.retirement_id),
                    "Retirement id belongs to different evidence",
                ),
                (
                    replayed.by_instance.get(expected.instance_revision_ref),
                    "Plugin Instance Revision already has a retirement intent",
                ),
            ):
                if candidate is not None:
                    raise _conflict(self._path, message)
            record = PluginRetirementIntentRecordV1(
                journal_revision=len(replayed.records) + 1,
                intent=expected,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=PLUGIN_RETIREMENT_INTENT_RECORD_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return expected

    def snapshot(self) -> PluginRetirementIntentSnapshotV1:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        return PluginRetirementIntentSnapshotV1(
            journal_revision=len(replayed.records),
            intents=tuple(record.intent for record in replayed.records),
        )

    def records(self) -> tuple[PluginRetirementIntentRecordV1, ...]:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            return self._load_and_replay_unlocked().records

    def _load_and_replay_unlocked(self) -> _ReplayedRetirementIntents:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginRetirementIntentRecordV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PLUGIN_RETIREMENT_INTENT_RECORD_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
            )
        except JournalFileError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "invalid_plugin_retirement_record",
                    "unsupported_plugin_retirement_record_version",
                }
                else "plugin_retirement_journal_corrupt"
            )
            raise PluginRetirementError(
                "Plugin retirement intent journal cannot be decoded",
                code=code,
                path=self._path,
            ) from exc
        return _replay(snapshot.records, path=self._path)


def retirement_intent_for_transition(
    transition: PluginDesiredStateJournalTransition,
) -> PluginRetirementIntentV1 | None:
    subject = _retirement_subject(transition)
    if subject is None:
        return None
    trigger, instance_revision_ref, package_revision = subject
    return PluginRetirementIntentV1(
        retirement_id=retirement_id_for(transition),
        trigger=trigger,
        mode="graceful",
        instance_revision_ref=instance_revision_ref,
        package_revision=package_revision,
        source_transition=transition,
    )


def retirement_id_for(transition: PluginDesiredStateJournalTransition) -> str:
    payload = StrictPluginJsonCodec.encode(transition.to_dict())
    return sha256(b"plugin-retirement-intent-v1\0" + payload).hexdigest()


def _retirement_subject(
    transition: PluginDesiredStateJournalTransition,
) -> tuple[
    PluginRetirementTrigger,
    PluginInstanceRevisionRef,
    PluginPackageRevisionRefV1,
] | None:
    previous = transition.previous_state.selection
    if previous.desired_state != "installed_enabled":
        return None
    if isinstance(transition, PluginDesiredStateTransitionV1):
        if transition.transition_kind not in {"disable", "remove"}:
            return None
        trigger = cast(PluginRetirementTrigger, transition.transition_kind)
    else:
        trigger = "update"
    instance_revision_ref = previous.instance_revision_ref
    package_revision = previous.package_revision
    if instance_revision_ref is None or package_revision is None:
        raise ValueError("Enabled retirement predecessor is incomplete")
    return trigger, instance_revision_ref, package_revision


def _empty_replay() -> _ReplayedRetirementIntents:
    return _ReplayedRetirementIntents(
        records=(),
        by_operation={},
        by_retirement_id={},
        by_instance={},
    )


def _replay(
    records: tuple[PluginRetirementIntentRecordV1, ...],
    *,
    path: Path,
) -> _ReplayedRetirementIntents:
    replayed = _empty_replay()
    for expected_revision, record in enumerate(records, start=1):
        intent = record.intent
        if record.journal_revision != expected_revision:
            raise _corrupt(path, "Retirement journal revision is not contiguous")
        if intent.source_operation_id in replayed.by_operation:
            raise _corrupt(path, "Retirement source operation is duplicated")
        if intent.retirement_id in replayed.by_retirement_id:
            raise _corrupt(path, "Retirement id is duplicated")
        if intent.instance_revision_ref in replayed.by_instance:
            raise _corrupt(path, "Plugin Instance retirement subject is duplicated")
        replayed.by_operation[intent.source_operation_id] = intent
        replayed.by_retirement_id[intent.retirement_id] = intent
        replayed.by_instance[intent.instance_revision_ref] = intent
    replayed.records = records
    return replayed


def _wire_object(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _invalid_record(str(exc)) from exc


def _wire_mapping(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise ValueError(str(exc)) from exc


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
        raise PluginRetirementRecordCodecError(
            "Unsupported Plugin retirement record version",
            code="unsupported_plugin_retirement_record_version",
        )


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _wire_instance_ref(value: object) -> PluginInstanceRevisionRef:
    return PluginInstanceRevisionRef.from_dict(value)


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_positive_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin retirement record version")


def _invalid_record(message: str) -> PluginRetirementRecordCodecError:
    return PluginRetirementRecordCodecError(
        message, code="invalid_plugin_retirement_record"
    )


def _conflict(path: Path, message: str) -> PluginRetirementError:
    return PluginRetirementError(
        message, code="plugin_retirement_intent_conflict", path=path
    )


def _corrupt(path: Path, message: str) -> PluginRetirementError:
    return PluginRetirementError(
        message, code="plugin_retirement_journal_corrupt", path=path
    )


__all__ = [
    "PLUGIN_RETIREMENT_INTENT_RECORD_CODEC",
    "PLUGIN_RETIREMENT_INTENT_RECORD_VERSION",
    "PLUGIN_RETIREMENT_INTENT_VERSION",
    "PluginRetirementError",
    "PluginRetirementIntentLedger",
    "PluginRetirementIntentRecordV1",
    "PluginRetirementIntentSnapshotV1",
    "PluginRetirementIntentV1",
    "PluginRetirementMode",
    "PluginRetirementRecordCodecError",
    "PluginRetirementTrigger",
    "retirement_id_for",
    "retirement_intent_for_transition",
]
