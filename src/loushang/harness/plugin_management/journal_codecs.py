from __future__ import annotations

from typing import TypeAlias, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.journal import FunctionalJournalRecordCodec
from loushang.harness.plugin_management.operations import (
    PluginManagementOperationEventV1,
    PluginManagementRecordCodecError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateTransitionV1,
    PluginLifecycleCodecError,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
    PluginUpdateOperationEventV2,
)

PluginDesiredStateJournalTransition: TypeAlias = (
    PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2
)
PluginManagementOperationEvent: TypeAlias = (
    PluginManagementOperationEventV1 | PluginUpdateOperationEventV2
)


def _encode_desired_transition(
    transition: PluginDesiredStateJournalTransition,
) -> dict[str, object]:
    if not isinstance(
        transition,
        (PluginDesiredStateTransitionV1, PluginDesiredStateUpdateTransitionV2),
    ):
        raise TypeError("Plugin desired-state journal transition is required")
    return transition.to_dict()


def _decode_desired_transition(
    value: object,
) -> PluginDesiredStateJournalTransition:
    try:
        document = cast(
            dict[str, object],
            require_json_mapping(value, name="Plugin desired-state transition"),
        )
    except JsonValueError as exc:
        raise PluginLifecycleCodecError(
            str(exc), code="invalid_plugin_lifecycle_record"
        ) from exc
    version = document.get("recordVersion")
    if version == 1 and not isinstance(version, bool):
        return PluginDesiredStateTransitionV1.from_dict(document)
    if version == 2 and not isinstance(version, bool):
        return PluginDesiredStateUpdateTransitionV2.from_dict(document)
    raise PluginLifecycleCodecError(
        "Unsupported Plugin lifecycle record version",
        code="unsupported_plugin_lifecycle_record_version",
    )


PLUGIN_DESIRED_STATE_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_desired_transition,
    decoder=_decode_desired_transition,
)


def _encode_operation_event(
    event: PluginManagementOperationEvent,
) -> dict[str, object]:
    if not isinstance(
        event,
        (PluginManagementOperationEventV1, PluginUpdateOperationEventV2),
    ):
        raise TypeError("Plugin management operation event is required")
    return event.to_dict()


def _decode_operation_event(value: object) -> PluginManagementOperationEvent:
    try:
        document = cast(
            dict[str, object],
            require_json_mapping(value, name="Plugin management operation event"),
        )
    except JsonValueError as exc:
        raise PluginManagementRecordCodecError(
            str(exc), code="invalid_plugin_management_record"
        ) from exc
    version = document.get("recordVersion")
    if version == 1 and not isinstance(version, bool):
        return PluginManagementOperationEventV1.from_dict(document)
    if version == 2 and not isinstance(version, bool):
        return PluginUpdateOperationEventV2.from_dict(document)
    raise PluginManagementRecordCodecError(
        "Unsupported Plugin management record version",
        code="unsupported_plugin_management_record_version",
    )


PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_operation_event,
    decoder=_decode_operation_event,
)


__all__ = [
    "PLUGIN_DESIRED_STATE_JOURNAL_CODEC",
    "PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC",
    "PluginDesiredStateJournalTransition",
    "PluginManagementOperationEvent",
]
