from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from loushang.foundation.json import (
    JsonValueError,
    _unique_json_object_hook,
    require_json_mapping,
)
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    decode_jsonl,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.journal.jsonl import _journal_io_path
from loushang.harness.plugin_management.journal_codecs import (
    PLUGIN_DESIRED_STATE_JOURNAL_CODEC,
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateTransitionV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
    _record_document,
    _require_positive_integer,
)
from loushang.harness.plugin_management.records import (
    _require_digest as _require_sha256,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
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
        document = _decode_document(
            value,
            name="Plugin retirement intent",
            schema=_PLUGINRETIREMENTINTENT_SCHEMA,
            version=PLUGIN_RETIREMENT_INTENT_VERSION,
            version_field="intentVersion",
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
            document["trigger"] = trigger
            document["sourceTransition"] = source_document
            return _PLUGINRETIREMENTINTENT_SCHEMA.decode(cls, document)
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
        document = _decode_document(
            value,
            name="Plugin retirement intent record",
            schema=_PLUGINRETIREMENTINTENTRECORD_SCHEMA,
            version=PLUGIN_RETIREMENT_INTENT_RECORD_VERSION,
            version_field="recordVersion",
        )
        try:
            return _PLUGINRETIREMENTINTENTRECORD_SCHEMA.decode(cls, document)
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

    def __init__(
        self, path: str | Path, *, load_policy: JournalLoadPolicy | None = None
    ) -> None:
        self._path = Path(path)
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = load_policy or JournalLoadPolicy(partial_tail="repair")

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
                    raise _conflict(
                        self._path, "Retirement source operation was reused"
                    )
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
        with journal_file_read_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=self._load_policy.create_lock,
        ):
            replayed = self._load_and_replay_unlocked()
        return PluginRetirementIntentSnapshotV1(
            journal_revision=len(replayed.records),
            intents=tuple(record.intent for record in replayed.records),
        )

    def records(self) -> tuple[PluginRetirementIntentRecordV1, ...]:
        with journal_file_read_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=self._load_policy.create_lock,
        ):
            return self._load_and_replay_unlocked().records

    def _load_and_replay_unlocked(self) -> _ReplayedRetirementIntents:
        if not _journal_io_path(self._path).exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginRetirementIntentRecordV1] = load_jsonl(
                self._path,
                record_codec=PLUGIN_RETIREMENT_INTENT_RECORD_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
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


def decode_plugin_retirement_intent_capture(
    raw: str, *, path: Path
) -> PluginRetirementIntentSnapshotV1:
    """Replay frozen retirement-intent bytes without opening the old journal."""

    if not isinstance(raw, str) or not isinstance(path, Path):
        raise TypeError("Retirement intent capture requires text and path")
    if raw and not raw.endswith("\n"):
        raise PluginRetirementError(
            "Retirement intent capture is incomplete",
            code="plugin_retirement_journal_corrupt",
            path=path,
        )
    try:
        for line in raw.splitlines():
            if line.strip():
                json.loads(line, object_pairs_hook=_unique_capture_object)
        snapshot: JsonlSnapshot[None, PluginRetirementIntentRecordV1] = decode_jsonl(
            raw,
            target=path,
            record_codec=PLUGIN_RETIREMENT_INTENT_RECORD_CODEC,
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        )
    except (JournalFileError, ValueError) as exc:
        raise PluginRetirementError(
            "Retirement intent capture cannot be decoded",
            code="plugin_retirement_journal_corrupt",
            path=path,
        ) from exc
    replayed = _replay(snapshot.records, path=path)
    return PluginRetirementIntentSnapshotV1(
        journal_revision=len(replayed.records),
        intents=tuple(record.intent for record in replayed.records),
    )


_unique_capture_object = _unique_json_object_hook(
    lambda: "Retirement capture has duplicate JSON keys",
)


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
) -> (
    tuple[
        PluginRetirementTrigger,
        PluginInstanceRevisionRef,
        PluginPackageRevisionRefV1,
    ]
    | None
):
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


def _wire_mapping(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise ValueError(str(exc)) from exc


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
    "decode_plugin_retirement_intent_capture",
    "retirement_id_for",
    "retirement_intent_for_transition",
]


