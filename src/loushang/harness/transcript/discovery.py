"""Portable provenance and health contracts for Session discovery.

Discovery is a read model.  A source may contribute candidates, aliases, and
diagnostics, but it never becomes a writable authority merely because it is
visible to a Product.  Products render these values while the transcript
lifecycle continues to own restore/import transactions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SessionSourceMode = Literal["canonical", "compatibility"]
SessionOrigin = Literal[
    "global",
    "cwd",
    "home",
    "configured",
    "custom",
]
SessionDiscoveryHealth = Literal[
    "available",
    "legacy",
    "needs_attention",
    "conflict",
]
SessionAssetHealthState = Literal[
    "available",
    "partial",
    "missing",
    "corrupt",
    "none",
    "unavailable",
]
SessionDiscoveryIssueCode = Literal[
    "unsafe_root",
    "unreadable_root",
]


def _nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _absolute_path(value: str | Path) -> Path:
    absolute = Path(os.path.abspath(Path(value).expanduser()))
    return absolute.parent.resolve(strict=False) / absolute.name


@dataclass(frozen=True, slots=True)
class SessionDiscoverySource:
    """One declared local transcript root, authority mode, and origin label.

    This path contract is intentionally machine-local. Remote and plugin-backed
    stores participate through Conversation providers instead of impersonating a
    filesystem root.
    """

    source_id: str
    root: Path
    mode: SessionSourceMode
    origin: SessionOrigin
    priority: int = 100

    def __post_init__(self) -> None:
        _nonempty(self.source_id, name="session discovery source_id")
        if self.mode not in {"canonical", "compatibility"}:
            raise ValueError("session discovery source mode is invalid")
        if self.origin not in {"global", "cwd", "home", "configured", "custom"}:
            raise ValueError("session discovery source origin is invalid")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("session discovery source priority must be non-negative")
        object.__setattr__(self, "root", _absolute_path(self.root))

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceId": self.source_id,
            "root": str(self.root),
            "mode": self.mode,
            "origin": self.origin,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class SessionLocator:
    """Stable identity for one exact machine-local discovered transcript."""

    source_id: str
    conversation_id: str
    session_file: Path
    revision: str

    def __post_init__(self) -> None:
        _nonempty(self.source_id, name="session locator source_id")
        _nonempty(self.conversation_id, name="session locator conversation_id")
        _nonempty(self.revision, name="session locator revision")
        object.__setattr__(self, "session_file", _absolute_path(self.session_file))

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceId": self.source_id,
            "conversationId": self.conversation_id,
            "sessionFile": str(self.session_file),
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class SessionDiscoveryMetadata:
    """Merged provenance attached to a projected Session summary."""

    locator: SessionLocator
    mode: SessionSourceMode
    origin: SessionOrigin
    health: SessionDiscoveryHealth
    aliases: tuple[SessionLocator, ...] = ()
    conflicts: tuple[SessionLocator, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.locator, SessionLocator):
            raise TypeError("session discovery locator must be a SessionLocator")
        if self.mode not in {"canonical", "compatibility"}:
            raise ValueError("session discovery mode is invalid")
        if self.origin not in {"global", "cwd", "home", "configured", "custom"}:
            raise ValueError("session discovery origin is invalid")
        if self.health not in {
            "available",
            "legacy",
            "needs_attention",
            "conflict",
        }:
            raise ValueError("session discovery health is invalid")
        aliases = tuple(self.aliases)
        conflicts = tuple(self.conflicts)
        if any(not isinstance(value, SessionLocator) for value in (*aliases, *conflicts)):
            raise TypeError("session discovery aliases must be SessionLocator values")
        if set(aliases) & set(conflicts):
            raise ValueError("a session locator cannot be both an alias and a conflict")
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "conflicts", conflicts)

    @property
    def resumable(self) -> bool:
        return self.health != "conflict"

    def to_dict(self) -> dict[str, object]:
        return {
            "locator": self.locator.to_dict(),
            "mode": self.mode,
            "origin": self.origin,
            "health": self.health,
            "resumable": self.resumable,
            "aliases": [value.to_dict() for value in self.aliases],
            "conflicts": [value.to_dict() for value in self.conflicts],
        }


@dataclass(frozen=True, slots=True)
class SessionDiscoveryIssue:
    """Fail-closed diagnostic for one declared discovery source."""

    source_id: str
    code: SessionDiscoveryIssueCode
    path: Path
    detail: str

    def __post_init__(self) -> None:
        _nonempty(self.source_id, name="session discovery issue source_id")
        if self.code not in {"unsafe_root", "unreadable_root"}:
            raise ValueError("session discovery issue code is invalid")
        _nonempty(self.detail, name="session discovery issue detail")
        object.__setattr__(self, "path", _absolute_path(self.path))

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceId": self.source_id,
            "code": self.code,
            "path": str(self.path),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SessionAssetHealthSummary:
    """Bounded selected-Session asset projection for CLI/TUI previews."""

    state: SessionAssetHealthState
    reference_count: int = 0
    object_count: int = 0
    total_bytes: int = 0
    available: int = 0
    missing: int = 0
    corrupt: int = 0

    def __post_init__(self) -> None:
        if self.state not in {
            "available",
            "partial",
            "missing",
            "corrupt",
            "none",
            "unavailable",
        }:
            raise ValueError("session asset health state is invalid")
        for name in (
            "reference_count",
            "object_count",
            "total_bytes",
            "available",
            "missing",
            "corrupt",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"session asset {name} must be non-negative")
        if self.available + self.missing + self.corrupt != self.reference_count:
            raise ValueError("session asset health counts do not match references")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "referenceCount": self.reference_count,
            "objectCount": self.object_count,
            "totalBytes": self.total_bytes,
            "available": self.available,
            "missing": self.missing,
            "corrupt": self.corrupt,
        }


def session_origin_from_resource_id(resource_id: str) -> SessionOrigin:
    """Map the machine-resource vocabulary to a stable Session origin."""

    if resource_id == "sessions.global":
        return "global"
    if resource_id == "sessions.cwd_compatibility":
        return "cwd"
    if resource_id == "sessions.home_compatibility":
        return "home"
    if resource_id.startswith("sessions.configured_compatibility."):
        return "configured"
    return "custom"


__all__ = [
    "SessionAssetHealthState",
    "SessionAssetHealthSummary",
    "SessionDiscoveryHealth",
    "SessionDiscoveryIssue",
    "SessionDiscoveryIssueCode",
    "SessionDiscoveryMetadata",
    "SessionDiscoverySource",
    "SessionLocator",
    "SessionOrigin",
    "SessionSourceMode",
    "session_origin_from_resource_id",
]
