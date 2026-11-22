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
    _HostedApprovalPresentation,
    _HostedResumeInputExecutionWork,
)
from loushang.appserver.execution.model import InteractiveGoalRecoveryV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionEventKindV1,
    SessionSnapshotRequestV1,
)
from loushang.appservice.client_scope import ScopedAppServicePortV1
from loushang.appservice.execution_guard import ExecutionWorkV1
from loushang.coding.composition.bootstrap import BootstrapServices
from loushang.coding.composition.sets import resolve_coding_composition_set
from loushang.coding.hosted.catalog import (
    CodingHostedCatalogError,
    CodingHostedResumeSourceV1,
)
from loushang.coding.hosted.goal_recovery import (
    read_interactive_goal_recovery,
    unavailable_recovery,
)
from loushang.coding.hosted.models import load_workspace_models
from loushang.coding.hosted.service_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSnapshotProjectionV1,
)
from loushang.coding.hosted.session import (
    _MAX_INTERACTIONS,
    _TEXT_LIMIT,
    CodingRealHostedSessionV1,
    _resolve_hosted_saved_model,
)
from loushang.coding.package.product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.resume.activation_plan import SessionActivationPlanV1
from loushang.coding.resume.input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
)
from loushang.coding.resume.permission_confirmation import NativeResumePolicy
from loushang.coding.runtime.resume_planning import ResumePlanningSlot
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.approval import (
    ApprovalOutcome,
    DenyApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.events import RuntimeEvent
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.runtime._owned_tasks import _get_close_task
from loushang.harness.session import SessionControlPort
from loushang.harness.session.model_selection import (
    apply_session_model_selection,
    iter_available_model_details,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace import workspace_tool_runtime_settings
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory


class _DeferredHostedControlV1(_DeferredSessionControl[CodingRealHostedSessionV1]):
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
        user_choice_enabled: bool = False,
    ) -> None:
        self._source = source
        self.identity = source.record.identity
        self._services = services
        self._model = model
        self._stream_fn = stream_fn
        self._tools = tools
        self._user_choice_enabled = user_choice_enabled
        self._output_capture_factory = output_capture_factory
        self._product_owner_selection = product_owner_selection
        self._approval = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        self._approval.open_session()
        self._approval.set_request_presenter(
            self._present_approval, dismisser=self._dismiss_approval
        )
        self._control = _DeferredHostedControlV1(self)
        self._planning: ResumePlanningSlot | None = None
        self._activation_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._interactions: dict[str, str] = {}
        self._latest_input_query: CodingResumeInputLookupQueryV1 | None = None

    @property
    def control(self) -> SessionControlPort:
        return cast(SessionControlPort, self._control)

    @property
    def _active(self) -> CodingRealHostedSessionV1 | None:
        return self._control.resume_binding

    @property
    def execution_available(self) -> bool:
        return self._close_task is None and not self._control.resume_handoff_failed

    @property
    def supports_interactive_goal_recovery(self) -> bool:
        return self._active is None and self.execution_available

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
            if not self.execution_available:
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
        from loushang.coding.resume.activation_attempt import (
            CodingResumeRecoveryRequired,
        )
        from loushang.coding.resume.activation_plan import plan_coding_resume_async

        self._source.require_current_source()
        policy = workspace_tool_runtime_settings(self._services.settings_manager)
        raw_policy_engine = policy.policy_engine
        if raw_policy_engine is None:
            raise CodingHostedCatalogError()
        policy_engine = cast(NativeResumePolicy, raw_policy_engine)
        plan = await plan_coding_resume_async(
            self._source.history,
            resolve_coding_composition_set("coding-standard"),
            workspace_root=self._source.record.scope.cwd,
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
        await settled_io(load_workspace_models, self._services, self._source.record.scope.cwd)
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
            workspace_root=self._source.record.scope.cwd,
            resource_loader=self._services.resource_loader,
            subject_digest=self._plan_subject_digest(),
            policy_digest=policy_engine.configuration_fingerprint(),
            max_work_units=200,
            time_budget_seconds=5.0,
        )

    def create_execution_work(
        self, text: str, cancel_requested: Callable[[], bool],
    ) -> ExecutionWorkV1:
        from loushang.coding.hosted._execution_work import (
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
        from loushang.coding.resume.activation_projection_v2 import (
            observe_latest_bound_input,
        )
        from loushang.coding.resume.input_lookup import (
            coding_resume_input_record_digest,
        )

        try:
            selected = observe_latest_bound_input(
                self._source.history.selected_records,
                current_session_id=self.identity.session_id,
                input_id=query.input_id, expected_digest=query.record_digest,
                digest=coding_resume_input_record_digest,
            )
        except ValueError:
            return CodingResumeInputLookupResultV1(query.input_id, None, "unknown")
        if isinstance(selected, str):
            return CodingResumeInputLookupResultV1(query.input_id, None, selected)
        if selected is not None:
            return CodingResumeInputLookupResultV1(query.input_id, selected.record_id, "committed")
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

        from loushang.coding.composition.capability_plugins import (
            require_coding_resume_plugin_effect_settlement,
        )
        from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
        from loushang.coding.resume.continuation import (
            prepare_coding_resume_continuation,
        )
        from loushang.coding.resume.first_input import (
            prepare_first_input_effects,
            require_first_input_attempt,
        )

        async with self._activation_lock:
            if not self.execution_available:
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
                workspace,
                require_current_admission=require_subject,
                settings_manager=self._services.settings_manager,
            )
            require_subject()
            effects = prepare_first_input_effects(
                plan,
                history=self._source.history,
                session_dir=self._source.record.scope.session_dir,
                settings_manager=self._services.settings_manager,
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
            attempt, settle = effects.bind(
                attempt_id=f"resume-attempt:{token_hex(16)}",
                request_id=f"resume-input:{stable}",
                epoch_fingerprint=epoch_fingerprint,
                subject_digest=subject_digest,
                clock=lambda: time.time_ns() // 1_000_000,
                verify_plugin_effects=require_coding_resume_plugin_effect_settlement,
            )

            def admit(observed: CodingActivationAttemptV1) -> None:
                require_first_input_attempt(observed)
                require_subject()
                if self._close_task is not None:
                    raise CodingHostedCatalogError()

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
                tool_policy_evaluator=policy_engine,
                observe_input_identity=self._observe_input_identity,
                product_owner_selection=self._product_owner_selection,
                resume_writer_factory=self._source.writer_factory,
            )
            def bind() -> CodingRealHostedSessionV1:
                real = CodingRealHostedSessionV1(
                    continuation.session, self.identity, self._approval
                )
                if self._user_choice_enabled:
                    real.enable_user_choice()
                return real

            await self._control.complete_resume_handoff(
                continuation.session,
                close_history=self._source.close,
                bind=bind,
                committed_input_event=cast(RuntimeEvent[object], {
                    "type": "hosted_resume_committed_input",
                    "hosted_resume_committed_input": True,
                    "text": text,
                }),
            )
            return _ActivatedHostedResumeV1(
                continuation.session,
                continuation.attempt_id,
                continuation.input_record_id,
            )

    def _observe_input_identity(self, query: CodingResumeInputLookupQueryV1) -> None:
        self._latest_input_query = query

    async def close(self) -> None:
        self._close_task = _get_close_task(
            self._close_task, self._close_once, retry_cancelled=False
        )
        await asyncio.shield(self._close_task)

    async def _close_once(self) -> None:
        async with self._activation_lock:
            self._control.close()
            await self._control.settle_resume_handoff()
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


class _HostedResumeExecutionWorkV1(_HostedResumeInputExecutionWork):
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
        async def activate() -> _ActivatedHostedResumeV1:
            return await binding.activate(
                text,
                scope=scope,
                subject_control=control,
                subject_digest=subject_digest,
                submission_id=submission_id,
            )

        super().__init__(
            cancel_requested, activate=activate,
            on_success=lambda: binding.start_title_if_unnamed(),
        )


__all__ = ["CodingDeferredHostedSessionV1"]
