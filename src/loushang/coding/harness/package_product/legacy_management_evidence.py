"""One settled-history proof over the caller's original snapshot read authority.

The sole read port borrows either existing fenced snapshot reads or the current
cutover owner. No second snapshot, journal, lock or mutable state is created.
Original nominal/parser globals and Product wire declarations remain explicit
intermediate dependencies; callers retain their distinct error identities.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from loushang.coding.package import legacy_installation_inventory as _wire


def verify_settled_history(
    *,
    lifecycle: _wire.CodingPluginLifecycleStateLayout,
    instance_members: tuple[str, ...],
    desired: _wire.CodingLegacyDesiredEvidenceV1,
    read_member: Callable[..., bytes | None],
    receiver: ModuleType,
    error_type: type[ValueError],
    messages: tuple[str, str, str, str],
) -> None:
    service_locks: tuple[tuple[_wire.CodingLegacyEvidenceDomain, str], ...] = (
        ("desired_state", _wire._LEGACY_PROGRAM_VALUES["value_012"]),
        ("desired_state", _wire._LEGACY_PROGRAM_VALUES["value_013"]),
        ("instance_state", _wire._LEGACY_PROGRAM_VALUES["value_014"]),
        ("instance_state", _wire._LEGACY_PROGRAM_VALUES["value_015"]),
    )
    if _wire._LEGACY_PROGRAM_VALUES["value_010"] in instance_members:
        service_locks += (
            ("instance_state", _wire._LEGACY_PROGRAM_VALUES["value_018"]),
            ("instance_state", _wire._LEGACY_PROGRAM_VALUES["value_019"]),
        )
    for domain, name in service_locks:
        if read_member(domain=domain, member_name=name, maximum_bytes=8) != b"\x00":
            raise error_type(messages[1])
    read_settled_management_history(
        lifecycle=lifecycle,
        instance_members=instance_members,
        desired=desired,
        read_member=read_member,
        receiver=receiver,
        error_type=error_type,
        missing_messages=(messages[0], messages[2], messages[3]),
    )


def read_settled_management_history(
    *,
    lifecycle: _wire.CodingPluginLifecycleStateLayout,
    instance_members: tuple[str, ...],
    desired: _wire.CodingLegacyDesiredEvidenceV1,
    read_member: Callable[..., bytes | None],
    receiver: ModuleType,
    error_type: type[ValueError],
    missing_messages: tuple[str, str, str],
    operation_maximum_bytes: int | None = 2 * 1024 * 1024,
    retain_operation_digest: bool = False,
) -> str | None:
    """Verify captured history with the caller's snapshot reader and errors."""

    operation_limit = (
        {}
        if operation_maximum_bytes is None
        else {"maximum_bytes": operation_maximum_bytes}
    )
    operations_raw = read_member(
        domain="desired_state",
        member_name=_wire._LEGACY_PROGRAM_VALUES["value_016"],
        **operation_limit,
    )
    if operations_raw is None:
        raise error_type(missing_messages[0])
    retirements = None
    if _wire._LEGACY_PROGRAM_VALUES["value_011"] in instance_members:
        intents_raw = read_member(
            domain="instance_state",
            member_name=_wire._LEGACY_PROGRAM_VALUES["value_011"],
            maximum_bytes=2 * 1024 * 1024,
        )
        sets_raw = read_member(
            domain="instance_state",
            member_name=_wire._LEGACY_PROGRAM_VALUES["value_021"],
            maximum_bytes=2 * 1024 * 1024,
        )
        if intents_raw is None or sets_raw is None:
            raise error_type(missing_messages[1])
        retirements = receiver.CodingLegacyRetirementCaptureV1(
            intents_raw=intents_raw,
            sets_raw=sets_raw,
            intents_path=lifecycle.retirement_intents,
            sets_path=lifecycle.retirement_sets,
        )
    operation = receiver.parse_coding_legacy_operation_evidence(
        operations_raw,
        desired=desired,
        path=lifecycle.management_operations,
        retirements=retirements,
    )
    digest: str | None = operation.journal_digest if retain_operation_digest else None
    if _wire._LEGACY_PROGRAM_VALUES["value_010"] in instance_members:
        runtime_raw = read_member(
            domain="instance_state",
            member_name=_wire._LEGACY_PROGRAM_VALUES["value_010"],
            maximum_bytes=2 * 1024 * 1024,
        )
        if runtime_raw is None or retirements is None:
            raise error_type(missing_messages[2])
        receiver.parse_coding_legacy_retired_instance_capture(
            runtime_raw,
            intents_raw=retirements.intents_raw,
            sets_raw=retirements.sets_raw,
            desired=desired,
            lifecycle=lifecycle,
        )
    return digest
