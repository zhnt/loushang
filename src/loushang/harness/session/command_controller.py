"""Product-neutral session command source composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from loushang.harness.capabilities.commands import (
    CommandRuntimeSource,
    SessionCommandRuntime,
)
from loushang.harness.capabilities.packs import CapabilityPackComposer
from loushang.harness.capabilities.prompt_preflight import PromptPreflightResult
from loushang.harness.commands import (
    CommandDispatchOutcome,
    ParsedSlashCommand,
    SessionCommandDescriptor,
    split_slash_command,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.types import ResolvedCommand
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.session.command_sources import (
    ExtensionCommandProvider,
    ExtensionCommandSourceRuntime,
    ResourceCommandSourceRuntime,
)
from loushang.harness.session.commands.catalog import (
    is_standard_session_command,
    list_standard_session_command_descriptors,
)
from loushang.harness.session.commands.execution import (
    StandardSessionCommandPorts,
    execute_standard_session_command_async,
)
from loushang.harness.session.commands.projection import (
    project_standard_session_command_result,
)
from loushang.harness.session.diagnostics import (
    SessionDiagnosticScope,
    SessionDiagnosticsRuntime,
)

ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class CommandExecutionResult:
    """Neutral result envelope for one named session command."""

    invocation_name: str
    result: object | None = None


class SessionCommandStorePort(Protocol):
    def get_header(self) -> object: ...

    def get_leaf_id(self) -> str | None: ...

    def get_cwd(self) -> str: ...


ExtensionRunnerProvider = Callable[[], ExtensionCommandProvider | None]
BuiltinDescriptorProvider = Callable[[], list[SessionCommandDescriptor]]
BuiltinCommandExecutor = Callable[[str, str], Awaitable[ResultT | None]]
BuiltinCommandMatcher = Callable[[str], bool]


@dataclass
class SessionCommandController(Generic[ResultT]):
    """Compose builtin, extension, and resource command sources.

    The controller deliberately accepts Product callbacks for builtin command
    definitions and result shaping. The source lifecycle, diagnostics routing,
    preflight behavior, and command runtime remain shared.
    """

    session_manager: SessionCommandStorePort
    get_extension_runner: ExtensionRunnerProvider
    get_resource_bundle: Callable[[], ResourceBundle | None]
    get_diagnostics_service: Callable[[], DiagnosticsService | None]
    result_factory: Callable[[str, object | None], ResultT]
    extension_result_factory: Callable[[ResolvedCommand], ResultT]
    builtin_descriptors: BuiltinDescriptorProvider = lambda: []
    builtin_executor: BuiltinCommandExecutor[ResultT] | None = None
    builtin_matcher: BuiltinCommandMatcher = lambda _name: False
    diagnostics_runtime: SessionDiagnosticsRuntime | None = None
    pack_composer: CapabilityPackComposer = field(
        default_factory=CapabilityPackComposer
    )
    _runtime: SessionCommandRuntime[SessionCommandDescriptor, ResultT] = field(
        init=False,
        repr=False,
    )
    _extension_source: ExtensionCommandSourceRuntime[ResultT] = field(
        init=False,
        repr=False,
    )
    _resource_source: ResourceCommandSourceRuntime[ResultT] = field(
        init=False,
        repr=False,
    )
    _diagnostics_runtime: SessionDiagnosticsRuntime = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._diagnostics_runtime = (
            self.diagnostics_runtime
            or SessionDiagnosticsRuntime(
                diagnostics_service=self.get_diagnostics_service(),
                get_scope=lambda: SessionDiagnosticScope(
                    session_id=self._conversation_id(),
                    entry_id=self.session_manager.get_leaf_id(),
                ),
                get_extension_diagnostics=lambda: None,
            )
        )
        self._extension_source = ExtensionCommandSourceRuntime(
            get_provider=self.get_extension_runner,
            get_cwd=self.session_manager.get_cwd,
            result_factory=self.extension_result_factory,
            record_error=lambda command, exc: (
                self._diagnostics_runtime.record_extension_command_error(
                    command=command,
                    exc=exc,
                )
            ),
        )
        self._resource_source = ResourceCommandSourceRuntime(
            get_resource_bundle=self.get_resource_bundle,
            record_diagnostics=self._diagnostics_runtime.record_preflight_diagnostics,
            record_command_not_found=self._diagnostics_runtime.record_command_not_found,
            result_factory=lambda invocation_name, source, text: self.result_factory(
                invocation_name,
                {"source": source, "text": text},
            ),
        )
        self._runtime = SessionCommandRuntime(
            sources=(
                CommandRuntimeSource(
                    pack_id="harness.standard-session-commands",
                    source="product",
                    descriptor_priority=300,
                    handler_priority=200,
                    list_descriptors=self.builtin_descriptors,
                    handler_name="standard-session",
                    handler=self._dispatch_builtin_command,
                ),
                CommandRuntimeSource(
                    pack_id="extension.commands",
                    source="extension",
                    descriptor_priority=200,
                    handler_priority=300,
                    list_descriptors=self._extension_source.list_descriptors,
                    handler_name="extension",
                    handler=self._extension_source.dispatch,
                ),
                CommandRuntimeSource(
                    pack_id="resource.commands",
                    source="product",
                    descriptor_priority=100,
                    handler_priority=100,
                    list_descriptors=self._resource_source.list_descriptors,
                    handler_name="resource",
                    handler=self._resource_source.dispatch,
                ),
            ),
            pack_composer=self.pack_composer,
        )

    def list_commands(self) -> list[SessionCommandDescriptor]:
        return self._runtime.list_commands()

    async def execute_command_async(
        self, invocation_name: str, args: str
    ) -> ResultT | None:
        return await self._runtime.execute(invocation_name, args)

    async def _dispatch_builtin_command(
        self,
        invocation: ParsedSlashCommand,
    ) -> CommandDispatchOutcome[ResultT]:
        result = await self.execute_builtin_command_async(
            invocation.name,
            invocation.args,
        )
        if result is None:
            return CommandDispatchOutcome.unhandled()
        return CommandDispatchOutcome.handled_result(result)

    async def execute_builtin_command_async(
        self, invocation_name: str, args: str
    ) -> ResultT | None:
        if self.builtin_executor is None:
            return None
        return await self.builtin_executor(invocation_name, args)

    def execute_resource_command(
        self, invocation_name: str, args: str
    ) -> ResultT | None:
        return self._resource_source.execute(invocation_name, args)

    def record_command_not_found(self, invocation_name: str, args: str) -> None:
        self._diagnostics_runtime.record_command_not_found(invocation_name, args)

    async def get_command_argument_completions(
        self, invocation_name: str, prefix: str
    ) -> list[object] | None:
        return await self._extension_source.get_argument_completions(
            invocation_name,
            prefix,
        )

    def extract_extension_command_invocation(
        self, user_input: str
    ) -> tuple[str, str] | None:
        return self._extension_source.extract_invocation(user_input)

    def extract_builtin_command_invocation(
        self, user_input: str
    ) -> tuple[str, str] | None:
        if self.builtin_executor is None:
            return None
        parsed = split_slash_command(user_input)
        if parsed is None or not self.builtin_matcher(parsed[0]):
            return None
        return parsed

    def raise_if_queued_extension_command(self, user_input: str) -> None:
        command = self.extract_extension_command_invocation(user_input)
        if command is not None:
            invocation_name, _args = command
            raise RuntimeError(
                f'Extension command "/{invocation_name}" cannot be queued. '
                "Use prompt() or execute the command when not streaming."
            )

    def preflight_user_input(
        self, user_input: str, *, allow_extension_commands: bool = True
    ) -> PromptPreflightResult:
        del allow_extension_commands
        return self._resource_source.preflight_user_input(user_input)

    async def preflight_user_input_async(
        self, user_input: str, *, allow_extension_commands: bool = True
    ) -> PromptPreflightResult:
        if allow_extension_commands:
            for command in (
                self.extract_extension_command_invocation(user_input),
                self.extract_builtin_command_invocation(user_input),
            ):
                if command is not None:
                    invocation_name, args = command
                    await self.execute_command_async(invocation_name, args)
                    return PromptPreflightResult(text=user_input, consumed=True)
        return self._resource_source.preflight_user_input(user_input)

    def record_preflight_diagnostics(
        self, diagnostics: tuple[DiagnosticDraft, ...]
    ) -> None:
        self._diagnostics_runtime.record_preflight_diagnostics(diagnostics)

    def record_extension_command_error(
        self, *, command: ResolvedCommand, exc: BaseException
    ) -> None:
        self._diagnostics_runtime.record_extension_command_error(
            command=command,
            exc=exc,
        )

    def _conversation_id(self) -> str:
        header = self.session_manager.get_header()
        conversation_id = getattr(header, "conversation_id", None)
        if not isinstance(conversation_id, str):
            raise TypeError("session header must expose a conversation_id")
        return conversation_id


class StandardSessionCommandController(
    SessionCommandController[CommandExecutionResult]
):
    """Bind the standard session command pack to shared command sources."""

    def __init__(
        self,
        *,
        session_manager: SessionCommandStorePort,
        get_extension_runner: ExtensionRunnerProvider,
        get_resource_bundle: Callable[[], ResourceBundle | None],
        get_diagnostics_service: Callable[[], DiagnosticsService | None],
        standard_ports: StandardSessionCommandPorts | None = None,
        diagnostics_runtime: SessionDiagnosticsRuntime | None = None,
        pack_composer: CapabilityPackComposer | None = None,
    ) -> None:
        super().__init__(
            session_manager=session_manager,
            get_extension_runner=get_extension_runner,
            get_resource_bundle=get_resource_bundle,
            get_diagnostics_service=get_diagnostics_service,
            result_factory=lambda invocation_name, result: CommandExecutionResult(
                invocation_name=invocation_name,
                result=result,
            ),
            extension_result_factory=lambda command: CommandExecutionResult(
                invocation_name=command.invocation_name,
                result=None,
            ),
            builtin_descriptors=(
                list_standard_session_command_descriptors
                if standard_ports is not None
                else (lambda: [])
            ),
            builtin_executor=(
                (
                    lambda invocation_name, args: _execute_standard_command(
                        invocation_name,
                        args,
                        standard_ports,
                    )
                )
                if standard_ports is not None
                else None
            ),
            builtin_matcher=is_standard_session_command,
            diagnostics_runtime=diagnostics_runtime,
            pack_composer=pack_composer or CapabilityPackComposer(),
        )


async def _execute_standard_command(
    invocation_name: str,
    args: str,
    ports: StandardSessionCommandPorts | None,
) -> CommandExecutionResult | None:
    if ports is None:
        return None
    result = await execute_standard_session_command_async(
        invocation_name,
        args,
        ports,
    )
    if result is None:
        return None
    return CommandExecutionResult(
        invocation_name=invocation_name,
        result=project_standard_session_command_result(result),
    )


__all__ = [
    "BuiltinCommandExecutor",
    "BuiltinCommandMatcher",
    "BuiltinDescriptorProvider",
    "SessionCommandController",
    "SessionCommandStorePort",
    "StandardSessionCommandController",
]
