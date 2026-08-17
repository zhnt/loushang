"""Product-neutral binding of parsed CLI commands to Product handlers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.harness.cli.types import CliInvocation, CliProfileError

CliOperationHandler: TypeAlias = Callable[
    [CliInvocation], object | Awaitable[object]
]
CliExitOperationHandler: TypeAlias = Callable[
    [], int | None | Awaitable[int | None]
]


class CliOperationUnavailableError(LookupError):
    """Raised when a profile command has no bound Product operation."""


@dataclass(frozen=True, slots=True)
class CliOperationSpec:
    """One command-to-handler binding supplied by a Product host."""

    operation_id: str
    handler: CliOperationHandler
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation_id.strip():
            raise CliProfileError("CLI operation id must be non-empty")
        if not callable(self.handler):
            raise TypeError("CLI operation handler must be callable")
        if any(not alias or alias.startswith("-") for alias in self.aliases):
            raise CliProfileError("CLI operation aliases must be command names")

    @property
    def names(self) -> tuple[str, ...]:
        return (self.operation_id, *self.aliases)


class CliOperationRuntime:
    """Resolve a parsed command and invoke the injected Product handler.

    This runtime does not know about sessions, transports, JSON, or Product
    command semantics.  Channel or a Product host owns framing and error
    projection; Harness owns only this binding and duplicate detection.
    """

    def __init__(self, operations: Mapping[str, CliOperationSpec]) -> None:
        by_name: dict[str, CliOperationSpec] = {}
        for key, operation in operations.items():
            if key != operation.operation_id:
                raise CliProfileError(
                    "CLI operation mapping keys must match operation_id"
                )
            for name in operation.names:
                if name in by_name:
                    raise CliProfileError(f"duplicate CLI operation name: {name!r}")
                by_name[name] = operation
        self._operations = by_name

    async def dispatch(self, invocation: CliInvocation) -> object:
        if invocation.command_id is None:
            raise CliOperationUnavailableError(
                "CLI invocation does not identify a command operation"
            )
        return await self.dispatch_name(invocation.command_id, invocation)

    async def dispatch_name(
        self,
        operation_name: str,
        invocation: CliInvocation,
    ) -> object:
        try:
            operation = self._operations[operation_name]
        except KeyError as exc:
            raise CliOperationUnavailableError(
                f"CLI operation is not bound: {operation_name}"
            ) from exc
        result = operation.handler(invocation)
        if inspect.isawaitable(result):
            return await result
        return result


@dataclass(frozen=True, slots=True)
class CliOperationStage:
    """One ordered, product-selected CLI operation."""

    operation_id: str
    handler: CliExitOperationHandler

    def __post_init__(self) -> None:
        if not self.operation_id.strip():
            raise CliProfileError("CLI operation stage id must be non-empty")
        if not callable(self.handler):
            raise TypeError("CLI operation stage handler must be callable")


@dataclass(frozen=True, slots=True)
class CliOperationInsertion:
    """Insert one Product-selected stage relative to a shared stage."""

    stage: CliOperationStage
    target_operation_id: str
    position: Literal["before", "after"] = "after"

    def __post_init__(self) -> None:
        if not self.target_operation_id.strip():
            raise CliProfileError("CLI insertion target must be non-empty")


def compose_cli_operation_stages(
    stages: Sequence[CliOperationStage],
    insertions: Sequence[CliOperationInsertion] = (),
) -> tuple[CliOperationStage, ...]:
    """Compose shared stages with explicit Product insertions."""

    composed = list(stages)
    for insertion in insertions:
        matching_indexes = [
            index
            for index, stage in enumerate(composed)
            if stage.operation_id == insertion.target_operation_id
        ]
        if not matching_indexes:
            raise CliProfileError(
                "CLI insertion target is not present: "
                f"{insertion.target_operation_id!r}"
            )
        index = matching_indexes[0]
        if insertion.position == "after":
            index += 1
        composed.insert(index, insertion.stage)
    return tuple(composed)


class CliOperationSequence:
    """Run ordered CLI operations until one handles the invocation.

    Products own the stage list and therefore command availability and
    precedence. Harness owns the reusable synchronous/asynchronous dispatch
    contract.
    """

    def __init__(self, stages: Sequence[CliOperationStage]) -> None:
        seen: set[str] = set()
        for stage in stages:
            if stage.operation_id in seen:
                raise CliProfileError(
                    f"duplicate CLI operation stage: {stage.operation_id!r}"
                )
            seen.add(stage.operation_id)
        self._stages = tuple(stages)

    async def run(self) -> int | None:
        for stage in self._stages:
            result = stage.handler()
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                return result
        return None


__all__ = [
    "CliOperationHandler",
    "CliOperationRuntime",
    "CliOperationInsertion",
    "CliOperationSpec",
    "CliOperationSequence",
    "CliOperationStage",
    "CliOperationUnavailableError",
    "compose_cli_operation_stages",
]
