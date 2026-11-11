from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Literal

from loushang.harness.journal import FunctionalJournalRecordCodec, JournalCodecError
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginLifecycleCodecError,
    _record_document,
    _require_positive_integer,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)

PLUGIN_MANAGEMENT_COMMAND_VERSION = 1
PLUGIN_MANAGEMENT_OPERATION_RESULT_VERSION = 1
PLUGIN_MANAGEMENT_OPERATION_EVENT_VERSION = 1
PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES = frozenset(
    {
        "invalid_plugin_lifecycle_transition",
        "plugin_installation_already_enabled",
        "plugin_instance_identity_conflict",
        "plugin_inventory_revision_conflict",
        "plugin_management_idempotency_conflict",
        "plugin_management_operation_conflict",
        "plugin_package_revision_mismatch",
        "plugin_update_requires_staging",
    }
)

PluginManagementAction = Literal["install", "enable", "disable", "remove"]
PluginManagementOperationStatus = Literal["accepted", "running", "terminal"]
PluginManagementProgressCode = Literal[
    "command_accepted",
    "desired_state_committing",
    "desired_state_committed",
    "desired_state_failed",
]
PluginManagementResultDisposition = Literal["succeeded", "failed"]
PluginManagementCompensationState = Literal["not_required"]

_ACTIONS = frozenset({"install", "enable", "disable", "remove"})
_STATUSES = frozenset({"accepted", "running", "terminal"})
_PROGRESS_CODES = frozenset(
    {
        "command_accepted",
        "desired_state_committing",
        "desired_state_committed",
        "desired_state_failed",
    }
)
_RESULT_DISPOSITIONS = frozenset({"succeeded", "failed"})


class PluginManagementRecordCodecError(JournalCodecError):
    """Strict Plugin management command/operation record failure."""


