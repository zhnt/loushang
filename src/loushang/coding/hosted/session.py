"""Real Coding AgentSession binding behind the product-neutral hosted port."""

from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection, normalize_model_selection
from loushang.ai.model.selection import is_usable_model_selection
from loushang.apphost import SessionBindingKeyV1
from loushang.apphost.integrations._session_projection import (
    _first_user_prompt,
    _hosted_session_title,
    _hosted_transcript_window,
    _HostedApprovalPresentation,
    _HostedConversationProjection,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionIdentityV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from loushang.appservice.execution_guard import ExecutionWorkV1
from loushang.coding.composition.bootstrap import BootstrapServices
from loushang.coding.composition.bootstrap import (
    create_agent_session_with_model_policy as create_agent_session,
)
from loushang.coding.hosted.catalog import (
    CodingHostedCandidateBindingV1,
    CodingHostedCatalogError,
    CodingHostedHistoryCandidateBindingV1,
)
from loushang.coding.hosted.service_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSessionBindingV1,
    CodingHostedSnapshotProjectionV1,
)
from loushang.coding.hosted.session_goal import HostedSessionGoal
from loushang.coding.hosted.user_choice import (
    ASK_USER,
    HostedUserChoice,
    pending_choice_from_transcript,
)
from loushang.coding.package.product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.resume.history import CodingResumeHistoryPreview
from loushang.coding.resume.input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session.manager import SessionManager
from loushang.harness.approval import (
    DenyApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.capabilities.tools import ToolSelection
from loushang.harness.events import RuntimeEvent
from loushang.harness.model_catalog import ModelCatalog
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeFactoryPort,
)
from loushang.harness.policy import PolicyEvaluator, PolicyEvaluatorChain
from loushang.harness.runtime._owned_tasks import _get_close_task
from loushang.harness.session import SessionControlPort
from loushang.harness.session.model_resolution import resolve_default_model
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace import workspace_tool_runtime_settings
from loushang.harness.transcript.session_catalog import (
    build_agent_transcript_session_context,
    load_agent_transcript_session_metadata,
)
from loushang.harness.transcript.types import AgentTranscriptContext
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

CodingHostedProductRuntimeFactoryForSession = Callable[
    [SessionManager], PackageProductRuntimeFactoryPort
]

if TYPE_CHECKING:
    from loushang.coding.hosted.resume import CodingDeferredHostedSessionV1


