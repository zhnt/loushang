"""Read-only cross-check of frozen old management operations and Desired state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.plugin_management.retirement_sets import (
    RetirementCaptureFields,
)
from loushang.harness.plugin_management.service import (
    inspect_settled_management_capture,
)

from .legacy_desired_evidence import CodingLegacyDesiredEvidenceV1

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
class CodingLegacyRetirementCaptureV1(RetirementCaptureFields):
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
    return CodingLegacyOperationEvidenceV1(
        *inspect_settled_management_capture(
            raw,
            path=path,
            desired_transitions=desired.transitions,
            retirements=retirements,
            maximum_bytes=_MAX_OPERATION_BYTES,
            error_type=CodingLegacyOperationEvidenceError,
            label="Coding old",
        )
    )


__all__ = [
    "CodingLegacyOperationEvidenceError",
    "CodingLegacyOperationEvidenceV1",
    "CodingLegacyRetirementCaptureV1",
    "classify_coding_legacy_management_members",
    "parse_coding_legacy_operation_evidence",
]
