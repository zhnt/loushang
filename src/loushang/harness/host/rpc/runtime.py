"""Product-neutral JSONL RPC runtime."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, TextIO, cast

from loushang.harness.events import RuntimeEvent
from loushang.harness.host.jsonl_command_host import (
    JsonlCommand,
    JsonlCommandHost,
    JsonlCommandHostError,
)
from loushang.harness.host.jsonl_command_router import (
    JsonlCommandRoute,
    JsonlCommandRouter,
)
from loushang.harness.host.mode import ModeAdapter, ModeState
from loushang.harness.host.product_host import (
    ProductHostRuntime,
    ProductHostTaskTracker,
)
from loushang.harness.host.rpc.commands import (
    RpcBashMaintenanceCommands,
    RpcCommandCatalogCommands,
    RpcConversationCommands,
    RpcDiagnosticsCommands,
    RpcModelSettingsCommands,
    RpcPackageCommands,
    RpcSessionLifecycleCommands,
    RpcTranscriptCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.projections import (
    STANDARD_AGENT_RPC_EVENT_PROJECTION,
    STANDARD_RPC_DIAGNOSTICS_PROJECTION,
    RpcDiagnosticsProjection,
    RpcEventProjection,
)
from loushang.harness.host.rpc.remote_ui import RpcExtensionUIContext
from loushang.harness.host.rpc.routing import legacy_rpc_routes
from loushang.harness.host.rpc.wire import (
    project_session_state,
    session_messages,
)
from loushang.harness.presentation import ToolDefinitionResolver, ToolRenderRuntime
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session import (
    SessionLifecycleOperationPorts,
    SessionOperationResolver,
    SessionOperationRuntime,
    SessionRpcOperationBinding,
    current_session_operation_resolver,
)
from loushang.harness.transcript import (
    SessionQuery,
    create_agent_transcript_message_codec,
)

_MISSING = object()
_MESSAGE_CODEC = create_agent_transcript_message_codec()
serialize_agent_message = _MESSAGE_CODEC.serialize


class _RpcHostRuntime(Protocol):
    """Required runtime seam; optional RPC groups keep their own leaf ports."""

    def get_current_session(self) -> object | None: ...

    async def new_session_operation(
        self,
        *,
        cwd: str | None = None,
        parent_session: str | None = None,
    ) -> SessionOperationResult[Any, Any]: ...

    async def restore_session_operation(
        self,
        session_ref: str | Path,
    ) -> SessionOperationResult[Any, Any]: ...

    async def fork_session_operation(
        self,
        entry_id: str | None,
        *,
        position: str = "at",
    ) -> SessionOperationResult[Any, Any]: ...

    def refresh_session_index(self) -> object: ...

    def refresh_all_session_indexes(self) -> object: ...

    def find_session_summaries(self, query: SessionQuery) -> object: ...

    def find_all_session_summaries(self, query: SessionQuery) -> object: ...

    def find_indexed_session_summaries(self, query: SessionQuery) -> object: ...

    def find_all_indexed_session_summaries(self, query: SessionQuery) -> object: ...


class _RpcSessionBindingPort(Protocol):
    """Session event and presentation capabilities required by the RPC host."""

    def bind_extension_ui(self, context: RpcExtensionUIContext) -> None: ...

    def subscribe(
        self,
        *,
        runtime_listener: Callable[[RuntimeEvent[object]], None],
        session_listener: Callable[[object], None],
    ) -> Callable[[], None]: ...

    def cwd(self) -> str: ...

    def tool_definition_resolver(self) -> ToolDefinitionResolver | None: ...


class _DynamicRpcSessionBinding:
    """Keep compatibility reflection at the Product composition edge."""

    def __init__(self, session: object) -> None:
        self._session = session

    def bind_extension_ui(self, context: RpcExtensionUIContext) -> None:
        setter = getattr(self._session, "set_extension_ui_context", None)
        if callable(setter):
            setter(context)

    def subscribe(
        self,
        *,
        runtime_listener: Callable[[RuntimeEvent[object]], None],
        session_listener: Callable[[object], None],
    ) -> Callable[[], None]:
        subscribe_runtime_events = getattr(
            self._session, "subscribe_runtime_events", None
        )
        if callable(subscribe_runtime_events):
            unsubscribe = subscribe_runtime_events(runtime_listener)
        else:
            subscribe = getattr(self._session, "subscribe", None)
            if not callable(subscribe):
                raise TypeError("RPC session does not expose an event subscription")
            unsubscribe = subscribe(session_listener)
        if not callable(unsubscribe):
            raise TypeError("RPC session subscription did not return an unsubscribe hook")
        return unsubscribe

    def cwd(self) -> str:
        session_manager = getattr(self._session, "session_manager", None)
        get_cwd = getattr(session_manager, "get_cwd", None)
        if callable(get_cwd):
            try:
                return str(get_cwd())
            except Exception:
                return ""
        return ""

    def tool_definition_resolver(self) -> ToolDefinitionResolver | None:
        getter = getattr(self._session, "get_tool_definition", None)
        if not callable(getter):
            return None

        def resolve(name: str):
            try:
                return getter(name)
            except Exception:
                return None

        return resolve


class RpcHost(ModeAdapter):
    """Product-neutral JSONL RPC host for an active Agent session."""

    def __init__(
        self,
        *,
        runtime: object,
        stdin: TextIO,
        stdout: TextIO,
        stderr: TextIO | None = None,
        event_view: str = "full",
        event_select: str | Sequence[str] | None = None,
        render_tool_events: bool = False,
        event_projection: RpcEventProjection = STANDARD_AGENT_RPC_EVENT_PROJECTION,
        diagnostics_projection: RpcDiagnosticsProjection = (
            STANDARD_RPC_DIAGNOSTICS_PROJECTION
        ),
    ) -> None:
        if event_view not in event_projection.supported_views:
            raise ValueError(f"unsupported json event view: {event_view}")
        self.runtime = cast(_RpcHostRuntime, runtime)
        self.stdin = stdin
        self.stdout = stdout
        self._rpc_output = RpcOutput(stdout)
        self.stderr = sys.stderr if stderr is None else stderr
        self.event_view = event_view
        self._event_projection = event_projection
        self.event_select = tuple(event_projection.normalize_select(event_select))
        self.render_tool_events = render_tool_events
        self._host_runtime = ProductHostRuntime(stdin=stdin)
        self.session: Any = self._require_current_session()
        self._session_binding: _RpcSessionBindingPort = _DynamicRpcSessionBinding(
            self.session
        )
        self._session_operation_resolver = self._build_session_operation_resolver()
        self._rpc_operations = SessionRpcOperationBinding(
            get_operations=self._require_session_operations,
            bind_session=self._bind_session,
        )
        self._tool_render_runtime: ToolRenderRuntime | None = None
        self._tool_definition_resolver: ToolDefinitionResolver | None = None
        self._configure_tool_rendering()
        self._unsubscribe = self._subscribe_to_events()
        self._task_tracker = ProductHostTaskTracker()
        self.extension_ui_context = RpcExtensionUIContext(self._write_json_line)
        self._bind_extension_ui_context()
        self._diagnostics_commands = RpcDiagnosticsCommands(
            runtime=runtime,
            get_session=lambda: self.session,
            output=self._rpc_output,
            projection=diagnostics_projection,
        )
        self._package_commands = RpcPackageCommands(
            runtime=runtime,
            get_session=lambda: self.session,
            output=self._rpc_output,
        )
        self._session_lifecycle_commands = RpcSessionLifecycleCommands(
            runtime=self.runtime,
            get_session=lambda: self.session,
            operations=self._rpc_operations,
            output=self._rpc_output,
        )
        self._model_settings_commands = RpcModelSettingsCommands(
            get_session=lambda: self.session,
            get_operations=self._require_session_operations,
            output=self._rpc_output,
        )
        self._transcript_commands = RpcTranscriptCommands(
            get_session=lambda: self.session,
            get_messages=lambda session: self._get_session_messages(session),
            output=self._rpc_output,
        )
        self._bash_maintenance_commands = RpcBashMaintenanceCommands(
            get_session=lambda: self.session,
            operations=self._rpc_operations,
            output=self._rpc_output,
            task_tracker=self._task_tracker,
        )
        self._command_catalog_commands = RpcCommandCatalogCommands(
            get_session=lambda: self.session,
            output=self._rpc_output,
        )
        self._conversation_commands = RpcConversationCommands(
            get_session=lambda: self.session,
            get_operations=self._require_session_operations,
            operations=self._rpc_operations,
            output=self._rpc_output,
            task_tracker=self._task_tracker,
        )
        self._command_router = JsonlCommandRouter(
            routes=self._command_routes(),
            on_unsupported=self._handle_unsupported_jsonl_command,
        )
        self._command_host = JsonlCommandHost(
            port=self._command_router,
            on_error=self._handle_jsonl_command_error,
            stdin=stdin,
            command_name="rpc_command",
        )

    async def start(self, user_input: str | None = None) -> int:
        del user_input
        return await self.run()

    async def stop(self) -> int:
        self._host_runtime.stop()
        self._command_host.stop()
        self._unsubscribe()
        return 0

    async def submit_input(self, input_payload: object) -> int:
        if not isinstance(input_payload, str):
            raise TypeError("Rpc mode submit_input expects a string")
        try:
            await self._command_host.handle_line(input_payload)
        except Exception:
            return 1
        return 0

    async def wait_for_idle(self) -> int:
        await self._require_session_operations().wait_for_idle()
        return 0

    async def settle_background_tasks(self) -> None:
        """Wait for prompt/bash tasks started by this host."""

        await self._task_tracker.drain()

    def rebind_session(self, session: object | None = None) -> int:
        if session is None:
            session = self._require_current_session()
        self._bind_session(session)
        return 0

    async def dispose(self) -> int:
        self._host_runtime.stop()
        self._command_host.stop()
        try:
            disposer = getattr(self.runtime, "dispose", None)
            if callable(disposer):
                await disposer()
        finally:
            await self.settle_background_tasks()
            self._unsubscribe()
        return 0

    def render_event(self, event: object) -> None:
        self._handle_event(event)

    async def run(self) -> int:
        try:
            return await self._host_runtime.run(
                self._command_host.handle_line,
                handle_failure=self._handle_host_failure,
            )
        finally:
            await self.settle_background_tasks()
            self._command_host.stop()
            self._unsubscribe()

    def get_mode_state(self) -> ModeState:
        try:
            return cast(ModeState, project_session_state(self.session))
        except Exception:
            return {
                "sessionId": "",
                "thinkingLevel": "off",
                "isStreaming": False,
                "isCompacting": False,
                "steeringMode": "one-at-a-time",
                "followUpMode": "one-at-a-time",
                "autoCompactionEnabled": False,
                "messageCount": 0,
                "pendingMessageCount": 0,
                "model": None,
            }

    async def _handle_host_failure(self, error: Exception) -> None:
        self.stderr.write(f"Error: {error}\n")

    def _command_routes(self) -> tuple[JsonlCommandRoute, ...]:
        """Bind the declared Product RPC surface to the Harness JSONL router.

        This explicit table replaces the former ``getattr`` convention.  The
        route registry is transport-neutral; response projection is handled by
        the shared host contract.
        """

        return (
            JsonlCommandRoute(
                command_type="extension_ui_response",
                handler=self._handle_extension_ui_response,
            ),
            *legacy_rpc_routes(
                (
                    *self._conversation_commands.bindings(),
                    (
                        "get_extension_ui_state",
                        self._handle_get_extension_ui_state_command,
                    ),
                    *self._session_lifecycle_commands.bindings(),
                    *self._model_settings_commands.bindings(),
                    *self._transcript_commands.bindings(),
                    *self._command_catalog_commands.bindings(),
                    *self._diagnostics_commands.bindings(),
                    *self._package_commands.bindings(),
                    *self._bash_maintenance_commands.bindings(),
                )
            ),
        )

    def _handle_extension_ui_response(self, command: JsonlCommand) -> None:
        self.extension_ui_context.resolve_response(dict(command.payload))

    def _handle_unsupported_jsonl_command(self, command: JsonlCommand) -> None:
        self._write_response_error(
            id=command.command_id,
            command=command.command_type,
            error=f"unsupported command: {command.command_type}",
            code="unsupported_command",
        )

    def _handle_jsonl_command_error(self, error: JsonlCommandHostError) -> None:
        if error.reason == "invalid_json":
            self._write_response_error(
                command="parse", error=f"Failed to parse command: {error.message}"
            )
            return
        if error.reason == "not_object":
            self._write_response_error(
                command="invalid", error="RPC commands must be JSON objects"
            )
            return
        if error.reason == "non_json_value":
            detail = error.message.removeprefix(
                "JSONL command contains a value outside strict JSON: "
            )
            self._write_response_error(
                id=error.command_id,
                command="invalid",
                error=f"RPC command contains a value outside strict JSON: {detail}",
            )
            return
        if error.reason == "invalid_id":
            self._write_response_error(
                command="invalid", error="command id must be a string"
            )
            return
        if error.reason == "missing_type":
            self._write_response_error(
                id=error.command_id,
                command="invalid",
                error="RPC command missing string type",
            )
            return
        self._write_response_error(
            id=error.command_id,
            command=error.command_type or "invalid",
            error=error.message,
        )

    def _handle_get_extension_ui_state_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        self._write_response_success(
            id=command_id,
            command="get_extension_ui_state",
            data=self.extension_ui_context.get_snapshot(),
        )


    def _bind_session(self, session: object) -> None:
        self._unsubscribe()
        self.session = session
        self._session_binding = _DynamicRpcSessionBinding(session)
        self._configure_tool_rendering()
        self._unsubscribe = self._subscribe_to_events()
        self._bind_extension_ui_context()

    def _bind_extension_ui_context(self) -> None:
        self._session_binding.bind_extension_ui(self.extension_ui_context)

    def _handle_event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        for projected_event in self._event_projection.project_session_event(
            event,
            event_view=self.event_view,
            tool_render_runtime=self._tool_render_runtime,
            tool_definition_resolver=self._tool_definition_resolver,
        ):
            if self._event_projection.should_emit_projected_event(
                projected_event, self.event_select
            ):
                self._write_json_line(
                    self._event_projection.shape_stream_event(
                        projected_event, event_view=self.event_view
                    )
                )

    def _subscribe_to_events(self) -> Callable[[], None]:
        """Prefer the common runtime event stream when one is available.

        Products may still expose a lower-level session event stream when no
        runtime projection is available; the injected projection owns its
        payload vocabulary.
        """

        return self._session_binding.subscribe(
            runtime_listener=self._handle_runtime_event,
            session_listener=self._handle_event,
        )

    def _handle_runtime_event(self, event: RuntimeEvent[object]) -> None:
        for projected_event in self._event_projection.project_runtime_event_to_json_views(
            event,
            event_view=self.event_view,
            tool_render_runtime=self._tool_render_runtime,
            tool_definition_resolver=self._tool_definition_resolver,
        ):
            if self._event_projection.should_emit_runtime_event_view(
                projected_event, self.event_select
            ):
                self._write_json_line(
                    self._event_projection.shape_runtime_event_view(projected_event)
                )

    def _configure_tool_rendering(self) -> None:
        if not self.render_tool_events:
            self._tool_render_runtime = None
            self._tool_definition_resolver = None
            return
        self._tool_render_runtime = ToolRenderRuntime(cwd=self._session_binding.cwd())
        self._tool_definition_resolver = (
            self._session_binding.tool_definition_resolver()
        )


    def _require_current_session(self) -> object:
        session = self.runtime.get_current_session()
        if session is None:
            raise RuntimeError("RPC mode requires an active session")
        return session

    def _build_session_operation_resolver(self) -> SessionOperationResolver:
        runtime = self.runtime
        clone_operation = getattr(runtime, "clone_session_operation", None)
        if not callable(clone_operation):

            async def clone_operation():
                return await runtime.fork_session_operation(None, position="at")

        return current_session_operation_resolver(
            runtime,
            lifecycle=SessionLifecycleOperationPorts(
                new_session=lambda cwd, parent: runtime.new_session_operation(
                    cwd=cwd, parent_session=parent
                ),
                restore_session=lambda session_ref: runtime.restore_session_operation(
                    session_ref
                ),
                fork_session=lambda entry_id, position: runtime.fork_session_operation(
                    entry_id, position=position
                ),
                clone_session=clone_operation,
            ),
        )

    def _require_session_operations(self) -> SessionOperationRuntime:
        return self._session_operation_resolver()

    def _get_session_messages(self, session: object) -> list[object]:
        """Narrow test seam for validating malformed upstream message logs."""

        return session_messages(session)


    def _write_response_success(
        self, *, command: str, id: str | None = None, data: object = _MISSING
    ) -> None:
        if data is _MISSING:
            self._rpc_output.success(command=command, request_id=id)
        else:
            self._rpc_output.success(command=command, request_id=id, data=data)

    def _write_response_error(
        self,
        *,
        command: str,
        error: str,
        id: str | None = None,
        code: str | None = None,
    ) -> None:
        self._rpc_output.error(
            command=command,
            error=error,
            request_id=id,
            code=code,
        )

    def _write_json_line(self, payload: object) -> None:
        self._rpc_output.write(payload)


async def run_rpc_host(
    *,
    runtime: object,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO | None = None,
    event_view: str = "full",
    event_select: str | Sequence[str] | None = None,
    render_tool_events: bool = False,
    event_projection: RpcEventProjection = STANDARD_AGENT_RPC_EVENT_PROJECTION,
    diagnostics_projection: RpcDiagnosticsProjection = (
        STANDARD_RPC_DIAGNOSTICS_PROJECTION
    ),
) -> int:
    mode = RpcHost(
        runtime=runtime,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        event_view=event_view,
        event_select=event_select,
        render_tool_events=render_tool_events,
        event_projection=event_projection,
        diagnostics_projection=diagnostics_projection,
    )
    return await mode.run()

__all__ = ["RpcHost", "run_rpc_host"]
