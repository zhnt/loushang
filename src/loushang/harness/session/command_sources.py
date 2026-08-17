"""Product-bound source adapters for a live session command runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from loushang.harness.capabilities.prompt_preflight import (
    PromptPreflightResult,
    preflight_user_input,
)
from loushang.harness.commands import (
    CommandDispatchOutcome,
    ParsedSlashCommand,
    SessionCommandDescriptor,
    list_resource_command_descriptors,
    split_slash_command,
)
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.commands import list_extension_command_descriptors
from loushang.harness.extensions.types import ResolvedCommand
from loushang.harness.resources.types import ResourceBundle

ResultT = TypeVar("ResultT")
ResourceCommandKind = Literal["prompt", "skill"]


class ExtensionCommandProvider(Protocol):
    """Resolved extension commands available to a Product session."""

    def get_registered_commands(self) -> list[ResolvedCommand]: ...

    def get_command(self, invocation_name: str) -> ResolvedCommand | None: ...

    def create_command_context(self, *, fallback_cwd: str = "") -> object: ...

    async def get_command_argument_completions(
        self, invocation_name: str, prefix: str
    ) -> list[object] | None: ...


ExtensionCommandProviderFactory = Callable[[], ExtensionCommandProvider | None]
ExtensionCommandResultFactory = Callable[[ResolvedCommand], ResultT]
ExtensionCommandErrorRecorder = Callable[[ResolvedCommand, BaseException], None]


@dataclass
class ExtensionCommandSourceRuntime(Generic[ResultT]):
    """Expose and dispatch resolved extension commands through injected ports."""

    get_provider: ExtensionCommandProviderFactory
    get_cwd: Callable[[], str]
    result_factory: ExtensionCommandResultFactory[ResultT]
    record_error: ExtensionCommandErrorRecorder

    def list_descriptors(self) -> list[SessionCommandDescriptor]:
        provider = self.get_provider()
        if provider is None:
            return []
        return list_extension_command_descriptors(provider.get_registered_commands())

    async def dispatch(
        self, invocation: ParsedSlashCommand
    ) -> CommandDispatchOutcome[ResultT]:
        provider = self.get_provider()
        if provider is None:
            return CommandDispatchOutcome.unhandled()
        command = provider.get_command(invocation.name)
        if command is None:
            return CommandDispatchOutcome.unhandled()
        context = provider.create_command_context(fallback_cwd=self.get_cwd())
        try:
            await command.handler(invocation.args, context)
        except Exception as exc:
            self.record_error(command, exc)
        return CommandDispatchOutcome.handled_result(self.result_factory(command))

    async def get_argument_completions(
        self, invocation_name: str, prefix: str
    ) -> list[object] | None:
        provider = self.get_provider()
        if provider is None:
            return None
        return await provider.get_command_argument_completions(invocation_name, prefix)

    def extract_invocation(self, user_input: str) -> tuple[str, str] | None:
        provider = self.get_provider()
        if provider is None:
            return None
        parsed = split_slash_command(user_input)
        if parsed is None:
            return None
        invocation_name, args = parsed
        if provider.get_command(invocation_name) is None:
            return None
        return invocation_name, args


ResourceCommandBundleProvider = Callable[[], ResourceBundle | None]
DiagnosticDraftRecorder = Callable[[tuple[DiagnosticDraft, ...]], None]
ResourceCommandNotFoundRecorder = Callable[[str, str], None]
ResourceCommandResultFactory = Callable[[str, ResourceCommandKind, str], ResultT]


@dataclass
class ResourceCommandSourceRuntime(Generic[ResultT]):
    """Resolve resource slash commands while Products own diagnostics and views."""

    get_resource_bundle: ResourceCommandBundleProvider
    record_diagnostics: DiagnosticDraftRecorder
    record_command_not_found: ResourceCommandNotFoundRecorder
    result_factory: ResourceCommandResultFactory[ResultT]

    def list_descriptors(self) -> list[SessionCommandDescriptor]:
        return list_resource_command_descriptors(self.get_resource_bundle())

    def dispatch(
        self, invocation: ParsedSlashCommand
    ) -> CommandDispatchOutcome[ResultT]:
        result = self.execute(invocation.name, invocation.args)
        if result is None:
            return CommandDispatchOutcome.unhandled()
        return CommandDispatchOutcome.handled_result(result)

    def execute(self, invocation_name: str, args: str) -> ResultT | None:
        resource_bundle = self.get_resource_bundle()
        if resource_bundle is None:
            self.record_command_not_found(invocation_name, args)
            return None
        command_text = f"/{invocation_name}{f' {args}' if args else ''}"
        result = preflight_user_input(command_text, resource_bundle=resource_bundle)
        self.record_diagnostics(result.diagnostics)
        if result.diagnostics:
            return None
        if result.text == command_text:
            self.record_command_not_found(invocation_name, args)
            return None
        source: ResourceCommandKind = (
            "skill" if invocation_name.startswith("skill:") else "prompt"
        )
        return self.result_factory(invocation_name, source, result.text)

    def preflight_user_input(self, user_input: str) -> PromptPreflightResult:
        result = preflight_user_input(
            user_input,
            resource_bundle=self.get_resource_bundle(),
        )
        self.record_diagnostics(result.diagnostics)
        return result


__all__ = [
    "ExtensionCommandErrorRecorder",
    "ExtensionCommandProvider",
    "ExtensionCommandProviderFactory",
    "ExtensionCommandResultFactory",
    "ExtensionCommandSourceRuntime",
    "ResourceCommandBundleProvider",
    "ResourceCommandKind",
    "ResourceCommandNotFoundRecorder",
    "ResourceCommandResultFactory",
    "ResourceCommandSourceRuntime",
    "DiagnosticDraftRecorder",
]
