"""Reusable Product binding for the standard Agent session composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, cast

from loushang.agent import Agent
from loushang.ai.api_registry import (
    APIRegistry,
    get_default_api_registry,
)
from loushang.ai.model import ModelSelection
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.capabilities import CapabilityCompositionRuntime
from loushang.harness.config.agent import (
    CompactionSettings,
    RetrySettings,
    SettingsManager,
)
from loushang.harness.context import serialize_context_usage_payload
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.extensions import ExtensionProviderRuntime
from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.extensions.context import (
    ReplacedSessionContext,
    SessionBeforeCompactEvent,
    SessionStartEvent,
)
from loushang.harness.extensions.provider_config import provider_from_extension_config
from loushang.harness.extensions.runtime_bindings import ExtensionRuntimeBindingFactory
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.catalog import PackageSummaryProvider
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.session import (
    SessionPackageController,
    SessionPackageSettingsManager,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import (
    CancellationSignal,
    ResolvedRuntimeProfile,
    SideQuestionAnswer,
    SideQuestionCoordinator,
    SideQuestionUpdate,
)
from loushang.harness.session.agent_adapter import (
    AgentSessionAdapterMixin,
    initialize_composed_session,
)
from loushang.harness.session.approval_interaction import (
    AgentSessionApprovalRuntime,
)
from loushang.harness.session.command_controller import (
    StandardSessionCommandController,
)
from loushang.harness.session.commands.execution import StandardSessionCommandPorts
from loushang.harness.session.composition import (
    ProductCompactionExecutor,
    SessionCompositionPorts,
    SessionExtensionCompositionPort,
    SessionFoundationInputs,
    SessionMaintenanceInputs,
    SessionModelCatalogPort,
    SessionProductInputs,
    compose_session_runtime,
)
from loushang.harness.session.diagnostics import SessionDiagnosticsRuntime
from loushang.harness.session.extension_bridge import AgentSessionExtensionBridge
from loushang.harness.session.operations_runtime import SessionOperationsPorts
from loushang.harness.session.settings import SessionSettingsBinding
from loushang.harness.session.side_question import (
    SIDE_QUESTION_BOUNDARY_PROMPT,
    AgentSideQuestionProvider,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionHookDecision,
    CompactionHookRequest,
    CompactionResult,
    ProductTranscriptSession,
)
from loushang.harness.workspace.exec import ExecService

BranchSummaryExecutor = Callable[..., Awaitable[BranchSummaryOutput]]
ChangelogProvider = Callable[[str, str], object]
ClipboardWriter = Callable[[str], object]
RetrySleeper = Callable[[int, CancellationSignal], Awaitable[None]]


class FooterDataPort(Protocol):
    """Footer updates consumed by the shared Product session adapter."""

    def set_extension_status(self, name: str, status: str | None) -> None: ...

    def set_available_provider_count(self, count: int) -> None: ...

    def dispose(self) -> None: ...


class AgentProductSession(AgentSessionAdapterMixin):
    """Bind Product callbacks to the existing standard session runtimes."""

    resource_bundle: ResourceBundle | None

    def __init__(
        self,
        *,
        agent: Agent,
        session_manager: ProductTranscriptSession[Any, Any],
        capability_runtime: CapabilityCompositionRuntime,
        execute_compaction: ProductCompactionExecutor,
        execute_branch_summary: BranchSummaryExecutor,
        get_changelog: ChangelogProvider,
        copy_to_clipboard: ClipboardWriter,
        retry_sleep: RetrySleeper,
        footer_data_provider: FooterDataPort,
        package_summary_provider: PackageSummaryProvider | None = None,
        settings_manager: SettingsManager | None = None,
        model_registry: SessionModelCatalogPort | None = None,
        resource_loader: ResourceLoader | None = None,
        resource_bundle: ResourceBundle | None = None,
        extension_runner: SessionExtensionCompositionPort | None = None,
        tool_registry: WorkspaceToolRegistry | None = None,
        allowed_tool_names: list[str] | None = None,
        active_tool_names: list[str] | None = None,
        default_activate_new_tools: bool | None = None,
        show_empty_tool_prompt: bool = False,
        base_prompt: str | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        package_materializer: PackageMaterializer | None = None,
        session_start_event: SessionStartEvent | None = None,
        api_registry: APIRegistry | None = None,
        exec_service: ExecService | None = None,
        tool_exec_service: ExecService | None = None,
        approval_resolver: InteractiveApprovalResolver | None = None,
        tool_policy_evaluator: PolicyEvaluator | None = None,
    ) -> None:
        self.agent = agent
        self._session_default_model = agent.model
        self.session_manager = session_manager
        self._settings_controller = SessionSettingsBinding(
            settings_manager=settings_manager,
            create_settings_manager=SettingsManager,
            default_compaction=CompactionSettings,
            default_retry=RetrySettings,
            get_steering_mode_callback=lambda: self.agent.steering_mode,
            set_steering_mode_callback=self._set_agent_steering_mode,
            get_follow_up_mode_callback=lambda: self.agent.follow_up_mode,
            set_follow_up_mode_callback=self._set_agent_follow_up_mode,
        )
        self.model_registry = model_registry
        self.api_registry = api_registry or get_default_api_registry()
        self._resource_loader = resource_loader
        self.resource_bundle = resource_bundle
        self._extension_runner = extension_runner
        self._extension_bridge = AgentSessionExtensionBridge()
        self._tool_registry = tool_registry
        self.diagnostics_service = diagnostics_service
        self._package_materializer = package_materializer
        self._exec_service = exec_service or ExecService()
        self._tool_exec_service = tool_exec_service
        self._capability_runtime: CapabilityCompositionRuntime | None = (
            capability_runtime
        )
        side_question_factory = capability_runtime.side_question_provider_factory
        self._side_question = (
            SideQuestionCoordinator(side_question_factory.bind(self))
            if side_question_factory is not None
            else None
        )
        self.footer_data_provider = footer_data_provider
        self._base_prompt = (
            base_prompt if base_prompt is not None else self.agent.system_prompt
        )
        self._execute_product_compaction = execute_compaction
        self._execute_product_branch_summary = execute_branch_summary
        self._get_product_changelog = get_changelog
        self._copy_product_text = copy_to_clipboard
        self._retry_sleep = retry_sleep
        self._bind_package_progress_events()
        self._session_start_event = session_start_event or SessionStartEvent(
            reason="startup"
        )
        self._approval_runtime = AgentSessionApprovalRuntime(
            resolver=approval_resolver,
            get_permission_profile_snapshot=(
                self._settings_controller.get_permission_profile_snapshot
            ),
            set_permission_profile=self._settings_controller.set_permission_profile,
            dispatch_event=self._dispatch_event,
            abort=self.abort,
        )
        self._tool_policy_evaluator = tool_policy_evaluator
        self._package_controller = SessionPackageController(
            get_session_id=lambda: self.session_manager.get_session_record().session_id,
            get_cwd=self.session_manager.get_cwd,
            get_settings_manager=lambda: cast(
                SessionPackageSettingsManager | None,
                self._settings_controller.get_settings_manager(),
            ),
            get_package_materializer=lambda: self._package_materializer,
            get_resource_loader=lambda: self._resource_loader,
            get_diagnostics_service=lambda: self.diagnostics_service,
            refresh_resources=self._refresh_resources_for_extension_runtime,
            summary_provider=package_summary_provider,
        )
        self._extension_provider_controller = ExtensionProviderRuntime(
            model_registry=self.model_registry,
            api_registry=self.api_registry,
            provider_factory=provider_from_extension_config,
        )
        self._extension_replacement_controller = ExtensionReplacementRuntime(
            get_runtime_host=lambda: self._extension_bridge.runtime_host,
        )
        self._extension_runtime_binding_factory = ExtensionRuntimeBindingFactory(
            get_cwd=self.session_manager.get_cwd,
            session_manager=self.session_manager,
            model_registry=self.model_registry,
            get_active_tool_names=lambda: self.get_active_tool_names(),
            get_all_tools=lambda: list(self.get_all_tools()),
            get_model_selection=self._get_extension_model_selection,
            set_active_tools=self._set_active_tools_from_extension,
            set_model=self._set_model_from_extension,
            register_tool=self._register_extension_runtime_tool,
            append_entry=self._append_extension_entry,
            send_message=self._send_message_from_extension,
            send_user_message=self._send_user_message_from_extension_async,
            get_signal=lambda: self.agent.signal,
            set_session_name=self.set_session_name,
            get_session_name=lambda: self.session_name,
            set_label=self._set_extension_label,
            list_commands=lambda: self.list_commands(),
            request_resource_refresh=self.request_resource_refresh,
            shutdown=self._abort_from_extension,
            record_diagnostic=self._record_extension_runtime_diagnostic,
            abort=self._abort_from_extension,
            is_idle=lambda: not self.agent.is_streaming,
            has_pending_messages=self.has_pending_messages,
            get_context_usage=self.get_context_usage,
            get_thinking_level=lambda: self.agent.thinking_level,
            set_thinking_level=self.set_thinking_level,
            register_provider=self._register_provider_from_extension,
            unregister_provider=self._unregister_provider_from_extension,
            set_extension_status=self._set_extension_status_from_extension,
            get_footer_data_provider=lambda: self.footer_data_provider,
            compact=self._compact_from_extension,
            get_system_prompt=lambda: self.agent.system_prompt,
            wait_for_idle=self.wait_for_idle,
            reload=self._reload_from_extension,
            navigate_tree=self._navigate_tree_from_extension,
            fork=self._fork_from_extension,
            new_session=self._new_session_from_extension,
            switch_session=self._switch_session_from_extension,
            get_ui_context=lambda: self._extension_bridge.ui_context,
            exec_command=self._exec_command_from_extension,
        )
        composition = compose_session_runtime(
            self._composition_ports(
                allowed_tool_names=allowed_tool_names,
                active_tool_names=active_tool_names,
                default_activate_new_tools=default_activate_new_tools,
                show_empty_tool_prompt=show_empty_tool_prompt,
                capability_runtime=capability_runtime,
            )
        )
        initialize_composed_session(
            self,
            composition,
            operations_ports=SessionOperationsPorts(
                composition=composition,
                agent=self.agent,
                session_manager=self.session_manager,
                extension_runner=self._extension_runner,
                execute_branch_summary=self._execute_product_branch_summary,
                before_tree=self._apply_before_tree_hook,
                dispose_runtime_profile=self._dispose_session_runtime_profile,
                finalize_shutdown=self._finalize_after_session_shutdown,
                invalidate_extension_contexts=self._invalidate_extension_contexts,
                sync_extension_diagnostics=self._sync_extension_diagnostics,
                close_approvals=self._close_session_approvals,
            ),
            settings=self._settings_controller,
            session_manager=self.session_manager,
            active_tool_names=active_tool_names,
            show_empty_tool_prompt=show_empty_tool_prompt,
            tool_registry=self._tool_registry,
            apply_context=self._apply_agent_transcript_context,
            sync_footer=self._sync_footer_available_provider_count,
        )

    @property
    def capability_profile(self) -> ResolvedRuntimeProfile:
        """Return the final resolved Session capability profile."""

        runtime = self._capability_runtime
        if runtime is None:
            raise RuntimeError("Session capability profile has been disposed.")
        return runtime.profile

    def _composition_ports(
        self,
        *,
        allowed_tool_names: list[str] | None,
        active_tool_names: list[str] | None,
        default_activate_new_tools: bool | None,
        show_empty_tool_prompt: bool,
        capability_runtime: CapabilityCompositionRuntime,
    ) -> SessionCompositionPorts:
        def build_command_controller(
            diagnostics_runtime: SessionDiagnosticsRuntime,
        ) -> StandardSessionCommandController:
            return StandardSessionCommandController(
                session_manager=self.session_manager,
                get_extension_runner=lambda: self._extension_runner,
                get_resource_bundle=lambda: self.resource_bundle,
                get_diagnostics_service=lambda: self.diagnostics_service,
                diagnostics_runtime=diagnostics_runtime,
                standard_ports=StandardSessionCommandPorts(
                    get_session_info=self._get_builtin_session_info,
                    set_session_name=self.set_session_name,
                    export_html=self.export_to_html,
                    export_jsonl=self.export_to_jsonl,
                    compact=self.compact,
                    reload=self.reload_extension_runtime,
                    get_recent_assistant_texts=self.get_recent_assistant_texts,
                    get_last_assistant_text=self.get_last_assistant_text,
                    copy_text=self._copy_product_text,
                    get_changelog=lambda args: self._get_product_changelog(
                        self.session_manager.get_cwd(), args
                    ),
                    new_session=self._new_session_from_extension,
                    resume_session=self._switch_session_from_extension,
                    fork_session=self._fork_from_extension,
                    clone_session=self._extension_replacement_controller.clone_session,
                    navigate_tree=self._navigate_tree_from_extension,
                    import_session=self._extension_replacement_controller.import_session,
                    get_active_tool_names=self.get_active_tool_names,
                    get_all_tools=self.get_all_tool_infos,
                    set_active_tools=self.set_active_tools,
                    get_default_active_tool_names=self._default_active_tool_names,
                    get_extensions=self.list_extensions,
                ),
                pack_composer=capability_runtime.command_pack_composer,
            )

        return SessionCompositionPorts(
            agent=self.agent,
            session_manager=self.session_manager,
            settings=self._settings_controller,
            capability_runtime=capability_runtime,
            foundation=SessionFoundationInputs(
                resource_loader=self._resource_loader,
                get_resource_bundle=lambda: self.resource_bundle,
                tool_registry=self._tool_registry,
                allowed_tool_names=allowed_tool_names,
                active_tool_names=active_tool_names,
                default_activate_new_tools=default_activate_new_tools,
                show_empty_tool_prompt=show_empty_tool_prompt,
                base_prompt=self._base_prompt,
                diagnostics_service=self.diagnostics_service,
                tool_exec_service=self._tool_exec_service,
                approval_resolver=self._approval_runtime.resolver,
                tool_policy_evaluator=self._tool_policy_evaluator,
                apply_context=self._apply_agent_transcript_context,
                refresh_agent_messages=self._refresh_agent_messages,
                dispatch_event=self._dispatch_event,
                record_runtime_exception=self._record_runtime_exception,
                before_bash=self._before_bash,
                get_bash_definition=self._get_bash_definition,
                create_bash_call_id=self._create_bash_call_id,
                get_resource_watch_paths=self._resource_watch_paths,
                prepare_resource_refresh=self._prepare_resource_refresh,
                rebuild_prompt_and_tools_view=self._rebuild_prompt_and_tools_view,
                set_resource_bundle=self._set_resource_bundle,
                record_extension_runtime_diagnostic=(
                    self._record_extension_runtime_diagnostic
                ),
            ),
            maintenance=SessionMaintenanceInputs(
                execute_compaction=self._execute_product_compaction,
                before_compaction=self._before_product_compaction,
                after_compaction=self._after_product_compaction,
                sleep_for_retry=self._retry_sleep,
            ),
            product=SessionProductInputs(
                model_registry=self.model_registry,
                api_registry=self.api_registry,
                extension_runner=self._extension_runner,
                session_start_event=self._session_start_event,
                footer_data_provider=self.footer_data_provider,
                command_controller=build_command_controller,
                extension_provider_controller=self._extension_provider_controller,
                extension_replacement_controller=(
                    self._extension_replacement_controller
                ),
                extension_runtime_binding_factory=(
                    self._extension_runtime_binding_factory
                ),
                extension_bridge=self._extension_bridge,
                get_context_usage=lambda: self.get_context_usage(),
                package_controller=self._package_controller,
                execute_branch_summary=lambda entries, signal: (
                    self._branch_summary_runner(
                        custom_instructions=None,
                        replace_instructions=False,
                    )(entries, signal)
                ),
                before_agent_start_system_prompt_options=(
                    self._before_agent_start_system_prompt_options
                ),
            ),
        )

    def get_context_usage(self):
        return serialize_context_usage_payload(super().get_context_usage())

    def get_exec_service(self) -> ExecService:
        """Return the live session execution service for Product-owned runners."""

        return self._exec_service

    async def ask_side_question(
        self,
        question: str,
        *,
        on_update: SideQuestionUpdate | None = None,
    ) -> SideQuestionAnswer:
        coordinator = self._side_question
        if coordinator is None:
            raise RuntimeError("Side questions are not available for this session.")
        return await coordinator.ask(question, on_update=on_update)

    def create_side_question_provider(self) -> AgentSideQuestionProvider:
        return AgentSideQuestionProvider(
            session=self,
            boundary_prompt=SIDE_QUESTION_BOUNDARY_PROMPT,
        )

    def cancel_side_question(self) -> bool:
        coordinator = self._side_question
        return coordinator.cancel() if coordinator is not None else False

    async def _dispose_session_runtime_profile(self) -> None:
        # Stop the selected Provider before its capability factory is disposed.
        self.cancel_side_question()
        await super()._dispose_session_runtime_profile()

    def _finalize_after_session_shutdown(self) -> None:
        self.cancel_side_question()
        self._close_session_approvals()
        if self._extension_runner is not None:
            self._invalidate_extension_contexts(
                "Extension context is stale after session replacement or shutdown."
            )
        self.footer_data_provider.dispose()
        self._capability_runtime = None

    def _abort_from_extension(self) -> None:
        self.abort()

    def _register_provider_from_extension(self, name: str, config: object) -> None:
        self._extension_provider_controller.register_provider(name, config)
        self._sync_footer_available_provider_count()

    def _get_extension_model_selection(self) -> ModelSelection | None:
        return cast(ModelSelection | None, self.get_model_selection())

    def _unregister_provider_from_extension(self, name: str) -> None:
        self._extension_provider_controller.unregister_provider(name)
        self._sync_footer_available_provider_count()

    def _set_extension_status_from_extension(self, key: str, text: str | None) -> None:
        self.footer_data_provider.set_extension_status(key, text)

    def _sync_footer_available_provider_count(self) -> None:
        providers = {
            selection.provider
            for selection in self._composition.selection_runtime.get_available_models()
            if isinstance(selection.provider, str)
        }
        self.footer_data_provider.set_available_provider_count(len(providers))

    def _create_replaced_session_context(
        self, session: object | None
    ) -> ReplacedSessionContext:
        if not isinstance(session, AgentProductSession):
            raise RuntimeError(
                "Session replacement callback requires a valid Agent session."
            )
        return cast(
            ReplacedSessionContext,
            self._extension_replacement_controller.create_context(session),
        )

    def _branch_summary_runner(
        self,
        *,
        custom_instructions: str | None,
        replace_instructions: bool,
    ) -> Callable[
        [Sequence[object], CancellationSignal], Awaitable[BranchSummaryOutput]
    ]:
        async def run(
            entries: Sequence[object], signal: CancellationSignal
        ) -> BranchSummaryOutput:
            return await self._execute_product_branch_summary(
                entries,
                model=self.agent.model,
                signal=signal,
                custom_instructions=custom_instructions,
                replace_instructions=replace_instructions,
            )

        return run

    async def _before_product_compaction(
        self,
        request: CompactionHookRequest,
    ) -> CompactionHookDecision | None:
        extension_runner = self._extension_runner
        if extension_runner is None:
            return None
        decision = await extension_runner.before_session_compact(
            SessionBeforeCompactEvent(
                reason=request.reason,
                cwd=str(self.session_manager.get_cwd()),
                custom_instructions=request.custom_instructions,
            )
        )
        if decision is not None and decision.cancel:
            self._sync_extension_diagnostics(phase="runtime")
            return CompactionHookDecision(cancel=True)
        result = decision.compaction if decision is not None else None
        if result is not None and not isinstance(result, CompactionResult):
            raise TypeError(
                "Extension compaction hooks must return a CompactionResult."
            )
        return CompactionHookDecision(result=result) if result is not None else None

    async def _after_product_compaction(
        self,
        result: CompactionResult,
        record_id: str,
        from_hook: bool,
    ) -> None:
        extension_runner = self._extension_runner
        if extension_runner is None:
            return
        await extension_runner.emit_agent_event(
            {
                "type": "session_compact",
                "compaction": result,
                "compaction_entry": self.session_manager.get_entry(record_id),
                "from_extension": from_hook,
            },
            cwd=self.session_manager.get_cwd(),
        )


__all__ = ["AgentProductSession"]
