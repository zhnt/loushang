"""Private AppHost bridge over the existing Harness Session control owner.

No Session/Agent/queue creation, transport listener, authorization or journal.
Each Product facade remains the same single resource-owning Session object.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Protocol, TypeVar, cast
from uuid import uuid4

from loushang.ai.model import model_selection_ref, normalize_model_selection
from loushang.ai.model.selection import is_usable_model_selection
from loushang.ai.types import AssistantMessage
from loushang.apphost.application import _method_descriptor
from loushang.apphost.contracts import SessionBindingKeyV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppServiceError,
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
    UserChoicePromptV1,
)
from loushang.appservice import HostedSessionEventListenerV1
from loushang.appservice.execution_contract import (
    ExecutionContentEventV1,
    ExecutionObservationV1,
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionSourceSnapshotV1,
    ExecutionStateV1,
    ExecutionStatusV1,
    InterruptModeV1,
)
from loushang.appservice.execution_guard import ExecutionControlV1, ExecutionGuardV1
from loushang.foundation._owned_tasks import (
    _observe_task_result,
    _task_failed_or_cancelled,
)
from loushang.harness.events import RuntimeEvent
from loushang.harness.session import (
    SessionControlPort,
    SessionOperationRuntime,
    SessionPromptRequest,
)
from loushang.harness.session._cleanup import SessionConstructionCleanup
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
    @property
    def user_choice(self) -> UserChoicePromptV1 | None: ...
    @property
    def truncated(self) -> bool: ...


class _EventProjection(Protocol):
    @property
    def kind(self) -> SessionEventKindV1: ...
    @property
    def text(self) -> str | None: ...
    @property
    def interaction_id(self) -> str | None: ...
    @property
    def truncated(self) -> bool: ...


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


_HostedBindingT = TypeVar("_HostedBindingT", bound=_HostedBinding[Any, Any])


class _SessionServiceAdapter(Generic[SnapshotT, EventT]):
    """Adapt one admitted Product binding through its original Session control."""

    _product_id: str
    _product_label: str
    _snapshot_type: type[SnapshotT]
    _event_type: type[EventT]

    __slots__ = (
        "_binding",
        "_model_lock",
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
        self._model_lock = asyncio.Lock()
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
            user_choice=projection.user_choice,
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
        operations = self._require_operations()
        if (await self.list_models()).current_id is None or self._model_lock.locked():
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        await operations.prompt(request=self._prompt_request(text))


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
        active_model = getattr(getattr(control, "agent", None), "model", None)
        selection = normalize_model_selection(active_model)
        if not is_usable_model_selection(selection):
            active_model = selection = await get_session_model_selection(control)
        selection = selection if is_usable_model_selection(selection) else None
        current = model_selection_ref(selection) if selection is not None else None
        details = await iter_available_model_details(control)
        if selection is not None:
            details.append(active_model)
        return project_session_models(
            current, details, _thinking_settings(control) if current is not None else None
        )


    async def select_model(
        self, model_id: str, thinking_level: str | None = None,
    ) -> SessionModelsV1:
        self._require_open()
        async with self._model_lock:
            return await self._select_model(model_id, thinking_level)


    async def _select_model(self, model_id: str, thinking_level: str | None) -> SessionModelsV1:
        self._require_open()
        control = self._binding.control
        if getattr(control, "is_streaming", False):
            raise RuntimeError(f"{self._product_id}_model_change_while_running")
        if thinking_level is not None:
            before = await self.list_models()
            setter = getattr(control, "set_thinking_level", None)
            if (
                getattr(control, "is_streaming", False)
                or before.current_id != model_id or before.thinking is None
                or thinking_level not in before.thinking.available_levels
                or not callable(setter)
            ):
                raise ValueError(f"{self._product_id}_thinking_level_unavailable")
            await setter(thinking_level)
            return await self.list_models()
        choices = model_choice_data_from_details(
            await iter_available_model_details(control)
        )
        selected = next(
            (choice.selection for choice in choices if choice.value == model_id), None
        )
        if not is_usable_model_selection(normalize_model_selection(selected)):
            raise ValueError(f"{self._product_id}_model_unavailable")
        await self._apply_selected_model(control, selected)
        return await self.list_models()


    async def _apply_selected_model(self, control: SessionControlPort | None, selected: object) -> None:
        await apply_session_model_selection(control, selected)

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


class _ExecutionSessionServiceAdapter(_SessionServiceAdapter[SnapshotT, EventT]):
    """Publish and settle the optional execution stream on one Hosted Session."""

    _legacy_turns = True

    if TYPE_CHECKING:
        def start_execution(self, request: ExecutionRequestV1) -> None: ...

    def __init__(
        self,
        binding: _HostedBinding[SnapshotT, EventT],
        *,
        execution_submission: bool = False,
    ) -> None:
        self._content: set[Callable[[ExecutionContentEventV1], None]] = set()
        self._draft = ""
        self._truncated = False
        self._closing = False
        self._execution_close_task: asyncio.Task[None] | None = None
        super().__init__(binding, execution_submission=execution_submission)

    def _start_execution_observation(self, source: _HostedBinding[SnapshotT, EventT]) -> None:
        self._projection = source.project_snapshot()
        self._guard = ExecutionGuardV1(source_cursor=self._complete_source)

    @property
    def execution_state(self) -> ExecutionStateV1 | None:
        return self._guard.state

    async def wait_execution(self, execution_id: str) -> ExecutionOutcomeV1:
        return await self._guard.wait(execution_id)

    def subscribe_execution_observation(
        self, listener: Callable[[ExecutionObservationV1], None]
    ) -> Callable[[], None]:
        self._require_open()
        return self._guard.subscribe_observation(listener)

    def interrupt_execution(self, execution_id: str, mode: InterruptModeV1) -> bool:
        if mode is not InterruptModeV1.WHOLE_EXECUTION:
            self._require_legacy_turns()
        self._require_open()
        return self._guard.interrupt(execution_id, mode)

    async def retry_execution_settlement(self, execution_id: str) -> None:
        await self._guard.retry_settlement(execution_id)

    async def start_turn(self, text: str) -> None:
        self._require_legacy_turns()
        execution_id = "legacy-" + uuid4().hex
        self.start_execution(ExecutionRequestV1(execution_id, text))
        outcome = await self.wait_execution(execution_id)
        if isinstance(outcome.legacy_result, AppFailureV1):
            raise AppServiceError(outcome.legacy_result.code)

    def steer_turn(self, text: str) -> None:
        self._require_legacy_turns()
        super().steer_turn(text)

    def follow_up_turn(self, text: str) -> None:
        self._require_legacy_turns()
        super().follow_up_turn(text)

    def interrupt_turn(self) -> bool:
        self._require_legacy_turns()
        self._require_open()
        state = self._guard.state
        return state is not None and self._guard.interrupt(
            state.execution_id, InterruptModeV1.LEGACY_TURN_ONLY
        )

    def _require_legacy_turns(self) -> None:
        if not self._legacy_turns:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    async def snapshot_execution(self) -> ExecutionSourceSnapshotV1:
        self._require_open()
        projection, observation = self._projection, self._guard.observation
        return ExecutionSourceSnapshotV1(
            source=SessionSnapshotV1(
                identity=self.identity,
                title=projection.title,
                cursor=self._cursor,
                revision=projection.revision,
                running=observation.status is ExecutionStatusV1.RUNNING,
                records=projection.records,
                user_choice=projection.user_choice,
            ),
            observation=observation,
            draft=self._draft
            if observation.status is ExecutionStatusV1.RUNNING
            else "",
            truncated=self._truncated or projection.truncated,
        )

    def subscribe_execution_content(
        self, listener: Callable[[ExecutionContentEventV1], None]
    ) -> Callable[[], None]:
        self._require_open()
        if not callable(listener):
            raise TypeError("execution content listener must be callable")
        self._content.add(listener)
        return lambda: self._content.discard(listener)

    def _observe_projection(
        self, projection: EventT, event: SessionEventV1
    ) -> None:
        self._projection = self._binding.project_snapshot()
        if event.kind is SessionEventKindV1.ASSISTANT_DELTA:
            text = self._draft + (event.text or "")
            self._truncated |= len(text) > 16_384 or projection.truncated
            self._draft = text[:16_384]
        elif event.kind in {
            SessionEventKindV1.ASSISTANT_MESSAGE,
            SessionEventKindV1.TURN_STARTED,
            SessionEventKindV1.TURN_COMPLETED,
            SessionEventKindV1.TURN_INTERRUPTED,
        }:
            self._draft = ""
            self._truncated = False
        observation = self._guard.observation
        envelope = ExecutionContentEventV1(
            event,
            observation.execution_id
            if observation.status is ExecutionStatusV1.RUNNING
            else None,
        )
        for listener in tuple(self._content):
            try:
                listener(envelope)
            except Exception:
                self._content.discard(listener)

    def _complete_source(self) -> int:
        self._projection = self._binding.project_snapshot()
        self._draft = ""
        self._truncated = False
        return self._cursor

    async def close(self) -> None:
        self._closing = True
        task = self._execution_close_task
        if task is None or _task_failed_or_cancelled(task):
            task = asyncio.create_task(self._close_execution())
            task.add_done_callback(_observe_task_result)
            self._execution_close_task = task
        await asyncio.shield(task)

    async def _close_execution(self) -> None:
        state = self._guard.state
        if state is not None and not state.status.terminal:
            self._guard.interrupt(state.execution_id, InterruptModeV1.WHOLE_EXECUTION)
            await self._guard.retry_settlement(state.execution_id)
        await self._dispose_execution_resources()
        await super().close()
        self._content.clear()
        self._release_execution_resources()

    async def _dispose_execution_resources(self) -> None:
        """Close Product work after invocation settlement and before closing the Session."""

    def _release_execution_resources(self) -> None:
        """Drop retained Product work references after the Session closes successfully."""

    def _require_open(self) -> None:
        super()._require_open()
        if self._closing:
            raise RuntimeError(f"{self._product_id}_hosted_session_closed")


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


def project_session_models(
    current: str | None, details: Sequence[object], thinking: SessionThinkingV1 | None = None,
) -> SessionModelsV1:
    models: list[SessionModelChoiceV1] = []
    for choice in model_choice_data_from_details(details):
        reference = normalize_model_selection(choice.selection)
        if reference is None or not is_usable_model_selection(reference):
            continue
        models.append(SessionModelChoiceV1(
            id=choice.value,
            provider=reference.provider,
            endpoint_id=reference.endpoint_id,
            model_id=reference.model_id,
            label=choice.label,
            supports_thinking=bool(
                getattr(choice.selection, "supports_thinking", False)
                or getattr(choice.selection, "reasoning", False)
            ),
        ))
    visible = models[:256]
    active_choice = next((model for model in models[256:] if model.id == current), None)
    if active_choice is not None:
        visible[-1] = active_choice
    return SessionModelsV1(current, tuple(visible), thinking)


def _thinking_settings(control: object) -> SessionThinkingV1 | None:
    getter = getattr(control, 'get_available_thinking_levels', None)
    current = getattr(control, 'thinking_level', None)
    if not callable(getter):
        return None
    levels = tuple(getter())
    if not levels:
        return None
    return SessionThinkingV1(current if current in levels else None, levels)


class _HostedAgentExecutionWork:
    """Same-instance Agent observation and Session dispatch at the AppHost bridge."""

    session: AgentProductSession
    text: str
    _cancel_requested: Callable[[], bool]
    _interrupted: bool
    _agent_outcome: ExecutionOutcomeV1 | None
    _unsubscribe: Callable[[], None] | None
    _unbind_turn: Callable[[], None] | None

    def __init__(self, cancel_requested: Callable[[], bool]) -> None:
        self._cancel_requested = cancel_requested
        self._interrupted = False
        self._agent_outcome = None
        self._unsubscribe = None
        self._unbind_turn = None

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
        self._bind_agent_turn(control, self.session)
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
        self._bind_agent_turn(control, session)
        await session._run_published_resume_input(
            attempt_id=attempt_id,
            input_record_id=input_record_id,
        )
        return self._agent_outcome or ExecutionOutcomeV1(
            ExecutionStatusV1.FAILED, error_code="missing_agent_outcome"
        )

    def _bind_agent_turn(
        self, control: ExecutionControlV1, session: AgentProductSession
    ) -> None:
        self._unsubscribe = session.agent.subscribe(self._outcome_observer())
        self._unbind_turn = control.bind_turn_interrupt(
            lambda: session.abort() if session.is_streaming else False
        )

    async def _settle_session(
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

    def _agent_succeeded(self) -> bool:
        return (
            not self._cancel_requested()
            and self._agent_outcome is not None
            and self._agent_outcome.status is ExecutionStatusV1.SUCCEEDED
        )


class _HostedPromptExecutionWork(_HostedAgentExecutionWork):
    def __init__(
        self,
        session: AgentProductSession,
        text: str,
        cancel_requested: Callable[[], bool],
        *,
        start_title: Callable[[], None] | None = None,
        wait_for_title: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(cancel_requested)
        self.session = session
        self.text = text
        self._start_title = start_title
        self._wait_for_title = wait_for_title

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        try:
            if self._wait_for_title is not None:
                await self._wait_for_title()
            self._checkpoint()
            return await self._execute_hosted_prompt(control)
        except asyncio.CancelledError:
            self._interrupted = True
            self._abort_hosted_prompt()
            raise
        finally:
            self._clear_turn()

    async def settle(self) -> None:
        await self._settle_session(self.session)
        if self._start_title is not None and self._agent_succeeded():
            start_title, self._start_title = self._start_title, None
            start_title()


class _PublishedResumeInput(Protocol):
    @property
    def session(self) -> _ResumeContinuationSession[Any]: ...
    @property
    def attempt_id(self) -> str: ...
    @property
    def input_record_id(self) -> str: ...


class _HostedResumeInputExecutionWork(_HostedAgentExecutionWork):
    def __init__(
        self,
        cancel_requested: Callable[[], bool],
        *,
        activate: Callable[[], Awaitable[_PublishedResumeInput]],
        on_success: Callable[[], None],
    ) -> None:
        super().__init__(cancel_requested)
        self._activate = activate
        self._on_success = on_success
        self._session: _ResumeContinuationSession[Any] | None = None

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        if self._cancel_requested():
            return ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
        try:
            activated = await self._activate()
            self._session = activated.session
            return await self._execute_published_input(
                control, self._session, activated.attempt_id, activated.input_record_id
            )
        except asyncio.CancelledError:
            self._interrupted = True
            if self._session is not None:
                self._session.abort()
            raise
        finally:
            self._clear_turn()

    async def settle(self) -> None:
        await self._settle_session(self._session)
        if self._agent_succeeded():
            self._on_success()


def _assistant_outcome(message: AssistantMessage) -> ExecutionOutcomeV1:
    if message.stop_reason == "aborted":
        return ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
    if message.stop_reason == "error":
        return ExecutionOutcomeV1(
            ExecutionStatusV1.FAILED, error_code="assistant_response_error"
        )
    return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)


class _DeferredSessionControl(Generic[_HostedBindingT]):
    """Keep one control identity across deferred subscription and activation."""

    def __init__(
        self,
        *,
        closed_message: str,
        invalid_activation: Callable[[], Exception],
    ) -> None:
        self._delegate: SessionControlPort | None = None
        self._listeners: set[Callable[[RuntimeEvent[object]], object]] = set()
        self._unsubscribe: Callable[[], None] | None = None
        self._closed = False
        self._closed_message = closed_message
        self._invalid_activation = invalid_activation
        self._resume_handoff_failed = False
        self._resume_handoff_cleanup: SessionConstructionCleanup | None = None
        self.resume_binding: _HostedBindingT | None = None

    @property
    def resume_handoff_failed(self) -> bool:
        return self._resume_handoff_failed

    async def complete_resume_handoff(
        self,
        session: AgentProductSession,
        *,
        close_history: Callable[[], Awaitable[None]],
        bind: Callable[[], _HostedBindingT],
        committed_input_event: RuntimeEvent[object],
    ) -> None:
        """Deliver one prepared Session through the original deferred control."""
        try:
            await close_history()
            binding = bind()
            self.activate(cast(SessionControlPort, binding.control))
        except BaseException as error:
            self._resume_handoff_failed = True
            self._resume_handoff_cleanup = SessionConstructionCleanup(session)
            try:
                await self.settle_resume_handoff()
            except BaseException as cleanup_error:
                with suppress(BaseException):
                    BaseException.add_note(
                        error, f"Hosted Resume Session cleanup also failed: {cleanup_error!r}"
                    )
            raise
        self.resume_binding = binding
        # The live binding owns the Session before readers observe the input.
        await self.emit(committed_input_event)

    async def settle_resume_handoff(self) -> None:
        cleanup = self._resume_handoff_cleanup
        if cleanup is not None:
            await cleanup.retry_cleanup()
            self._resume_handoff_cleanup = None

    @property
    def session_id(self) -> str:
        raise NotImplementedError

    @property
    def session_name(self) -> str | None:
        return None if self._delegate is None else self._delegate.session_name

    async def set_session_name(self, name: str | None) -> None:
        await self._require_active().set_session_name(name)

    def subscribe_runtime_events(
        self,
        listener: Callable[[RuntimeEvent[object]], object],
    ) -> Callable[[], None]:
        if self._closed or not callable(listener):
            raise RuntimeError(self._closed_message)
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
            raise self._invalid_activation()
        if control.session_id != self.session_id:
            raise self._invalid_activation()

        async def relay(event: RuntimeEvent[object]) -> None:
            await self.emit(event)

        unsubscribe = control.subscribe_runtime_events(relay)
        if not callable(unsubscribe):
            raise self._invalid_activation()
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
            raise RuntimeError(self._closed_message)
        if self._delegate is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return self._delegate


# Presentation aliases are independent of the existing approval broker authority.
class _HostedApprovalPresentation:
    _interactions: dict[str, str]
    _approval_action: ClassVar[str]
    _approval_limit: ClassVar[Callable[[], int]]
    _approval_text_limit: ClassVar[Callable[[], int]]
    _approval_id: ClassVar[Callable[[], str]]
    _approval_publish_rollback: ClassVar[bool]

    def _approval_dispatcher(self) -> Callable[[RuntimeEvent[object]], Awaitable[None]]:
        raise NotImplementedError

    async def _present_approval(self, request: dict[str, object]) -> None:
        action_id = request.get("action_id")
        if (
            not isinstance(action_id, str)
            or len(self._interactions) >= type(self)._approval_limit()
        ):
            raise RuntimeError("hosted_approval_unavailable")
        text = "\n".join(
            (
                str(request.get("action", self._approval_action)),
                str(request.get("risk", "")),
                json.dumps(
                    request.get("arguments", {}), ensure_ascii=False, sort_keys=True
                ),
            )
        )
        if len(text) > type(self)._approval_text_limit():
            raise RuntimeError("hosted_approval_too_large")
        interaction_id = type(self)._approval_id()
        self._interactions[interaction_id] = action_id
        if self._approval_publish_rollback:
            try:
                await self._publish_approval(interaction_id, text)
            except BaseException:
                self._interactions.pop(interaction_id, None)
                raise
        else:
            await self._publish_approval(interaction_id, text)

    async def _publish_approval(self, interaction_id: str, text: str) -> None:
        # Resolve the real dispatcher only after inserting the original alias.
        await self._approval_dispatcher()(
            cast(
                RuntimeEvent[object],
                {
                    "type": "tool_approval_requested",
                    "hosted_presentation": True,
                    "interaction_id": interaction_id,
                    "text": text,
                },
            )
        )

    async def _dismiss_approval(self, action_id: str) -> None:
        for interaction_id, pending in tuple(self._interactions.items()):
            if pending == action_id:
                self._interactions.pop(interaction_id, None)
                await self._approval_dispatcher()(
                    cast(
                        RuntimeEvent[object],
                        {
                            "type": "tool_approval_resolved",
                            "hosted_presentation": True,
                            "interaction_id": interaction_id,
                        },
                    )
                )
