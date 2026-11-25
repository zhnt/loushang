"""Bounded child-start lookup message, not launch or connection authority.

The inherited socket is passed separately and admitted by the bootstrap owner.
No credentials, file descriptors, Product factories or environment are decoded.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loushang.hosting.contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting.service_windows import WindowsServiceLaunchRequestV1

from .contracts import (
    _HEX32,
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _match,
    _path,
)
from .paths import resolve_managed_paths

_VERSION = "loushang.managed-child/v1"
_VERSION_SCRATCH = "loushang.managed-child/v2"
_VERSION_TRACE = "loushang.managed-child/v3"
_MAX_BYTES = 64 * 1024
_MAX_SCRATCH_BYTES = 96 * 1024
_FIELDS = frozenset({
    "version", "platformHome", "userId", "machineId", "productId", "hostRoot",
    "profile", "instanceId", "attemptId", "runtimeRoot",
})
_SCRATCH_FIELDS = _FIELDS | {"temporaryRoot"}
_TRACE_FIELDS = _FIELDS | {"traceDeadlineMs"}
_ALL_FIELDS = _SCRATCH_FIELDS | _TRACE_FIELDS


def _validate_trace_deadline(value: int | None) -> None:
    if value is not None and (type(value) is not int or not 0 < value <= 10**15):
        raise ManagedContractError()


@dataclass(frozen=True, slots=True)
class ManagedChildInvocationV1:
    """Immutable addressing facts; the child must still verify durable birth."""

    namespace: ManagedNamespaceV1
    service: ManagedServiceKeyV1
    instance: ManagedInstanceRefV1
    attempt_id: str = field(repr=False)
    runtime_root: str = field(repr=False)
    temporary_override: str | None = field(default=None, repr=False)
    trace_deadline_ms: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Reuse the exact identity and lexical layout checks, without native IO.
        resolve_managed_paths(self.namespace, self.service, self.instance, runtime_root=self.runtime_root,
                              temporary_override=self.temporary_override)
        _match(self.attempt_id, _HEX32)
        _validate_trace_deadline(self.trace_deadline_ms)

    def to_json(self) -> str:
        record: dict[str, str | int] = {
            "version": _VERSION if self.temporary_override is None else _VERSION_SCRATCH,
            "platformHome": self.namespace.platform_home,
            "userId": self.namespace.user_id,
            "machineId": self.namespace.machine_id,
            "productId": self.service.product_id,
            "hostRoot": self.service.host_root,
            "profile": self.service.profile,
            "instanceId": self.instance.instance_id,
            "attemptId": self.attempt_id,
            "runtimeRoot": self.runtime_root,
        }
        if self.temporary_override is not None:
            record["temporaryRoot"] = self.temporary_override
        if self.trace_deadline_ms is not None:
            record["version"] = _VERSION_TRACE
            record["traceDeadlineMs"] = self.trace_deadline_ms
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        _bounded(payload, maximum=_MAX_BYTES if self.temporary_override is None else _MAX_SCRATCH_BYTES)
        return payload

    @classmethod
    def from_json(cls, payload: str) -> ManagedChildInvocationV1:
        """Reject malformed data before any filesystem or descriptor admission."""
        _bounded(payload, maximum=_MAX_SCRATCH_BYTES)
        try:
            record = json.loads(payload, object_pairs_hook=_object, parse_constant=_constant)
            if type(record) is not dict:
                raise ManagedContractError()
            trace_deadline = None
            if record.get("version") == _VERSION and record.keys() == _FIELDS:
                _bounded(payload, maximum=_MAX_BYTES)
                temporary = None
            elif record.get("version") == _VERSION_SCRATCH and record.keys() == _SCRATCH_FIELDS:
                temporary = record["temporaryRoot"]
            elif record.get("version") == _VERSION_TRACE and (
                record.keys() == _TRACE_FIELDS or record.keys() == _ALL_FIELDS
            ):
                temporary = record.get("temporaryRoot")
                trace_deadline = record["traceDeadlineMs"]
                if temporary is None:
                    _bounded(payload, maximum=_MAX_BYTES)
            else:
                raise ManagedContractError()
            namespace = ManagedNamespaceV1(record["platformHome"], record["userId"], record["machineId"])
            service = ManagedServiceKeyV1(record["productId"], record["hostRoot"], record["profile"])
            instance = ManagedInstanceRefV1(namespace.namespace_key, service.service_id, record["instanceId"])
            return cls(namespace, service, instance, record["attemptId"], record["runtimeRoot"], temporary, trace_deadline)
        except (ValueError, TypeError, RecursionError):
            raise ManagedContractError() from None


def _bounded(payload: str, *, maximum: int) -> None:
    # Character count first avoids allocating a huge UTF-8 copy of invalid input.
    if type(payload) is not str or len(payload) > maximum:
        raise ManagedContractError()
    try:
        if len(payload.encode("utf-8")) > maximum:
            raise ManagedContractError()
    except UnicodeError:
        raise ManagedContractError() from None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key, value in pairs:
        if key in record or key not in _ALL_FIELDS or type(value) not in (str, int):
            raise ManagedContractError()
        record[key] = value
    return record


def _constant(value: str) -> Any:
    raise ManagedContractError()


def build_managed_child_launch_request(
    invocation: ManagedChildInvocationV1,
    descriptor: int,
    *,
    product_id: str,
    module: str,
    executable: str,
    environment: Mapping[str, str],
    session_root: Path | None,
    default_session_directory: str,
) -> ProcessLaunchRequest | WindowsServiceLaunchRequestV1:
    """Build pure launch material for a selected Product's managed child."""
    if type(invocation) is not ManagedChildInvocationV1 or invocation.service.product_id != product_id:
        raise ManagedContractError()
    require_managed_descriptor(descriptor)
    _path(executable)
    selected = (
        session_root if session_root is not None
        else Path(invocation.namespace.platform_home) / default_session_directory
    )
    if not isinstance(selected, Path):
        raise ManagedContractError()
    _path(str(selected))
    effective = {**environment, **managed_child_environment(invocation)}
    executable_args = (executable, "-m", module)
    invocation_json = invocation.to_json()
    windows = sys.platform == "win32"
    arguments = ("--inherited", str(descriptor)) if windows else (invocation_json, str(selected), str(descriptor))
    request = ProcessLaunchRequest(
        (*executable_args, *arguments), invocation.namespace.platform_home, tuple(effective.items()),
        ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD),
    )
    if windows:
        startup = json.dumps([invocation_json, str(selected)], ensure_ascii=False, separators=(",", ":"))
        return WindowsServiceLaunchRequestV1(request, startup.encode("utf-8"))
    return request


def require_managed_descriptor(value: int) -> None:
    maximum = 2**64 if sys.platform == "win32" else 2**31
    if type(value) is not int or not 3 <= value < maximum:
        raise ManagedContractError()


def managed_child_environment(invocation: ManagedChildInvocationV1) -> dict[str, str]:
    paths = resolve_managed_paths(
        invocation.namespace, invocation.service, invocation.instance,
        runtime_root=invocation.runtime_root, temporary_override=invocation.temporary_override,
    )
    return {
        "LOUSHANG_HOME": invocation.namespace.platform_home,
        "LOUSHANG_RUNTIME_DIR": invocation.runtime_root,
        "LOUSHANG_TMPDIR": str(paths.temporary),
    }


__all__ = ["ManagedChildInvocationV1", "build_managed_child_launch_request"]
