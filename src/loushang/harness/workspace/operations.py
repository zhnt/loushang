from __future__ import annotations

import inspect
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias, TypeVar

from loushang.harness.authorization.execution_profile import (
    EffectiveExecutionProfile,
    ExecutionProfileProvider,
    execution_path_is_covered,
    select_execution_profile,
)

T = TypeVar("T")
OperationResult: TypeAlias = T | Awaitable[T]


async def resolve_operation(value: OperationResult[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


class ReadOperations(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def is_file(self, path: Path) -> OperationResult[bool]: ...

    def read_bytes(self, path: Path) -> OperationResult[bytes]: ...


class WriteOperations(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def is_file(self, path: Path) -> OperationResult[bool]: ...

    def mkdir(self, path: Path, *, parents: bool, exist_ok: bool) -> OperationResult[None]: ...

    def write_text(self, path: Path, content: str, *, newline: str | None = None) -> OperationResult[None]: ...


class EditOperations(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def is_file(self, path: Path) -> OperationResult[bool]: ...

    def read_text(self, path: Path, *, newline: str | None = None) -> OperationResult[str]: ...

    def write_text(self, path: Path, content: str, *, newline: str | None = None) -> OperationResult[None]: ...


class LsOperations(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def is_dir(self, path: Path) -> OperationResult[bool]: ...

    def iterdir(self, path: Path) -> OperationResult[Iterable[Path]]: ...


class FindOperations(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def is_dir(self, path: Path) -> OperationResult[bool]: ...

    def walk_files(self, path: Path) -> OperationResult[Iterable[Path]]: ...


class GrepOperations(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def is_file(self, path: Path) -> OperationResult[bool]: ...

    def is_dir(self, path: Path) -> OperationResult[bool]: ...

    def read_text(self, path: Path, *, newline: str | None = None) -> OperationResult[str]: ...

    def walk_files(self, path: Path) -> OperationResult[Iterable[Path]]: ...


class ToolOperations(
    ReadOperations,
    WriteOperations,
    EditOperations,
    LsOperations,
    FindOperations,
    GrepOperations,
    Protocol,
):
    pass


class WorkspaceOperationAdmission:
    """Apply the live execution ceiling before delegating a file operation."""

    __slots__ = ()

    root: Path
    operations: ToolOperations
    execution_profile: EffectiveExecutionProfile
    execution_profile_provider: ExecutionProfileProvider | None
    _profile_type_error = "workspace operations require an EffectiveExecutionProfile"

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        object.__setattr__(self, "root", root)
        if not isinstance(self.execution_profile, EffectiveExecutionProfile):
            raise TypeError(self._profile_type_error)

    def exists(self, path: Path) -> OperationResult[bool]:
        return self.operations.exists(self._read_path(path))

    def is_file(self, path: Path) -> OperationResult[bool]:
        return self.operations.is_file(self._read_path(path))

    def is_dir(self, path: Path) -> OperationResult[bool]:
        return self.operations.is_dir(self._read_path(path))

    def read_bytes(self, path: Path) -> OperationResult[bytes]:
        return self.operations.read_bytes(self._read_path(path))

    def read_text(
        self,
        path: Path,
        *,
        newline: str | None = None,
    ) -> OperationResult[str]:
        return self.operations.read_text(self._read_path(path), newline=newline)

    def mkdir(
        self,
        path: Path,
        *,
        parents: bool,
        exist_ok: bool,
    ) -> OperationResult[None]:
        return self.operations.mkdir(
            self._write_path(path),
            parents=parents,
            exist_ok=exist_ok,
        )

    def write_text(
        self,
        path: Path,
        content: str,
        *,
        newline: str | None = None,
    ) -> OperationResult[None]:
        return self.operations.write_text(
            self._write_path(path),
            content,
            newline=newline,
        )

    def iterdir(self, path: Path) -> OperationResult[Iterable[Path]]:
        return self.operations.iterdir(self._read_path(path))

    def walk_files(self, path: Path) -> OperationResult[Iterable[Path]]:
        return self.operations.walk_files(self._read_path(path))

    def _read_path(
        self, path: Path, profile: EffectiveExecutionProfile | None = None
    ) -> Path:
        profile = profile or select_execution_profile(
            self.execution_profile, self.execution_profile_provider
        )
        candidate = path.expanduser().resolve()
        if (
            self.execution_profile_provider is None
            and not candidate.is_relative_to(self.root)
        ):
            raise PermissionError(
                f"workspace operation path is outside the admitted root: {path}"
            )
        if execution_path_is_covered(candidate, profile.denied_roots):
            raise PermissionError(f"workspace operation path is denied: {path}")
        if not execution_path_is_covered(candidate, profile.readable_roots):
            raise PermissionError(
                f"workspace operation path is outside the admitted readable roots: {path}"
            )
        return candidate

    def _write_path(self, path: Path) -> Path:
        profile = select_execution_profile(
            self.execution_profile, self.execution_profile_provider
        )
        candidate = self._read_path(path, profile)
        if not execution_path_is_covered(candidate, profile.writable_roots):
            raise PermissionError(
                "workspace operation path is outside the admitted writable roots"
            )
        return candidate


@dataclass(frozen=True, slots=True)
class ScopedWorkspaceOperations(WorkspaceOperationAdmission):
    """Bind admitted workspace operations to a live execution profile."""

    root: Path
    operations: ToolOperations
    execution_profile: EffectiveExecutionProfile
    execution_profile_provider: ExecutionProfileProvider | None = None


@dataclass(frozen=True)
class LocalToolOperations:
    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def read_text(self, path: Path, *, newline: str | None = None) -> str:
        with path.open("r", encoding="utf-8", newline=newline) as handle:
            return handle.read()

    def write_text(self, path: Path, content: str, *, newline: str | None = None) -> None:
        with path.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(content)

    def mkdir(self, path: Path, *, parents: bool, exist_ok: bool) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def iterdir(self, path: Path) -> Iterable[Path]:
        return path.iterdir()

    def walk_files(self, path: Path) -> Iterable[Path]:
        return (candidate for candidate in sorted(path.rglob("*")) if candidate.is_file())


LOCAL_TOOL_OPERATIONS = LocalToolOperations()
