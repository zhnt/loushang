"""Read and verify the management evidence in an admitted legacy snapshot."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.plugin_management.instance_runtime import (
    inspect_gracefully_retired_instance_capture,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
    PluginLifecycleError,
    decode_plugin_desired_state_capture,
)
from loushang.harness.plugin_management.retirement_sets import RetirementCaptureFields
from loushang.harness.plugin_management.service import (
    inspect_settled_management_capture,
)

_MANAGEMENT_OPERATIONS = "management-operations.jsonl"
_INSTANCE_RUNTIME = "instance-runtime.jsonl"
_RETIREMENT_INTENTS = "retirement-intents.jsonl"
_RETIREMENT_SETS = "retirement-sets.jsonl"
LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES = 2 * 1024 * 1024

_SIMPLE_DESIRED_MEMBERS = ("desired-state.jsonl",)
_SERVICE_DESIRED_MEMBERS = (
    "desired-state.jsonl",
    "desired-state.jsonl.lock",
    _MANAGEMENT_OPERATIONS,
    "management-operations.jsonl.lock",
)
_SERVICE_INSTANCE_MEMBERS = (
    "retirement-intents.jsonl.lock",
    "retirement-sets.jsonl.lock",
)
_SERVICE_RETIRED_INSTANCE_MEMBERS = (
    _RETIREMENT_INTENTS,
    "retirement-intents.jsonl.lock",
    _RETIREMENT_SETS,
    "retirement-sets.jsonl.lock",
)
_RUNTIME_LOCK_MARKERS = (
    "instance-runtime.jsonl.lock",
    "instance-runtime.security-acceptances.jsonl.lock",
)
_SERVICE_RETIRED_RUNTIME_INSTANCE_MEMBERS = (
    _INSTANCE_RUNTIME,
    *_RUNTIME_LOCK_MARKERS,
    *_SERVICE_RETIRED_INSTANCE_MEMBERS,
)
_LOCK_HISTORY_MEMBERS = {
    ("package-lock.json",),
    ("package-lock.json", "package-lock.json.lock"),
}
SERVICE_LOCK_MARKERS = (
    ("desired_state", "desired-state.jsonl.lock"),
    ("desired_state", "management-operations.jsonl.lock"),
    ("instance_state", "retirement-intents.jsonl.lock"),
    ("instance_state", "retirement-sets.jsonl.lock"),
)


def classify_management_members(
    *,
    desired_members: tuple[str, ...],
    instance_members: tuple[str, ...],
    lock_members: tuple[str, ...],
    has_binding: bool,
    allow_retirement: bool,
    allow_retired_runtime: bool,
    error_type: type[ValueError],
    label: str,
) -> bool:
    """Recognize the exact simple or managed journal membership."""
    if (
        type(has_binding) is not bool
        or type(allow_retirement) is not bool
        or type(allow_retired_runtime) is not bool
    ):
        raise error_type(f"{label} Package binding shape is invalid")
    valid_locks = (
        lock_members in _LOCK_HISTORY_MEMBERS if has_binding else lock_members == ()
    )
    if not valid_locks:
        raise error_type(f"{label} Package lock shape is unsupported")
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
    raise error_type(f"{label} management journal shape is unsupported")


def decode_legacy_desired_evidence(
    raw: bytes,
    *,
    path: Path,
    product_id: str,
    scope_id: str,
    maximum_bytes: int,
    error_type: type[ValueError],
    label: str,
) -> tuple[
    PluginDesiredStateSnapshotV1, str, tuple[PluginDesiredStateJournalTransition, ...]
]:
    """Decode complete committed history and check its Installation scope."""
    if not isinstance(raw, bytes) or len(raw) > maximum_bytes:
        raise error_type(f"{label} desired journal exceeds budget")
    reject_duplicate_keys = _unique_json_object_hook(
        lambda: f"{label} desired state has duplicate JSON keys",
    )
    try:
        text = raw.decode("utf-8")
        if text and not text.endswith("\n"):
            raise ValueError("Old desired journal has an incomplete final record")
        for line in text.splitlines():
            if line.strip():
                json.loads(line, object_pairs_hook=reject_duplicate_keys)
        snapshot, transitions = decode_plugin_desired_state_capture(text, path=path)
    except (UnicodeError, ValueError, PluginLifecycleError) as exc:
        raise error_type(f"{label} desired state is invalid") from exc
    if any(
        state.installation_key.product_id != product_id
        or state.installation_key.installation_scope != "workspace"
        or state.installation_key.scope_id != scope_id
        for state in snapshot.installations
    ):
        raise error_type(f"{label} desired state has a foreign Installation")
    return snapshot, sha256(raw).hexdigest(), transitions


def require_empty_lock_markers(
    read_member: Callable[..., bytes | None],
    markers: Iterable[tuple[str, str]],
    *,
    error_type: type[ValueError],
    message: str,
) -> None:
    """Read each captured marker in order through the caller's read authority."""
    for domain, name in markers:
        if read_member(domain=domain, member_name=name, maximum_bytes=8) != b"\0":
            raise error_type(message)


