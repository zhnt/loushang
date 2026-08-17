"""Standard Product-facing operations over an already composed Agent session.

``SessionRuntime`` owns the Agent loop, queues, event stream, and transcript
commit ordering.  The optional ``SessionFacade`` presents the common session
operations exposed by Products without choosing a model, prompt, extension API,
storage provider, or UI projection.  Products compose their existing adapters
and pass them in through narrow ports.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from loushang.ai.types import ImagePart
from loushang.harness.approval import (
    ApprovalOutcome,
    ApprovalPermissionsSnapshot,
)
from loushang.harness.events import RuntimeEvent
from loushang.harness.permissions import PermissionProfileSnapshot
from loushang.harness.session.facade_optional import (
    SessionApplicationInputPort,
    SessionDiagnosticsPort,
    SessionExtensionPort,
    SessionFacadeOptionalOperations,
    SessionModelPort,
    SessionPackagePort,
    SessionSettingsPort,
)
from loushang.harness.session.runtime import SessionRuntime
from loushang.harness.workspace.exec import ExecOutputChunk

ContextT = TypeVar("ContextT", covariant=True)
RecordT = TypeVar("RecordT", covariant=True)
StateT = TypeVar("StateT", covariant=True)
ToolT = TypeVar("ToolT", covariant=True)
CommandDescriptorT = TypeVar("CommandDescriptorT", covariant=True)
CommandResultT = TypeVar("CommandResultT", covariant=True)
UsageT = TypeVar("UsageT", covariant=True)
EventT = TypeVar("EventT")

RuntimeEventListener = Callable[[RuntimeEvent[object]], Awaitable[None] | None]
SessionEventListener = Callable[[EventT], Awaitable[None] | None]
SessionEventProjector = Callable[[RuntimeEvent[object]], EventT | None]
OutputCallback = Callable[[ExecOutputChunk], Awaitable[None] | None]
ApprovalRequestPresenter = Callable[
    [dict[str, object]], Awaitable[None] | None
]
ApprovalRequestDismisser = Callable[[str], Awaitable[None] | None]


class ApprovalPresentationLease(Protocol):
    """One generation-safe binding to a Session approval presenter."""

    def close(
        self,
        reason: str = "Approval presenter closed before approval was resolved",
    ) -> None: ...


class SessionApprovalInteractionPort(Protocol):
    """Optional presentation/response port over the authoritative resolver."""

    def bind_presenter(
        self,
        presenter: ApprovalRequestPresenter,
        *,
        dismisser: ApprovalRequestDismisser | None = None,
    ) -> ApprovalPresentationLease:
        """Atomically replace presentation and replay unresolved requests."""
        ...

    async def respond(
        self,
        action_id: str,
        *,
        outcome: ApprovalOutcome,
        reason: str | None = None,
    ) -> bool: ...

    def permissions_snapshot(self) -> ApprovalPermissionsSnapshot: ...

    def permission_profile_snapshot(self) -> PermissionProfileSnapshot: ...

    async def apply_permission_action(self, action: str) -> bool: ...


class SessionTranscriptPort(Protocol[ContextT, RecordT]):
    """Read-only transcript operations exposed on a session surface."""

    def build_session_context(self) -> ContextT: ...

    def get_session_record(self) -> RecordT: ...

    def get_session_file(self) -> object | None: ...


class SessionToolsPort(Protocol[ToolT]):
    """Product-admitted tool view and selection results."""

    def get_active_tool_names(self) -> list[str]: ...

    def get_all_tools(self) -> Sequence[ToolT]: ...

    def get_tool_definition(self, name: str) -> ToolT | None: ...


class SessionCommandsPort(Protocol[CommandDescriptorT, CommandResultT]):
    """Command catalog and dispatch supplied by the Product."""

    def list_commands(self) -> Sequence[CommandDescriptorT]: ...

    async def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> CommandResultT | None: ...


class SessionCommandExecutionPort(Protocol):
    """One Product-selected command tool, commonly a shell tool."""

    @property
    def is_running(self) -> bool: ...

    @property
    def has_pending_messages(self) -> bool: ...

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: list[list[str] | tuple[str, str]]
        | tuple[tuple[str, str], ...]
        | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        exclude_from_context: bool = False,
        on_output: OutputCallback | None = None,
        operations: object | None = None,
    ) -> dict[str, object]: ...

    async def record_result(
        self,
        *,
        command: str,
        result: Mapping[str, object],
        exclude_from_context: bool = False,
    ) -> None: ...

    def abort(self) -> None: ...


class SessionViewPort(Protocol[StateT, UsageT]):
    """Stable session inspection supplied by a Product projection adapter."""

    def get_state(self, *, steering: list[str], follow_up: list[str]) -> StateT: ...

    def get_context_usage(self) -> UsageT | None: ...

    def get_user_messages_for_forking(self) -> list[dict[str, str]]: ...

    def get_entry_text(self, entry_id: str) -> str | None: ...

    def get_last_assistant_text(self) -> str | None: ...

    def get_recent_assistant_texts(self) -> tuple[str, ...]: ...


class SessionRetryPort(Protocol):
    """Common retry controls whose policy remains Product-selected."""

    @property
    def is_retrying(self) -> bool: ...

    def abort(self) -> None: ...

    async def wait(self) -> None: ...


class SessionIdentityPort(Protocol):
    """Stable session identity and Product-persisted display metadata."""

    @property
    def session_id(self) -> str: ...

    @property
    def session_name(self) -> str | None: ...

    async def set_session_name(self, name: str | None) -> None: ...


class SessionMaintenancePort(Protocol):
    """Product-selected transcript maintenance controls."""

    @property
    def is_compacting(self) -> bool: ...

    @property
    def auto_retry_enabled(self) -> bool: ...

    @property
    def auto_compaction_enabled(self) -> bool: ...

    def set_auto_retry_enabled(self, enabled: bool) -> None: ...

    def set_auto_compaction_enabled(self, enabled: bool) -> None: ...

    async def compact(self, custom_instructions: str | None = None) -> object: ...

    def abort_compaction(self) -> None: ...


class SessionResourcePort(Protocol):
    """Resource refresh controls exposed by a composed Product session."""

    def get_prompt_templates(self) -> Sequence[object]: ...

    async def refresh_resources(self) -> None: ...

    def request_resource_refresh(self) -> None: ...


class SessionControlPort(Protocol):
    """Stable common control surface exposed by a composed Product session.

    This deliberately excludes Product vocabulary such as model selection,
    provider authentication, extension UI, and Product-specific command or
    output schemas.  Those remain on the Product adapter around this port.
    """

    @property
    def session_id(self) -> str: ...

    @property
    def session_name(self) -> str | None: ...

    async def set_session_name(self, name: str | None) -> None: ...

    def subscribe_runtime_events(
        self,
        listener: RuntimeEventListener,
    ) -> Callable[[], None]: ...

    async def prompt(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
        *,
        streaming_behavior: str | None = None,
        source: str | None = None,
        preflight_result: Callable[[bool], None] | None = None,
    ) -> None: ...

    def steer(self, user_input: str, images: list[ImagePart] | None = None) -> None: ...

    def follow_up(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
    ) -> None: ...

    @property
    def pending_message_count(self) -> int: ...

    def get_steering_messages(self) -> list[str]: ...

    def get_follow_up_messages(self) -> list[str]: ...

    def clear_queue(self) -> dict[str, list[str]]: ...

    async def continue_run(self) -> None: ...

    def abort(self) -> bool: ...

    async def wait_for_idle(self) -> None: ...

    def abort_retry(self) -> None: ...

    async def wait_for_retry(self) -> None: ...

    @property
    def is_retrying(self) -> bool: ...

    @property
    def is_compacting(self) -> bool: ...

    @property
    def auto_retry_enabled(self) -> bool: ...

    @property
    def auto_compaction_enabled(self) -> bool: ...

    def set_auto_retry_enabled(self, enabled: bool) -> None: ...

    def set_auto_compaction_enabled(self, enabled: bool) -> None: ...

    async def compact(self, custom_instructions: str | None = None) -> object: ...

    def abort_compaction(self) -> None: ...

    async def refresh_resources(self) -> None: ...

    def request_resource_refresh(self) -> None: ...


def require_active_session(runtime: object) -> object:
    """Resolve the active Session published by a Product runtime."""

    getter = getattr(runtime, "get_current_session", None)
    if not callable(getter):
        raise TypeError("Session runtime must provide get_current_session()")
    session = getter()
    if session is None:
        raise RuntimeError("Session runtime requires an active session")
    return session


def require_active_session_control(runtime: object) -> SessionControlPort:
    """Resolve the standard control port from an active Product runtime."""

    session = require_active_session(runtime)
    control = getattr(session, "session_control", None)
    if control is None:
        raise TypeError("Active session must expose session_control")
    return cast(SessionControlPort, control)


@dataclass(frozen=True)
class SessionFacadePorts(
    Generic[
        ContextT,
        RecordT,
        StateT,
        ToolT,
        CommandDescriptorT,
        CommandResultT,
        UsageT,
    ]
):
    """Product-bound adapters consumed by :class:`SessionFacade`.

    Keeping this composition object separate from ``SessionRuntime`` makes the
    ownership boundary explicit: Harness owns common session controls, while a
    Product supplies its transcript, capability, inspection, and retry ports.
    """

    transcript: SessionTranscriptPort[ContextT, RecordT]
    tools: SessionToolsPort[ToolT]
    commands: SessionCommandsPort[CommandDescriptorT, CommandResultT]
    command_execution: SessionCommandExecutionPort
    view: SessionViewPort[StateT, UsageT]
    retry: SessionRetryPort
    identity: SessionIdentityPort
    maintenance: SessionMaintenancePort
    resources: SessionResourcePort
    diagnostics: SessionDiagnosticsPort | None = None
    packages: SessionPackagePort | None = None
    model_selection: SessionModelPort | None = None
    extensions: SessionExtensionPort | None = None
    settings: SessionSettingsPort | None = None
    application_input: SessionApplicationInputPort | None = None
    approval_interaction: SessionApprovalInteractionPort | None = None
    event_projector: Callable[[RuntimeEvent[object]], object | None] | None = None


@dataclass
class SessionFacade(
    SessionFacadeOptionalOperations,
    Generic[
        ContextT,
        RecordT,
        StateT,
        ToolT,
        CommandDescriptorT,
        CommandResultT,
        UsageT,
    ]
):
    """Compose standard session controls without Product implementation policy.

    The passed ports are already admitted and bound by the Product.  This
    facade neither discovers capabilities nor interprets Product messages; it
    keeps the shared surface consistent across Coding, Research, Design, PPT,
    and OEM adapters that choose to expose it.
    """

    runtime: SessionRuntime
    transcript: SessionTranscriptPort[ContextT, RecordT]
    tools: SessionToolsPort[ToolT]
    commands: SessionCommandsPort[CommandDescriptorT, CommandResultT]
    command_execution: SessionCommandExecutionPort
    view: SessionViewPort[StateT, UsageT]
    retry: SessionRetryPort
    identity: SessionIdentityPort
    maintenance: SessionMaintenancePort
    resources: SessionResourcePort
    diagnostics: SessionDiagnosticsPort | None = None
    packages: SessionPackagePort | None = None
    model_selection: SessionModelPort | None = None
    extensions: SessionExtensionPort | None = None
    settings: SessionSettingsPort | None = None
    application_input: SessionApplicationInputPort | None = None
    approval_interaction: SessionApprovalInteractionPort | None = None
    event_projector: Callable[[RuntimeEvent[object]], object | None] | None = None

    @classmethod
    def from_ports(
        cls,
        *,
        runtime: SessionRuntime,
        ports: SessionFacadePorts[
            ContextT,
            RecordT,
            StateT,
            ToolT,
            CommandDescriptorT,
            CommandResultT,
            UsageT,
        ],
    ) -> "SessionFacade[ContextT, RecordT, StateT, ToolT, CommandDescriptorT, CommandResultT, UsageT]":
        """Build the common surface from a Product's explicit port bundle."""

        return cls(
            runtime=runtime,
            transcript=ports.transcript,
            tools=ports.tools,
            commands=ports.commands,
            command_execution=ports.command_execution,
            view=ports.view,
            retry=ports.retry,
            identity=ports.identity,
            maintenance=ports.maintenance,
            resources=ports.resources,
            diagnostics=ports.diagnostics,
            packages=ports.packages,
            model_selection=ports.model_selection,
            extensions=ports.extensions,
            settings=ports.settings,
            application_input=ports.application_input,
            approval_interaction=ports.approval_interaction,
            event_projector=ports.event_projector,
        )

    @property
    def session_control(self) -> SessionControlPort:
        """Expose the shared control surface without a Product subclass."""

        return self

    @property
    def session_id(self) -> str:
        return self.identity.session_id

    @property
    def session_name(self) -> str | None:
        return self.identity.session_name

    async def set_session_name(self, name: str | None) -> None:
        await self.identity.set_session_name(name)

    def get_state(self) -> StateT:
        return self.view.get_state(
            steering=self.runtime.queue.get_steering_messages(),
            follow_up=self.runtime.queue.get_follow_up_messages(),
        )

    def get_session_context(self) -> ContextT:
        return self.transcript.build_session_context()

    def get_session_record(self) -> RecordT:
        return self.transcript.get_session_record()

    def get_session_file(self) -> object | None:
        return self.transcript.get_session_file()

    def get_active_tool_names(self) -> list[str]:
        return self.tools.get_active_tool_names()

    def get_all_tools(self) -> list[ToolT]:
        return list(self.tools.get_all_tools())

    def get_tool_definition(self, name: str) -> ToolT | None:
        return self.tools.get_tool_definition(name)

    def get_all_tool_infos(self) -> list[dict[str, object]]:
        getter = getattr(self.tools, "get_all_tool_infos", None)
        if not callable(getter):
            return []
        return list(getter())

    def list_commands(self) -> list[CommandDescriptorT]:
        return list(self.commands.list_commands())

    async def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> CommandResultT | None:
        return await self.commands.execute_command_async(invocation_name, args)

    def get_context_usage(self) -> UsageT | None:
        return self.view.get_context_usage()

    def get_session_stats(self) -> dict[str, object]:
        """Project common Agent/session counters for a transport host."""

        from loushang.harness.session.inspection_projection import project_session_stats

        return project_session_stats(
            agent=self.runtime.agent,
            session_manager=self.transcript,
            context_usage=self.view.get_context_usage(),
        )

    @property
    def model(self) -> object:
        """Expose the bound Agent model without selecting a provider."""

        return getattr(self.runtime.agent, "model")

    @property
    def thinking_level(self) -> object:
        """Expose the bound Agent thinking level."""

        return getattr(self.runtime.agent, "thinking_level")

    @property
    def is_streaming(self) -> bool:
        return bool(getattr(self.runtime.agent, "is_streaming", False))

    @property
    def system_prompt(self) -> str:
        return str(getattr(self.runtime.agent, "system_prompt", ""))

    @property
    def retry_attempt(self) -> int:
        return int(getattr(self.retry, "attempt", 0))

    @property
    def messages(self) -> list[object]:
        state = getattr(self.runtime.agent, "state", None)
        messages = getattr(state, "messages", ())
        return messages if isinstance(messages, list) else list(messages)

    @property
    def extension_runner(self) -> object | None:
        getter = getattr(self.runtime.turn_policy, "get_extension_runner", None)
        return getter() if callable(getter) else None

    def get_user_messages_for_forking(self) -> list[dict[str, str]]:
        return self.view.get_user_messages_for_forking()

    def get_entry_text(self, entry_id: str) -> str | None:
        return self.view.get_entry_text(entry_id)

    def get_last_assistant_text(self) -> str | None:
        return self.view.get_last_assistant_text()

    def get_recent_assistant_texts(self) -> tuple[str, ...]:
        return self.view.get_recent_assistant_texts()

    def subscribe_runtime_events(
        self,
        listener: RuntimeEventListener,
    ) -> Callable[[], None]:
        return self.runtime.subscribe(listener)

    def subscribe(
        self,
        listener: SessionEventListener[EventT],
        *,
        project: SessionEventProjector[EventT] | None = None,
    ) -> Callable[[], None]:
        selected_project = project
        if selected_project is None:
            if self.event_projector is None:
                raise RuntimeError("A session event projector is not configured.")
            selected_project = cast(
                SessionEventProjector[EventT],
                self.event_projector,
            )

        def relay(event: RuntimeEvent[object]) -> Awaitable[None] | None:
            projected = selected_project(event)
            if projected is None:
                return None
            return listener(projected)

        return self.runtime.subscribe(relay)

    async def prompt(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
        *,
        streaming_behavior: str | None = None,
        source: str | None = None,
        preflight_result: Callable[[bool], None] | None = None,
    ) -> None:
        await self.runtime.prompt(
            user_input,
            images=images,
            streaming_behavior=streaming_behavior,
            source=source,
            preflight_result=preflight_result,
        )

    def steer(self, user_input: str, images: list[ImagePart] | None = None) -> None:
        self.runtime.steer(user_input, images=images)

    def follow_up(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
    ) -> None:
        self.runtime.follow_up(user_input, images=images)

    @property
    def pending_message_count(self) -> int:
        return self.runtime.queue.pending_message_count

    def get_steering_messages(self) -> list[str]:
        return self.runtime.queue.get_steering_messages()

    def get_follow_up_messages(self) -> list[str]:
        return self.runtime.queue.get_follow_up_messages()

    def clear_queue(self) -> dict[str, list[str]]:
        return self.runtime.queue.clear_queue()

    async def execute_command_tool(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: list[list[str] | tuple[str, str]]
        | tuple[tuple[str, str], ...]
        | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        exclude_from_context: bool = False,
        on_output: OutputCallback | None = None,
        operations: object | None = None,
    ) -> dict[str, object]:
        return await self.command_execution.execute(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            exclude_from_context=exclude_from_context,
            on_output=on_output,
            operations=operations,
        )

    async def execute_bash(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: list[list[str] | tuple[str, str]]
        | tuple[tuple[str, str], ...]
        | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        exclude_from_context: bool = False,
        on_output: OutputCallback | None = None,
        operations: object | None = None,
    ) -> dict[str, object]:
        """Execute the bound shell capability through the common facade."""

        return await self.execute_command_tool(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            exclude_from_context=exclude_from_context,
            on_output=on_output,
            operations=operations,
        )

    async def record_bash_result(
        self,
        command: str,
        result: Mapping[str, object],
        *,
        exclude_from_context: bool = False,
    ) -> None:
        record_result = getattr(self.command_execution, "record_result", None)
        if not callable(record_result):
            raise RuntimeError("Command result recording is not available.")
        await record_result(
            command=command,
            result=result,
            exclude_from_context=exclude_from_context,
        )

    @property
    def is_command_running(self) -> bool:
        return self.command_execution.is_running

    @property
    def has_pending_command_messages(self) -> bool:
        return self.command_execution.has_pending_messages

    async def continue_run(self) -> None:
        await self.runtime.continue_run()

    def abort(self) -> bool:
        return self.runtime.abort()

    async def wait_for_idle(self) -> None:
        await self.runtime.wait_for_idle()

    def abort_command(self) -> None:
        self.command_execution.abort()

    def abort_bash(self) -> None:
        """Abort the bound shell capability through the common facade."""

        self.abort_command()

    def abort_retry(self) -> None:
        self.retry.abort()

    async def wait_for_retry(self) -> None:
        await self.retry.wait()
        await self.runtime.wait_for_idle()

    @property
    def is_retrying(self) -> bool:
        return self.retry.is_retrying

    @property
    def is_compacting(self) -> bool:
        return self.maintenance.is_compacting

    @property
    def auto_retry_enabled(self) -> bool:
        return self.maintenance.auto_retry_enabled

    @property
    def auto_compaction_enabled(self) -> bool:
        return self.maintenance.auto_compaction_enabled

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.maintenance.set_auto_retry_enabled(enabled)

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.maintenance.set_auto_compaction_enabled(enabled)

    async def compact(self, custom_instructions: str | None = None) -> object:
        return await self.maintenance.compact(custom_instructions)

    def abort_compaction(self) -> None:
        self.maintenance.abort_compaction()

    def get_prompt_templates(self) -> list[object]:
        return list(self.resources.get_prompt_templates())

    async def refresh_resources(self) -> None:
        await self.resources.refresh_resources()

    def request_resource_refresh(self) -> None:
        self.resources.request_resource_refresh()

__all__ = [
    "ApprovalPresentationLease",
    "ApprovalRequestDismisser",
    "ApprovalRequestPresenter",
    "OutputCallback",
    "RuntimeEventListener",
    "SessionControlPort",
    "SessionApprovalInteractionPort",
    "SessionCommandExecutionPort",
    "SessionCommandsPort",
    "SessionEventListener",
    "SessionEventProjector",
    "SessionFacade",
    "SessionFacadePorts",
    "SessionExtensionPort",
    "SessionIdentityPort",
    "SessionMaintenancePort",
    "SessionModelPort",
    "SessionDiagnosticsPort",
    "SessionPackagePort",
    "SessionResourcePort",
    "SessionRetryPort",
    "SessionToolsPort",
    "SessionTranscriptPort",
    "SessionViewPort",
    "require_active_session",
    "require_active_session_control",
]
