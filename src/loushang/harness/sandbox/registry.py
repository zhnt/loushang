from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from loushang.harness.environment import HostEnvironment, OperatingSystemFamily

from .protocols import SandboxBackend
from .types import SandboxBackendStatus

SandboxBackendFactory = Callable[[], SandboxBackend]
_OS_FAMILIES: frozenset[str] = frozenset({"linux", "macos", "windows", "other"})


@dataclass(frozen=True, slots=True)
class SandboxBackendRegistration:
    backend_id: str
    os_families: frozenset[OperatingSystemFamily]
    factory: SandboxBackendFactory
    platform_names: frozenset[str] | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.backend_id:
            raise ValueError("sandbox backend registration id must be non-empty")
        families = frozenset(self.os_families)
        if not families:
            raise ValueError("sandbox backend registration requires an OS family")
        if any(family not in _OS_FAMILIES for family in families):
            raise ValueError("sandbox backend registration has an invalid OS family")
        object.__setattr__(self, "os_families", families)
        if self.platform_names is not None:
            names = frozenset(name.lower() for name in self.platform_names)
            if not names:
                raise ValueError("platform_names must be non-empty when provided")
            object.__setattr__(self, "platform_names", names)
        if not callable(self.factory):
            raise TypeError("sandbox backend factory must be callable")
        if type(self.priority) is not int:
            raise TypeError("sandbox backend priority must be an integer")

    def applies_to(self, environment: HostEnvironment) -> bool:
        if environment.os_family not in self.os_families:
            return False
        return (
            self.platform_names is None
            or environment.platform_name in self.platform_names
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class SandboxBackendResolution:
    environment: HostEnvironment
    backend: SandboxBackend | None
    statuses: tuple[SandboxBackendStatus, ...]

    @property
    def selected_status(self) -> SandboxBackendStatus | None:
        if self.backend is None:
            return None
        for status in self.statuses:
            if (
                status.backend_id == self.backend.backend_id
                and status.state == "available"
            ):
                return status
        return None

    def unavailable_reason(self) -> str:
        reasons = [
            f"{status.backend_id}: {status.reason}"
            for status in self.statuses
            if status.state == "unavailable"
        ]
        if reasons:
            return "; ".join(reasons)
        return f"no sandbox backend is applicable to {self.environment.platform_name}"

    def _claim_managed_process_backend_authority(self) -> object | None:
        record = _verified_managed_resolution(self)
        return record.authority if record is not None else None

    async def _plan_managed_process(self, request: object, scope: object) -> object:
        record = _verified_managed_resolution(self)
        if record is None:
            raise RuntimeError("managed Sandbox resolution authority changed")
        result = record.provider(record.backend, request, scope)
        return await result if inspect.isawaitable(result) else result


class SandboxBackendRegistry:
    def __init__(
        self,
        registrations: Iterable[SandboxBackendRegistration] = (),
    ) -> None:
        indexed = tuple(enumerate(registrations))
        ids = [registration.backend_id for _, registration in indexed]
        duplicates = sorted(
            backend_id for backend_id in set(ids) if ids.count(backend_id) > 1
        )
        if duplicates:
            raise ValueError(
                "sandbox backend registration ids must be unique: "
                + ", ".join(duplicates)
            )
        self._registrations = tuple(
            registration
            for _, registration in sorted(
                indexed,
                key=lambda item: (-item[1].priority, item[0]),
            )
        )

    def resolve(self, environment: HostEnvironment) -> SandboxBackendResolution:
        managed_registry = _verified_managed_registry(self)
        statuses: list[SandboxBackendStatus] = []
        for registration in self._registrations:
            if not registration.applies_to(environment):
                statuses.append(
                    SandboxBackendStatus(
                        backend_id=registration.backend_id,
                        state="not_applicable",
                        reason=(
                            f"backend does not apply to {environment.platform_name}"
                        ),
                    )
                )
                continue

            try:
                backend = registration.factory()
            except Exception as error:
                statuses.append(
                    SandboxBackendStatus(
                        backend_id=registration.backend_id,
                        state="unavailable",
                        reason=f"backend factory failed: {error}",
                    )
                )
                continue
            if backend.backend_id != registration.backend_id:
                raise ValueError(
                    "sandbox backend factory identity mismatch: "
                    f"registered {registration.backend_id!r}, "
                    f"created {backend.backend_id!r}"
                )
            try:
                status = backend.probe(environment)
            except Exception as error:
                statuses.append(
                    SandboxBackendStatus(
                        backend_id=registration.backend_id,
                        state="unavailable",
                        reason=f"backend probe failed: {error}",
                    )
                )
                continue
            if not isinstance(status, SandboxBackendStatus):
                raise TypeError(
                    "sandbox backend probe must return SandboxBackendStatus"
                )
            if status.backend_id != registration.backend_id:
                raise ValueError(
                    "sandbox backend probe identity mismatch: "
                    f"expected {registration.backend_id!r}, "
                    f"received {status.backend_id!r}"
                )
            statuses.append(status)
            if status.state == "available":
                resolution = SandboxBackendResolution(
                    environment=environment,
                    backend=backend,
                    statuses=tuple(statuses),
                )
                if (
                    managed_registry is not None
                    and registration is managed_registry.registration
                ):
                    _register_managed_resolution(
                        resolution,
                        registry_record=managed_registry,
                        backend=backend,
                    )
                return resolution

        return SandboxBackendResolution(
            environment=environment,
            backend=None,
            statuses=tuple(statuses),
        )


def _builtin_sandbox_backend_registry(
    local_backend: object | None = None,
) -> SandboxBackendRegistry:
    """Build the one non-injectable backend set admitted for managed processes."""

    from loushang.harness.workspace.exec import LocalExecBackend

    from .backends.linux import LinuxBubblewrapBackend
    from .runtime import _ExecServiceBackend

    trusted_backend = local_backend is None or type(local_backend) is LocalExecBackend
    if type(local_backend) is _ExecServiceBackend:
        trusted_backend = local_backend._uses_builtin_local_backend()
    if not trusted_backend:
        raise TypeError("managed Sandbox registry requires the builtin local backend")

    registration = SandboxBackendRegistration(
        backend_id=LinuxBubblewrapBackend.backend_id,
        os_families=frozenset({"linux"}),
        factory=lambda: LinuxBubblewrapBackend(
            local_backend=local_backend,  # type: ignore[arg-type]
        ),
    )
    registry = SandboxBackendRegistry((registration,))
    registry_id = id(registry)
    provider = cast(
        Callable[..., object],
        LinuxBubblewrapBackend.__dict__["_plan_hosted_process"],
    )
    probe = cast(
        Callable[..., object],
        LinuxBubblewrapBackend.__dict__["probe"],
    )

    def discard(reference: weakref.ReferenceType[SandboxBackendRegistry]) -> None:
        current = _MANAGED_REGISTRIES.get(registry_id)
        if current is not None and current.registry_ref is reference:
            _MANAGED_REGISTRIES.pop(registry_id, None)

    registry_ref = weakref.ref(registry, discard)
    _MANAGED_REGISTRIES[registry_id] = _ManagedRegistryRecord(
        registry_ref=registry_ref,
        registration=registration,
        factory=registration.factory,
        authority=object(),
        backend_type=LinuxBubblewrapBackend,
        provider=provider,
        probe=probe,
    )
    return registry


@dataclass(frozen=True, slots=True)
class _ManagedRegistryRecord:
    registry_ref: weakref.ReferenceType[SandboxBackendRegistry]
    registration: SandboxBackendRegistration
    factory: SandboxBackendFactory
    authority: object
    backend_type: type[object]
    provider: Callable[..., object]
    probe: Callable[..., object]


@dataclass(frozen=True, slots=True)
class _ManagedResolutionRecord:
    resolution_ref: weakref.ReferenceType[SandboxBackendResolution]
    registry: SandboxBackendRegistry
    registration: SandboxBackendRegistration
    backend: SandboxBackend
    statuses: tuple[SandboxBackendStatus, ...]
    authority: object
    provider: Callable[..., object]
    backend_state: tuple[object, ...]


_MANAGED_REGISTRIES: dict[int, _ManagedRegistryRecord] = {}
_MANAGED_RESOLUTIONS: dict[int, _ManagedResolutionRecord] = {}


def _verified_managed_registry(
    registry: SandboxBackendRegistry,
) -> _ManagedRegistryRecord | None:
    record = _MANAGED_REGISTRIES.get(id(registry))
    registrations = getattr(registry, "_registrations", None)
    backend_type = record.backend_type if record is not None else None
    if (
        record is None
        or record.registry_ref() is not registry
        or type(registrations) is not tuple
        or len(registrations) != 1
        or registrations[0] is not record.registration
        or record.registration.factory is not record.factory
        or backend_type is None
        or backend_type.__dict__.get("_plan_hosted_process") is not record.provider
        or backend_type.__dict__.get("probe") is not record.probe
    ):
        return None
    return record


def _register_managed_resolution(
    resolution: SandboxBackendResolution,
    *,
    registry_record: _ManagedRegistryRecord,
    backend: SandboxBackend,
) -> None:
    backend_state = _managed_backend_state(
        backend,
        backend_type=registry_record.backend_type,
    )
    if (
        backend_state is None
        or getattr(backend, "_managed_process_bindings", None) is not True
        or getattr(backend, "_managed_process_unavailable_reason", None) is not None
        or registry_record.backend_type.__dict__.get("_plan_hosted_process")
        is not registry_record.provider
    ):
        return
    resolution_id = id(resolution)

    def discard(reference: weakref.ReferenceType[SandboxBackendResolution]) -> None:
        current = _MANAGED_RESOLUTIONS.get(resolution_id)
        if current is not None and current.resolution_ref is reference:
            _MANAGED_RESOLUTIONS.pop(resolution_id, None)

    resolution_ref = weakref.ref(resolution, discard)
    registry = registry_record.registry_ref()
    assert registry is not None
    _MANAGED_RESOLUTIONS[resolution_id] = _ManagedResolutionRecord(
        resolution_ref=resolution_ref,
        registry=registry,
        registration=registry_record.registration,
        backend=backend,
        statuses=resolution.statuses,
        authority=registry_record.authority,
        provider=registry_record.provider,
        backend_state=backend_state,
    )


def _verified_managed_resolution(
    resolution: SandboxBackendResolution,
) -> _ManagedResolutionRecord | None:
    record = _MANAGED_RESOLUTIONS.get(id(resolution))
    registry = record.registry if record is not None else None
    registry_record = (
        _verified_managed_registry(registry) if registry is not None else None
    )
    if (
        record is None
        or record.resolution_ref() is not resolution
        or registry_record is None
        or registry_record.registration is not record.registration
        or registry_record.authority is not record.authority
        or resolution.backend is not record.backend
        or resolution.statuses is not record.statuses
        or resolution.selected_status is None
        or _managed_backend_state(
            record.backend,
            backend_type=registry_record.backend_type,
        )
        != record.backend_state
    ):
        return None
    return record


def _managed_backend_state(
    backend: object,
    *,
    backend_type: type[object],
) -> tuple[object, ...] | None:
    expected_fields = {
        "_available",
        "_closed",
        "_configured_path",
        "_executable_finder",
        "_local_backend",
        "_managed_process_bindings",
        "_managed_process_unavailable_reason",
        "_probe_runner",
        "_resolved_path",
    }
    state = vars(backend)
    if type(backend) is not backend_type or set(state) != expected_fields:
        return None
    return (
        state["_configured_path"],
        state["_executable_finder"],
        state["_probe_runner"],
        state["_local_backend"],
        state["_managed_process_bindings"],
        state["_managed_process_unavailable_reason"],
        state["_resolved_path"],
        state["_available"],
        state["_closed"],
    )


__all__ = [
    "SandboxBackendFactory",
    "SandboxBackendRegistration",
    "SandboxBackendRegistry",
    "SandboxBackendResolution",
]