class CodingHostedHistoryBindingV1:
    """Detached historical display with no Writer or execution control.

    The catalog admits identity and the source revision before constructing this
    binding. AppService still owns caller read authorization. A display snapshot
    cannot be promoted into a current runtime or used as activation evidence.
    """

    def __init__(
        self, identity: SessionIdentityV1, history: CodingResumeHistoryPreview,
    ) -> None:
        if (
            type(identity) is not SessionIdentityV1
            or identity.product_id != "coding"
            or type(history) is not CodingResumeHistoryPreview
            or identity.session_id != history.header_preview.header.conversation_id
        ):
            raise CodingHostedCatalogError()
        self.identity = identity
        self._history = history
        self._closed = False
        records, truncated = _hosted_transcript_window(
            (entry.payload for entry in reversed(history.selected_records)),
            flag_clipped_rows=False,
        )
        title = load_agent_transcript_session_metadata(
            history.header_preview.header, history.records
        ).name
        self._projection = CodingHostedSnapshotProjectionV1(
            title=_hosted_session_title(title, (entry.payload for entry in history.records)),
            revision=0, running=False, records=records, truncated=truncated,
            user_choice=pending_choice_from_transcript(history.selected_records, identity.session_id),
        )

    @property
    def control(self) -> None:
        return None

    @cached_property
    def context(self) -> AgentTranscriptContext:
        history = self.resume_history
        return build_agent_transcript_session_context(history.records, history.selected_leaf_id)

    @property
    def resume_history(self) -> CodingResumeHistoryPreview:
        if self._closed:
            raise RuntimeError("coding_hosted_session_closed")
        return self._history

    def project_snapshot(self, *, resume_on_submit: bool = False) -> CodingHostedSnapshotProjectionV1:
        if self._closed:
            raise RuntimeError("coding_hosted_session_closed")
        notice = (
            "Sending a message resumes the session runtime."
            if resume_on_submit else "Historical session is read-only."
        )
        return replace(
            self._projection,
            records=(*self._projection.records, TranscriptRecordV1(TranscriptRecordKindV1.STATUS, notice)),
        )

    def project_event(
        self, event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None:
        return None

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        return False

    async def close(self) -> None:
        self._closed = True


class CodingRealHostedSessionV1(_HostedApprovalPresentation):
    _approval_action = "Tool approval"
    _approval_publish_rollback = True

    def _approval_dispatcher(self) -> Callable[[RuntimeEvent[object]], Awaitable[None]]:
        return self._session.runtime.dispatch_event

    def __init__(
        self,
        session: AgentSession,
        identity: SessionIdentityV1,
        approval: InteractiveApprovalResolver,
        *,
        workspace: Path | None = None,
    ) -> None:
        self._session = session
        self.identity = identity
        self._approval = approval
        self._interactions: dict[str, str] = {}
        self._projection = _HostedConversationProjection(CodingHostedEventProjectionV1)
        self._close_task: asyncio.Task[None] | None = None
        self._title_task: asyncio.Task[None] | None = None
        self._execution_idle_for_goal: Callable[[], bool] | None = None
        self._goal = HostedSessionGoal(
            session, identity, workspace if workspace is not None else Path(session.session_manager.get_cwd()).resolve(),
            closing=lambda: self._close_task is not None,
            execution_idle=lambda: self._execution_idle_for_goal is None or self._execution_idle_for_goal(),
            title_pending=lambda: self._title_task is not None and not self._title_task.done(),
        )
        self.create_interactive_goal = self._goal.create_interactive_goal
        self.interactive_goal_review = self._goal.interactive_goal_review
        self.control_interactive_goal = self._goal.control_interactive_goal
        self.interactive_goal_view = self._goal.interactive_goal_view
        self.interactive_goal_status = self._goal.interactive_goal_status
        self.close_interactive_goal = self._goal.close_interactive_goal
        self._user_choice = HostedUserChoice()
        session.set_approval_presenter(
            self._present_approval, dismisser=self._dismiss_approval
        )

    @property
    def control(self) -> SessionControlPort:
        return self._session

    def enable_user_choice(self) -> None:
        self._user_choice.install(self._session)

    @property
    def current_model(self) -> Model:
        return self._session.agent.model

    @property
    def execution_claimed(self) -> bool:
        return self._execution_idle_for_goal is not None

    def claim_execution(self, idle_for_goal: Callable[[], bool]) -> None:
        if self.execution_claimed or self._close_task is not None:
            raise ValueError("Coding Session already has an execution owner")
        self._execution_idle_for_goal = idle_for_goal

    def release_failed_execution_claim(self) -> None:
        self._execution_idle_for_goal = None

    async def lookup_resume_input(
        self, query: CodingResumeInputLookupQueryV1,
    ) -> CodingResumeInputLookupResultV1:
        """Product observation for an already read-authorized Hosted caller.

        This internal port does not negotiate a new client protocol, authorize
        reads, or infer model outcome from durable message presence.
        """

        if self._close_task is not None:
            raise CodingHostedCatalogError()
        manager = self._session.session_manager
        if not isinstance(manager, SessionManager) or manager.header.conversation_id != self.identity.session_id:
            raise CodingHostedCatalogError()
        return await manager.lookup_resume_input(query)

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        records, truncated = _hosted_transcript_window(reversed(self._session.messages))
        return CodingHostedSnapshotProjectionV1(
            title=_hosted_session_title(self._session.session_name, _title_messages(self._session)),
            revision=self._projection.revision,
            running=self._session.is_streaming,
            records=records,
            truncated=truncated,
            user_choice=self._user_choice.pending,
        )

    def project_event(
        self, event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None:
        # Publish the consumed question with the next actual user message.
        return self._projection.project_event(event, on_user_message=self._user_choice.clear)

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        action_id = self._interactions.get(interaction_id)
        if action_id is None or outcome not in {"allow_once", "deny", "abort"}:
            return False
        return await self._session.handle_screen_approval(
            {"action_id": action_id, "outcome": outcome}
        )

    async def close(self) -> None:
        self._close_task = _get_close_task(self._close_task, self._close_once)
        await asyncio.shield(self._close_task)

    async def _close_once(self) -> None:
        await self.close_interactive_goal()
        self._user_choice.clear()
        self._approval.end_session()
        if self._title_task is not None:
            self._title_task.cancel()
            await asyncio.gather(self._title_task, return_exceptions=True)
        await self._session.dispose()
        self._interactions.clear()

    @property
    def goal_command_running(self) -> bool:
        return self._goal.goal_command_running

    @property
    def execution_available(self) -> bool:
        return self._goal.execution_available

    def create_execution_work(
        self, text: str, cancel_requested: Callable[[], bool],
    ) -> ExecutionWorkV1:
        from loushang.coding.hosted._execution_work import CodingExecutionWorkV1

        return CodingExecutionWorkV1(
            self._session, text, cancel_requested,
            start_title=self.start_title_if_unnamed,
            wait_for_title=self.wait_for_title,
        )

    async def wait_for_title(self) -> None:
        # The title and the conversation share the durable Model Input writer.
        task = self._title_task
        if task is not None and not task.done():
            await asyncio.shield(task)

    def start_title_if_unnamed(self) -> None:
        if (
            self._close_task is not None or self._session.session_name
            or not _uses_automatic_title(self.identity)
            or (self._title_task is not None and not self._title_task.done())
        ):
            return
        question = _first_user_prompt(_title_messages(self._session))
        if question is None:
            return
        from loushang.coding.hosted._execution_work import set_first_turn_title

        self._title_task = asyncio.create_task(set_first_turn_title(self._session, question))


class CodingRealHostedSessionFactoryV1:
    """Trusted outer configuration; no remote module, model or factory names."""

    def __init__(
        self,
        *,
        services_factory: Callable[[Path], BootstrapServices],
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
        session_tool_policy: PolicyEvaluator | None = None,
        session_active_tools: list[str] | None = None,
        session_allowed_tools: list[str] | None = None,
        session_system_prompt: str | None = None,
        output_capture_factory: ExecCaptureFactory | None = None,
        package_product_runtime_factory_for_session: (
            CodingHostedProductRuntimeFactoryForSession | None
        ) = None,
    ) -> None:
        self._services_factory = services_factory
        self._model = model
        self._stream_fn = stream_fn
        self._tools = tools
        self._session_tool_policy = session_tool_policy
        self._session_active_tools = session_active_tools
        self._session_allowed_tools = session_allowed_tools
        self._user_choice_enabled = (
            session_active_tools is None or ASK_USER in session_active_tools
        ) and (session_allowed_tools is None or ASK_USER in session_allowed_tools)
        self._session_system_prompt = session_system_prompt
        self._output_capture_factory = output_capture_factory
        self._package_product_runtime_factory_for_session = (
            package_product_runtime_factory_for_session
        )
        self._product_owner_selection = CodingFencedProductApplicationSelection(
            windows_candidate=sys.platform == "win32"
        )
        self._closing = False
        self._closed = False

    def _default_product_factory_for_session(
        self, manager: SessionManager, services: BootstrapServices
    ) -> PackageProductRuntimeFactoryPort | None:
        return self._product_owner_selection.factory_for_session(
            manager, settings_manager=services.settings_manager
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        self._product_owner_selection.close()
        self._closed = True

    async def create_session(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> (
        CodingRealHostedSessionV1
        | CodingHostedHistoryBindingV1
        | CodingDeferredHostedSessionV1
    ):
        if self._closing:
            raise CodingHostedCatalogError()
        if type(opaque_session_binding) not in (
            CodingHostedCandidateBindingV1, CodingHostedHistoryCandidateBindingV1,
        ):
            raise CodingHostedCatalogError()
        opaque_session_binding = cast(
            CodingHostedCandidateBindingV1 | CodingHostedHistoryCandidateBindingV1,
            opaque_session_binding,
        )
        identity = opaque_session_binding.record.identity
        if binding_key != SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        ):
            raise CodingHostedCatalogError()
        if isinstance(opaque_session_binding, CodingHostedHistoryCandidateBindingV1):
            if not opaque_session_binding.supports_writable_resume:
                return opaque_session_binding.take_binding()
            from loushang.coding.hosted.resume import CodingDeferredHostedSessionV1

            source = opaque_session_binding.take_resume_source()
            try:
                binding = CodingDeferredHostedSessionV1(
                    source,
                    services=self._services_factory(source.record.scope.cwd),
                    model=self._model,
                    stream_fn=self._stream_fn,
                    tools=self._tools,
                    user_choice_enabled=self._user_choice_enabled,
                    output_capture_factory=self._output_capture_factory,
                    product_owner_selection=self._product_owner_selection,
                )
                await binding.start_background_planning()
                return binding
            except BaseException:
                await source.close()
                raise
        manager = opaque_session_binding.manager_for_construction()
        try:
            approval = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
            services = self._services_factory(opaque_session_binding.record.scope.cwd)
            policy = workspace_tool_runtime_settings(services.settings_manager)
            runtime_factory = None
            if self._package_product_runtime_factory_for_session is not None:
                runtime_factory = self._package_product_runtime_factory_for_session(
                    manager
                )
                if runtime_factory is None:
                    raise TypeError("Package Product runtime factory is required")
            else:
                runtime_factory = self._default_product_factory_for_session(
                    manager, services
                )
            created = opaque_session_binding.created
            model = self._model
            if not created and model is not None:
                model = _resolve_hosted_saved_model(
                    manager.build_session_context().model, services.model_registry, model,
                )
            session = create_agent_session(
                session_manager=manager,
                model=model,
                _use_default_model=created,
                stream_fn=self._stream_fn,
                services=services,
                tools=self._tools,
                approval_resolver=approval,
                tool_policy_evaluator=(PolicyEvaluatorChain(
                    tuple(p for p in (self._session_tool_policy, policy.policy_engine) if p is not None),
                    strategy="most_restrictive",
                ) if self._session_tool_policy is not None else policy.policy_engine),
                active_tool_names=self._session_active_tools,
                allowed_tool_names=self._session_allowed_tools if self._session_allowed_tools is not None else ToolSelection.ALL,
                system_prompt=self._session_system_prompt,
                output_capture_factory=self._output_capture_factory,
                package_product_runtime_factory=runtime_factory,
            )
            opaque_session_binding.retain_constructed_owner(session.dispose)
            selection = normalize_model_selection(session.agent.model)
            if created and selection is not None and is_usable_model_selection(selection):
                await manager.append_model_change(
                    selection.provider, selection.model_id, endpoint_id=selection.endpoint_id,
                )
                if session.agent.thinking_level is not None:
                    await manager.append_thinking_level_change(session.agent.thinking_level)
            real_binding = CodingRealHostedSessionV1(
                session, identity, approval, workspace=opaque_session_binding.record.scope.cwd,
            )
            if self._user_choice_enabled:
                real_binding.enable_user_choice()
            opaque_session_binding.take_manager()
            return real_binding
        except BaseException:
            # The claimed candidate retains failed cleanup for the outer
            # AppHost owner to retry; no acquired owner disappears on failure.
            await opaque_session_binding.close()
            raise


def _resolve_hosted_saved_model(
    saved: object,
    catalog: ModelCatalog,
    explicit: Model | ModelSelection | None,
) -> Model | None:
    """Restore the recorded route, or use an explicitly injected Host model."""
    selection = normalize_model_selection(saved if saved is not None else explicit)
    if not is_usable_model_selection(selection):
        return None
    if isinstance(explicit, Model) and normalize_model_selection(explicit) == selection:
        return explicit
    return resolve_default_model(selection, build_model=catalog.build_model).model


def _uses_automatic_title(identity: SessionIdentityV1) -> bool:
    return identity.continuity_id.startswith(("gui-new-", "gui-default-", "gui-draft-"))


def _title_messages(session: AgentSession) -> Iterable[object]:
    manager = getattr(session, "session_manager", None)
    if isinstance(manager, SessionManager):
        return (entry.payload for entry in manager.entries)
    return session.messages


__all__ = [
    "CodingHostedHistoryBindingV1",
    "CodingHostedProductRuntimeFactoryForSession",
    "CodingRealHostedSessionFactoryV1",
    "CodingRealHostedSessionV1",
]


async def _lookup_coding_resume_input(
    binding: CodingHostedSessionBindingV1, query: ResumeInputLookupQueryV1,
) -> ResumeInputLookupResultV1:
    lookup = getattr(binding, "lookup_resume_input", None)
    if not inspect.iscoroutinefunction(lookup):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    result = await lookup(CodingResumeInputLookupQueryV1(query.input_id, query.record_digest))
    if type(result) is not CodingResumeInputLookupResultV1:
        raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
    return ResumeInputLookupResultV1(result.input_id, result.record_id, result.status)
