"""Hosted Resume history-first planning and in-place first-input activation."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import cast

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection, normalize_model_selection
from loushang.ai.utils.capabilities import validate_image_input_compatibility
from loushang.apphost.integrations.session_control import _HostedAgentExecutionWork
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
from .hosted_session import (
    _MAX_INTERACTIONS,
    _TEXT_LIMIT,
    CodingRealHostedSessionV1,
    _observe_close,
    _resolve_hosted_saved_model,
)
from .package_product_runtime import CodingFencedProductApplicationSelection
from .resume_activation_plan import SessionActivationPlanV1
from .resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
)
from .resume_permission_confirmation import NativeResumePolicy
from .runtime.resume_planning import ResumePlanningSlot
from .session.agent_session import AgentSession


class _DeferredHostedControlV1:
    """Stable control identity that later relays the activated Session."""

    def __init__(self, binding: CodingDeferredHostedSessionV1) -> None:
        self._binding = binding
        self._delegate: SessionControlPort | None = None
        self._listeners: set[Callable[[RuntimeEvent[object]], object]] = set()
        self._unsubscribe: Callable[[], None] | None = None
        self._closed = False

    @property
    def session_id(self) -> str:
        return self._binding.identity.session_id

    @property
    def session_name(self) -> str | None:
        return None if self._delegate is None else self._delegate.session_name

    async def set_session_name(self, name: str | None) -> None:
        await self._require_active().set_session_name(name)

    def subscribe_runtime_events(
        self, listener: Callable[[RuntimeEvent[object]], object],
    ) -> Callable[[], None]:
        if self._closed or not callable(listener):
            raise RuntimeError("coding_hosted_session_closed")
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def emit(self, event: RuntimeEvent[object]) -> None:
        for listener in tuple(self._listeners):
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self._listeners.discard(listener)

    def activate(self, control: SessionControlPort) -> None:
        if self._closed or self._delegate is not None:
            raise CodingHostedCatalogError()
        if control.session_id != self.session_id:
            raise CodingHostedCatalogError()

        async def relay(event: RuntimeEvent[object]) -> None:
            await self.emit(event)

        unsubscribe = control.subscribe_runtime_events(relay)
        if not callable(unsubscribe):
            raise CodingHostedCatalogError()
        self._delegate = control
        self._unsubscribe = unsubscribe

    async def prompt(self, user_input: str, images=None, **kwargs) -> None:
        await self._require_active().prompt(user_input, images=images, **kwargs)

    def steer(self, user_input: str, images=None) -> None:
        self._require_active().steer(user_input, images=images)

    def follow_up(self, user_input: str, images=None) -> None:
        self._require_active().follow_up(user_input, images=images)

    async def wait_for_idle(self) -> None:
        await self._require_active().wait_for_idle()

    def abort(self) -> bool:
        return False if self._delegate is None else self._delegate.abort()

    @property
    def is_streaming(self) -> bool:
        return bool(getattr(self._delegate, "is_streaming", False))

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
        return getattr(self._delegate, "thinking_level", None)

    def get_available_thinking_levels(self) -> tuple[str, ...]:
        getter = getattr(self._delegate, "get_available_thinking_levels", None)
        return tuple(getter()) if callable(getter) else ()

    async def set_thinking_level(self, level: str) -> None:
        setter = getattr(self._require_active(), "set_thinking_level", None)
        if not callable(setter):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        await setter(level)

    def close(self) -> None:
        self._closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._listeners.clear()

    def _require_active(self) -> SessionControlPort:
        if self._closed:
            raise RuntimeError("coding_hosted_session_closed")
        if self._delegate is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return self._delegate


class CodingDeferredHostedSessionV1:
    """One AppHost binding from detached history through first activation."""

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
    ) -> None:
        self._source = source
        self.identity = source.record.identity
        self._services = services
        self._model = model
        self._stream_fn = stream_fn
        self._tools = tools
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
        async with self._activation_lock:
            if self._close_task is not None:
                raise CodingHostedCatalogError()
            if self._active is not None:
                await apply_session_model_selection(self._active.control, selection)
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
            model = self._services.model_registry.build_model(selection)
            context = self._source.history_binding.context
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
                await manager.append_model_change(
                    selection.provider, selection.model_id, endpoint_id=selection.endpoint_id,
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

    def _load_model_catalog(self) -> None:
        cwd = self._source.record.scope.cwd
        inputs = self._services.resource_loader.preview_catalog_input_receipt(cwd)
        # Match the ordinary bootstrap's nearest project context, then user context.
        roots_with_context = {fact.root for fact in inputs.context_file_facts if fact.status == "file"}
        roots = (*inputs.user_resource_roots, *inputs.project_context_roots)
        project_root = next((root for root in reversed(roots) if root in roots_with_context), cwd)
        self._services.model_registry.reload_if_project_layer(
            user_dir=Path.home() / ".loushang" / "models",
            project_dir=project_root / ".loushang" / "models",
        )

    async def start_background_planning(self) -> None:
        self._source.require_current_source()
        await settled_io(self._load_model_catalog)
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

    async def _present_approval(self, request: dict[str, object]) -> None:
        action_id = request.get("action_id")
        if not isinstance(action_id, str) or len(self._interactions) >= _MAX_INTERACTIONS:
            raise RuntimeError("hosted_approval_unavailable")
        text = "\n".join((
            str(request.get("action", "Resume approval")),
            str(request.get("risk", "")),
            json.dumps(request.get("arguments", {}), ensure_ascii=False, sort_keys=True),
        ))
        if len(text) > _TEXT_LIMIT:
            raise RuntimeError("hosted_approval_too_large")
        interaction_id = token_hex(16)
        self._interactions[interaction_id] = action_id
        await self._control.emit(cast(RuntimeEvent[object], {
            "type": "tool_approval_requested",
            "hosted_presentation": True,
            "interaction_id": interaction_id,
            "text": text,
        }))

    async def _dismiss_approval(self, action_id: str) -> None:
        for interaction_id, pending in tuple(self._interactions.items()):
            if pending == action_id:
                self._interactions.pop(interaction_id, None)
                await self._control.emit(cast(RuntimeEvent[object], {
                    "type": "tool_approval_resolved",
                    "hosted_presentation": True,
                    "interaction_id": interaction_id,
                }))

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
                workspace,
                require_current_admission=require_subject,
                settings_manager=self._services.settings_manager,
            )
            require_subject()
            plugins_enabled = _resume_capability_plugins_required(
                plan_set_id=plan.composition_comparison.candidate_set_id,
                settings_manager=self._services.settings_manager,
                no_tools=None,
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
                tool_policy_evaluator=policy_engine,
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
                    continuation.session, self.identity, self._approval
                )
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
