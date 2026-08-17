"""Product-neutral composition and dispatch of dynamic command sources."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposer,
    CapabilityPackSource,
)
from loushang.harness.commands import (
    CommandDispatchOutcome,
    CommandHandler,
    CommandHandlerBinding,
    ParsedSlashCommand,
    dispatch_command_async,
    normalize_command_name,
)

DescriptorT = TypeVar("DescriptorT")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class CommandRuntimeSource(Generic[DescriptorT, ResultT]):
    """One approved dynamic command contribution source."""

    pack_id: str
    source: CapabilityPackSource
    descriptor_priority: int
    handler_priority: int
    list_descriptors: Callable[[], Iterable[DescriptorT]]
    handler_name: str
    handler: CommandHandler[ResultT]


@dataclass
class SessionCommandRuntime(Generic[DescriptorT, ResultT]):
    """Compose and dispatch dynamic command sources for one runtime owner."""

    sources: tuple[CommandRuntimeSource[DescriptorT, ResultT], ...]
    pack_composer: CapabilityPackComposer = field(
        default_factory=CapabilityPackComposer
    )

    def list_commands(self) -> list[DescriptorT]:
        packs = tuple(
            CapabilityPack(
                pack_id=source.pack_id,
                source=source.source,
                priority=source.descriptor_priority,
                items=tuple(source.list_descriptors()),
            )
            for source in self.sources
        )
        return list(self.pack_composer.compose(packs).items)

    async def dispatch(
        self,
        invocation_name: str,
        args: str,
    ) -> CommandDispatchOutcome[ResultT]:
        """Return the complete disposition, preserving handled ``None``."""

        normalized_name = normalize_command_name(invocation_name)
        invocation = ParsedSlashCommand(
            name=normalized_name,
            args=args,
            is_mcp=normalized_name.endswith(" (MCP)"),
        )
        handlers = self.pack_composer.compose(
            CapabilityPack(
                pack_id=source.pack_id,
                source=source.source,
                priority=source.handler_priority,
                items=(CommandHandlerBinding(source.handler_name, source.handler),),
            )
            for source in self.sources
        ).items
        return await dispatch_command_async(invocation, handlers)

    async def execute(
        self,
        invocation_name: str,
        args: str,
    ) -> ResultT | None:
        """Compatibility result surface for callers that do not need disposition."""

        outcome = await self.dispatch(invocation_name, args)
        return outcome.result if outcome.handled else None


__all__ = ["CommandRuntimeSource", "SessionCommandRuntime"]
