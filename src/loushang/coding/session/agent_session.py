from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from loushang.agent import Agent
from loushang.ai.api_registry import ApiProviderRegistry
from loushang.coding.compaction.adapter import (
    execute_coding_branch_summary,
    execute_coding_compaction,
)
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.resource_runtime import summarize_coding_package_root
from loushang.coding.session_manager import SessionManager
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.capabilities import (
    CapabilityCompositionRuntime,
    bind_capability_composition_runtime,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.events import RuntimeEvent
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import SessionStartEvent
from loushang.harness.model_catalog import ModelCatalog as ModelRegistry
from loushang.harness.multiagent import DelegatedExecutionProfile
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.sandbox import SandboxExecutionRuntime, SandboxStatus
from loushang.harness.session import AgentProductSession
from loushang.harness.session.changelog import read_changelog_for_cwd
from loushang.harness.session.composition import sleep_for_retry
from loushang.harness.session.event_types import AgentSessionEvent
from loushang.harness.session.footer import FooterDataProvider
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import BranchSummaryOutput
from loushang.harness.workspace.exec import ExecService

SessionEventListener = Callable[[AgentSessionEvent], Awaitable[None] | None]
# project_runtime_event_to_session_event remains an external migration label.
RuntimeEventListener = Callable[[RuntimeEvent[object]], Awaitable[None] | None]


def _copy_to_clipboard(text: str) -> object:
    from loushang.tui.clipboard import copy_to_clipboard

    return copy_to_clipboard(text)


async def _execute_coding_compaction(**kwargs: object) -> object:
    return await execute_coding_compaction(**kwargs)


async def _execute_coding_compaction_runtime(**kwargs: object) -> object:
    return await _execute_coding_compaction(**kwargs)


async def _execute_coding_branch_summary(
    entries: Sequence[object], **kwargs: object
) -> BranchSummaryOutput:
    return await execute_coding_branch_summary(entries, **kwargs)


class AgentSession(AgentProductSession):
    """Coding content and policy bound to the shared Agent Product session."""

    def __init__(
        self,
        *,
        agent: Agent,
        session_manager: SessionManager,
        settings_manager: SettingsManager | None = None,
        model_registry: ModelRegistry | None = None,
        resource_loader: DefaultResourceLoader | None = None,
        resource_bundle: ResourceBundle | None = None,
        extension_runner: ExtensionRunner | None = None,
        tool_registry: WorkspaceToolRegistry | None = None,
        allowed_tool_names: list[str] | None = None,
        active_tool_names: list[str] | None = None,
        default_activate_new_tools: bool | None = None,
        show_empty_tool_prompt: bool = False,
        base_prompt: str | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        package_materializer: PackageMaterializer | None = None,
        session_start_event: SessionStartEvent | None = None,
        api_provider_registry: ApiProviderRegistry | None = None,
        footer_data_provider: FooterDataProvider | None = None,
        exec_service: ExecService | None = None,
        approval_resolver: InteractiveApprovalResolver | None = None,
        capability_runtime: CapabilityCompositionRuntime | None = None,
        sandbox_runtime: SandboxExecutionRuntime | None = None,
        delegated_execution_profile: DelegatedExecutionProfile | None = None,
    ) -> None:
        self._sandbox_runtime = sandbox_runtime
        self.delegated_execution_profile = delegated_execution_profile
        resolved_capability_runtime = (
            capability_runtime
            or bind_capability_composition_runtime(CODING_CAPABILITY_PROFILE)
        )
        super().__init__(
            agent=agent,
            session_manager=session_manager,
            capability_runtime=resolved_capability_runtime,
            execute_compaction=_execute_coding_compaction_runtime,
            execute_branch_summary=_execute_coding_branch_summary,
            get_changelog=read_changelog_for_cwd,
            copy_to_clipboard=_copy_to_clipboard,
            retry_sleep=lambda delay, signal: sleep_for_retry(delay, signal),
            footer_data_provider=footer_data_provider
            or FooterDataProvider(session_manager.get_cwd()),
            package_summary_provider=summarize_coding_package_root,
            settings_manager=settings_manager,
            model_registry=model_registry,
            resource_loader=resource_loader,
            resource_bundle=resource_bundle,
            extension_runner=extension_runner,
            tool_registry=tool_registry,
            allowed_tool_names=allowed_tool_names,
            active_tool_names=active_tool_names,
            default_activate_new_tools=default_activate_new_tools,
            show_empty_tool_prompt=show_empty_tool_prompt,
            base_prompt=base_prompt,
            diagnostics_service=diagnostics_service,
            package_materializer=package_materializer,
            session_start_event=session_start_event,
            api_provider_registry=api_provider_registry,
            exec_service=exec_service,
            tool_exec_service=(
                exec_service
                if (
                    sandbox_runtime is not None
                    and sandbox_runtime.status().state != "disabled"
                )
                or getattr(exec_service, "execution_profile", None) is not None
                else None
            ),
            approval_resolver=approval_resolver,
        )

    def get_sandbox_status(self) -> SandboxStatus:
        if self._sandbox_runtime is None:
            return SandboxStatus(state="disabled")
        return self._sandbox_runtime.status()

    async def _dispose_session_runtime_profile(self) -> None:
        try:
            await super()._dispose_session_runtime_profile()
        finally:
            if self._sandbox_runtime is not None:
                await self._sandbox_runtime.close()
