from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, Protocol, TypeVar

SourceScope = Literal["user", "project", "temporary"]
SourceOrigin = Literal["package", "top-level"]
SourcePathT = TypeVar("SourcePathT", str, Path)


@dataclass(frozen=True)
class SourceInfo(Generic[SourcePathT]):
    path: SourcePathT
    source: str = "filesystem"
    scope: SourceScope = "project"
    origin: SourceOrigin = "top-level"
    base_dir: SourcePathT | None = None


class ResourceSourceDescriptor(Protocol):
    """Common provenance fields exposed by resource descriptors."""

    @property
    def source_path(self) -> Path: ...

    @property
    def source(self) -> str: ...

    @property
    def source_kind(self) -> str: ...

    @property
    def source_scope(self) -> str: ...

    @property
    def source_root(self) -> Path | None: ...


def create_source_info(
    path: str | Path,
    *,
    source: str = "filesystem",
    scope: SourceScope = "project",
    origin: SourceOrigin = "top-level",
    base_dir: str | Path | None = None,
) -> SourceInfo[str]:
    """Build the canonical string-path provenance record for a resource."""

    return SourceInfo(
        path=source_path_text(path),
        source=source,
        scope=scope,
        origin=origin,
        base_dir=source_path_text(base_dir) if base_dir is not None else None,
    )


def source_info_from_resource_descriptor(
    descriptor: ResourceSourceDescriptor,
) -> SourceInfo[str]:
    """Project shared resource descriptor provenance into ``SourceInfo``."""

    return create_source_info(
        descriptor.source_path,
        source=descriptor.source or "filesystem",
        scope=source_scope_from_descriptor(
            source_scope=descriptor.source_scope,
            source_kind=descriptor.source_kind,
        ),
        origin=source_origin_from_descriptor(
            source_scope=descriptor.source_scope,
            source_kind=descriptor.source_kind,
        ),
        base_dir=(
            descriptor.source_root
            if descriptor.source_root is not None
            else descriptor.source_path.parent
        ),
    )


def source_scope_from_descriptor(
    *, source_scope: object, source_kind: object
) -> SourceScope:
    if source_scope == "user":
        return "user"
    if source_kind == "temporary" or source_scope == "temporary":
        return "temporary"
    return "project"


def source_origin_from_descriptor(
    *, source_scope: object, source_kind: object
) -> SourceOrigin:
    if source_scope in {"package", "builtin"} or source_kind in {
        "external_package",
        "built_in",
    }:
        return "package"
    return "top-level"


def source_path_text(path: str | Path | object) -> str:
    if isinstance(path, Path):
        return path.as_posix()
    if isinstance(path, str):
        return path
    return str(path)


__all__ = [
    "ResourceSourceDescriptor",
    "SourceInfo",
    "SourceOrigin",
    "SourcePathT",
    "SourceScope",
    "create_source_info",
    "source_info_from_resource_descriptor",
    "source_origin_from_descriptor",
    "source_path_text",
    "source_scope_from_descriptor",
]
