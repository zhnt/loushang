from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SandboxRequirement = Literal["best_effort", "required"]
NetworkAccess = Literal["denied", "restricted", "allowed"]
SandboxBackendState = Literal["not_applicable", "available", "unavailable"]
SandboxServiceState = Literal["disabled", "enabled", "degraded", "unavailable"]
SandboxScopeState = Literal["enforcing", "degraded"]

_REQUIREMENTS: frozenset[str] = frozenset({"best_effort", "required"})
_NETWORK_ACCESS: frozenset[str] = frozenset({"denied", "restricted", "allowed"})
_BACKEND_STATES: frozenset[str] = frozenset(
    {"not_applicable", "available", "unavailable"}
)
_SERVICE_STATES: frozenset[str] = frozenset(
    {"disabled", "enabled", "degraded", "unavailable"}
)
_SCOPE_STATES: frozenset[str] = frozenset({"enforcing", "degraded"})


@dataclass(frozen=True, slots=True)
class SandboxSettings:
    enabled: bool = False
    requirement: SandboxRequirement = "best_effort"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("sandbox enabled must be a bool")
        if self.requirement not in _REQUIREMENTS:
            raise ValueError(f"unsupported sandbox requirement: {self.requirement!r}")
        if not self.enabled and self.requirement == "required":
            raise ValueError("required sandboxing cannot be disabled")


@dataclass(frozen=True, slots=True)
class SandboxScopeRequest:
    cwd: Path
    readable_roots: tuple[Path, ...] = ()
    writable_roots: tuple[Path, ...] = ()
    denied_roots: tuple[Path, ...] = ()
    network: NetworkAccess = "allowed"

    def __post_init__(self) -> None:
        if self.network not in _NETWORK_ACCESS:
            raise ValueError(f"unsupported sandbox network access: {self.network!r}")
        object.__setattr__(self, "cwd", _normalize_absolute_path(self.cwd, "cwd"))
        for name in ("readable_roots", "writable_roots", "denied_roots"):
            object.__setattr__(
                self,
                name,
                _normalize_absolute_paths(getattr(self, name), name),
            )


@dataclass(frozen=True, slots=True)
class SandboxBackendStatus:
    backend_id: str
    state: SandboxBackendState
    enforced_capabilities: frozenset[str] = frozenset()
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.backend_id, "backend_id")
        if self.state not in _BACKEND_STATES:
            raise ValueError(f"unsupported sandbox backend state: {self.state!r}")
        object.__setattr__(
            self,
            "enforced_capabilities",
            _normalize_capabilities(self.enforced_capabilities),
        )
        if self.state != "available" and not self.reason:
            raise ValueError(f"{self.state} sandbox backend status requires a reason")


@dataclass(frozen=True, slots=True)
class SandboxStatus:
    state: SandboxServiceState
    backend_id: str | None = None
    enforced_capabilities: frozenset[str] = frozenset()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in _SERVICE_STATES:
            raise ValueError(f"unsupported sandbox service state: {self.state!r}")
        if self.backend_id is not None:
            _require_nonempty(self.backend_id, "backend_id")
        object.__setattr__(
            self,
            "enforced_capabilities",
            _normalize_capabilities(self.enforced_capabilities),
        )
        if self.state in {"degraded", "unavailable"} and not self.reason:
            raise ValueError(f"{self.state} sandbox status requires a reason")


@dataclass(frozen=True, slots=True)
class SandboxScopeDescriptor:
    state: SandboxScopeState
    backend_id: str | None = None
    enforced_capabilities: frozenset[str] = frozenset()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in _SCOPE_STATES:
            raise ValueError(f"unsupported sandbox scope state: {self.state!r}")
        if self.backend_id is not None:
            _require_nonempty(self.backend_id, "backend_id")
        object.__setattr__(
            self,
            "enforced_capabilities",
            _normalize_capabilities(self.enforced_capabilities),
        )
        if self.state == "enforcing" and self.backend_id is None:
            raise ValueError("an enforcing sandbox scope requires a backend_id")
        if self.state == "degraded" and not self.reason:
            raise ValueError("a degraded sandbox scope requires a reason")


@dataclass(frozen=True, slots=True)
class SandboxDiagnostic:
    code: str
    message: str
    backend_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.code, "diagnostic code")
        _require_nonempty(self.message, "diagnostic message")
        if self.backend_id is not None:
            _require_nonempty(self.backend_id, "backend_id")


class SandboxUnavailableError(RuntimeError):
    pass


def _normalize_absolute_paths(
    values: tuple[Path, ...] | list[Path],
    name: str,
) -> tuple[Path, ...]:
    if isinstance(values, (str, bytes, Path)):
        raise TypeError(f"{name} must be a sequence of paths")
    normalized: list[Path] = []
    for value in values:
        path = _normalize_absolute_path(value, name)
        if path not in normalized:
            normalized.append(path)
    return tuple(normalized)


def _normalize_absolute_path(value: Path, name: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"sandbox {name} paths must be absolute: {path}")
    return path.resolve(strict=False)


def _normalize_capabilities(values: frozenset[str]) -> frozenset[str]:
    normalized = frozenset(values)
    if any(not isinstance(value, str) or not value for value in normalized):
        raise ValueError("sandbox capabilities must be non-empty strings")
    return normalized


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


__all__ = [
    "NetworkAccess",
    "SandboxBackendState",
    "SandboxBackendStatus",
    "SandboxDiagnostic",
    "SandboxRequirement",
    "SandboxScopeDescriptor",
    "SandboxScopeRequest",
    "SandboxScopeState",
    "SandboxServiceState",
    "SandboxSettings",
    "SandboxStatus",
    "SandboxUnavailableError",
]
