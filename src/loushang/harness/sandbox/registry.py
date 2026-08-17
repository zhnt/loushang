from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
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
                return SandboxBackendResolution(
                    environment=environment,
                    backend=backend,
                    statuses=tuple(statuses),
                )

        return SandboxBackendResolution(
            environment=environment,
            backend=None,
            statuses=tuple(statuses),
        )


__all__ = [
    "SandboxBackendFactory",
    "SandboxBackendRegistration",
    "SandboxBackendRegistry",
    "SandboxBackendResolution",
]
