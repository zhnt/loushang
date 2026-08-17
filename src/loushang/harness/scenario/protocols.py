from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias


@dataclass(frozen=True)
class CommandRunResult:
    exit_code: int
    stdout: str
    stderr: str
    error: str | None = None


class CommandRunner(Protocol):
    """Execute an assertion command under Product-selected policy."""

    def __call__(
        self,
        command: str,
        *,
        cwd: Path,
        timeout_s: float | None,
    ) -> CommandRunResult | Awaitable[CommandRunResult]: ...


class ScenarioAdapter(Protocol):
    async def run_prompt(self, prompt: str) -> str:
        """Submit one Product-defined input and return its visible text result."""


WorkflowAdapter: TypeAlias = ScenarioAdapter


__all__ = [
    "CommandRunner",
    "CommandRunResult",
    "ScenarioAdapter",
    "WorkflowAdapter",
]
