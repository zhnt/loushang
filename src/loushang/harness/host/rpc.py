from __future__ import annotations

import asyncio
import inspect
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, NotRequired, Required, TextIO, TypedDict, cast

from loushang.ai.model import ModelSelection
from loushang.harness.commands import complete_slash_commands
from loushang.harness.diagnostics.serialization import (
    serialize_diagnostic,
    serialize_diagnostic_summary,
    serialize_error_report,
)
from loushang.harness.diagnostics.types import DiagnosticsQuery
from loushang.harness.events import (
    RuntimeEvent,
    normalize_event_select,
)
from loushang.harness.host.json_projection import project_host_value
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
from loushang.harness.host.remote_ui import RemoteUiContext
from loushang.harness.presentation import ToolDefinitionResolver, ToolRenderRuntime
from loushang.harness.session import (
    SUPPORTED_JSON_EVENT_VIEWS,
    SessionLifecycleOperationPorts,
    SessionOperationRuntime,
    SessionPromptRequest,
    SessionRpcOperationBinding,
    project_runtime_event_to_json_views,
    project_session_event,
    shape_runtime_event_view,
    shape_stream_event,
    should_emit_projected_event,
    should_emit_runtime_event_view,
)
from loushang.harness.transcript import (
    SessionQuery,
    create_agent_transcript_message_codec,
)