@dataclass(frozen=True, slots=True)
class PluginManagementCommandV1:
    action: PluginManagementAction
    mutation: PluginDesiredStateMutationV1
    command_version: int = PLUGIN_MANAGEMENT_COMMAND_VERSION

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS:
            raise ValueError("Unsupported Plugin management action")
        _require_version(
            self.command_version,
            expected=PLUGIN_MANAGEMENT_COMMAND_VERSION,
        )
        desired_state = self.mutation.desired_state
        package = self.mutation.package_revision
        if self.action == "install":
            if desired_state != "installed_disabled" or package is None:
                raise ValueError(
                    "Plugin install requires disabled desired state and Package Revision"
                )
            return
        if package is not None:
            raise ValueError(f"Plugin {self.action} cannot carry a Package Revision")
        expected_state = {
            "enable": "installed_enabled",
            "disable": "installed_disabled",
            "remove": "absent",
        }[self.action]
        if desired_state != expected_state:
            raise ValueError(
                f"Plugin {self.action} mutation has the wrong desired state"
            )

    @property
    def operation_id(self) -> str:
        return self.mutation.operation_id

    @property
    def idempotency_key(self) -> str:
        return self.mutation.idempotency_key

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "commandVersion": self.command_version,
            "mutation": self.mutation.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginManagementCommandV1:
        document = _decode_document(
            value,
            name="Plugin management command",
            schema=_PLUGINMANAGEMENTCOMMAND_SCHEMA,
            version=PLUGIN_MANAGEMENT_COMMAND_VERSION,
            version_field="commandVersion",
        )
        try:
            action = _wire_string(
                document["action"],
                name="Plugin management action",
            )
            if action not in _ACTIONS:
                raise ValueError("Unsupported Plugin management action")
            document["action"] = action
            return _PLUGINMANAGEMENTCOMMAND_SCHEMA.decode(cls, document)
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginManagementOperationResultV1:
    disposition: PluginManagementResultDisposition
    transition: PluginDesiredStateTransitionV1 | None
    error_code: str | None
    result_version: int = PLUGIN_MANAGEMENT_OPERATION_RESULT_VERSION

    def __post_init__(self) -> None:
        if self.disposition not in _RESULT_DISPOSITIONS:
            raise ValueError("Unsupported Plugin management result disposition")
        _require_version(
            self.result_version,
            expected=PLUGIN_MANAGEMENT_OPERATION_RESULT_VERSION,
        )
        if self.disposition == "succeeded":
            if self.transition is None or self.error_code is not None:
                raise ValueError(
                    "Successful Plugin management result requires only a transition"
                )
            return
        if self.transition is not None or self.error_code is None:
            raise ValueError(
                "Failed Plugin management result requires only an error code"
            )
        if self.error_code not in PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES:
            raise ValueError("Unsupported Plugin management terminal error code")

    @classmethod
    def succeeded(
        cls,
        *,
        transition: PluginDesiredStateTransitionV1,
    ) -> PluginManagementOperationResultV1:
        return cls(
            disposition="succeeded",
            transition=transition,
            error_code=None,
        )

    @classmethod
    def failed(cls, *, error_code: str) -> PluginManagementOperationResultV1:
        return cls(
            disposition="failed",
            transition=None,
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "errorCode": self.error_code,
            "resultVersion": self.result_version,
            "transition": (
                None if self.transition is None else self.transition.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginManagementOperationResultV1:
        document = _decode_document(
            value,
            name="Plugin management operation result",
            schema=_PLUGINMANAGEMENTOPERATIONRESULT_SCHEMA,
            version=PLUGIN_MANAGEMENT_OPERATION_RESULT_VERSION,
            version_field="resultVersion",
        )
        try:
            disposition = _wire_string(
                document["disposition"],
                name="Plugin management result disposition",
            )
            if disposition not in _RESULT_DISPOSITIONS:
                raise ValueError("Unsupported Plugin management result disposition")
            transition = (
                None
                if document["transition"] is None
                else PluginDesiredStateTransitionV1.from_dict(document["transition"])
            )
            error_code = _wire_optional_string(
                document["errorCode"],
                name="Plugin management error code",
            )
            document["disposition"] = disposition
            document["transition"] = transition
            document["errorCode"] = error_code
            return _PLUGINMANAGEMENTOPERATIONRESULT_SCHEMA.decode(cls, document)
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginManagementOperationEventV1:
    journal_revision: int
    operation_revision: int
    command: PluginManagementCommandV1
    status: PluginManagementOperationStatus
    progress_code: PluginManagementProgressCode
    compensation_state: PluginManagementCompensationState
    result: PluginManagementOperationResultV1 | None
    record_version: int = PLUGIN_MANAGEMENT_OPERATION_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        _require_positive_integer(self.operation_revision, name="operation revision")
        if self.status not in _STATUSES:
            raise ValueError("Unsupported Plugin management operation status")
        if self.progress_code not in _PROGRESS_CODES:
            raise ValueError("Unsupported Plugin management progress code")
        if self.compensation_state != "not_required":
            raise ValueError("Unsupported PLC2-2 compensation state")
        _require_version(
            self.record_version,
            expected=PLUGIN_MANAGEMENT_OPERATION_EVENT_VERSION,
        )
        expected = {
            "accepted": (1, "command_accepted", False),
            "running": (2, "desired_state_committing", False),
            "terminal": (3, None, True),
        }[self.status]
        expected_revision, expected_progress, requires_result = expected
        if self.operation_revision != expected_revision:
            raise ValueError(
                "Plugin management operation revision does not match status"
            )
        if requires_result != (self.result is not None):
            raise ValueError("Plugin management operation result does not match status")
        if expected_progress is not None and self.progress_code != expected_progress:
            raise ValueError("Plugin management progress does not match status")
        if self.result is None:
            return
        result_progress = (
            "desired_state_committed"
            if self.result.disposition == "succeeded"
            else "desired_state_failed"
        )
        if self.progress_code != result_progress:
            raise ValueError(
                "Plugin management terminal progress does not match result"
            )
        if (
            self.result.transition is not None
            and self.result.transition.mutation != self.command.mutation
        ):
            raise ValueError(
                "Plugin management result transition does not match command"
            )

    @classmethod
    def accepted(
        cls,
        *,
        journal_revision: int,
        command: PluginManagementCommandV1,
    ) -> PluginManagementOperationEventV1:
        return cls(
            journal_revision=journal_revision,
            operation_revision=1,
            command=command,
            status="accepted",
            progress_code="command_accepted",
            compensation_state="not_required",
            result=None,
        )

    @classmethod
    def running(
        cls,
        *,
        journal_revision: int,
        command: PluginManagementCommandV1,
    ) -> PluginManagementOperationEventV1:
        return cls(
            journal_revision=journal_revision,
            operation_revision=2,
            command=command,
            status="running",
            progress_code="desired_state_committing",
            compensation_state="not_required",
            result=None,
        )

    @classmethod
    def terminal(
        cls,
        *,
        journal_revision: int,
        command: PluginManagementCommandV1,
        result: PluginManagementOperationResultV1,
    ) -> PluginManagementOperationEventV1:
        return cls(
            journal_revision=journal_revision,
            operation_revision=3,
            command=command,
            status="terminal",
            progress_code=(
                "desired_state_committed"
                if result.disposition == "succeeded"
                else "desired_state_failed"
            ),
            compensation_state="not_required",
            result=result,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command.to_dict(),
            "compensationState": self.compensation_state,
            "journalRevision": self.journal_revision,
            "operationRevision": self.operation_revision,
            "progressCode": self.progress_code,
            "recordVersion": self.record_version,
            "result": None if self.result is None else self.result.to_dict(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginManagementOperationEventV1:
        document = _decode_document(
            value,
            name="Plugin management operation event",
            schema=_PLUGINMANAGEMENTOPERATIONEVENT_SCHEMA,
            version=PLUGIN_MANAGEMENT_OPERATION_EVENT_VERSION,
            version_field="recordVersion",
        )
        try:
            status = _wire_string(
                document["status"],
                name="Plugin management operation status",
            )
            progress = _wire_string(
                document["progressCode"],
                name="Plugin management progress code",
            )
            compensation = _wire_string(
                document["compensationState"],
                name="Plugin management compensation state",
            )
            if status not in _STATUSES:
                raise ValueError("Unsupported Plugin management operation status")
            if progress not in _PROGRESS_CODES:
                raise ValueError("Unsupported Plugin management progress code")
            if compensation != "not_required":
                raise ValueError("Unsupported PLC2-2 compensation state")
            document["status"] = status
            document["progressCode"] = progress
            document["compensationState"] = compensation
            return _PLUGINMANAGEMENTOPERATIONEVENT_SCHEMA.decode(cls, document)
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


PLUGIN_MANAGEMENT_OPERATION_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginManagementOperationEventV1.to_dict,
    decoder=PluginManagementOperationEventV1.from_dict,
)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid_record(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid_record(f"{name} must be an integer")
    return value


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin management record version")


def _invalid_record(message: str) -> PluginManagementRecordCodecError:
    return PluginManagementRecordCodecError(
        message,
        code="invalid_plugin_management_record",
    )


__all__ = [
    "PLUGIN_MANAGEMENT_COMMAND_VERSION",
    "PLUGIN_MANAGEMENT_OPERATION_EVENT_CODEC",
    "PLUGIN_MANAGEMENT_OPERATION_EVENT_VERSION",
    "PLUGIN_MANAGEMENT_OPERATION_RESULT_VERSION",
    "PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES",
    "PluginManagementAction",
    "PluginManagementCommandV1",
    "PluginManagementCompensationState",
    "PluginManagementOperationEventV1",
    "PluginManagementOperationResultV1",
    "PluginManagementOperationStatus",
    "PluginManagementProgressCode",
    "PluginManagementRecordCodecError",
    "PluginManagementResultDisposition",
]


_PLUGINMANAGEMENTCOMMAND_SCHEMA = RecordSchema.for_dataclass(
    PluginManagementCommandV1,
    _wire_string,
    RecordField("action", decoder=lambda value: value),
    RecordField("mutation", decoder=PluginDesiredStateMutationV1.from_dict),
    RecordField("command_version", decoder=int),
    derive_labels=True,
)


_PLUGINMANAGEMENTOPERATIONRESULT_SCHEMA = RecordSchema.for_dataclass(
    PluginManagementOperationResultV1,
    _wire_string,
    RecordField("disposition", decoder=lambda value: value),
    RecordField("transition", decoder=lambda value: value),
    RecordField("error_code", decoder=lambda value: value),
    RecordField("result_version", decoder=int),
    derive_labels=True,
)


_PLUGINMANAGEMENTOPERATIONEVENT_SCHEMA = RecordSchema.for_dataclass(
    PluginManagementOperationEventV1,
    _wire_string,
    RecordField("journal_revision", "journal revision", _wire_integer),
    RecordField("operation_revision", "operation revision", _wire_integer),
    RecordField("command", decoder=PluginManagementCommandV1.from_dict),
    RecordField("status", decoder=lambda value: value),
    RecordField("progress_code", decoder=lambda value: value),
    RecordField("compensation_state", decoder=lambda value: value),
    RecordField(
        "result",
        decoder=lambda value: (
            None
            if value is None
            else PluginManagementOperationResultV1.from_dict(value)
        ),
    ),
    RecordField("record_version", decoder=int),
    derive_labels=True,
)


_decode_document = partial(
    _record_document,
    invalid_record=_invalid_record,
    unsupported_version=lambda: PluginManagementRecordCodecError(
        "Unsupported Plugin management record version",
        code="unsupported_plugin_management_record_version",
    ),
)
