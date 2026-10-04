"""Read-only cross-check of frozen old management operations and Desired state."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.plugin_management.retirement import (
    PluginRetirementError,
    decode_plugin_retirement_intent_capture,
    retirement_intent_for_transition,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetError,
    decode_plugin_retirement_set_capture,
)
from loushang.harness.plugin_management.service import (
    PluginManagementError,
    decode_plugin_management_operation_capture,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
)

from .package_legacy_desired_evidence import CodingLegacyDesiredEvidenceV1

_MAX_OPERATION_BYTES = 2 * 1024 * 1024
_SIMPLE_DESIRED_MEMBERS = ("desired-state.jsonl",)
_SERVICE_DESIRED_MEMBERS = (
    "desired-state.jsonl",
    "desired-state.jsonl.lock",
    "management-operations.jsonl",
    "management-operations.jsonl.lock",
)
_SERVICE_INSTANCE_MEMBERS = (
    "retirement-intents.jsonl.lock",
    "retirement-sets.jsonl.lock",
)
_SERVICE_RETIRED_INSTANCE_MEMBERS = (
    "retirement-intents.jsonl",
    "retirement-intents.jsonl.lock",
    "retirement-sets.jsonl",
    "retirement-sets.jsonl.lock",
)
_SERVICE_RETIRED_RUNTIME_INSTANCE_MEMBERS = (
    "instance-runtime.jsonl",
    "instance-runtime.jsonl.lock",
    "instance-runtime.security-acceptances.jsonl.lock",
    *_SERVICE_RETIRED_INSTANCE_MEMBERS,
)
_LOCK_HISTORY_MEMBERS = {
    ("package-lock.json",),
    ("package-lock.json", "package-lock.json.lock"),
}


class CodingLegacyOperationEvidenceError(ValueError):
    """The old operation journal cannot prove settled Desired history."""


def classify_coding_legacy_management_members(
    *,
    desired_members: tuple[str, ...],
    instance_members: tuple[str, ...],
    lock_members: tuple[str, ...],
    has_binding: bool = True,
    allow_retirement: bool = False,
    allow_retired_runtime: bool = False,
) -> bool:
    """Identify only the simple or exact Service shape without retirement rows."""

    if (
        type(has_binding) is not bool
        or type(allow_retirement) is not bool
        or type(allow_retired_runtime) is not bool
    ):
        raise CodingLegacyOperationEvidenceError(
            "Coding old Package binding shape is invalid"
        )
    valid_locks = (
        lock_members in _LOCK_HISTORY_MEMBERS if has_binding else lock_members == ()
    )
    if not valid_locks:
        raise CodingLegacyOperationEvidenceError(
            "Coding old Package lock shape is unsupported"
        )
    if desired_members == _SIMPLE_DESIRED_MEMBERS and instance_members == ():
        return False
    if desired_members == _SERVICE_DESIRED_MEMBERS and (
        instance_members == _SERVICE_INSTANCE_MEMBERS
        or (allow_retirement and instance_members == _SERVICE_RETIRED_INSTANCE_MEMBERS)
        or (
            allow_retirement
            and allow_retired_runtime
            and instance_members == _SERVICE_RETIRED_RUNTIME_INSTANCE_MEMBERS
        )
    ):
        return True
    raise CodingLegacyOperationEvidenceError(
        "Coding old management journal shape is unsupported"
    )


@dataclass(frozen=True, slots=True)
class CodingLegacyOperationEvidenceV1:
    journal_digest: str
    update_operation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodingLegacyRetirementCaptureV1:
    intents_raw: bytes
    sets_raw: bytes
    intents_path: Path
    sets_path: Path


def parse_coding_legacy_operation_evidence(
    raw: bytes,
    *,
    desired: CodingLegacyDesiredEvidenceV1,
    path: Path,
    retirements: CodingLegacyRetirementCaptureV1 | None = None,
) -> CodingLegacyOperationEvidenceV1:
    """Verify settled operations against one complete old Desired capture."""

    if (
        not isinstance(raw, bytes)
        or len(raw) > _MAX_OPERATION_BYTES
        or not isinstance(desired, CodingLegacyDesiredEvidenceV1)
        or not isinstance(path, Path)
        or (
            retirements is not None
            and not isinstance(retirements, CodingLegacyRetirementCaptureV1)
        )
    ):
        raise CodingLegacyOperationEvidenceError(
            "Coding old management operation evidence is invalid"
        )
    try:
        latest = decode_plugin_management_operation_capture(
            raw.decode("utf-8"), path=path
        )
    except (UnicodeError, PluginManagementError) as exc:
        raise CodingLegacyOperationEvidenceError(
            "Coding old management operation journal is invalid"
        ) from exc
    by_operation = {
        transition.mutation.operation_id: transition
        for transition in desired.transitions
    }
    terminal = {event.command.operation_id: event for event in latest}
    for event in latest:
        if event.status != "terminal" or event.result is None:
            raise CodingLegacyOperationEvidenceError(
                "Coding old management operation is unsettled"
            )
        expected = by_operation.get(event.command.operation_id)
        committed = event.result.disposition in {"succeeded", "restart_required"}
        if (committed and event.result.transition != expected) or (
            not committed and expected is not None
        ):
            raise CodingLegacyOperationEvidenceError(
                "Coding old management operation differs from Desired state"
            )
        if event.result.disposition == "restart_required" and not isinstance(
            expected, PluginDesiredStateUpdateTransitionV2
        ):
            raise CodingLegacyOperationEvidenceError(
                "Coding old management restart is not an update"
            )
    for operation_id in by_operation:
        if operation_id not in terminal:
            raise CodingLegacyOperationEvidenceError(
                "Coding old Desired transition has no management operation"
            )
    updates = tuple(
        transition
        for transition in desired.transitions
        if isinstance(transition, PluginDesiredStateUpdateTransitionV2)
    )
    for transition in updates:
        update_event = terminal.get(transition.mutation.operation_id)
        if (
            update_event is None
            or update_event.status != "terminal"
            or update_event.result is None
            or update_event.result.disposition
            != (
                "restart_required"
                if retirement_intent_for_transition(transition) is not None
                else "succeeded"
            )
            or update_event.result.transition != transition
        ):
            raise CodingLegacyOperationEvidenceError(
                "Coding old Desired update has no settled management operation"
            )
    expected_retirements = {
        intent.retirement_id: intent
        for transition in desired.transitions
        if (intent := retirement_intent_for_transition(transition)) is not None
    }
    if retirements is None:
        if expected_retirements:
            raise CodingLegacyOperationEvidenceError(
                "Coding old management retirement evidence is required"
            )
    else:
        if (
            not expected_retirements
            or not isinstance(retirements.intents_raw, bytes)
            or not isinstance(retirements.sets_raw, bytes)
            or len(retirements.intents_raw) > _MAX_OPERATION_BYTES
            or len(retirements.sets_raw) > _MAX_OPERATION_BYTES
            or not isinstance(retirements.intents_path, Path)
            or not isinstance(retirements.sets_path, Path)
        ):
            raise CodingLegacyOperationEvidenceError(
                "Coding old retirement capture is invalid"
            )
        try:
            intents = decode_plugin_retirement_intent_capture(
                retirements.intents_raw.decode("utf-8"),
                path=retirements.intents_path,
            )
            sets = decode_plugin_retirement_set_capture(
                retirements.sets_raw.decode("utf-8"),
                path=retirements.sets_path,
                intents=intents,
            )
        except (UnicodeError, PluginRetirementError, PluginRetirementSetError) as exc:
            raise CodingLegacyOperationEvidenceError(
                "Coding old retirement journals are invalid"
            ) from exc
        if (
            {item.retirement_id: item for item in intents.intents}
            != expected_retirements
            or {item.intent.retirement_id for item in sets.sets}
            != set(expected_retirements)
            or any(
                item.state != "succeeded"
                or item.plan is None
                or not item.plan.targets
                or len(item.latest_outcomes) != len(item.plan.targets)
                or any(
                    outcome.disposition != "succeeded"
                    for outcome in item.latest_outcomes
                )
                for item in sets.sets
            )
        ):
            raise CodingLegacyOperationEvidenceError(
                "Coding old retirement evidence is not fully settled"
            )
    return CodingLegacyOperationEvidenceV1(
        journal_digest=sha256(raw).hexdigest(),
        update_operation_ids=tuple(
            sorted(item.mutation.operation_id for item in updates)
        ),
    )


__all__ = [
    "CodingLegacyOperationEvidenceError",
    "CodingLegacyOperationEvidenceV1",
    "CodingLegacyRetirementCaptureV1",
    "classify_coding_legacy_management_members",
    "parse_coding_legacy_operation_evidence",
]