_PLUGINRETIREMENTINTENT_SCHEMA = RecordSchema.for_dataclass(
    PluginRetirementIntentV1,
    _wire_string,
    RecordField("trigger", decoder=lambda value: value),
    RecordField("mode", decoder=lambda value: "graceful"),
    RecordField("instance_revision_ref", decoder=_wire_instance_ref),
    RecordField("package_revision", decoder=PluginPackageRevisionRefV1.from_dict),
    RecordField(
        "source_transition", decoder=PLUGIN_DESIRED_STATE_JOURNAL_CODEC.decode_record
    ),
    RecordField("intent_version", decoder=int),
    derive_labels=True,
)


_PLUGINRETIREMENTINTENTRECORD_SCHEMA = RecordSchema.for_dataclass(
    PluginRetirementIntentRecordV1,
    _wire_string,
    RecordField("journal_revision", "journal revision", _wire_integer),
    RecordField("intent", decoder=PluginRetirementIntentV1.from_dict),
    RecordField("record_version", decoder=int),
    derive_labels=True,
)


_decode_document = partial(
    _record_document,
    invalid_record=_invalid_record,
    unsupported_version=lambda: PluginRetirementRecordCodecError(
        "Unsupported Plugin retirement record version",
        code="unsupported_plugin_retirement_record_version",
    ),
)


@dataclass(frozen=True, slots=True)
class RemovedInstallationEpoch:
    """An inert proof over decoded Desired transitions, with no mutation authority."""

    install: PluginDesiredStateTransitionV1
    head: PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2
    removal: PluginDesiredStateTransitionV1
    package_revision: PluginPackageRevisionRefV1

    @property
    def head_transition_kind(self) -> Literal["install", "update"]:
        return (
            "update"
            if isinstance(self.head, PluginDesiredStateUpdateTransitionV2)
            else "install"
        )


def inspect_removed_installation_epoch(
    history: tuple[PluginDesiredStateJournalTransition, ...],
    *,
    error_type: type[Exception],
    label: str,
    mismatch_message: str,
) -> RemovedInstallationEpoch:
    """Bind the last install/update epoch to its final removal, without replaying IO.

    The caller supplies the already verified history for one Installation and
    retains Source selection/admission. This proof neither classifies old formats nor
    accepts a binding merely because its final Desired row is absent.
    """
    if len(history) < 2 or any(
        not isinstance(
            item,
            (PluginDesiredStateTransitionV1, PluginDesiredStateUpdateTransitionV2),
        )
        for item in history
    ):
        raise error_type(f"{label} history is incomplete")
    last = history[-1]
    installs = tuple(
        item
        for item in history[:-1]
        if item.transition_kind == "install"
        and isinstance(item, PluginDesiredStateTransitionV1)
    )
    if not installs:
        raise error_type(f"{label} has no final install epoch")
    head_install = installs[-1]
    head_index = history.index(head_install)
    installed = head_install.committed_state.selection.package_revision
    if (
        head_install.previous_state.selection.desired_state != "absent"
        or head_install.committed_state.selection.desired_state
        not in {"installed_disabled", "installed_enabled"}
        or installed is None
        or not isinstance(last, PluginDesiredStateTransitionV1)
        or last.transition_kind != "remove"
        or last.committed_state.selection.desired_state != "absent"
    ):
        raise error_type(mismatch_message)
    head: PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2 = (
        head_install
    )
    for item in history[head_index + 1 : -1]:
        if item.previous_state.selection.package_revision != installed:
            raise error_type(f"{label} revision chain changed")
        if isinstance(item, PluginDesiredStateUpdateTransitionV2):
            installed = item.committed_state.selection.package_revision
            head = item
        elif (
            isinstance(item, PluginDesiredStateTransitionV1)
            and item.transition_kind in {"enable", "disable"}
            and item.committed_state.selection.package_revision == installed
        ):
            continue
        else:
            raise error_type(f"{label} history is unsupported")
    if installed is None or last.previous_state.selection.package_revision != installed:
        raise error_type(mismatch_message)
    return RemovedInstallationEpoch(head_install, head, last, installed)