def require_service_lock_markers(
    read_member: Callable[..., bytes | None],
    instance_members: tuple[str, ...],
    *,
    error_type: type[ValueError],
    message: str,
) -> None:
    markers: tuple[tuple[str, str], ...] = SERVICE_LOCK_MARKERS
    if _INSTANCE_RUNTIME in instance_members:
        markers += tuple(("instance_state", name) for name in _RUNTIME_LOCK_MARKERS)
    require_empty_lock_markers(
        read_member, markers, error_type=error_type, message=message
    )


@dataclass(frozen=True, slots=True)
class LegacyManagementCapturePaths:
    management_operations: Path
    retirement_intents: Path
    retirement_sets: Path
    instance_runtime: Path


@dataclass(frozen=True, slots=True)
class _RetirementCapture(RetirementCaptureFields):
    intents_raw: bytes
    sets_raw: bytes
    intents_path: Path
    sets_path: Path


def read_settled_management_history(
    read_member: Callable[..., bytes | None],
    *,
    paths: LegacyManagementCapturePaths,
    instance_members: tuple[str, ...],
    desired_snapshot: PluginDesiredStateSnapshotV1,
    desired_transitions: tuple[PluginDesiredStateJournalTransition, ...],
    error_type: type[ValueError],
    missing_messages: tuple[str, str, str],
    operation_error: type[ValueError],
    operation_label: str,
    instance_error: type[ValueError],
    operation_maximum_bytes: int | None = LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
    retain_operation_digest: bool = False,
) -> str | None:
    """Verify old management and retired-runtime history over existing decoders."""
    maximum = LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES
    operation_limit = (
        {}
        if operation_maximum_bytes is None
        else {"maximum_bytes": operation_maximum_bytes}
    )
    operations_raw = read_member(
        domain="desired_state", member_name=_MANAGEMENT_OPERATIONS, **operation_limit
    )
    if operations_raw is None:
        raise error_type(missing_messages[0])
    retirements = None
    if _RETIREMENT_INTENTS in instance_members:
        intents_raw = read_member(
            domain="instance_state",
            member_name=_RETIREMENT_INTENTS,
            maximum_bytes=maximum,
        )
        sets_raw = read_member(
            domain="instance_state", member_name=_RETIREMENT_SETS, maximum_bytes=maximum
        )
        if intents_raw is None or sets_raw is None:
            raise error_type(missing_messages[1])
        retirements = _RetirementCapture(
            intents_raw, sets_raw, paths.retirement_intents, paths.retirement_sets
        )
    if (
        not isinstance(operations_raw, bytes)
        or len(operations_raw) > maximum
        or not isinstance(paths.management_operations, Path)
    ):
        raise operation_error(
            f"{operation_label} management operation evidence is invalid"
        )
    digest, _ = inspect_settled_management_capture(
        operations_raw,
        path=paths.management_operations,
        desired_transitions=desired_transitions,
        retirements=retirements,
        maximum_bytes=maximum,
        error_type=operation_error,
        label=operation_label,
    )
    if _INSTANCE_RUNTIME in instance_members:
        runtime_raw = read_member(
            domain="instance_state",
            member_name=_INSTANCE_RUNTIME,
            maximum_bytes=maximum,
        )
        if runtime_raw is None or retirements is None:
            raise error_type(missing_messages[2])
        if any(
            not isinstance(raw, bytes) or len(raw) > maximum
            for raw in (runtime_raw, retirements.intents_raw, retirements.sets_raw)
        ):
            raise instance_error("Old Instance capture is invalid")
        inspect_gracefully_retired_instance_capture(
            runtime_raw,
            runtime_path=paths.instance_runtime,
            desired_snapshot=desired_snapshot,
            desired_transitions=desired_transitions,
            retirements=retirements,
            error_type=instance_error,
            label="Old Instance",
        )
    return digest if retain_operation_digest else None
