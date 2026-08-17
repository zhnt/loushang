from __future__ import annotations

import inspect
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias, TypeVar

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