_THINKING_LEVEL_ORDER: tuple[str, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
_MISSING = object()
_MESSAGE_CODEC = create_agent_transcript_message_codec()
serialize_agent_message = _MESSAGE_CODEC.serialize


class RpcModelCost(TypedDict):
    input: float | int
    output: float | int
    cacheRead: float | int
    cacheWrite: float | int


class RpcModel(TypedDict, total=False):
    provider: Required[str]
    id: Required[str]
    name: Required[str]
    endpointId: NotRequired[str]
    api: NotRequired[str]
    baseUrl: NotRequired[str]
    input: NotRequired[list[str]]
    contextWindow: NotRequired[int]
    maxTokens: NotRequired[int]
    reasoning: NotRequired[bool]
    cost: NotRequired[RpcModelCost]
    compat: NotRequired[dict[str, Any]]


class RpcSessionState(TypedDict, total=False):
    sessionId: Required[str]
    sessionName: NotRequired[str]
    sessionFile: NotRequired[str]
    model: Required[RpcModel | None]
    thinkingLevel: Required[str]
    isStreaming: Required[bool]
    isCompacting: Required[bool]
    steeringMode: Required[str | None]
    followUpMode: Required[str | None]
    autoCompactionEnabled: Required[bool | None]
    messageCount: Required[int]
    pendingMessageCount: Required[int]


@dataclass(frozen=True)
class RpcEventProjection:
    """Product-injected event projection for the shared RPC host.

    Event names and view payloads are deliberately supplied by the Product;
    the host only subscribes, filters, and writes them to the transport.
    """

    supported_views: Sequence[str]
    normalize_select: Callable[[str | Sequence[str] | None], Sequence[str]]
    project_session_event: Callable[..., Sequence[dict[str, Any]]]
    should_emit_projected_event: Callable[[dict[str, Any], Sequence[str]], bool]
    shape_stream_event: Callable[..., dict[str, Any]]
    project_runtime_event_to_json_views: Callable[..., Sequence[object]]
    should_emit_runtime_event_view: Callable[[object, Sequence[str]], bool]
    shape_runtime_event_view: Callable[[object], dict[str, Any]]


@dataclass(frozen=True)
class RpcDiagnosticsProjection:
    """Product-injected diagnostics wire projection."""

    serialize_diagnostic: Callable[[object], dict[str, object]]
    serialize_diagnostic_summary: Callable[[object], dict[str, object]]
    serialize_error_report: Callable[[object], dict[str, object] | None]


STANDARD_AGENT_RPC_EVENT_PROJECTION = RpcEventProjection(
    supported_views=SUPPORTED_JSON_EVENT_VIEWS,
    normalize_select=normalize_event_select,
    project_session_event=project_session_event,
    should_emit_projected_event=should_emit_projected_event,
    shape_stream_event=shape_stream_event,
    project_runtime_event_to_json_views=project_runtime_event_to_json_views,
    should_emit_runtime_event_view=should_emit_runtime_event_view,
    shape_runtime_event_view=shape_runtime_event_view,
)

STANDARD_RPC_DIAGNOSTICS_PROJECTION = RpcDiagnosticsProjection(
    serialize_diagnostic=serialize_diagnostic,
    serialize_diagnostic_summary=serialize_diagnostic_summary,
    serialize_error_report=serialize_error_report,
)


class RpcExtensionUIContext(RemoteUiContext):
    """RPC-backed extension UI context for headless hosts."""

    def __init__(self, output) -> None:
        self._output = output

        def emit(payload: dict[str, object]) -> None:
            if payload.get("type") == "remote_ui_request":
                payload = {**payload, "type": "extension_ui_request"}
            self._output(payload)

        super().__init__(emit)

    def emit_extension_error(self, error: dict[str, object]) -> None:
        self._output(
            {
                "type": "extension_error",
                "extensionPath": str(error.get("extensionPath", "")),
                "event": str(error.get("event", "")),
                "error": str(error.get("error", "")),
            }
        )


class RpcHost(ModeAdapter):
    """Product-neutral JSONL RPC host for an active Agent session."""

    def __init__(
        self,
        *,
        runtime: Any,
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
        self.runtime = runtime
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = sys.stderr if stderr is None else stderr
        self.event_view = event_view
        self._event_projection = event_projection
        self._diagnostics_projection = diagnostics_projection
        self.event_select = tuple(event_projection.normalize_select(event_select))
        self.render_tool_events = render_tool_events
        self._host_runtime = ProductHostRuntime(stdin=stdin)
        self.session = self._require_current_session()
        self._session_operations = self._find_session_operations(self.session)
        self._rpc_operations = SessionRpcOperationBinding(
            get_operations=self._require_session_operations,
            bind_session=self._bind_session,
        )
        self._tool_render_runtime: ToolRenderRuntime | None = None
        self._tool_definition_resolver: ToolDefinitionResolver | None = None
        self._configure_tool_rendering(self.session)
        self._unsubscribe = self._subscribe_to_events(self.session)
        self._task_tracker = ProductHostTaskTracker()
        self._active_prompt_task: asyncio.Task[None] | None = None
        self._active_bash_task: asyncio.Task[None] | None = None
        self.extension_ui_context = RpcExtensionUIContext(self._write_json_line)
        self._bind_extension_ui_context(self.session)
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

    def rebind_session(self, session: object | None = None) -> int:
        if session is None:
            session = self._require_current_session()
        self._bind_session(session)
        return 0

    async def dispose(self) -> int:
        self._host_runtime.stop()
        self._command_host.stop()
        self._unsubscribe()
        disposer = getattr(self.runtime, "dispose", None)
        if callable(disposer):
            await disposer()
        return 0

    def render_event(self, event: object) -> None:
        self._handle_event(event)

    async def run(self) -> int:
        try:
            return await self._host_runtime.run(
                self._handle_line,
                handle_failure=self._handle_host_failure,
            )
        finally:
            await self._task_tracker.drain()
            self._command_host.stop()
            self._unsubscribe()

    def get_mode_state(self) -> ModeState:
        try:
            return self._serialize_session_state(self.session)
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

    async def _drain_background_tasks(self) -> None:
        """Compatibility hook over the Channel-owned task tracker."""

        await self._task_tracker.drain()

    async def _handle_line(self, line: str) -> None:
        """Test-facing adapter for the Channel-owned JSONL command host."""

        await self._command_host.handle_line(line)

    def _command_routes(self) -> tuple[JsonlCommandRoute, ...]:
        """Bind the declared Product RPC surface to the Channel router.

        This explicit table replaces the former ``getattr`` convention.  The
        route registry is transport-neutral; response projection is handled by
        the shared host contract.
        """

        return (
            JsonlCommandRoute(
                command_type="extension_ui_response",
                handler=self._handle_extension_ui_response,
            ),
            self._legacy_command_route("prompt", self._handle_prompt_command),
            self._legacy_command_route("steer", self._handle_steer_command),
            self._legacy_command_route("follow_up", self._handle_follow_up_command),
            self._legacy_command_route("abort", self._handle_abort_command),
            self._legacy_command_route("get_state", self._handle_get_state_command),
            self._legacy_command_route(
                "get_extension_ui_state", self._handle_get_extension_ui_state_command
            ),
            self._legacy_command_route(
                "get_messages", self._handle_get_messages_command
            ),
            self._legacy_command_route(
                "list_sessions", self._handle_list_sessions_command
            ),
            self._legacy_command_route("new_session", self._handle_new_session_command),
            self._legacy_command_route(
                "switch_session", self._handle_switch_session_command
            ),
            self._legacy_command_route("fork", self._handle_fork_command),
            self._legacy_command_route("clone", self._handle_clone_command),
            self._legacy_command_route("set_model", self._handle_set_model_command),
            self._legacy_command_route(
                "get_available_models", self._handle_get_available_models_command
            ),
            self._legacy_command_route("cycle_model", self._handle_cycle_model_command),
            self._legacy_command_route(
                "set_active_tools", self._handle_set_active_tools_command
            ),
            self._legacy_command_route(
                "set_thinking_level", self._handle_set_thinking_level_command
            ),
            self._legacy_command_route(
                "cycle_thinking_level", self._handle_cycle_thinking_level_command
            ),
            self._legacy_command_route(
                "set_steering_mode", self._handle_set_steering_mode_command
            ),
            self._legacy_command_route(
                "set_follow_up_mode", self._handle_set_follow_up_mode_command
            ),
            self._legacy_command_route(
                "get_session_stats", self._handle_get_session_stats_command
            ),
            self._legacy_command_route(
                "set_session_name", self._handle_set_session_name_command
            ),
            self._legacy_command_route(
                "get_last_assistant_text", self._handle_get_last_assistant_text_command
            ),
            self._legacy_command_route(
                "get_fork_messages", self._handle_get_fork_messages_command
            ),
            self._legacy_command_route(
                "get_commands", self._handle_get_commands_command
            ),
            self._legacy_command_route(
                "get_command_completions", self._handle_get_command_completions_command
            ),
            self._legacy_command_route(
                "get_diagnostics", self._handle_get_diagnostics_command
            ),
            self._legacy_command_route(
                "get_session_diagnostics", self._handle_get_session_diagnostics_command
            ),
            self._legacy_command_route(
                "get_diagnostics_summary", self._handle_get_diagnostics_summary_command
            ),
            self._legacy_command_route(
                "get_session_diagnostics_summary",
                self._handle_get_session_diagnostics_summary_command,
            ),
            self._legacy_command_route(
                "get_last_error_report", self._handle_get_last_error_report_command
            ),
            self._legacy_command_route(
                "get_packages", self._handle_get_packages_command
            ),
            self._legacy_command_route(
                "materialize_package", self._handle_materialize_package_command
            ),
            self._legacy_command_route(
                "install_package", self._handle_install_package_command
            ),
            self._legacy_command_route(
                "update_package", self._handle_update_package_command
            ),
            self._legacy_command_route(
                "update_packages", self._handle_update_packages_command
            ),
            self._legacy_command_route(
                "check_package_updates", self._handle_check_package_updates_command
            ),
            self._legacy_command_route(
                "remove_package", self._handle_remove_package_command
            ),
            self._legacy_command_route(
                "uninstall_package", self._handle_uninstall_package_command
            ),
            self._legacy_command_route("bash", self._handle_bash_command),
            self._legacy_command_route("abort_bash", self._handle_abort_bash_command),
            self._legacy_command_route("compact", self._handle_compact_command),
            self._legacy_command_route(
                "set_auto_retry", self._handle_set_auto_retry_command
            ),
            self._legacy_command_route("abort_retry", self._handle_abort_retry_command),
            self._legacy_command_route(
                "set_auto_compaction", self._handle_set_auto_compaction_command
            ),
            self._legacy_command_route("export_html", self._handle_export_html_command),
        )

    def _legacy_command_route(
        self,
        command_type: str,
        handler: Callable[[str | None, dict[str, Any]], object],
    ) -> JsonlCommandRoute:
        async def route(command: JsonlCommand) -> None:
            result = handler(command.command_id, dict(command.payload))
            if inspect.isawaitable(result):
                await result

        return JsonlCommandRoute(command_type=command_type, handler=route)

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

    async def _handle_prompt_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        request = self._rpc_operations.prompt_request(payload)
        task = asyncio.create_task(
            self._run_prompt(
                operations=self._require_session_operations(),
                command_id=command_id,
                request=request,
            )
        )
        self._active_prompt_task = task
        self._task_tracker.track(task)

    async def _run_prompt(
        self,
        *,
        operations: SessionOperationRuntime,
        command_id: str | None,
        request: SessionPromptRequest,
    ) -> None:
        preflight_succeeded = False

        def on_preflight(did_succeed: bool) -> None:
            nonlocal preflight_succeeded
            if did_succeed and not preflight_succeeded:
                preflight_succeeded = True
                self._write_response_success(id=command_id, command="prompt")

        try:
            await operations.prompt(
                request,
                on_preflight=on_preflight,
            )
        except Exception as exc:
            if not preflight_succeeded:
                self._write_response_error(
                    id=command_id, command="prompt", error=str(exc)
                )
        else:
            if not preflight_succeeded:
                self._write_response_success(id=command_id, command="prompt")
        finally:
            if self._active_prompt_task is asyncio.current_task():
                self._active_prompt_task = None

    def _handle_steer_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._rpc_operations.steer(payload)
        self._write_response_success(id=command_id, command="steer")

    def _handle_follow_up_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._rpc_operations.follow_up(payload)
        self._write_response_success(id=command_id, command="follow_up")

    def _handle_abort_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        self._rpc_operations.abort()
        self._write_response_success(id=command_id, command="abort")

    def _handle_get_state_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            state = self._serialize_session_state(self.session)
        except Exception:
            self._write_response_error(
                id=command_id,
                command="get_state",
                error="Failed to serialize session state.",
            )
            return
        self._write_response_success(
            id=command_id,
            command="get_state",
            data=state,
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

    def _handle_get_messages_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        messages = self._get_session_messages(self.session)
        if not isinstance(messages, list):
            self._write_response_error(
                id=command_id,
                command="get_messages",
                error="Message log returned an invalid response.",
            )
            return
        serialized_messages: list[dict[str, Any]] = []
        for message in messages:
            try:
                serialized_messages.append(serialize_agent_message(message))
            except Exception:
                continue
        self._write_response_success(
            id=command_id,
            command="get_messages",
            data={"messages": serialized_messages},
        )

    def _handle_list_sessions_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            query = self._session_query_from_payload(payload)
        except ValueError as error:
            self._write_response_error(
                id=command_id, command="list_sessions", error=str(error)
            )
            return
        all_sessions = payload.get("allSessions", payload.get("all_sessions", False))
        if not isinstance(all_sessions, bool):
            raise ValueError("list_sessions allSessions must be boolean")
        use_index = payload.get("useIndex", payload.get("use_index", False))
        refresh_index = payload.get("refreshIndex", payload.get("refresh_index", False))
        if not isinstance(use_index, bool):
            raise ValueError("list_sessions useIndex must be boolean")
        if not isinstance(refresh_index, bool):
            raise ValueError("list_sessions refreshIndex must be boolean")
        use_index = use_index or refresh_index
        if refresh_index:
            refresher = getattr(
                self.runtime,
                "refresh_all_session_indexes"
                if all_sessions
                else "refresh_session_index",
                None,
            )
            if not callable(refresher):
                self._write_response_error(
                    id=command_id,
                    command="list_sessions",
                    error="Session index refresh is not available.",
                )
                return
            try:
                refresher()
            except Exception as error:
                self._write_response_error(
                    id=command_id,
                    command="list_sessions",
                    error=f"Failed to refresh session index: {error}",
                )
                return
        finder = (
            getattr(
                self.runtime,
                "find_all_indexed_session_summaries"
                if use_index
                else "find_all_session_summaries",
                None,
            )
            if all_sessions
            else None
        )
        if not callable(finder):
            finder = getattr(
                self.runtime,
                "find_indexed_session_summaries"
                if use_index
                else "find_session_summaries",
                None,
            )
        if callable(finder):

            def lister():
                return finder(query)
        else:
            if all_sessions:
                lister = getattr(
                    self.runtime,
                    "list_all_indexed_session_summaries"
                    if use_index
                    else "list_all_session_summaries",
                    None,
                )
            else:
                lister = getattr(
                    self.runtime,
                    "list_indexed_session_summaries"
                    if use_index
                    else "list_session_summaries",
                    None,
                )
            if not callable(lister) and not use_index:
                lister = getattr(self.runtime, "list_sessions", None)
        if not callable(lister):
            self._write_response_error(
                id=command_id,
                command="list_sessions",
                error="Session listing is not available.",
            )
            return
        try:
            raw_sessions = lister()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="list_sessions",
                error=f"Failed to list sessions: {error}",
            )
            return
        if not isinstance(raw_sessions, list):
            self._write_response_error(
                id=command_id,
                command="list_sessions",
                error="Session listing returned an invalid response.",
            )
            return
        sessions = []
        for session in raw_sessions:
            try:
                sessions.append(self._serialize_session_listing_item(session))
            except Exception:
                continue
        self._write_response_success(
            id=command_id,
            command="list_sessions",
            data={"sessions": sessions},
        )

    def _session_query_from_payload(self, payload: dict[str, Any]) -> SessionQuery:
        limit = self._optional_int(payload, "limit")
        if limit is not None and limit < 0:
            raise ValueError("Session limit must be non-negative.")
        return SessionQuery(
            cwd=self._optional_string(payload, "cwd"),
            name=self._optional_string(payload, "name"),
            parent_session=self._optional_string(
                payload, "parentSession", "parent_session"
            ),
            text=self._optional_string(payload, "text", "query"),
            has_diagnostics=self._optional_bool(
                payload, "hasDiagnostics", "has_diagnostics"
            ),
            limit=limit,
        )

    async def _handle_new_session_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        previous = self.session
        try:
            operation = await self._rpc_operations.new_session(payload)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="new_session",
                error=f"Failed to create new session: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="new_session",
            data={
                "cancelled": operation.current is previous,
            },
        )

    async def _handle_switch_session_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        previous = self.session
        try:
            operation = await self._rpc_operations.switch_session(payload)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="switch_session",
                error=f"Failed to switch session: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="switch_session",
            data={
                "cancelled": operation.current is previous,
            },
        )

    async def _handle_fork_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        previous = self.session
        try:
            operation = await self._rpc_operations.fork(payload)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="fork",
                error=f"Failed to fork session: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="fork",
            data={
                "cancelled": operation.current is previous,
                "text": operation.payload,
            },
        )

    async def _handle_clone_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        previous = self.session
        try:
            operation = await self._rpc_operations.clone()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="clone",
                error=f"Failed to clone session: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="clone",
            data={"cancelled": operation.current is previous},
        )

    async def _handle_set_model_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        provider = self._require_string(payload, "provider")
        model_id = self._require_string(payload, "modelId", "model_id")
        endpoint_id = payload.get("endpointId") or payload.get("endpoint_id")
        selection = ModelSelection(
            provider=provider,
            model_id=model_id,
            endpoint_id=endpoint_id if isinstance(endpoint_id, str) else None,
        )
        try:
            available_models = self.session.get_available_models()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_model",
                error=f"Failed to query model registry: {error}",
            )
            return
        if not isinstance(available_models, list):
            self._write_response_error(
                id=command_id,
                command="set_model",
                error="Model registry returned an invalid response.",
            )
            return
        if available_models and selection not in available_models:
            self._write_response_error(
                id=command_id,
                command="set_model",
                error=f"Model not found: {provider}/{model_id}",
            )
            return
        try:
            await self.session.set_model(selection)
        except KeyError:
            self._write_response_error(
                id=command_id,
                command="set_model",
                error=f"Model not found: {provider}/{model_id}",
            )
            return
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_model",
                error=f"Failed to set model: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="set_model",
            data=self._serialize_state_model(self.session, self.session.get_state()),
        )

    def _handle_get_available_models_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        getter = getattr(self.session, "get_available_models", None)
        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command="get_available_models",
                error="Model registry is not available.",
            )
            return
        try:
            models = getter()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_available_models",
                error=f"Failed to query model registry: {error}",
            )
            return
        if not isinstance(models, list):
            self._write_response_error(
                id=command_id,
                command="get_available_models",
                error="Model registry returned an invalid response.",
            )
            return
        try:
            serialized = self._serialize_available_models(self.session, models)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_available_models",
                error=f"Failed to serialize model registry: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="get_available_models",
            data={"models": serialized},
        )

    async def _handle_cycle_model_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            selection = await self.session.cycle_model()
        except TypeError as error:
            if str(error) == "Model registry returned an invalid response.":
                self._write_response_error(
                    id=command_id,
                    command="cycle_model",
                    error=str(error),
                )
                return
            self._write_response_error(
                id=command_id,
                command="cycle_model",
                error=f"Failed to cycle model: {error}",
            )
            return
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="cycle_model",
                error=f"Failed to cycle model: {error}",
            )
            return
        if selection is None:
            self._write_response_success(
                id=command_id,
                command="cycle_model",
                data=None,
            )
            return
        try:
            model = self._serialize_state_model(self.session, self.session.get_state())
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="cycle_model",
                error=f"Failed to serialize model: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="cycle_model",
            data={
                "model": model,
                "thinkingLevel": self.session.get_state().thinking_level,
                "isScoped": False,
            },
        )

    async def _handle_set_active_tools_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        tool_names = payload.get("toolNames", payload.get("tool_names"))
        if not isinstance(tool_names, list) or not all(
            isinstance(name, str) and name for name in tool_names
        ):
            raise ValueError("set_active_tools requires toolNames")
        try:
            await self.session.set_active_tools(tool_names)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_active_tools",
                error=f"Failed to set active tools: {error}",
            )
            return
        try:
            state = self._serialize_session_state(self.session)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_active_tools",
                error=f"Failed to read session state: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="set_active_tools",
            data=state,
        )

    async def _handle_set_thinking_level_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        level = self._require_string(payload, "level")
        try:
            result = self.session.set_thinking_level(level)
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_thinking_level",
                error=f"Failed to set thinking level: {error}",
            )
            return
        self._write_response_success(id=command_id, command="set_thinking_level")

    async def _handle_cycle_thinking_level_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            result = self.session.cycle_thinking_level()
            next_level = await result if inspect.isawaitable(result) else result
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="cycle_thinking_level",
                error=f"Failed to set thinking level: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="cycle_thinking_level",
            data={"level": next_level},
        )

    def _handle_set_steering_mode_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        mode = self._require_mode(payload, "mode")
        try:
            self.session.set_steering_mode(mode)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_steering_mode",
                error=f"Failed to set steering mode: {error}",
            )
            return
        self._write_response_success(id=command_id, command="set_steering_mode")

    def _handle_set_follow_up_mode_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        mode = self._require_mode(payload, "mode")
        try:
            self.session.set_follow_up_mode(mode)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_follow_up_mode",
                error=f"Failed to set follow-up mode: {error}",
            )
            return
        self._write_response_success(id=command_id, command="set_follow_up_mode")

    def _handle_get_session_stats_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        getter = getattr(self.session, "get_session_stats", None)
        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command="get_session_stats",
                error="Session stats are not available.",
            )
            return
        try:
            stats = getter()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_session_stats",
                error=f"Failed to query session stats: {error}",
            )
            return
        try:
            serialized = self._serialize_session_stats(stats)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_session_stats",
                error=f"Session stats returned an invalid response: {error}",
            )
            return
        if not isinstance(serialized, dict):
            self._write_response_error(
                id=command_id,
                command="get_session_stats",
                error="Session stats returned an invalid response.",
            )
            return
        self._write_response_success(
            id=command_id,
            command="get_session_stats",
            data=serialized,
        )

    async def _handle_set_session_name_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        name = self._require_string(payload, "name").strip()
        if not name:
            self._write_response_error(
                id=command_id,
                command="set_session_name",
                error="Session name cannot be empty",
            )
            return
        try:
            await self._require_session_operations().set_session_name(name)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_session_name",
                error=f"Failed to set session name: {error}",
            )
            return
        self._write_response_success(id=command_id, command="set_session_name")

    def _handle_get_last_assistant_text_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            text = self._extract_last_assistant_text()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_last_assistant_text",
                error=f"Failed to read last assistant text: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="get_last_assistant_text",
            data={"text": text},
        )

    def _handle_get_fork_messages_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        getter = getattr(self.session, "get_user_messages_for_forking", None)
        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command="get_fork_messages",
                error="Fork messages are not available.",
            )
            return
        try:
            raw_messages = getter()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_fork_messages",
                error=f"Failed to query fork messages: {error}",
            )
            return
        if not isinstance(raw_messages, list):
            self._write_response_error(
                id=command_id,
                command="get_fork_messages",
                error="Fork messages returned an invalid response.",
            )
            return
        messages = self._camelize(self._serialize_json_value(raw_messages))
        self._write_response_success(
            id=command_id,
            command="get_fork_messages",
            data={"messages": messages},
        )

    def _handle_get_commands_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        commands = []
        getter = getattr(self.session, "list_commands", None)
        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command="get_commands",
                error="Command registry is not available.",
            )
            return
        try:
            raw_commands = getter()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_commands",
                error=f"Failed to query commands: {error}",
            )
            return
        if not isinstance(raw_commands, list):
            self._write_response_error(
                id=command_id,
                command="get_commands",
                error="Command registry returned an invalid response.",
            )
            return
        for command in raw_commands:
            try:
                commands.append(self._serialize_command_descriptor(command))
            except Exception:
                continue
        self._write_response_success(
            id=command_id,
            command="get_commands",
            data={"commands": commands},
        )

    async def _handle_get_command_completions_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        prefix = payload.get("prefix", "")
        if not isinstance(prefix, str):
            self._write_response_error(
                id=command_id,
                command="get_command_completions",
                error="Command completion prefix must be a string.",
                code="invalid_request",
            )
            return
        command_name = payload.get("command")
        if command_name is not None:
            if not isinstance(command_name, str) or not command_name:
                self._write_response_error(
                    id=command_id,
                    command="get_command_completions",
                    error="Command completion command must be a non-empty string.",
                    code="invalid_request",
                )
                return
            getter = getattr(self.session, "get_command_argument_completions", None)
            if not callable(getter):
                self._write_response_success(
                    id=command_id,
                    command="get_command_completions",
                    data={"completions": []},
                )
                return
            try:
                completions = await getter(command_name, prefix)
            except Exception as error:
                self._write_response_error(
                    id=command_id,
                    command="get_command_completions",
                    error=f"Failed to query command completions: {error}",
                    code="command_completion_failed",
                )
                return
            self._write_response_success(
                id=command_id,
                command="get_command_completions",
                data={
                    "completions": completions if isinstance(completions, list) else []
                },
            )
            return

        getter = getattr(self.session, "list_commands", None)
        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command="get_command_completions",
                error="Command registry is not available.",
                code="command_registry_unavailable",
            )
            return
        try:
            raw_commands = getter()
            if not isinstance(raw_commands, list):
                raise TypeError("Command registry returned an invalid response.")
            completions = complete_slash_commands(prefix, raw_commands)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_command_completions",
                error=f"Failed to query command completions: {error}",
                code="command_completion_failed",
            )
            return
        self._write_response_success(
            id=command_id,
            command="get_command_completions",
            data={"completions": completions},
        )

    def _handle_get_diagnostics_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._handle_diagnostics_query_command(
            command_id=command_id,
            payload=payload,
            command="get_diagnostics",
            runtime_method="get_diagnostics",
            session_method="get_diagnostics",
            fallback_to_last=True,
        )

    def _handle_get_session_diagnostics_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._handle_diagnostics_query_command(
            command_id=command_id,
            payload=payload,
            command="get_session_diagnostics",
            runtime_method="get_session_diagnostics",
            session_method="get_session_diagnostics",
            fallback_to_last=False,
        )

    def _handle_get_diagnostics_summary_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._handle_diagnostics_summary_command(
            command_id=command_id,
            payload=payload,
            command="get_diagnostics_summary",
            runtime_method="get_diagnostics_summary",
            session_method="get_diagnostics_summary",
        )

    def _handle_get_session_diagnostics_summary_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._handle_diagnostics_summary_command(
            command_id=command_id,
            payload=payload,
            command="get_session_diagnostics_summary",
            runtime_method="get_session_diagnostics_summary",
            session_method="get_session_diagnostics_summary",
        )

    def _handle_diagnostics_query_command(
        self,
        *,
        command_id: str | None,
        payload: dict[str, Any],
        command: str,
        runtime_method: str,
        session_method: str,
        fallback_to_last: bool,
    ) -> None:
        raw_limit = payload.get("limit", 50)
        if not isinstance(raw_limit, int) or raw_limit <= 0:
            self._write_response_error(
                id=command_id,
                command=command,
                error="Diagnostic limit must be a positive integer.",
            )
            return

        query = self._diagnostics_query_from_payload(payload, default_limit=raw_limit)
        getter = getattr(self.runtime, runtime_method, None)
        if callable(getter):

            def get_diagnostics():
                return getter(query=query)
        else:
            getter = getattr(self.session, session_method, None)
            if callable(getter):

                def get_diagnostics():
                    return getter(query=query)
            else:
                getter = (
                    getattr(self.session, "get_last_diagnostics", None)
                    if fallback_to_last
                    else None
                )
                if callable(getter):

                    def get_diagnostics():
                        return getter(limit=raw_limit)

        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command=command,
                error="Diagnostics are not available.",
            )
            return
        try:
            raw_diagnostics = get_diagnostics()
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command=command,
                error=f"Failed to query diagnostics: {error}",
            )
            return
        if not isinstance(raw_diagnostics, list):
            self._write_response_error(
                id=command_id,
                command=command,
                error="Diagnostics returned an invalid response.",
            )
            return

        diagnostics = []
        for record in raw_diagnostics:
            try:
                diagnostics.append(
                    self._diagnostics_projection.serialize_diagnostic(record)
                )
            except Exception:
                continue
        self._write_response_success(
            id=command_id,
            command=command,
            data={"diagnostics": diagnostics},
        )

    def _handle_diagnostics_summary_command(
        self,
        *,
        command_id: str | None,
        payload: dict[str, Any],
        command: str,
        runtime_method: str,
        session_method: str,
    ) -> None:
        try:
            query = self._diagnostics_query_from_payload(payload, default_limit=None)
        except ValueError as error:
            self._write_response_error(id=command_id, command=command, error=str(error))
            return
        getter = getattr(self.runtime, runtime_method, None)
        if callable(getter):

            def get_summary():
                return getter(query=query)
        else:
            getter = getattr(self.session, session_method, None)
            if callable(getter):

                def get_summary():
                    return getter(query=query)

        if not callable(getter):
            self._write_response_error(
                id=command_id, command=command, error="Diagnostics are not available."
            )
            return
        try:
            summary = self._diagnostics_projection.serialize_diagnostic_summary(
                get_summary()
            )
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command=command,
                error=f"Failed to query diagnostics: {error}",
            )
            return
        self._write_response_success(
            id=command_id, command=command, data={"summary": summary}
        )

    def _diagnostics_query_from_payload(
        self, payload: dict[str, Any], *, default_limit: int | None
    ) -> DiagnosticsQuery:
        raw_limit = payload.get("limit", default_limit)
        if raw_limit is not None and (not isinstance(raw_limit, int) or raw_limit <= 0):
            raise ValueError("Diagnostic limit must be a positive integer.")
        return DiagnosticsQuery(
            phase=self._optional_string(payload, "phase"),  # type: ignore[arg-type]
            source=self._optional_string(payload, "source"),  # type: ignore[arg-type]
            level=self._optional_string(
                payload, "level", "diagnosticType", "diagnostic_type"
            ),  # type: ignore[arg-type]
            session_id=self._optional_string(payload, "sessionId", "session_id"),
            entry_id=self._optional_string(payload, "entryId", "entry_id"),
            tool_call_id=self._optional_string(payload, "toolCallId", "tool_call_id"),
            code=self._optional_string(payload, "code"),
            limit=raw_limit,
        )

    def _handle_get_last_error_report_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        getter = getattr(self.session, "get_last_error_report", None)
        if not callable(getter):
            self._write_response_error(
                id=command_id,
                command="get_last_error_report",
                error="Diagnostics are not available.",
            )
            return
        try:
            report = self._diagnostics_projection.serialize_error_report(getter())
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_last_error_report",
                error=f"Failed to query last error report: {error}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="get_last_error_report",
            data={"report": report},
        )

    def _handle_get_packages_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        catalog_path = self._optional_string(payload, "catalogPath", "catalog_path")
        getter = getattr(self.runtime, "get_packages", None)
        if callable(getter):
            get_packages = getter
        else:
            getter = getattr(self.session, "get_packages", None)
            if not callable(getter):
                self._write_response_error(
                    id=command_id,
                    command="get_packages",
                    error="Package listing is not available.",
                )
                return
            get_packages = getter
        try:
            packages = get_packages(catalog_path=catalog_path)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="get_packages",
                error=f"Failed to query packages: {error}",
                code="package_query_failed",
            )
            return
        if not isinstance(packages, list):
            self._write_response_error(
                id=command_id,
                command="get_packages",
                error="Package listing returned an invalid response.",
                code="invalid_package_query_response",
            )
            return
        self._write_response_success(
            id=command_id, command="get_packages", data={"packages": packages}
        )

    async def _handle_materialize_package_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_lifecycle_command(
            command_id=command_id,
            payload=payload,
            command="materialize_package",
            method_name="materialize_package",
            unavailable_message="Package materialization is not available.",
            failure_message="Failed to materialize package",
            invalid_message="Package materialization returned an invalid response.",
            failure_code="package_materialization_failed",
            invalid_code="invalid_package_materialization_response",
        )

    async def _handle_install_package_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_lifecycle_command(
            command_id=command_id,
            payload=payload,
            command="install_package",
            method_name="install_package",
            unavailable_message="Package installation is not available.",
            failure_message="Failed to install package",
            invalid_message="Package installation returned an invalid response.",
            failure_code="package_installation_failed",
            invalid_code="invalid_package_installation_response",
        )

    async def _handle_update_package_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_lifecycle_command(
            command_id=command_id,
            payload=payload,
            command="update_package",
            method_name="update_package",
            unavailable_message="Package update is not available.",
            failure_message="Failed to update package",
            invalid_message="Package update returned an invalid response.",
            failure_code="package_update_failed",
            invalid_code="invalid_package_update_response",
        )

    async def _handle_update_packages_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_collection_command(
            command_id=command_id,
            command="update_packages",
            method_name="update_packages",
            data_key="records",
            unavailable_message="Package update is not available.",
            failure_message="Failed to update packages",
            invalid_message="Package update returned an invalid response.",
            failure_code="package_update_failed",
            invalid_code="invalid_package_update_response",
        )

    async def _handle_check_package_updates_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_collection_command(
            command_id=command_id,
            command="check_package_updates",
            method_name="check_package_updates",
            data_key="updates",
            unavailable_message="Package update check is not available.",
            failure_message="Failed to check package updates",
            invalid_message="Package update check returned an invalid response.",
            failure_code="package_update_check_failed",
            invalid_code="invalid_package_update_check_response",
        )

    async def _handle_remove_package_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_lifecycle_command(
            command_id=command_id,
            payload=payload,
            command="remove_package",
            method_name="remove_package",
            unavailable_message="Package removal is not available.",
            failure_message="Failed to remove package",
            invalid_message="Package removal returned an invalid response.",
            failure_code="package_removal_failed",
            invalid_code="invalid_package_removal_response",
        )

    async def _handle_uninstall_package_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        await self._handle_package_lifecycle_command(
            command_id=command_id,
            payload=payload,
            command="uninstall_package",
            method_name="uninstall_package",
            unavailable_message="Package uninstallation is not available.",
            failure_message="Failed to uninstall package",
            invalid_message="Package uninstallation returned an invalid response.",
            failure_code="package_uninstallation_failed",
            invalid_code="invalid_package_uninstallation_response",
        )

    async def _handle_package_collection_command(
        self,
        *,
        command_id: str | None,
        command: str,
        method_name: str,
        data_key: str,
        unavailable_message: str,
        failure_message: str,
        invalid_message: str,
        failure_code: str,
        invalid_code: str,
    ) -> None:
        method = getattr(self.runtime, method_name, None)
        if not callable(method):
            method = getattr(self.session, method_name, None)
        if not callable(method):
            self._write_response_error(
                id=command_id, command=command, error=unavailable_message
            )
            return
        try:
            result = method()
            if inspect.isawaitable(result):
                result = await result
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command=command,
                error=f"{failure_message}: {error}",
                code=failure_code,
            )
            return
        if not isinstance(result, list):
            self._write_response_error(
                id=command_id, command=command, error=invalid_message, code=invalid_code
            )
            return
        self._write_response_success(
            id=command_id, command=command, data={data_key: result}
        )

    async def _handle_package_lifecycle_command(
        self,
        *,
        command_id: str | None,
        payload: dict[str, Any],
        command: str,
        method_name: str,
        unavailable_message: str,
        failure_message: str,
        invalid_message: str,
        failure_code: str,
        invalid_code: str,
    ) -> None:
        source = self._require_string(payload, "source")
        getter = getattr(self.runtime, method_name, None)
        if callable(getter):
            lifecycle_method = getter
        else:
            getter = getattr(self.session, method_name, None)
            if not callable(getter):
                self._write_response_error(
                    id=command_id,
                    command=command,
                    error=unavailable_message,
                )
                return
            lifecycle_method = getter
        try:
            record = lifecycle_method(source)
            if inspect.isawaitable(record):
                record = await record
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command=command,
                error=f"{failure_message}: {error}",
                code=failure_code,
            )
            return
        if not isinstance(record, dict):
            self._write_response_error(
                id=command_id,
                command=command,
                error=invalid_message,
                code=invalid_code,
            )
            return
        if failure := _package_lifecycle_failure(record):
            self._write_response_error(
                id=command_id,
                command=command,
                error=f"{failure_message}: {failure}",
                code=failure_code,
            )
            return
        self._write_response_success(
            id=command_id, command=command, data={"record": record}
        )

    async def _handle_bash_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._ensure_no_active_bash(command="bash")
        command = self._require_string(payload, "command")
        task = asyncio.create_task(
            self._run_bash(
                command_id=command_id,
                command=command,
                cwd=self._optional_string(payload, "cwd"),
                env=self._coerce_env(payload.get("env")),
                timeout_seconds=self._optional_number(
                    payload, "timeoutSeconds", "timeout_seconds"
                ),
                stdin=self._optional_string(payload, "stdin"),
            )
        )
        self._active_bash_task = task
        self._task_tracker.track(task)

    async def _run_bash(
        self,
        *,
        command_id: str | None,
        command: str,
        cwd: str | None,
        env: list[list[str]] | None,
        timeout_seconds: float | None,
        stdin: str | None,
    ) -> None:
        try:
            result = await self.session.execute_bash(
                command,
                cwd=cwd,
                env=env,
                timeout_seconds=timeout_seconds,
                stdin=stdin,
            )
        except Exception as exc:
            self._write_response_error(id=command_id, command="bash", error=str(exc))
        else:
            try:
                data = self._camelize(self._serialize_json_value(result))
            except Exception as exc:
                self._write_response_error(
                    id=command_id,
                    command="bash",
                    error=f"Failed to serialize bash result: {exc}",
                )
                return
            self._write_response_success(
                id=command_id,
                command="bash",
                data=data,
            )
        finally:
            if self._active_bash_task is asyncio.current_task():
                self._active_bash_task = None

    def _handle_abort_bash_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        self.session.abort_bash()
        self._write_response_success(id=command_id, command="abort_bash")

    async def _handle_compact_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            result = await self._rpc_operations.compact(payload)
        except Exception as exc:
            self._write_response_error(
                id=command_id,
                command="compact",
                error=f"Failed to compact session: {exc}",
            )
            return
        try:
            data = self._camelize(self._serialize_json_value(result))
        except Exception as exc:
            self._write_response_error(
                id=command_id,
                command="compact",
                error=f"Failed to serialize compact response: {exc}",
            )
            return
        self._write_response_success(
            id=command_id,
            command="compact",
            data=data,
        )

    def _handle_set_auto_retry_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            self._rpc_operations.set_auto_retry(payload)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_auto_retry",
                error=f"Failed to set auto-retry: {error}",
            )
            return
        self._write_response_success(id=command_id, command="set_auto_retry")

    def _handle_abort_retry_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        self._rpc_operations.abort_retry()
        self._write_response_success(id=command_id, command="abort_retry")

    def _handle_set_auto_compaction_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            self._rpc_operations.set_auto_compaction(payload)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="set_auto_compaction",
                error=f"Failed to set auto-compaction: {error}",
            )
            return
        self._write_response_success(id=command_id, command="set_auto_compaction")

    def _handle_export_html_command(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        output_path = self._optional_string(payload, "outputPath", "output_path")
        try:
            path = self.session.export_to_html(output_path)
        except Exception as error:
            self._write_response_error(
                id=command_id,
                command="export_html",
                error=f"Failed to export HTML: {error}",
            )
            return
        if not isinstance(path, str):
            if isinstance(path, Path):
                path = str(path)
            else:
                self._write_response_error(
                    id=command_id,
                    command="export_html",
                    error="Export returned an invalid response.",
                )
                return
        self._write_response_success(
            id=command_id,
            command="export_html",
            data={"path": path},
        )

    def _bind_session(self, session: Any) -> None:
        self._unsubscribe()
        self.session = session
        self._session_operations = self._find_session_operations(session)
        self._configure_tool_rendering(session)
        self._unsubscribe = self._subscribe_to_events(session)
        self._bind_extension_ui_context(session)

    def _bind_extension_ui_context(self, session: Any) -> None:
        setter = getattr(session, "set_extension_ui_context", None)
        if callable(setter):
            setter(self.extension_ui_context)

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

    def _subscribe_to_events(self, session: Any):
        """Prefer the common runtime event stream when one is available.

        Products may still expose a lower-level session event stream when no
        runtime projection is available; the injected projection owns its
        payload vocabulary.
        """

        subscribe_runtime_events = getattr(session, "subscribe_runtime_events", None)
        if callable(subscribe_runtime_events):
            return subscribe_runtime_events(self._handle_runtime_event)
        return session.subscribe(self._handle_event)

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

    def _configure_tool_rendering(self, session: Any) -> None:
        if not self.render_tool_events:
            self._tool_render_runtime = None
            self._tool_definition_resolver = None
            return
        self._tool_render_runtime = ToolRenderRuntime(cwd=_session_cwd(session))
        self._tool_definition_resolver = _tool_definition_resolver(session)

    def _ensure_no_active_bash(self, *, command: str) -> None:
        task = self._active_bash_task
        if task is not None and not task.done():
            raise RuntimeError(
                f"{command} requires the active bash command to finish or abort first"
            )

    def _require_current_session(self) -> Any:
        getter = getattr(self.runtime, "get_current_session", None)
        if callable(getter):
            session = getter()
        else:
            session = getattr(self.runtime, "session", None)
        if session is None:
            raise RuntimeError("RPC mode requires an active session")
        return session

    def _find_session_operations(self, session: Any) -> SessionOperationRuntime | None:
        control = getattr(session, "session_control", None)
        if control is None:
            return None
        runtime = self.runtime
        clone_operation = getattr(runtime, "clone_session_operation", None)
        if not callable(clone_operation):
            async def clone_operation():
                return await runtime.fork_session_operation(None, position="at")
        return SessionOperationRuntime(
            cast(Any, control),
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
        if self._session_operations is None:
            raise TypeError("RPC mode session must expose Harness session_control")
        return self._session_operations

    def _serialize_session_state(self, session: Any) -> RpcSessionState:
        """Project the standard session state into the host state contract."""

        state = session.get_state()
        session_id = self._safe_getattr(session, "session_id", None)
        if session_id is None:
            session_id_value = ""
        elif isinstance(session_id, str):
            session_id_value = session_id
        else:
            session_id_value = self._safe_string(session_id)

        session_name = self._safe_getattr(session, "session_name", None)
        if session_name is not None and not isinstance(session_name, str):
            session_name = self._safe_string(session_name)

        session_file = self._safe_getattr(session, "session_file", None)
        if isinstance(session_file, Path):
            session_file_value: str | None = str(session_file)
        elif session_file is None:
            session_file_value = None
        else:
            session_file_value = self._safe_string(session_file)
        steering = self._list_attr(state, "steering")
        follow_up = self._list_attr(state, "follow_up")
        thinking_level = self._safe_getattr(state, "thinking_level", "off")
        if not isinstance(thinking_level, str):
            thinking_level = self._safe_string(thinking_level) or "off"
        if thinking_level not in _THINKING_LEVEL_ORDER:
            thinking_level = "off"
        try:
            model = self._serialize_state_model(session, state)
        except Exception:
            model = None
        payload = {
            "sessionId": session_id_value,
            "model": model,
            "isStreaming": self._run_status(state) == "running",
            "isCompacting": bool(self._safe_getattr(state, "is_compacting", False)),
            "steeringMode": self._queue_mode(session, "steering_mode"),
            "followUpMode": self._queue_mode(session, "follow_up_mode"),
            "autoCompactionEnabled": bool(
                self._safe_getattr(session, "auto_compaction_enabled", False)
            ),
            "messageCount": len(self._get_session_messages(session)),
            "pendingMessageCount": len(steering) + len(follow_up),
            "thinkingLevel": thinking_level,
        }
        if isinstance(session_name, str) and session_name:
            payload["sessionName"] = session_name
        if session_file_value:
            payload["sessionFile"] = session_file_value
        return payload

    def _run_status(self, state: Any) -> str:
        run = self._safe_getattr(state, "run", None)
        status = self._safe_getattr(run, "status", None)
        return status if isinstance(status, str) else "idle"

    def _queue_mode(self, session: Any, attr: str) -> str:
        value = self._safe_getattr(session, attr, None)
        if value in {"all", "one-at-a-time"}:
            return value
        agent_value = self._safe_getattr(
            self._safe_getattr(session, "agent", None), attr, None
        )
        if agent_value in {"all", "one-at-a-time"}:
            return agent_value
        return "one-at-a-time"

    def _list_attr(self, target: Any, attr: str) -> list[object]:
        value = self._safe_getattr(target, attr, None)
        return list(value) if isinstance(value, list) else []

    def _serialize_state_model(self, session: Any, state: Any) -> RpcModel | None:
        """Project the active session model into the RPC wire shape."""

        agent = self._safe_getattr(session, "agent", None)
        agent_state = self._safe_getattr(agent, "state", None)
        model = self._safe_getattr(agent_state, "model", None)
        if model is not None:
            try:
                payload = self._serialize_model(session, model)
                if payload is not None and not _is_unknown_model(payload):
                    return payload
            except Exception:
                pass

        selection = self._safe_getattr(state, "model_selection", None)
        resolved_model = self._resolve_model_for_rpc(session, selection)
        if resolved_model is not None:
            try:
                payload = self._serialize_model(session, resolved_model)
                if payload is not None and not _is_unknown_model(payload):
                    return payload
            except Exception:
                pass

        try:
            payload = self._serialize_model_selection_as_model(selection)
            if payload is not None and not _is_unknown_model(payload):
                return payload
            return self._serialize_default_model(session)
        except Exception:
            return None

    def _serialize_default_model(self, session: Any) -> RpcModel | None:
        """Fallback to first non-placeholder model from session's model list."""

        getter = getattr(session, "get_available_models", None)
        if not callable(getter):
            return None
        try:
            models = getter()
        except Exception:
            return None
        if not isinstance(models, list):
            return None
        for selection in models:
            payload = None
            try:
                payload = self._serialize_model_selection_as_model(selection)
            except Exception:
                payload = None
            if payload is not None and not _is_unknown_model(payload):
                return payload
            try:
                resolved = self._resolve_model_for_rpc(session, selection)
            except Exception:
                resolved = None
            if resolved is None:
                continue
            try:
                payload = self._serialize_model(session, resolved)
            except Exception:
                payload = None
            if payload is not None and not _is_unknown_model(payload):
                return payload
        return None

    def _serialize_available_models(
        self, session: Any, selections: list[Any]
    ) -> list[RpcModel]:
        serialized: list[RpcModel] = []
        for selection in selections:
            try:
                resolved_model = self._resolve_model_for_rpc(session, selection)
                payload = (
                    self._serialize_model(session, resolved_model)
                    if resolved_model is not None
                    else self._serialize_model_selection_as_model(selection)
                )
            except Exception:
                continue
            if payload is not None:
                serialized.append(payload)
        return serialized

    def _resolve_model_for_rpc(self, session: Any, selection: Any) -> object | None:
        registry = self._safe_getattr(session, "model_registry", None)
        builder = self._safe_getattr(registry, "build_model", None)
        if selection is not None and callable(builder):
            try:
                return builder(selection)
            except Exception:
                return None
        return None

    def _serialize_session_stats(self, stats: Any) -> dict[str, Any]:
        return self._camelize(self._serialize_json_value(stats))

    def _serialize_session_listing_item(self, session: Any) -> dict[str, Any]:
        fields = (
            "session_id",
            "cwd",
            "session_file",
            "parent_session",
            "leaf_id",
            "created_at",
            "updated_at",
            "name",
            "message_count",
            "entry_count",
            "first_message",
            "all_messages_text",
            "last_message_preview",
            "model",
            "has_diagnostics",
            "diagnostic_count",
            "last_diagnostic_code",
            "last_diagnostic_level",
        )
        raw = {
            name: value
            for name in fields
            if (value := self._safe_getattr(session, name, _MISSING)) is not _MISSING
        }
        if not isinstance(raw.get("session_id"), str):
            raise TypeError("session listing items require session_id")
        serialized = self._serialize_json_value(raw)
        if not isinstance(serialized, dict):
            raise TypeError("session listing items must serialize to objects")
        return self._camelize(serialized)

    def _serialize_command_descriptor(self, command: object) -> dict[str, Any]:
        name = self._safe_getattr(command, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("command descriptor requires name")
        description = self._safe_getattr(command, "description", None)
        source = self._safe_getattr(command, "source", None)
        payload = {
            "name": name,
            "description": description if isinstance(description, str) else None,
            "source": source if isinstance(source, str) else "",
            "sourceInfo": self._serialize_command_source_info(
                self._safe_getattr(command, "source_info", None)
            ),
        }
        invocation_name = self._safe_getattr(command, "invocation_name", None)
        if isinstance(invocation_name, str) and invocation_name:
            payload["invocationName"] = invocation_name
        conflict_group = self._safe_getattr(command, "conflict_group", None)
        if isinstance(conflict_group, str) and conflict_group:
            payload["conflictGroup"] = conflict_group
        argument_hint = self._safe_getattr(command, "argument_hint", None)
        if isinstance(argument_hint, str) and argument_hint:
            payload["argumentHint"] = argument_hint
        return payload

    def _serialize_command_source_info(self, source_info: object) -> dict[str, Any]:
        path = self._safe_getattr(source_info, "path", "")
        base_dir = self._safe_getattr(source_info, "base_dir", None)
        return {
            "path": self._safe_string(path),
            "source": self._safe_getattr(source_info, "source", "filesystem"),
            "scope": self._safe_getattr(source_info, "scope", "project"),
            "origin": self._safe_getattr(source_info, "origin", "top-level"),
            "baseDir": self._safe_string(base_dir) if base_dir is not None else None,
        }

    def _get_session_messages(self, session: Any) -> list[object]:
        context_getter = self._safe_getattr(session, "get_session_context", None)
        if callable(context_getter):
            try:
                context = context_getter()
            except Exception:
                context = None
            else:
                messages = self._safe_getattr(context, "messages", None)
                if isinstance(messages, list | tuple):
                    return list(messages)
        messages = self._safe_getattr(session, "messages", None)
        if isinstance(messages, list | tuple):
            return list(messages)
        return []

    def _serialize_model_selection(
        self, selection: ModelSelection | None
    ) -> dict[str, str] | None:
        if selection is None:
            return None
        payload = {
            "provider": selection.provider,
            "modelId": selection.model_id,
        }
        if selection.endpoint_id:
            payload["endpointId"] = selection.endpoint_id
        return payload

    def _serialize_model_selection_as_model(
        self, selection: ModelSelection | None
    ) -> RpcModel | None:
        if selection is None:
            return None
        provider = self._safe_getattr(selection, "provider", None)
        model_id = self._safe_getattr(selection, "model_id", None)
        if not isinstance(provider, str) or not isinstance(model_id, str):
            provider = self._safe_string(provider) if provider is not None else None
            model_id = self._safe_string(model_id) if model_id is not None else None
            if not provider or not model_id:
                return None
        payload: RpcModel = {
            "provider": provider,
            "id": model_id,
        }
        return payload

    def _serialize_model(self, session: Any, model: object) -> RpcModel | None:
        provider = self._safe_getattr(model, "provider_id", None) or self._safe_getattr(
            model, "provider", None
        )
        model_id = self._safe_getattr(model, "id", None)
        if not provider or not model_id:
            return None

        data: RpcModel = {
            "provider": str(provider),
            "id": str(model_id),
        }
        name = self._safe_getattr(model, "name", None)
        if isinstance(name, str) and name:
            data["name"] = name
        else:
            data["name"] = str(model_id)

        endpoint = self._resolve_model_endpoint(session, model)
        if endpoint is not None:
            api = self._safe_getattr(endpoint, "api", None)
            if isinstance(api, str) and api:
                data["api"] = api
            base_url = self._safe_getattr(endpoint, "base_url", None)
            if isinstance(base_url, str) and base_url:
                data["baseUrl"] = base_url

        modalities = self._safe_getattr(model, "input", None)
        if isinstance(modalities, tuple | list):
            data["input"] = [str(modality) for modality in modalities]

        context_window = self._safe_getattr(model, "context_window", None)
        if isinstance(context_window, int):
            data["contextWindow"] = context_window

        max_tokens = self._safe_getattr(model, "max_tokens", None)
        if isinstance(max_tokens, int):
            data["maxTokens"] = max_tokens

        reasoning = self._safe_getattr(model, "reasoning", None)
        if isinstance(reasoning, bool):
            data["reasoning"] = reasoning

        pricing = self._safe_getattr(model, "pricing", None)
        cost = self._serialize_model_cost(pricing)
        if cost is not None:
            data["cost"] = cost

        compat = self._safe_getattr(model, "compat", None)
        serialized_compat = self._serialize_model_compat(compat)
        if serialized_compat is not None:
            data["compat"] = serialized_compat

        return data

    def _resolve_model_endpoint(self, session: Any, model: object) -> object | None:
        provider = self._safe_getattr(model, "provider_id", None) or self._safe_getattr(
            model, "provider", None
        )
        endpoint_id = self._safe_getattr(model, "endpoint_id", None)
        if not provider or not endpoint_id:
            return None

        registry = self._safe_getattr(session, "model_registry", None)
        if registry is None:
            return None

        ai_registry = self._safe_getattr(registry, "ai_registry", None)
        getter = self._safe_getattr(ai_registry, "get_endpoint", None)
        if callable(getter):
            try:
                endpoint = getter(provider, endpoint_id)
            except Exception:
                endpoint = None
            if endpoint is not None:
                return endpoint

        getter = self._safe_getattr(registry, "get_endpoint", None)
        if callable(getter):
            try:
                return getter(provider, endpoint_id)
            except Exception:
                return None

        return None

    def _serialize_model_cost(self, pricing: object) -> RpcModelCost | None:
        if pricing is None:
            return None
        input_cost = self._safe_getattr(pricing, "input", None)
        output_cost = self._safe_getattr(pricing, "output", None)
        cache_read = self._safe_getattr(pricing, "cache_read", None)
        cache_write = self._safe_getattr(pricing, "cache_write", None)
        values = (input_cost, output_cost, cache_read, cache_write)
        if any(
            value is None
            or isinstance(value, bool)
            or not isinstance(value, int | float)
            or not isfinite(value)
            or value < 0
            for value in values
        ):
            return None
        return {
            "input": cast(float | int, input_cost),
            "output": cast(float | int, output_cost),
            "cacheRead": cast(float | int, cache_read),
            "cacheWrite": cast(float | int, cache_write),
        }

    def _serialize_model_compat(self, compat: object) -> dict[str, Any] | None:
        if compat is None:
            return None
        to_raw = self._safe_getattr(compat, "to_raw", None)
        if callable(to_raw):
            try:
                raw = to_raw()
            except Exception:
                return None
            if isinstance(raw, dict) and raw:
                return raw
            return None
        if isinstance(compat, dict) and compat:
            return compat
        return None

    def _safe_getattr(self, target: Any, name: str, default: object) -> object:
        try:
            return getattr(target, name, default)
        except Exception:
            return default

    def _serialize_json_value(self, value: object) -> object:
        return project_host_value(value, name="rpc_output", surface="RPC")

    def _camelize(self, value: object) -> object:
        if isinstance(value, dict):
            return {
                _snake_to_camel(str(key)): self._camelize(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._camelize(item) for item in value]
        return value

    def _extract_last_assistant_text(self) -> str | None:
        getter = getattr(self.session, "get_last_assistant_text", None)
        if callable(getter):
            return getter()
        return None

    def _extract_session_entry_text(self, entry_id: str) -> str | None:
        getter = getattr(self.session, "get_entry_text", None)
        if callable(getter):
            return getter(entry_id)
        return None

    def _safe_string(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, float) and not isfinite(value):
            return ""
        if isinstance(value, bool | int | float):
            return str(value)
        return ""

    def _coerce_env(self, env: object) -> list[list[str]] | None:
        if env is None:
            return None
        if isinstance(env, str) or not isinstance(env, list):
            raise ValueError("env must contain 2-item string pairs")
        normalized: list[list[str]] = []
        for pair in env:
            if (
                isinstance(pair, str)
                or not isinstance(pair, list | tuple)
                or len(pair) != 2
            ):
                raise ValueError("env must contain 2-item string pairs")
            if not all(isinstance(part, str) for part in pair):
                raise ValueError("env must contain 2-item string pairs")
            normalized.append([pair[0], pair[1]])
        return normalized

    def _require_mode(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if value in {"all", "one-at-a-time"}:
            return value
        raise ValueError(f"{key} must be 'all' or 'one-at-a-time'")

    def _require_string(self, payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        if not keys:
            raise ValueError("missing required string field")
        raise ValueError(f"missing required string field: {keys[0]}")

    def _optional_string(self, payload: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                return value
            raise ValueError(f"{key} must be a string")
        return None

    def _optional_number(self, payload: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, int | float) and not isinstance(value, bool):
                try:
                    normalized = float(value)
                except OverflowError as exc:
                    raise ValueError(f"{key} must be a finite number") from exc
                if isfinite(normalized):
                    return normalized
                raise ValueError(f"{key} must be a finite number")
            raise ValueError(f"{key} must be a number")
        return None

    def _optional_int(self, payload: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            raise ValueError(f"{key} must be an integer")
        return None

    def _optional_bool(self, payload: dict[str, Any], *keys: str) -> bool | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                return value
            raise ValueError(f"{key} must be a boolean")
        return None

    def _write_response_success(
        self, *, command: str, id: str | None = None, data: object = _MISSING
    ) -> None:
        payload: dict[str, object] = {
            "type": "response",
            "command": command,
            "success": True,
        }
        if id is not None:
            payload["id"] = id
        if data is not _MISSING:
            payload["data"] = data
        self._write_json_line(payload)

    def _write_response_error(
        self,
        *,
        command: str,
        error: str,
        id: str | None = None,
        code: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "type": "response",
            "command": command,
            "success": False,
            "error": error,
        }
        if id is not None:
            payload["id"] = id
        if code is not None:
            payload["errorCode"] = code
            payload["errorInfo"] = {
                "code": code,
                "message": error,
                "command": command,
            }
        self._write_json_line(payload)

    def _write_json_line(self, payload: object) -> None:
        def _safe_extract_fallback_fields(
            item: object,
        ) -> tuple[str | None, str | None]:
            if not isinstance(item, dict):
                return None, None
            return (
                _strict_fallback_string(item.get("id")),
                _strict_fallback_string(item.get("command")),
            )

        def _strict_fallback_string(value: object) -> str | None:
            if type(value) is not str:
                return None
            try:
                projected = project_host_value(
                    value, name="rpc_fallback", surface="RPC"
                )
            except Exception:
                return None
            return projected if isinstance(projected, str) else None

        try:
            serialized = self._serialize_json_value(payload)
            line = json.dumps(serialized, ensure_ascii=False)
        except Exception:
            fallback_id, fallback_command = _safe_extract_fallback_fields(payload)
            fallback_payload: dict[str, object] = {
                "type": "response",
                "command": "response",
                "success": False,
                "error": "Failed to serialize RPC output.",
            }
            if fallback_id is not None:
                fallback_payload["id"] = fallback_id
            if fallback_command is not None:
                fallback_payload["command"] = fallback_command
            line = json.dumps(
                project_host_value(
                    fallback_payload, name="rpc_fallback", surface="RPC"
                ),
                ensure_ascii=False,
                allow_nan=False,
            )
        self.stdout.write(line + "\n")
        flush = getattr(self.stdout, "flush", None)
        if callable(flush):
            flush()


async def run_rpc_host(
    *,
    runtime: Any,
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


def _session_cwd(session: Any) -> str:
    session_manager = getattr(session, "session_manager", None)
    get_cwd = getattr(session_manager, "get_cwd", None)
    if callable(get_cwd):
        try:
            return str(get_cwd())
        except Exception:
            return ""
    return ""


def _tool_definition_resolver(session: Any) -> ToolDefinitionResolver | None:
    getter = getattr(session, "get_tool_definition", None)
    if not callable(getter):
        return None

    def resolve(name: str):
        try:
            return getter(name)
        except Exception:
            return None

    return resolve


def _package_lifecycle_failure(record: dict[str, Any]) -> str | None:
    if record.get("lifecycle") != "failed":
        return None
    message = record.get("errorMessage", record.get("error_message"))
    return (
        str(message)
        if isinstance(message, str) and message
        else "Package lifecycle failed."
    )


def _snake_to_camel(value: str) -> str:
    if "_" not in value:
        return value
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _is_unknown_model(payload: RpcModel | dict[str, object] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    provider = payload.get("provider")
    model_id = payload.get("id")
    return provider == "unknown" and model_id == "unknown"


__all__ = [
    "RpcEventProjection",
    "RpcDiagnosticsProjection",
    "RpcExtensionUIContext",
    "RpcHost",
    "RpcModel",
    "RpcModelCost",
    "RpcSessionState",
    "STANDARD_AGENT_RPC_EVENT_PROJECTION",
    "STANDARD_RPC_DIAGNOSTICS_PROJECTION",
    "run_rpc_host",
]
