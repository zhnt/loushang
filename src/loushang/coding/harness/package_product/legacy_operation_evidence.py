"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_operation_evidence as _binding


def classify_management_members(
    *,
    desired_members: tuple[str, ...],
    instance_members: tuple[str, ...],
    lock_members: tuple[str, ...],
    has_binding: bool,
    allow_retirement: bool,
    allow_retired_runtime: bool,
) -> bool:
    """Identify only the simple or exact Service shape without retirement rows."""

    if (
        type(has_binding) is not bool
        or type(allow_retirement) is not bool
        or type(allow_retired_runtime) is not bool
    ):
        raise _binding.CodingLegacyOperationEvidenceError(
            _binding._LEGACY_EVIDENCE_VALUES["value_002"]
        )
    valid_locks = (
        lock_members in _binding._LOCK_HISTORY_MEMBERS
        if has_binding
        else lock_members == ()
    )
    if not valid_locks:
        raise _binding.CodingLegacyOperationEvidenceError(
            _binding._LEGACY_EVIDENCE_VALUES["value_003"]
        )
    if desired_members == _binding._SIMPLE_DESIRED_MEMBERS and instance_members == ():
        return False
    if desired_members == _binding._SERVICE_DESIRED_MEMBERS and (
        instance_members == _binding._SERVICE_INSTANCE_MEMBERS
        or (
            allow_retirement
            and instance_members == _binding._SERVICE_RETIRED_INSTANCE_MEMBERS
        )
        or (
            allow_retirement
            and allow_retired_runtime
            and instance_members == _binding._SERVICE_RETIRED_RUNTIME_INSTANCE_MEMBERS
        )
    ):
        return True
    raise _binding.CodingLegacyOperationEvidenceError(
        _binding._LEGACY_EVIDENCE_VALUES["value_001"]
    )
