from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self


@dataclass(frozen=True, slots=True)
class TerminalProcessDiagnostics:
    backend: str
    pid: int | None
    argv: tuple[str, ...]
    cwd: Path
    columns: int
    rows: int
    exit_status: int | None
    reader_alive: bool
    reader_error: str | None
    unknown_queries: tuple[str, ...]
    output_tail: str
    termination: str | None = None


class TerminalProcessDriver(Protocol):
    backend_name: str

    @classmethod
    def spawn(
        cls,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        columns: int,
        rows: int,
    ) -> Self: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> Literal[False]: ...

    def write(self, text: str) -> None: ...

    def read_until(
        self, predicate: Callable[[str], bool], *, timeout: float
    ) -> str: ...

    def resize(self, *, columns: int, rows: int) -> None: ...

    def is_alive(self) -> bool: ...

    def wait(self, *, timeout: float) -> int: ...

    def terminate_tree(self, *, timeout: float) -> None: ...

    def close(self, *, timeout: float = 5.0) -> None: ...

    @property
    def raw_output(self) -> str: ...

    @property
    def diagnostics(self) -> TerminalProcessDiagnostics: ...
