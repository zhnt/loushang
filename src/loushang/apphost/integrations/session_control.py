"""Private AppHost bridge over the existing Harness Session control owner.

No Session/Agent/queue creation, transport listener, authorization or journal.
Each Product facade remains the same single resource-owning Session object.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, cast

from loushang.ai.model import model_selection_ref, normalize_model_selection
from loushang.ai.types import AssistantMessage
from loushang.apphost.application import _method_descriptor
from loushang.apphost.contracts import SessionBindingKeyV1
from loushang.appserver.protocol import (
    InteractionOutcomeV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionModelChoiceV1,
    SessionModelsV1,
    SessionSnapshotV1,
    SessionSubmissionModeV1,
    SessionThinkingV1,
    TranscriptRecordV1,
)
from loushang.appservice import HostedSessionEventListenerV1
from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.appservice.execution_guard import ExecutionControlV1
from loushang.harness.events import RuntimeEvent
from loushang.harness.session import (
    SessionControlPort,
    SessionOperationRuntime,
    SessionPromptRequest,
)
from loushang.harness.session.model_selection import (
    apply_session_model_selection,
    get_session_model_selection,
    iter_available_model_details,
    model_choice_data_from_details,
)

if TYPE_CHECKING:
    from loushang.agent import AbortSignal
    from loushang.agent.types import AgentEvent
    from loushang.harness.session._resume_continuation import _ResumeContinuationSession
    from loushang.harness.session.agent_product import AgentProductSession


class _SnapshotProjection(Protocol):
    @property
    def title(self) -> str: ...
    @property
    def revision(self) -> int: ...
    @property
    def running(self) -> bool: ...
    @property
    def records(self) -> tuple[TranscriptRecordV1, ...]: ...


class _EventProjection(Protocol):
    @property
    def kind(self) -> SessionEventKindV1: ...
    @property
    def text(self) -> str | None: ...
    @property
    def interaction_id(self) -> str | None: ...


SnapshotT = TypeVar("SnapshotT", bound=_SnapshotProjection)
EventT = TypeVar("EventT", bound=_EventProjection)
SnapshotCo = TypeVar("SnapshotCo", bound=_SnapshotProjection, covariant=True)
EventCo = TypeVar("EventCo", bound=_EventProjection, covariant=True)


class _HostedBinding(Protocol[SnapshotCo, EventCo]):
    @property
    def identity(self) -> SessionIdentityV1: ...
    @property
    def control(self) -> SessionControlPort | None: ...
    def project_snapshot(self) -> SnapshotCo: ...
    def project_event(self, event: RuntimeEvent[object]) -> EventCo | None: ...
    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool: ...
    async def close(self) -> None: ...


class _SessionServiceAdapter(Generic[SnapshotT, EventT]):
    """Adapt one admitted Product binding through its original Session control."""

    _product_id: str
    _product_label: str
    _snapshot_type: type[SnapshotT]
    _event_type: type[EventT]

    __slots__ = (
        "_binding",
        "_close_lock",
        "_close_task",
        "_cursor",
        "_listeners",
        "_operations",
        "_settled",
        "_submission_mode",
        "_unsubscribe",
        "_unsubscribed",
        "identity",
    )

    def __init__(
        self,
        binding: _HostedBinding[SnapshotT, EventT],
        *,
        execution_submission: bool = False,
    ) -> None:
        self._require_binding(binding)
        if type(execution_submission) is not bool:
            raise TypeError(f"{self._product_label} hosted submission mode is invalid")
        identity = binding.identity
        if type(identity) is not SessionIdentityV1 or identity.product_id != (
            self._product_id
        ):
            raise TypeError(f"{self._product_label} hosted Session identity is invalid")
        self.identity = identity
        self._binding = binding
        self._submission_mode = (
            SessionSubmissionModeV1.EXECUTION
            if execution_submission
            else SessionSubmissionModeV1.LEGACY
        )
        control = binding.control
        self._operations = None if control is None else SessionOperationRuntime(control)
        self._listeners: set[HostedSessionEventListenerV1] = set()
        self._cursor = 0
        self._settled = False
        self._unsubscribed = False
        self._close_task: asyncio.Task[None] | None = None
        self._close_lock = asyncio.Lock()
        if control is None:
            self._unsubscribe = lambda: None
            return
        try:
            unsubscribe = control.subscribe_runtime_events(self._on_runtime_event)
        except BaseException:
            raise TypeError(
                f"{self._product_label} hosted event subscription is unavailable"
            ) from None
        if not callable(unsubscribe):
            raise TypeError(
                f"{self._product_label} hosted event subscription is unavailable"
            )
        self._unsubscribe = unsubscribe

    async def snapshot(self) -> SessionSnapshotV1:
        self._require_open()
        try:
            projection = self._binding.project_snapshot()
        except BaseException:
            raise RuntimeError(
                f"{self._product_id}_hosted_snapshot_unavailable"
            ) from None
        if type(projection) is not self._snapshot_type:
            raise RuntimeError(f"{self._product_id}_hosted_snapshot_unavailable")
        return SessionSnapshotV1(
            identity=self.identity,
            title=projection.title,
            cursor=self._cursor,
            revision=projection.revision,
            running=projection.running,
            records=projection.records,
            submission_mode=self._submission_mode,
        )

    def subscribe(
        self,
        listener: HostedSessionEventListenerV1,
    ) -> Callable[[], None]:
        self._require_open()
        if not callable(listener):
            raise TypeError(f"{self._product_label} hosted listener must be callable")
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    async def start_turn(self, text: str) -> None:
        self._require_open()
        await self._require_operations().prompt(
            request=self._prompt_request(text),
        )

    def steer_turn(self, text: str) -> None:
        self._require_open()
        self._require_operations().steer(text)

    def follow_up_turn(self, text: str) -> None:
        self._require_open()
        self._require_operations().follow_up(text)

    def interrupt_turn(self) -> bool:
        self._require_open()
        return False if self._operations is None else self._operations.abort_turn()

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: InteractionOutcomeV1,
    ) -> bool:
        self._require_open()
        if self._operations is None:
            return False
        mapped = {
            InteractionOutcomeV1.APPROVE: "allow_once",
            InteractionOutcomeV1.DENY: "deny",
            InteractionOutcomeV1.CANCEL: "abort",
        }[outcome]
        try:
            result = await self._binding.respond_interaction(interaction_id, mapped)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RuntimeError(
                f"{self._product_id}_hosted_interaction_unavailable"
            ) from None
        return result is True

    async def list_models(self) -> SessionModelsV1:
        self._require_open()
        control = self._binding.control
        active_model = getattr(getattr(control, 'agent', None), 'model', None)
        selection = normalize_model_selection(active_model)
        if selection is None:
            selection = await get_session_model_selection(control)
            active_model = selection
        current = model_selection_ref(selection) if selection is not None else None
        details = await iter_available_model_details(control)
        if active_model is not None:
            details.append(active_model)
        models: list[SessionModelChoiceV1] = []
        for choice in model_choice_data_from_details(details):
            reference = normalize_model_selection(choice.selection)
            if reference is None:
                continue
            models.append(SessionModelChoiceV1(id=choice.value, provider=reference.provider, endpoint_id=reference.endpoint_id, model_id=reference.model_id, label=choice.label, supports_thinking=bool(getattr(choice.selection, 'supports_thinking', False) or getattr(choice.selection, 'reasoning', False))))
        visible = models[:256]
        active_choice = next((model for model in models[256:] if model.id == current), None)
        if active_choice is not None:
            visible[-1] = active_choice
        return SessionModelsV1(current, tuple(visible), _thinking_settings(control) if current is not None else None)

    async def select_model(self, model_id: str, thinking_level: str | None=None) -> SessionModelsV1:
        self._require_open()
        control = self._binding.control
        if getattr(control, 'is_streaming', False):
            raise RuntimeError(f'{self._product_id}_model_change_while_running')
        if thinking_level is not None:
            before = await self.list_models()
            setter = getattr(control, 'set_thinking_level', None)
            if getattr(control, 'is_streaming', False) or before.current_id != model_id or before.thinking is None or (thinking_level not in before.thinking.available_levels) or (not callable(setter)):
                raise ValueError(f'{self._product_id}_thinking_level_unavailable')
            await setter(thinking_level)
            return await self.list_models()
        choices = model_choice_data_from_details(await iter_available_model_details(control))
        selected = next((choice.selection for choice in choices if choice.value == model_id), None)
        if selected is None:
            raise ValueError(f'{self._product_id}_model_unavailable')
        await apply_session_model_selection(control, selected)
        return await self.list_models()

    async def close(self) -> None:
        async with self._close_lock:
            if self._settled:
                return
            if not self._unsubscribed:
                self._unsubscribed = True
                with suppress(BaseException):
                    self._unsubscribe()
                self._listeners.clear()
            if self._close_task is None:
                self._close_task = asyncio.create_task(self._binding.close())
            task = self._close_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            async with self._close_lock:
                if self._close_task is task:
                    self._close_task = None
            raise
        async with self._close_lock:
            if self._close_task is task:
                self._settled = True
                self._close_task = None

    @property
    def closed(self) -> bool:
        return self._unsubscribed

    async def _on_runtime_event(self, event: RuntimeEvent[object]) -> None:
        if self._unsubscribed:
            return
        try:
            projection = self._binding.project_event(event)
        except BaseException:
            projection = None
        else:
            if projection is None:
                return
        if type(projection) is not self._event_type:
            projection = cast(Callable[..., EventT], self._event_type)(
                SessionEventKindV1.ERROR,
                "event_projection_unavailable",
            )
        self._cursor += 1
        hosted_event = SessionEventV1(
            session_id=self.identity.session_id,
            cursor=self._cursor,
            kind=projection.kind,
            text=projection.text,
            interaction_id=projection.interaction_id,
        )
        self._observe_projection(projection, hosted_event)
        for listener in tuple(self._listeners):
            try:
                result = listener(hosted_event)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    def _observe_projection(self, projection: EventT, event: SessionEventV1) -> None:
        """Synchronous Product observation before optional delivery listeners."""

    @staticmethod
    def _prompt_request(text: str) -> SessionPromptRequest:
        return SessionPromptRequest(text=text, source="appservice")

    def _require_open(self) -> None:
        if self._unsubscribed:
            raise RuntimeError(f"{self._product_id}_hosted_session_closed")

    def _require_operations(self) -> SessionOperationRuntime:
        if self._operations is None:
            from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        return self._operations

    @classmethod
    def _require_binding(cls, binding: object) -> None:
        _require_hosted_binding(binding, label=cls._product_label)


def _require_hosted_binding(binding: object, *, label: str) -> None:
    for name in ("project_snapshot", "project_event"):
        if not callable(getattr(binding, name, None)):
            raise TypeError(f"{label} hosted Session binding is invalid")
    for name in ("respond_interaction", "close"):
        if not inspect.iscoroutinefunction(getattr(binding, name, None)):
            raise TypeError(f"{label} hosted Session binding is invalid")
    try:
        control = cast(
            _HostedBinding[_SnapshotProjection, _EventProjection], binding
        ).control
    except BaseException:
        raise TypeError(f"{label} hosted Session binding is invalid") from None
    if control is None:
        return
    for name in (
        "subscribe_runtime_events",
        "prompt",
        "wait_for_idle",
        "steer",
        "follow_up",
        "abort",
    ):
        if not callable(getattr(control, name, None)):
            raise TypeError(f"{label} hosted Session control is invalid")


__all__: list[str] = []


def _validate_foreground_binding(
    binding: object,
    key: SessionBindingKeyV1,
    *,
    label: str,
) -> None:
    try:
        identity = cast(
            _HostedBinding[_SnapshotProjection, _EventProjection], binding
        ).identity
        control = cast(
            _HostedBinding[_SnapshotProjection, _EventProjection], binding
        ).control
    except BaseException:
        raise TypeError(f"{label} hosted Session binding is invalid") from None
    if (
        type(identity) is not SessionIdentityV1
        or identity.product_id != key.product_id
        or identity.continuity_id != key.continuity_id
        or identity.session_id != key.session_id
    ):
        raise TypeError(f"{label} hosted Session identity is invalid")
    for name in ("project_snapshot", "project_event"):
        if not callable(getattr(binding, name, None)):
            raise TypeError(f"{label} hosted Session binding is invalid")
    for name in ("respond_interaction", "close"):
        if not inspect.iscoroutinefunction(_method_descriptor(binding, name)):
            raise TypeError(f"{label} hosted Session binding is invalid")
    if control is None:
        return
    for name in (
        "subscribe_runtime_events",
        "prompt",
        "wait_for_idle",
        "steer",
        "follow_up",
        "abort",
    ):
        if not callable(getattr(control, name, None)):
            raise TypeError(f"{label} hosted Session control is invalid")


def _thinking_settings(control: object) -> SessionThinkingV1 | None:
    getter = getattr(control, 'get_available_thinking_levels', None)
    current = getattr(control, 'thinking_level', None)
    if not callable(getter) or not isinstance(current, str):
        return None
    levels = tuple(getter())
    if current not in levels or levels == ('off',):
        return None
    return SessionThinkingV1(current, levels)


class _HostedAgentExecutionWork:
    """Same-instance Agent observation and Session dispatch at the AppHost bridge."""

    session: AgentProductSession
    text: str
    _cancel_requested: Callable[[], bool]
    _interrupted: bool
    _agent_outcome: ExecutionOutcomeV1 | None
    _unsubscribe: Callable[[], None] | None
    _unbind_turn: Callable[[], None] | None

    def _outcome_observer(self) -> Callable[[AgentEvent, AbortSignal], None]:
        def observe(event: AgentEvent, _signal: AbortSignal) -> None:
            if event["type"] == "agent_end":
                for message in reversed(event["messages"]):
                    if isinstance(message, AssistantMessage):
                        self._agent_outcome = _assistant_outcome(message)
                        break

        return observe

    async def _execute_hosted_prompt(
        self, control: ExecutionControlV1
    ) -> ExecutionOutcomeV1:
        self._unsubscribe = self.session.agent.subscribe(self._outcome_observer())
        self._unbind_turn = control.bind_turn_interrupt(
            lambda: self.session.abort() if self.session.is_streaming else False
        )
        result = await self.session.execute_prompt(
            self.text, source="appservice", check_cancelled=self._checkpoint
        )
        if result.failure_code is not None:
            return ExecutionOutcomeV1(
                ExecutionStatusV1.FAILED, error_code=result.failure_code
            )
        if not result.accepted:
            return ExecutionOutcomeV1(
                ExecutionStatusV1.FAILED, error_code="input_not_accepted"
            )
        if not result.model_started:
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
        if self._agent_outcome is None:
            return ExecutionOutcomeV1(
                ExecutionStatusV1.FAILED, error_code="missing_agent_outcome"
            )
        return self._agent_outcome

    async def _execute_published_input(
        self,
        control: ExecutionControlV1,
        session: _ResumeContinuationSession[Any],
        attempt_id: str,
        input_record_id: str,
    ) -> ExecutionOutcomeV1:
        self._unsubscribe = session.agent.subscribe(self._outcome_observer())
        self._unbind_turn = control.bind_turn_interrupt(
            lambda: session.abort() if session.is_streaming else False
        )
        await session._run_published_resume_input(
            attempt_id=attempt_id,
            input_record_id=input_record_id,
        )
        return self._agent_outcome or ExecutionOutcomeV1(
            ExecutionStatusV1.FAILED, error_code="missing_agent_outcome"
        )

    async def _settle_hosted_prompt(self) -> None:
        await self.session.settle_execution(interrupted=self._interrupted)
        self._retire_subscription()

    async def _settle_published_input(
        self, session: AgentProductSession | None
    ) -> None:
        if session is not None:
            await session.settle_execution(interrupted=self._interrupted)
        self._retire_subscription()

    def _retire_subscription(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _abort_hosted_prompt(self) -> None:
        self.session.abort()
        self.session.abort_retry()
        self.session.abort_command()
        self.session.abort_compaction()
        self.session.abort_branch_summary()

    def _clear_turn(self) -> None:
        if self._unbind_turn is not None:
            self._unbind_turn()
            self._unbind_turn = None

    def _checkpoint(self) -> None:
        if self._cancel_requested():
            raise asyncio.CancelledError


def _assistant_outcome(message: AssistantMessage) -> ExecutionOutcomeV1:
    if message.stop_reason == "aborted":
        return ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
    if message.stop_reason == "error":
        return ExecutionOutcomeV1(
            ExecutionStatusV1.FAILED, error_code="assistant_response_error"
        )
    return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
