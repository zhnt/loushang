"""Hosted Resume history-first planning and in-place first-input activation."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import cast

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection, normalize_model_selection
from loushang.ai.model.reasoning import available_thinking_levels
from loushang.ai.utils.capabilities import validate_image_input_compatibility
from loushang.apphost.integrations.session_control import (
    _DeferredSessionControl,
    _HostedAgentExecutionWork,
    _HostedApprovalPresentation,
)
from loushang.appserver.execution.model import InteractiveGoalRecoveryV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionEventKindV1,
    SessionSnapshotRequestV1,
)
from loushang.appservice.client_scope import ScopedAppServicePortV1
from loushang.appservice.execution_contract import (
    ExecutionOutcomeV1,
    ExecutionStatusV1,
)
from loushang.appservice.execution_guard import ExecutionControlV1, ExecutionWorkV1
from loushang.harness.approval import (
    ApprovalOutcome,
    DenyApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.events import RuntimeEvent
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.policy import PolicyEvaluator, PolicyEvaluatorChain
from loushang.harness.session import SessionControlPort
from loushang.harness.session.model_selection import (
    apply_session_model_selection,
    iter_available_model_details,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace import workspace_tool_runtime_settings
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

from .appservice_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSnapshotProjectionV1,
)
from .bootstrap import BootstrapServices
from .composition_sets import resolve_coding_composition_set
from .hosted_catalog import CodingHostedCatalogError, CodingHostedResumeSourceV1
from .hosted_goal_recovery import read_interactive_goal_recovery, unavailable_recovery
from .hosted_models import load_workspace_models
from .hosted_session import (
    _MAX_INTERACTIONS,
    _TEXT_LIMIT,
    CodingRealHostedSessionV1,
    _observe_close,
    _resolve_hosted_saved_model,
)
from .hosted_workspace import CodingHostedWorkspace
from .package.product_runtime import CodingFencedProductApplicationSelection
from .resume_activation_plan import SessionActivationPlanV1
from .resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
)
from .resume_permission_confirmation import NativeResumePolicy
from .runtime.resume_planning import ResumePlanningSlot
from .session.agent_session import AgentSession


class _DeferredHostedControlV1(_DeferredSessionControl):
    """Stable control identity that later relays the activated Session."""

    def __init__(self, binding: CodingDeferredHostedSessionV1) -> None:
        self._binding = binding
        _DeferredSessionControl.__init__(
            self,
            closed_message="coding_hosted_session_closed",
            invalid_activation=lambda: CodingHostedCatalogError(),
        )

    @property
    def session_id(self) -> str:
        return self._binding.identity.session_id

    @property
    def settings_manager(self) -> SettingsManager:
        return self._binding._services.settings_manager

    async def get_model_selection(self) -> ModelSelection | None:
        return normalize_model_selection(self._binding.current_model)

    async def get_available_model_details(self) -> list[object]:
        if self._delegate is not None:
            return await iter_available_model_details(self._delegate)
        return list(self._binding._services.model_registry.ai_registry.list_models())

    async def set_model(self, selection: ModelSelection) -> None:
        await self._binding.set_model(selection)

    @property
    def thinking_level(self) -> object:
        if self._delegate is not None:
            return super().thinking_level
        return self._binding._source.history_binding.context.thinking_level

    def get_available_thinking_levels(self) -> tuple[str, ...]:
        if self._delegate is not None:
            return super().get_available_thinking_levels()
        model = self._binding.current_model
        return available_thinking_levels(model) if model is not None else ()

    async def set_thinking_level(self, level: str) -> None:
        await self._binding.set_thinking_level(level)


class CodingDeferredHostedSessionV1(_HostedApprovalPresentation):
    """One AppHost binding from detached history through first activation."""

    _approval_action = "Resume approval"
    _approval_limit = staticmethod(lambda: _MAX_INTERACTIONS)
    _approval_text_limit = staticmethod(lambda: _TEXT_LIMIT)
    _approval_id = staticmethod(lambda: token_hex(16))
    _approval_publish_rollback = False

    def _approval_dispatcher(self) -> Callable[[RuntimeEvent[object]], Awaitable[None]]:
        return self._control.emit

    def __init__(
        self,
        source: CodingHostedResumeSourceV1,
        *,
        services: BootstrapServices,
        model: Model | ModelSelection | None,
        stream_fn: StreamFn | None,
        tools: list[ToolDefinition] | None,
        output_capture_factory: ExecCaptureFactory | None,
        product_owner_selection: CodingFencedProductApplicationSelection,
        hosted_workspace: CodingHostedWorkspace | None = None,
        workspace_policy: PolicyEvaluator | None = None,
        user_choice_enabled: bool = False,
    ) -> None:
        self._source = source
        self.identity = source.record.identity
        self._services = services
        self._model = model
        self._stream_fn = stream_fn
        self._tools = tools
        self._hosted_workspace = hosted_workspace
        self._workspace = hosted_workspace.cwd if hosted_workspace is not None else source.record.scope.cwd
        self._workspace_tools = hosted_workspace is None or bool(hosted_workspace.roots)
        self._workspace_policy = workspace_policy
        self._user_choice_enabled = user_choice_enabled
        self._output_capture_factory = output_capture_factory
        self._product_owner_selection = product_owner_selection
        self._approval = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        self._approval.open_session()
        self._approval.set_request_presenter(
            self._present_approval, dismisser=self._dismiss_approval
        )
        self._control = _DeferredHostedControlV1(self)
        self._active: CodingRealHostedSessionV1 | None = None
        self._planning: ResumePlanningSlot | None = None
        self._activation_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._interactions: dict[str, str] = {}
        self._latest_input_query: CodingResumeInputLookupQueryV1 | None = None

    @property
    def control(self) -> SessionControlPort:
        return cast(SessionControlPort, self._control)

    @property
    def execution_available(self) -> bool:
        return self._close_task is None

    @property
    def supports_interactive_goal_recovery(self) -> bool:
        return self._active is None and self._close_task is None

    async def interactive_goal_recovery(self) -> InteractiveGoalRecoveryV1:
        source = self._source
        record = source.record
        try:
            history = source.history
            source.require_current_source()
            if (not self.supports_interactive_goal_recovery or self._activation_lock.locked()
                    or self.identity != record.identity
                    or history.header_preview.header != record.header
                    or record.header.conversation_id != self.identity.session_id
                    or record.scope.fingerprint != self.identity.scope_fingerprint
                    or record.path.parent != record.scope.session_dir):
                return unavailable_recovery("source_changed")
            result = await settled_io(read_interactive_goal_recovery, record.scope.session_dir, self.identity.session_id)
            if (not self.supports_interactive_goal_recovery or self._activation_lock.locked()
                    or source.history is not history):
                return unavailable_recovery("source_changed")
            source.require_current_source()
            return result
        except (CodingHostedCatalogError, OSError, ValueError):
            return unavailable_recovery("source_changed")

    @property
    def current_model(self) -> Model | None:
        if self._active is not None:
            return self._active.current_model
        self._source.require_current_source()
        return _resolve_hosted_saved_model(
            self._source.history_binding.context.model,
            self._services.model_registry,
            self._model,
        )

    async def set_model(self, selection: ModelSelection) -> None:
        await self._update_model_settings(selection)

    async def set_thinking_level(self, level: str) -> None:
        await self._update_model_settings(level)

    async def _update_model_settings(self, value: ModelSelection | str) -> None:
        async with self._activation_lock:
            if self._close_task is not None:
                raise CodingHostedCatalogError()
            if self._active is not None:
                if isinstance(value, str):
                    setter = getattr(self._active.control, "set_thinking_level", None)
                    if not callable(setter):
                        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                    await setter(value)
                else:
                    await apply_session_model_selection(self._active.control, value)
                return
            scope, control, digest = ScopedAppServicePortV1.current_resume_subject()

            def require_current() -> None:
                if self._close_task is not None:
                    raise CodingHostedCatalogError()
                scope.require_current_resume_subject(
                    control, digest, expected_session_id=self.identity.session_id,
                )
                self._source.require_current_source()

            require_current()
            context = self._source.history_binding.context
            if isinstance(value, str):
                model = self.current_model
                if model is None or value not in available_thinking_levels(model):
                    raise ValueError("Thinking level is unavailable for the saved session model")
                if value == context.thinking_level:
                    return
            else:
                model = self._services.model_registry.build_model(value)
                if context.provider_window is not None and not context.provider_window.matches(model):
                    raise ValueError("Selected model is incompatible with the active provider compaction checkpoint")
                validate_image_input_compatibility(model, context.messages)
            plan = await self._current_plan()
            require_current()
            manager = await self._source.manager_type._load_resume_writer(
                self._source.record.path, plan=plan, current_owner_inputs=plan.owner_inputs,
                _factory=self._source.writer_factory,
            )
            try:
                require_current()
                if isinstance(value, str):
                    await manager.append_thinking_level_change(value)
                else:
                    await manager.append_model_change(
                        value.provider, value.model_id, endpoint_id=value.endpoint_id,
                    )
                await self._source.refresh_after_model_change(manager)
            finally:
                await manager.dispose_runtime_profile()

    def _plan_subject_digest(self) -> str:
        return hashlib.sha256(
            (
                "coding.hosted.resume-plan/v1\\0"
                + self.identity.continuity_id
                + "\\0"
                + self.identity.session_id
                + "\\0"
                + self._source.history.source_fingerprint
            ).encode()
        ).hexdigest()

    async def _current_plan(self) -> SessionActivationPlanV1:
        from .resume_activation_attempt import CodingResumeRecoveryRequired
        from .resume_activation_plan import plan_coding_resume_async

        self._source.require_current_source()
        policy = workspace_tool_runtime_settings(self._services.settings_manager)
        raw_policy_engine = policy.policy_engine
        if raw_policy_engine is None:
            raise CodingHostedCatalogError()
        policy_engine = cast(NativeResumePolicy, raw_policy_engine)
        plan = await plan_coding_resume_async(
            self._source.history,
            resolve_coding_composition_set("coding-standard"),
            workspace_root=self._workspace,
            resource_loader=self._services.resource_loader,
            subject_digest=self._plan_subject_digest(),
            policy_digest=policy_engine.configuration_fingerprint(),
            max_work_units=200,
            time_budget_seconds=5.0,
            priority="foreground",
        )
        if self._planning is not None:
            plan = self._planning.current(
                self._source.history, current_owner_inputs=plan.owner_inputs
            ) or plan
            await self._planning.close()
            self._planning = None
        if plan.status != "needs_final_validation" or plan.ancestry_digest is None:
            raise CodingResumeRecoveryRequired("input.plan_unavailable")
        return plan

    async def start_background_planning(self) -> None:
        self._source.require_current_source()
        project_cwd = self._workspace if self._hosted_workspace is None else self._hosted_workspace.project_cwd
        if project_cwd is not None:
            await settled_io(load_workspace_models, self._services, project_cwd)
        self._source.require_current_source()
        policy = workspace_tool_runtime_settings(self._services.settings_manager)
        raw_policy_engine = policy.policy_engine
        if raw_policy_engine is None:
            raise CodingHostedCatalogError()
        policy_engine = cast(NativeResumePolicy, raw_policy_engine)
        planning = ResumePlanningSlot()
        self._planning = planning
        await planning.start(
            self._source.history,
            resolve_coding_composition_set("coding-standard"),
            workspace_root=self._workspace,
            resource_loader=self._services.resource_loader,
            subject_digest=self._plan_subject_digest(),
            policy_digest=policy_engine.configuration_fingerprint(),
            max_work_units=200,
            time_budget_seconds=5.0,
        )

    def create_execution_work(
        self, text: str, cancel_requested: Callable[[], bool],
    ) -> ExecutionWorkV1:
        from ._hosted_execution_work import (
            current_coding_hosted_resume_subject,
            current_coding_hosted_resume_submission_id,
        )

        if self._active is not None:
            return self._active.create_execution_work(text, cancel_requested)
        scope, control, subject_digest = current_coding_hosted_resume_subject()
        submission_id = current_coding_hosted_resume_submission_id()
        if submission_id is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return _HostedResumeExecutionWorkV1(
            self, text, cancel_requested, scope, control, subject_digest,
            submission_id,
        )

    async def wait_for_title(self) -> None:
        if self._active is not None:
            await self._active.wait_for_title()

    def start_title_if_unnamed(self) -> None:
        if self._active is not None:
            self._active.start_title_if_unnamed()

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        if self._close_task is not None:
            raise CodingHostedCatalogError()
        active = self._active
        return (
            active.project_snapshot()
            if active is not None
            else self._source.history_binding.project_snapshot(resume_on_submit=True)
        )

    def project_event(
        self, event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None:
        payload = event if isinstance(event, Mapping) else None
        if (
            payload is not None
            and payload.get("hosted_resume_committed_input") is True
            and isinstance(payload.get("text"), str)
        ):
            return CodingHostedEventProjectionV1(
                SessionEventKindV1.USER_MESSAGE,
                cast(str, payload["text"]),
            )
        active = self._active
        if active is not None:
            return active.project_event(event)
        if payload is not None and payload.get("hosted_presentation") is True:
            kind = payload.get("type")
            if kind in {"tool_approval_requested", "tool_approval_resolved"}:
                return CodingHostedEventProjectionV1(
                    SessionEventKindV1.INTERACTION_REQUESTED
                    if kind == "tool_approval_requested"
                    else SessionEventKindV1.INTERACTION_DISMISSED,
                    cast(str | None, payload.get("text")),
                    cast(str, payload["interaction_id"]),
                )
        return None

    async def lookup_resume_input(
        self, query: CodingResumeInputLookupQueryV1,
    ) -> CodingResumeInputLookupResultV1:
        active = self._active
        if active is not None:
            return await active.lookup_resume_input(query)
        from .resume_activation_projection_v2 import (
            project_coding_activation_attempt_path_v2,
        )
        from .resume_input_lookup import coding_resume_input_record_digest

        try:
            records = self._source.history.selected_records
            projection = project_coding_activation_attempt_path_v2(
                records, current_session_id=self.identity.session_id
            )
            binding = projection.binding
            if (
                projection.binding_status == "bound"
                and binding is not None
                and binding.input_id == query.input_id
                and projection.binding_record_id is not None
            ):
                candidates = tuple(
                    record
                    for record in records
                    if record.record_id == projection.binding_record_id
                )
                if len(candidates) != 1:
                    return CodingResumeInputLookupResultV1(
                        query.input_id, None, "unknown"
                    )
                if coding_resume_input_record_digest(candidates[0]) != query.record_digest:
                    return CodingResumeInputLookupResultV1(
                        query.input_id, None, "conflict"
                    )
                return CodingResumeInputLookupResultV1(
                    query.input_id, candidates[0].record_id, "committed"
                )
        except ValueError:
            return CodingResumeInputLookupResultV1(query.input_id, None, "unknown")
        retained = self._latest_input_query
        if retained is not None and retained.input_id == query.input_id:
            return CodingResumeInputLookupResultV1(
                query.input_id,
                None,
                "unknown" if retained == query else "conflict",
            )
        return CodingResumeInputLookupResultV1(query.input_id, None, "unknown")

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        active = self._active
        if active is not None:
            return await active.respond_interaction(interaction_id, outcome)
        action_id = self._interactions.get(interaction_id)
        mapped = cast(
            ApprovalOutcome | None,
            outcome if outcome in {"allow_once", "deny", "abort"} else None,
        )
        if action_id is None or mapped is None:
            return False
        return await self._approval.handle_result(action_id, outcome=mapped)

    async def activate(
        self,
        text: str,
        *,
        scope: ScopedAppServicePortV1,
        subject_control: SessionSnapshotRequestV1,
        subject_digest: str,
        submission_id: str,
    ) -> _ActivatedHostedResumeV1:

        from ._capability_plugin_composition import (
            prepare_coding_resume_plugin_effect_owners,
            require_coding_resume_plugin_effect_settlement,
        )
        from ._product_capability_plugin_composition import (
            prepare_coding_product_approval_state_root,
        )
        from .embedded_resume import (
            _require_no_capability_plugin_effects,
            _resume_capability_plugins_required,
        )
        from .resume_activation_attempt import (
            CodingActivationAttemptV1,
            CodingResumeRecoveryRequired,
        )
        from .resume_activation_attempt_v2 import CodingActivationAttemptV2
        from .resume_continuation import prepare_coding_resume_continuation

        async with self._activation_lock:
            if self._close_task is not None:
                raise CodingHostedCatalogError()
            if self._active is not None:
                raise CodingHostedCatalogError()

            def require_subject() -> None:
                scope.require_current_resume_subject(
                    subject_control,
                    subject_digest,
                    expected_session_id=plan.session_id,
                )

            self._source.require_current_source()
            policy = workspace_tool_runtime_settings(self._services.settings_manager)
            raw_policy_engine = policy.policy_engine
            if raw_policy_engine is None:
                raise CodingHostedCatalogError()
            policy_engine = cast(NativeResumePolicy, raw_policy_engine)
            model = self.current_model
            if model is None:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            plan = await self._current_plan()
            self._source.require_current_source()
            assert plan.ancestry_digest is not None
            workspace = Path(plan.workspace_root)

            require_subject()
            epoch_fingerprint = self._product_owner_selection.prepare_resume_epoch(
                self._hosted_workspace.anchor if self._hosted_workspace is not None else workspace,
                require_current_admission=require_subject,
                settings_manager=self._services.settings_manager,
                historical_origin=self._hosted_workspace.legacy_plugin_origin if self._hosted_workspace is not None else None,
            )
            require_subject()
            plugins_enabled = _resume_capability_plugins_required(
                plan_set_id=plan.composition_comparison.candidate_set_id,
                settings_manager=self._services.settings_manager,
                no_tools=None if self._workspace_tools else "all",
                history=self._source.history,
            )
            state_id = hashlib.sha256(
                b"loushang.coding-capability-plugin-state/v1\0"
                + plan.session_id.encode()
            ).hexdigest()
            plugin_state_root = (
                self._source.record.scope.session_dir
                / "plugin-state"
                / "coding-capability-plugins"
                / state_id
            )
            plugin_owners = (
                prepare_coding_resume_plugin_effect_owners(
                    session_id=plan.session_id, state_root=plugin_state_root
                )
                if plugins_enabled
                else ()
            )
            stable = hashlib.sha256(
                (
                    self.identity.continuity_id
                    + "\0"
                    + self.identity.session_id
                    + "\0"
                    + submission_id
                ).encode()
            ).hexdigest()
            attempt: CodingActivationAttemptV1 = CodingActivationAttemptV2(
                attempt_id=f"resume-attempt:{token_hex(16)}",
                request_id=f"resume-input:{stable}",
                session_id=plan.session_id,
                original_leaf_id=plan.selected_leaf_id,
                ancestry_digest=plan.ancestry_digest,
                plan_fingerprint=plan.plan_id,
                epoch_fingerprint=epoch_fingerprint,
                subject_digest=subject_digest,
                effect_owners=tuple(sorted(plugin_owners, key=lambda owner: owner.identity)),
            )
            def admit(observed: CodingActivationAttemptV1) -> None:
                if type(observed) is not CodingActivationAttemptV2:
                    raise CodingResumeRecoveryRequired(
                        "input.effect_owner_set_unsupported"
                    )
                require_subject()
                if self._close_task is not None:
                    raise CodingHostedCatalogError()

            def settle(
                observed: CodingActivationAttemptV1, receipt: Mapping[str, object]
            ) -> None:
                if type(observed) is not CodingActivationAttemptV2:
                    raise CodingResumeRecoveryRequired(
                        "input.effect_owner_set_unsupported"
                    )
                if plugin_owners:
                    require_coding_resume_plugin_effect_settlement(
                        observed,
                        receipt,
                        state_root=prepare_coding_product_approval_state_root(
                            plugin_state_root
                        ),
                        clock=lambda: time.time_ns() // 1_000_000,
                    )
                else:
                    _require_no_capability_plugin_effects(
                        observed,
                        receipt,
                        expected_set_id=plan.composition_comparison.candidate_set_id,
                    )

            continuation = await prepare_coding_resume_continuation(
                manager_type=self._source.manager_type,
                session_file=self._source.record.path,
                plan=plan,
                current_owner_inputs=plan.owner_inputs,
                attempt=attempt,
                input_record_id=f"resume-record:{stable}",
                text=text,
                created_at=datetime.now(UTC),
                require_current_admission=admit,
                require_current_epoch_settlement=settle,
                services=self._services,
                model=model,
                stream_fn=self._stream_fn,
                tools=self._tools,
                output_capture_factory=self._output_capture_factory,
                approval_resolver=self._approval,
                no_tools=None if self._workspace_tools else "all",
                tool_policy_evaluator=PolicyEvaluatorChain((self._workspace_policy, policy_engine))
                if self._workspace_policy is not None else policy_engine,
                _hosted_workspace=self._hosted_workspace,
                observe_input_identity=self._observe_input_identity,
                product_owner_selection=self._product_owner_selection,
                resume_writer_factory=self._source.writer_factory,
            )
            try:
                await self._source.close()
            except BaseException:
                await continuation.session.dispose()
                raise
            try:
                real = CodingRealHostedSessionV1(
                    continuation.session, self.identity, self._approval, workspace=self._workspace
                )
                if self._user_choice_enabled:
                    real.enable_user_choice()
                self._control.activate(real.control)
                self._active = real
                # The input was durably committed while the real adapter did
                # not yet exist. Publish its UI projection after the in-place
                # handoff; this event performs no transcript write or replay.
                await self._control.emit(cast(RuntimeEvent[object], {
                    "type": "hosted_resume_committed_input",
                    "hosted_resume_committed_input": True,
                    "text": text,
                }))
            except BaseException:
                await continuation.session.dispose()
                raise
            return _ActivatedHostedResumeV1(
                continuation.session,
                continuation.attempt_id,
                continuation.input_record_id,
            )

    def _observe_input_identity(self, query: CodingResumeInputLookupQueryV1) -> None:
        self._latest_input_query = query

    async def close(self) -> None:
        task = self._close_task
        if task is None or (task.done() and not task.cancelled() and task.exception()):
            task = asyncio.create_task(self._close_once())
            task.add_done_callback(_observe_close)
            self._close_task = task
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        async with self._activation_lock:
            self._control.close()
            active = self._active
            if active is not None:
                await active.close()
            else:
                self._approval.end_session()
                await self._source.close()
            if self._planning is not None:
                await self._planning.close()
            self._interactions.clear()


@dataclass(frozen=True, slots=True)
class _ActivatedHostedResumeV1:
    session: AgentSession
    attempt_id: str
    input_record_id: str


class _HostedResumeExecutionWorkV1(_HostedAgentExecutionWork):
    def __init__(
        self,
        binding: CodingDeferredHostedSessionV1,
        text: str,
        cancel_requested: Callable[[], bool],
        scope: ScopedAppServicePortV1,
        control: SessionSnapshotRequestV1,
        subject_digest: str,
        submission_id: str,
    ) -> None:
        self._binding = binding
        self._text = text
        self._cancel_requested = cancel_requested
        self._scope = scope
        self._control = control
        self._subject_digest = subject_digest
        self._submission_id = submission_id
        self._session: AgentSession | None = None
        self._interrupted = False
        self._agent_outcome: ExecutionOutcomeV1 | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._unbind_turn: Callable[[], None] | None = None

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        if self._cancel_requested():
            return ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
        try:
            activated = await self._binding.activate(
                self._text,
                scope=self._scope,
                subject_control=self._control,
                subject_digest=self._subject_digest,
                submission_id=self._submission_id,
            )
            session = activated.session
            self._session = session
            return await self._execute_published_input(
                control, session, activated.attempt_id, activated.input_record_id
            )
        except asyncio.CancelledError:
            self._interrupted = True
            if self._session is not None:
                self._session.abort()
            raise
        finally:
            self._clear_turn()

    async def settle(self) -> None:
        await self._settle_published_input(self._session)
        if (
            not self._cancel_requested() and self._agent_outcome is not None
            and self._agent_outcome.status is ExecutionStatusV1.SUCCEEDED
        ):
            self._binding.start_title_if_unnamed()


__all__ = ["CodingDeferredHostedSessionV1"]
