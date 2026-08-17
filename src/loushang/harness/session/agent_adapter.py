"""Reusable control surface for Product Agent session adapters.

The mixin deliberately relies on attributes assembled by ``SessionComposition``
and ``SessionOperations``.  It contains only lifecycle, resource, event, and
operation plumbing; Product subclasses retain their policies and content.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, cast

from loushang.agent import Agent, ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import AssistantMessage
from loushang.harness.approval import (
    ApprovalPermissionsSnapshot,
    InteractiveApprovalResolver,
)
from loushang.harness.capabilities import CapabilityCompositionRuntime
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft, DiagnosticPhase
from loushang.harness.events import (
    PackageProgressChanged,
    project_session_runtime_event,
)
from loushang.harness.extensions import ExtensionProviderRuntime
from loushang.harness.extensions.agent import ExtensionAgentHookRuntime
from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.extensions.context import (
    ReplacedSessionContext,
    SessionBeforeTreeEvent,
    SessionShutdownEvent,
)
from loushang.harness.permissions import (
    PermissionProfileSnapshot,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
    PackageProgressEvent,
)
from loushang.harness.resources.packages.session import SessionPackageController
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.session.agent_product_runtime import (
    AgentProductSessionRuntime as AgentProductSessionRuntime,
)
from loushang.harness.session.agent_product_runtime import (
    build_agent_product_session_runtime_ports,
    build_agent_session_lifecycle_hooks,
    prepare_current_agent_session,
)
from loushang.harness.session.approval_interaction import (
    AgentSessionApprovalRuntime,
)
from loushang.harness.session.bash import UserBashHookResult, UserBashRequest
from loushang.harness.session.composition import (
    SessionComposition,
    SessionExtensionCompositionPort,
    SessionModelCatalogPort,
)
from loushang.harness.session.export import (
    export_session_to_html,
    export_session_to_jsonl,
)
from loushang.harness.session.extension_bridge import AgentSessionExtensionBridge
from loushang.harness.session.facade import (
    SessionFacade,
)
from loushang.harness.session.operations_runtime import (
    SessionOperations,
    SessionOperationsPorts,
)
from loushang.harness.session.settings import SessionSettingsBinding
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.protocol import (
    normalize_bash_result_from_protocol,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import (
    AgentTranscriptContext,
    BranchSummaryOutput,
    CompactionResult,
    CompactionStatus,
    ProductTranscriptSession,
    TranscriptNavigationPlan,
    TranscriptNavigationResult,
    normalize_branch_summary_output,
)
from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecResult,
    ExecService,
    ExecUpdateCallback,
)


class _ReloadableSettings(Protocol):
    def reload(self) -> None: ...


class AgentSessionAdapterMixin(SessionFacade[Any, Any, Any, Any, Any, Any, Any]):
    """Typed base for standard Agent Product session adapters."""

    agent: Agent
    session_manager: ProductTranscriptSession[Any, Any]
    model_registry: SessionModelCatalogPort | None
    diagnostics_service: DiagnosticsService | None
    _approval_runtime: AgentSessionApprovalRuntime
    _capability_runtime: CapabilityCompositionRuntime | None
    _composition: SessionComposition
    _exec_service: ExecService
    _extension_provider_controller: ExtensionProviderRuntime
    _extension_replacement_controller: ExtensionReplacementRuntime
    _extension_runner: SessionExtensionCompositionPort | None
    _extension_tool_registration_leases: list[RegistrationLease]
    _extension_bridge: AgentSessionExtensionBridge
    _operations: SessionOperations
    _package_controller: SessionPackageController
    _package_materializer: PackageMaterializer | None
    _resource_loader: ResourceLoader | None
    _session_default_model: Model
    _settings_controller: SessionSettingsBinding
    _tool_registry: WorkspaceToolRegistry | None
    resource_bundle: ResourceBundle | None

    def _create_replaced_session_context(
        self,
        session: object | None,
    ) -> ReplacedSessionContext:
        raise NotImplementedError

    @property
    def resource_loader(self):
        return self._resource_loader

    @property
    def _approval_resolver(self) -> InteractiveApprovalResolver | None:
        """Compatibility view over the approval runtime's resolver."""

        return self._approval_runtime.resolver

    def create_replaced_session_context(self, session: object | None = None):
        return self._create_replaced_session_context(
            self if session is None else session
        )

    async def set_active_tools(self, tool_names: list[str]) -> None:
        await self._operations.set_active_tools(tool_names, emit_refresh=True)

    def register_runtime_tools(
        self,
        tools: Iterable[object],
        *,
        activate: bool = False,
        source_info: object | None = None,
    ) -> tuple[ToolDefinition, ...]:
        """Register live-bound tools without exposing composition internals."""

        definitions = tuple(
            self._composition.tool_controller.register_runtime_tool(
                tool,
                source_info=source_info,
            )
            for tool in tools
        )
        if activate:
            active = self._composition.tool_controller.get_active_tool_names()
            self._composition.tool_controller.apply_active_tools(
                [
                    *active,
                    *(
                        definition.name
                        for definition in definitions
                        if definition.name not in active
                    ),
                ]
            )
        return definitions

    def _apply_agent_transcript_context(
        self, session_context: AgentTranscriptContext
    ) -> None:
        self.agent.state.set_messages(list(session_context.messages))
        if self.session_manager.get_entries():
            self.agent.thinking_level = cast(
                ThinkingLevel,
                session_context.thinking_level,
            )
        resolved_model = self._session_default_model
        if session_context.model is not None and self.model_registry is not None:
            selection = ModelSelection(
                provider=session_context.model["provider"],
                endpoint_id=session_context.model["endpoint_id"],
                model_id=session_context.model["model_id"],
            )
            with suppress(KeyError, ValueError):
                resolved_model = self.model_registry.build_model(selection)
        self.agent.model = resolved_model

    def _refresh_agent_messages(self) -> None:
        self.agent.state.set_messages(
            list(self.session_manager.build_session_context().messages)
        )

    def _get_bash_definition(self):
        if self._tool_registry is None:
            raise RuntimeError("Shell execution requires a tool registry")
        for name in ("shell", "bash"):
            try:
                return self._tool_registry.get_definition(name)
            except KeyError:
                continue
        raise RuntimeError("Shell command tool is not registered")

    def _create_bash_call_id(self) -> str:
        return (
            f"bash-{self.session_manager.get_session_record().session_id}-"
            f"{len(self.session_manager.get_entries())}"
        )

    def _set_agent_steering_mode(self, mode: str) -> None:
        if mode not in {"all", "one-at-a-time"}:
            raise ValueError(f"Unsupported steering mode: {mode}")
        self.agent.steering_mode = mode

    def _set_agent_follow_up_mode(self, mode: str) -> None:
        if mode not in {"all", "one-at-a-time"}:
            raise ValueError(f"Unsupported follow-up mode: {mode}")
        self.agent.follow_up_mode = mode

    def set_approval_presenter(
        self,
        presenter: Callable[[dict[str, object]], Awaitable[None] | None] | None,
        *,
        dismisser: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        self._approval_runtime.set_presenter(presenter, dismisser=dismisser)

    async def handle_screen_approval(self, event: Mapping[str, object]) -> bool:
        return await self._approval_runtime.respond_to_event(event)

    def get_approval_permissions(self) -> ApprovalPermissionsSnapshot:
        return self._approval_runtime.permissions_snapshot()

    def get_permission_profile_snapshot(self) -> PermissionProfileSnapshot:
        return self._approval_runtime.permission_profile_snapshot()

    async def apply_approval_permission_action(self, action: str) -> bool:
        return await self._approval_runtime.apply_permission_action(action)

    def _stage_session_approvals(self) -> None:
        self._approval_runtime.stage_session()

    def _open_session_approvals(self) -> None:
        self._approval_runtime.open_session()

    def _close_session_approvals(
        self, reason: str = "Session closed before approval was resolved"
    ) -> None:
        self._approval_runtime.close_session(reason)

    async def _before_bash(self, request: UserBashRequest) -> UserBashHookResult | None:
        runner = self._extension_runner
        if runner is None or not runner.has_handlers("user_bash"):
            return None
        event_result = await runner.emit_user_bash(
            {
                "type": "user_bash",
                "command": request.command,
                "exclude_from_context": request.exclude_from_context,
                "cwd": request.cwd,
            },
            cwd=request.cwd,
        )
        self._sync_extension_diagnostics(phase="runtime")
        result = _bash_result_from_extension_result(event_result)
        if result is not None:
            return UserBashHookResult(result=result)
        return UserBashHookResult(
            operations=_bash_operations_from_extension_result(event_result)
        )

    async def get_command_argument_completions(
        self, invocation_name: str, prefix: str
    ) -> list[object] | None:
        return (
            await self._composition.command_controller.get_command_argument_completions(
                invocation_name, prefix
            )
        )

    def get_context_usage(self):
        return super().get_context_usage()

    def export_to_jsonl(self, output_path: str | None = None) -> str:
        return export_session_to_jsonl(self, output_path)

    def export_to_html(self, output_path: str | None = None) -> str:
        return export_session_to_html(self, output_path)

    def _get_builtin_session_info(self) -> dict[str, object]:
        record = self.session_manager.get_session_record()
        stats = self._composition.session_inspector.build_session_stats()
        compaction = self.get_compaction_status()
        context = stats.context_usage
        session_file = record.session_file
        return {
            "session_id": record.session_id,
            "session_name": record.metadata.name,
            "session_file": str(session_file) if session_file is not None else None,
            "cwd": record.cwd,
            "parent_session": record.parent_session,
            "leaf_id": record.leaf_id,
            "entry_count": stats.entry_count,
            "message_count": stats.message_count,
            "custom_message_count": stats.custom_message_count,
            "active_tool_count": stats.active_tool_count,
            "is_retrying": stats.is_retrying,
            "is_compacting": stats.is_compacting,
            "compaction": {
                "is_compacting": compaction.is_compacting,
                "is_branch_summarizing": compaction.is_branch_summarizing,
                "last_reason": compaction.last_reason,
                "last_stage": compaction.last_stage,
                "last_started_at": compaction.last_started_at,
                "last_completed_at": compaction.last_completed_at,
                "last_tokens_before": compaction.last_tokens_before,
                "last_tokens_after": compaction.last_tokens_after,
                "last_summary_mode": compaction.last_summary_mode,
                "last_succeeded": compaction.last_succeeded,
                "last_error": compaction.last_error,
                "aborted": compaction.aborted,
            },
            "context": {
                "tokens": context.tokens,
                "context_window": context.context_window,
                "reserve_tokens": context.reserve_tokens,
                "threshold_tokens": context.threshold_tokens,
                "threshold_reason": context.threshold_reason,
            }
            if context is not None
            else None,
        }

    async def _reload_from_extension(self) -> None:
        await self._extension_bridge.bind(reason="reload")

    def _apply_active_tools(self, tool_names: list[str]) -> None:
        self._operations.apply_active_tools(tool_names)

    async def maybe_compact_after_turn(
        self, assistant_message: AssistantMessage
    ) -> CompactionResult | None:
        return await self._operations.maybe_compact_after_turn(assistant_message)

    def get_compaction_status(self) -> CompactionStatus:
        return self._operations.get_compaction_status()

    async def navigate_tree(
        self,
        target_id: str,
        *,
        summarize: bool = False,
        custom_instructions: str | None = None,
        replace_instructions: bool = False,
        label: str | None = None,
    ) -> TranscriptNavigationResult:
        return await self._operations.navigate_tree(
            target_id,
            summarize=summarize,
            custom_instructions=custom_instructions,
            replace_instructions=replace_instructions,
            label=label,
        )

    def abort_branch_summary(self) -> None:
        self._operations.abort_branch_summary()

    async def _apply_before_tree_hook(
        self,
        plan: TranscriptNavigationPlan,
        *,
        summarize: bool,
        custom_instructions: str | None,
        replace_instructions: bool,
        label: str | None,
    ) -> tuple[str | None, bool, str | None, BranchSummaryOutput | None, bool]:
        runner = self._extension_runner
        if runner is None:
            return custom_instructions, replace_instructions, label, None, False
        decision = await runner.before_session_tree(
            SessionBeforeTreeEvent(
                target_id=plan.target_id,
                old_leaf_id=plan.old_leaf_id,
                new_leaf_id=plan.new_leaf_id,
                cwd=str(self.session_manager.get_cwd()),
                summarize=summarize,
                custom_instructions=custom_instructions,
                replace_instructions=replace_instructions,
                label=label,
            )
        )
        if decision is not None and decision.cancel:
            self._sync_extension_diagnostics(phase="runtime")
            return custom_instructions, replace_instructions, label, None, True
        if decision is None:
            return custom_instructions, replace_instructions, label, None, False
        return (
            decision.custom_instructions
            if decision.custom_instructions is not None
            else custom_instructions,
            decision.replace_instructions
            if decision.replace_instructions is not None
            else replace_instructions,
            decision.label if decision.label is not None else label,
            (
                normalize_branch_summary_output(decision.summary, from_hook=True)
                if decision.summary is not None
                else None
            ),
            False,
        )

    async def dispose(
        self, session_shutdown_event: SessionShutdownEvent | None = None
    ) -> None:
        await self._operations.dispose(session_shutdown_event)

    async def _dispose_after_session_shutdown(self) -> None:
        await self._operations.dispose_after_session_shutdown()

    async def _dispose_session_runtime_profile(self) -> None:
        dispose = getattr(self.session_manager, "dispose_runtime_profile", None)
        if callable(dispose):
            result = dispose()
            if hasattr(result, "__await__"):
                await result

    def _default_active_tool_names(self) -> list[str]:
        return self._composition.tool_controller.default_active_tool_names()

    def _register_extension_runtime_tool(
        self, tool: object, source_info: object | None = None
    ) -> None:
        definition = self._composition.tool_controller.register_runtime_tool(
            tool, source_info=source_info
        )
        if self._tool_registry is None:
            self._tool_registry = self._composition.tool_controller.tool_registry
        if definition.name in self.get_active_tool_names():
            self._extension_bridge.refresh_bindings()

    def _bind_extension_runtime_tool(
        self,
        tool: object,
        owner: RegistrationOwner | str,
        source_info: object | None = None,
    ) -> RegistrationLease:
        session_id = str(self.session_manager.get_session_record().session_id)
        resolved_owner = (
            owner
            if isinstance(owner, RegistrationOwner)
            else RegistrationOwner(
                owner_kind="extension",
                owner_id=owner,
                runtime_id=session_id,
                generation=0,
            )
        )
        lease = self._composition.tool_controller.bind_runtime_tool(
            tool,
            owner=resolved_owner,
            source_info=source_info,
        )
        if self._tool_registry is None:
            self._tool_registry = self._composition.tool_controller.tool_registry
        if isinstance(owner, str):
            self._extension_tool_registration_leases.append(lease)
        if lease.identity.public_key in self.get_active_tool_names():
            self._extension_bridge.refresh_bindings()
        return lease

    def _adopt_extension_runtime_tool(
        self,
        tool: object,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease | None:
        return self._composition.tool_controller.adopt_runtime_tool(
            tool,
            owner=owner,
            source_info=source_info,
        )

    def _stage_extension_runtime_tool(
        self,
        tool: object,
        owner: RegistrationOwner,
        source_info: object | None = None,
    ) -> RegistrationLease:
        return self._composition.tool_controller.stage_runtime_tool(
            tool,
            owner=owner,
            source_info=source_info,
        )

    def _rebuild_prompt_and_tools_view(self) -> None:
        self._composition.tool_controller.rebuild_prompt_and_tools_view()

    def _before_agent_start_system_prompt_options(self) -> dict[str, object]:
        return {
            "cwd": self.session_manager.get_cwd(),
            "selected_tools": list(self.get_active_tool_names()),
            "skills": list(self.resource_bundle.skills)
            if self.resource_bundle is not None
            else [],
            "context_files": [],
        }

    def _set_resource_bundle(self, resource_bundle: ResourceBundle | None) -> None:
        self.resource_bundle = resource_bundle

    def _refresh_resources_for_extension_runtime(self) -> None:
        self._composition.resource_refresh_runtime.refresh()

    def _resource_watch_paths(self) -> list[Path]:
        cwd = Path(self.session_manager.get_cwd())
        paths: set[Path] = {
            cwd / "AGENTS.md",
            cwd / "CLAUDE.md",
            cwd / "prompts",
            cwd / "skills",
            cwd / "extensions",
            cwd / "themes",
        }
        bundle = self.resource_bundle
        if bundle is not None:
            for descriptor in (
                *bundle.prompts,
                *bundle.skills,
                *bundle.extensions,
                *bundle.themes,
            ):
                source_root = getattr(descriptor, "source_root", None)
                source_path = getattr(descriptor, "source_path", None)
                if isinstance(source_root, Path):
                    paths.add(source_root)
                elif isinstance(source_path, Path):
                    paths.add(source_path.parent)
        return sorted(paths, key=lambda path: path.as_posix())

    def _prepare_resource_refresh(self) -> None:
        settings_manager = cast(
            _ReloadableSettings | None,
            self._settings_controller.get_settings_manager(),
        )
        if settings_manager is not None:
            settings_manager.reload()
        self._configure_package_resource_roots()

    def _configure_package_resource_roots(self) -> None:
        self._package_controller.configure_package_resource_roots()

    async def _set_active_tools_from_extension(self, tool_names: list[str]) -> None:
        await self._operations.set_active_tools(
            tool_names,
            emit_refresh=not self._extension_bridge.is_refreshing,
        )

    async def _set_model_from_extension(self, selection: object) -> None:
        await self._operations.set_model(
            selection,
            emit_refresh=not self._extension_bridge.is_refreshing,
            source="extension",
        )

    async def _append_extension_entry(
        self, custom_type: str, data: object | None = None
    ) -> None:
        await self.session_manager.append_custom_entry(custom_type, data)

    async def _set_extension_label(self, target_id: str, label: str | None) -> None:
        await self.session_manager.append_label(target_id, label)

    async def _send_message_from_extension(
        self, message: object, options: object | None = None
    ) -> None:
        await self._composition.extension_message_controller.send_message(
            message, options
        )

    async def _send_user_message_from_extension_async(
        self, content: object, options: object | None = None
    ) -> None:
        await self._composition.extension_message_controller.send_user_message(
            content, options
        )

    async def _compact_from_extension(
        self, custom_instructions: str | None = None
    ) -> object | None:
        return await self.compact(custom_instructions)

    async def _fork_from_extension(
        self, entry_id: str, options: object | None = None
    ) -> dict[str, object]:
        return await self._extension_replacement_controller.fork(entry_id, options)

    async def _new_session_from_extension(
        self, options: object | None = None
    ) -> dict[str, object]:
        return await self._extension_replacement_controller.new_session(options)

    async def _switch_session_from_extension(
        self, session_path: str, options: object | None = None
    ) -> dict[str, object]:
        return await self._extension_replacement_controller.switch_session(
            session_path, options
        )

    async def _exec_command_from_extension(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
        preview_max_lines: int = 2000,
        preview_max_bytes: int = 50 * 1024,
        artifact_dir: str | None = None,
        capture_full_output: bool = True,
        rolling_max_bytes: int = 100 * 1024,
    ) -> ExecResult:
        request = ExecRequest(
            command=_normalize_exec_command(command, args),
            cwd=_resolve_exec_cwd(self.session_manager.get_cwd(), cwd),
            env=_normalize_exec_env(env),
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            preview_max_lines=preview_max_lines,
            preview_max_bytes=preview_max_bytes,
            artifact_dir=str(artifact_dir) if artifact_dir is not None else None,
            capture_full_output=capture_full_output,
            rolling_max_bytes=rolling_max_bytes,
        )
        return await self._exec_service.execute(
            request,
            signal=self.agent.signal if signal is None else signal,
            on_update=on_update,
        )

    def _invalidate_extension_contexts(self, message: str) -> None:
        self._extension_bridge.invalidate_contexts(message)

    async def _navigate_tree_from_extension(
        self, target_id: str, options: object | None = None
    ) -> dict[str, object]:
        opts = options if isinstance(options, dict) else {}
        result = await self.navigate_tree(
            target_id,
            summarize=bool(opts.get("summarize", False)),
            custom_instructions=_optional_string(
                opts.get("customInstructions", opts.get("custom_instructions"))
            ),
            replace_instructions=bool(
                opts.get("replaceInstructions", opts.get("replace_instructions", False))
            ),
            label=_optional_string(opts.get("label")),
        )
        return {"cancelled": result.cancelled}

    def _bind_package_progress_events(self) -> None:
        if self._package_materializer is not None:
            self._package_materializer.set_progress_callback(
                self._emit_package_progress
            )

    def _emit_package_progress(self, progress: PackageProgressEvent) -> None:
        event = PackageProgressChanged(
            progress_type=progress.type,
            action=progress.action,
            source=progress.source,
            message=progress.message,
            target_path=str(progress.target_path)
            if progress.target_path is not None
            else None,
        )
        try:
            self._composition.session_runtime.schedule_event_dispatch(event)
        except RuntimeError:
            self._composition.session_runtime.dispatch_event_without_loop(event)

    async def _dispatch_event(
        self,
        event: object,
        *,
        source_record_id: str | None = None,
    ) -> None:
        await self._operations.dispatch_event(event, source_record_id=source_record_id)

    def _preflight_user_input(
        self, user_input: str, *, allow_extension_commands: bool = True
    ):
        return self._composition.command_controller.preflight_user_input(
            user_input, allow_extension_commands=allow_extension_commands
        )

    async def _preflight_user_input_async(
        self, user_input: str, *, allow_extension_commands: bool = True
    ):
        return await self._composition.command_controller.preflight_user_input_async(
            user_input, allow_extension_commands=allow_extension_commands
        )

    def _sync_extension_diagnostics(
        self,
        *,
        phase: DiagnosticPhase,
    ) -> None:
        self._composition.diagnostics_bridge.sync_extension_diagnostics(phase=phase)

    def _record_runtime_exception(self, *, code: str, exc: Exception | str) -> None:
        self._composition.diagnostics_bridge.record_runtime_exception(
            code=code, exc=exc
        )

    def _record_extension_runtime_diagnostic(self, diagnostic: DiagnosticDraft) -> None:
        self._composition.diagnostics_bridge.record_extension_runtime_diagnostic(
            diagnostic
        )

    def _wire_extension_hooks(self) -> None:
        if self._extension_runner is not None:
            ExtensionAgentHookRuntime(
                agent=self.agent,
                extension_runtime=self._extension_runner,
                get_cwd=self.session_manager.get_cwd,
            ).install()


def initialize_composed_session(
    session: AgentSessionAdapterMixin,
    composition: SessionComposition,
    *,
    operations_ports: SessionOperationsPorts,
    settings: SessionSettingsBinding,
    session_manager: ProductTranscriptSession[Any, Any],
    active_tool_names: list[str] | None,
    show_empty_tool_prompt: bool,
    tool_registry: WorkspaceToolRegistry | None,
    apply_context: Callable[[AgentTranscriptContext], None],
    sync_footer: Callable[[], None],
) -> None:
    """Install an assembled composition on a Product Session adapter."""

    if operations_ports.composition is not composition:
        raise ValueError("Session operations must use the installed composition.")
    package_controller = composition.package_controller
    if package_controller is None:
        raise RuntimeError("Agent Product sessions require package operations.")

    session._composition = composition
    session._capability_runtime = composition.capability_runtime
    session._package_controller = package_controller
    session._extension_provider_controller = composition.extension_provider_controller
    session._extension_replacement_controller = (
        composition.extension_replacement_controller
    )
    session._extension_bridge = composition.extension_bridge
    session._operations = SessionOperations(operations_ports)
    SessionFacade.__init__(
        session,
        runtime=composition.session_runtime,
        transcript=session_manager,
        tools=composition.tool_controller,
        commands=composition.command_controller,
        command_execution=composition.bash_runtime,
        view=composition.session_inspector,
        retry=composition.retry_runtime,
        identity=composition.identity_binding,
        maintenance=composition.maintenance_binding,
        resources=composition.resource_refresh_runtime,
        diagnostics=composition.diagnostics_bridge,
        packages=composition.package_controller,
        model_selection=composition.model_binding,
        extensions=composition.extension_binding,
        settings=settings,
        application_input=composition.extension_message_controller,
        event_projector=project_session_runtime_event,
        approval_interaction=(
            session._approval_runtime if session._approval_runtime.enabled else None
        ),
    )
    apply_context(session_manager.build_session_context())
    if tool_registry is not None:
        initial_names = (
            list(active_tool_names)
            if active_tool_names is not None
            else composition.tool_controller.default_active_tool_names()
        )
        session._apply_active_tools(initial_names)
    elif show_empty_tool_prompt:
        session._rebuild_prompt_and_tools_view()
    if session._extension_runner is not None:
        session._wire_extension_hooks()
        composition.extension_bridge.bind_bindings()
    sync_footer()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _normalize_exec_command(command: str, args: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(command, str):
        raise TypeError("exec_command command must be a string")
    if not command:
        raise ValueError("exec_command command must not be empty")
    if isinstance(args, str):
        raise TypeError("exec_command args must be a sequence of strings, not a string")
    normalized_args = tuple(args)
    if not all(isinstance(arg, str) for arg in normalized_args):
        raise TypeError("exec_command args must contain strings")
    return (command, *normalized_args)


def _normalize_exec_env(
    env: Mapping[str, str] | Sequence[tuple[str, str]] | None,
) -> tuple[tuple[str, str], ...]:
    if env is None:
        return ()
    if isinstance(env, Mapping):
        return tuple(env.items())
    return tuple(env)


def _resolve_exec_cwd(session_cwd: str, cwd: str | Path | None) -> str:
    base = Path(session_cwd)
    if cwd is None:
        return str(base)
    path = Path(cwd)
    return str(path if path.is_absolute() else base / path)


def _bash_result_from_extension_result(
    event_result: object | None,
) -> dict[str, object] | None:
    if event_result is None:
        return None
    result = (
        event_result.get("result")
        if isinstance(event_result, dict)
        else getattr(event_result, "result", None)
    )
    if not isinstance(result, dict):
        return None
    return normalize_bash_result_from_protocol(result)


def _bash_operations_from_extension_result(
    event_result: object | None,
) -> object | None:
    if event_result is None:
        return None
    if isinstance(event_result, dict):
        return event_result.get("operations")
    return getattr(event_result, "operations", None)


__all__ = [
    "AgentSessionAdapterMixin",
    "build_agent_product_session_runtime_ports",
    "build_agent_session_lifecycle_hooks",
    "prepare_current_agent_session",
]
