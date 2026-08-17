from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, TypeAlias

from ..json import JSONValue

ProblemSeverity: TypeAlias = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class ProblemRecord:
    code: str
    severity: ProblemSeverity = "error"
    source: str | None = None
    message: str = ""
    recoverable: bool = False
    details: dict[str, JSONValue] = field(default_factory=dict)
    exception_type: str | None = None
    exception_message: str | None = None
    time: str = ""
    monotonic_ms: int = 0
    module: str | None = None
    component: str | None = None
    session_id: str | None = None
    run_id: int | str | None = None
    cwd: str | None = None
    mode: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        return asdict(self)


@dataclass(frozen=True)
class DebugEventRecord:
    scope: str
    name: str
    data: dict[str, JSONValue] = field(default_factory=dict)
    time: str = ""
    monotonic_ms: int = 0
    module: str | None = None
    component: str | None = None
    session_id: str | None = None
    run_id: int | str | None = None
    cwd: str | None = None
    mode: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        return asdict(self)


__all__ = ["DebugEventRecord", "ProblemRecord", "ProblemSeverity"]
