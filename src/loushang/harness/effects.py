"""Product-neutral protected-resource effects declared by tool actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

FilesystemOperation = Literal["read", "write", "delete"]


def _non_empty_strings(
    values: tuple[str, ...] | list[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    normalized = tuple(values)
    if not normalized or any(
        not isinstance(value, str) or not value for value in normalized
    ):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return normalized


@dataclass(frozen=True, slots=True)
class FilesystemEffect:
    operation: FilesystemOperation
    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.operation not in {"read", "write", "delete"}:
            raise ValueError(f"unsupported filesystem operation: {self.operation}")
        object.__setattr__(
            self,
            "paths",
            _non_empty_strings(self.paths, field_name="filesystem effect paths"),
        )

    @property
    def capability(self) -> str:
        return f"filesystem.{self.operation}"


@dataclass(frozen=True, slots=True)
class ProcessEffect:
    command: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command",
            _non_empty_strings(self.command, field_name="process effect command"),
        )

    @property
    def capability(self) -> str:
        return "process.execute"


@dataclass(frozen=True, slots=True)
class NetworkEffect:
    target: str
    mutation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("network effect target must be a non-empty string")
        if not isinstance(self.mutation, bool):
            raise TypeError("network effect mutation must be a boolean")

    @property
    def capability(self) -> str:
        return "network.mutate" if self.mutation else "network.request"


@dataclass(frozen=True, slots=True)
class PublicationEffect:
    target: str
    repository: str | None = None
    remote: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("publication effect target must be a non-empty string")
        for name, value in (
            ("repository", self.repository),
            ("remote", self.remote),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(
                    f"publication effect {name} must be a non-empty string or None"
                )

    @property
    def capability(self) -> str:
        return "repository.publish"


ToolEffect: TypeAlias = (
    FilesystemEffect | ProcessEffect | NetworkEffect | PublicationEffect
)


def effect_capability(effect: ToolEffect) -> str:
    return effect.capability


def effect_snapshot(effect: ToolEffect) -> dict[str, object]:
    if isinstance(effect, FilesystemEffect):
        return {
            "kind": "filesystem",
            "capability": effect.capability,
            "operation": effect.operation,
            "paths": effect.paths,
        }
    if isinstance(effect, ProcessEffect):
        return {
            "kind": "process",
            "capability": effect.capability,
            "command": effect.command,
        }
    if isinstance(effect, NetworkEffect):
        return {
            "kind": "network",
            "capability": effect.capability,
            "target": effect.target,
            "mutation": effect.mutation,
        }
    if isinstance(effect, PublicationEffect):
        return {
            "kind": "publication",
            "capability": effect.capability,
            "target": effect.target,
            "repository": effect.repository,
            "remote": effect.remote,
        }
    raise TypeError(f"unsupported tool effect: {type(effect).__name__}")


def effect_audit_summary(effect: ToolEffect) -> dict[str, object]:
    """Describe an effect without copying raw resource values into audit."""

    if isinstance(effect, FilesystemEffect):
        return {
            "kind": "filesystem",
            "capability": effect.capability,
            "path_count": len(effect.paths),
        }
    if isinstance(effect, ProcessEffect):
        return {
            "kind": "process",
            "capability": effect.capability,
            "argument_count": max(0, len(effect.command) - 1),
        }
    if isinstance(effect, NetworkEffect):
        return {
            "kind": "network",
            "capability": effect.capability,
            "mutation": effect.mutation,
        }
    if isinstance(effect, PublicationEffect):
        return {
            "kind": "publication",
            "capability": effect.capability,
            "repository_configured": effect.repository is not None,
            "remote_configured": effect.remote is not None,
        }
    raise TypeError(f"unsupported tool effect: {type(effect).__name__}")


__all__ = [
    "FilesystemEffect",
    "FilesystemOperation",
    "NetworkEffect",
    "ProcessEffect",
    "PublicationEffect",
    "ToolEffect",
    "effect_audit_summary",
    "effect_capability",
    "effect_snapshot",
]
