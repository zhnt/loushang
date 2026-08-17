"""Session-turn binding over the canonical :mod:`loushang.harnesswork` runtime."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from loushang.harnesswork.event_log import EventLogBackend
from loushang.harnesswork.ports import WorkExecutionBinding, WorkExecutionContext
from loushang.harnesswork.runtime import WorkRuntime
from loushang.harnesswork.types import (
    WorkCancellationOutcome,
    WorkEventFact,
    WorkOperation,
    WorkRun,
    WorkRunSpec,
    WorkStepSpec,
)

RuntimeEventListener = Callable[[object], Awaitable[None] | None]
SessionEventFactProjector = Callable[[object], Sequence[WorkEventFact]]
SessionIdReader = Callable[[], str]


class SessionPromptPort(Protocol):
    """Session operations required by the reusable Work binding.

    ``prompt`` returns after the submitted turn has settled. ``wait_for_idle``
    exists for independently initiated cancellation settlement, not as a
    second step after an ordinary prompt.
    """

    def subscribe_runtime_events(
        self,
        listener: RuntimeEventListener,
    ) -> Callable[[], None]: ...

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[object] | None = None,
        streaming_behavior: str | None = None,
        source: str | None = None,
    ) -> Awaitable[None]: ...

    def abort(self) -> object: ...

    def wait_for_idle(self) -> Awaitable[None]: ...


class PreparedSessionWorkTurn(Protocol):
    """Domain turn fields projected into a shared session Work turn."""

    prepared_prompt: str
    method_id: str | None
    plan_id: str | None
    step_id: str | None
    step_index: int | None
    step_title: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SessionWorkProfile:
    """Product vocabulary injected into the shared session Work binding."""

    domain: str
    operation_kind: str
    source_type: str = "work_shell"
    fallback_source: str = "channel"

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("session Work profile domain must not be empty")
        if not self.operation_kind.strip():
            raise ValueError("session Work operation kind must not be empty")
        if not self.source_type.strip():
            raise ValueError("session Work source type must not be empty")
        if not self.fallback_source.strip():
            raise ValueError("session Work fallback source must not be empty")


@dataclass(frozen=True, slots=True)
class SessionWorkTurn:
    """One Product-neutral Agent session turn prepared for Work execution."""

    text: str
    images: Sequence[object] | None = None
    method_id: str | None = None
    plan_id: str | None = None
    step_id: str | None = None
    step_index: int | None = None
    step_title: str | None = None
    planned_constraint: Mapping[str, object] | None = None
    audit_policy: Mapping[str, object] | None = None
    plan_facts: Mapping[str, object] | None = None
    step_facts: Mapping[str, object] | None = None
    streaming_behavior: str | None = None
    source: str | None = None
    follow_up_messages: tuple[str, ...] = ()

    def to_operation(
        self,
        *,
        profile: SessionWorkProfile,
        session_id: str,
        operation_id: str,
    ) -> WorkOperation:
        payload: dict[str, object] = {"text": self.text}
        if self.images is not None:
            payload["image_count"] = len(self.images)
        if self.method_id is not None:
            payload["method_id"] = self.method_id
        if self.plan_id is not None:
            payload["plan_id"] = self.plan_id
        if self.step_id is not None:
            payload["step_id"] = self.step_id
        if self.step_index is not None:
            payload["step_index"] = self.step_index
        if self.step_title is not None:
            payload["step_title"] = self.step_title
        if self.planned_constraint:
            payload["planned_constraint"] = dict(self.planned_constraint)
        if self.audit_policy:
            payload["audit_policy"] = dict(self.audit_policy)
        if self.plan_facts:
            payload["plan_facts"] = dict(self.plan_facts)
        if self.step_facts:
            payload["step_facts"] = dict(self.step_facts)
        if self.streaming_behavior is not None:
            payload["streaming_behavior"] = self.streaming_behavior
        if self.follow_up_messages:
            payload["follow_up_count"] = len(self.follow_up_messages)
        return WorkOperation(
            operation_id=operation_id,
            kind=profile.operation_kind,
            session_id=session_id,
            domain=profile.domain,
            payload=payload,
        )

    def to_run_spec(
        self,
        *,
        profile: SessionWorkProfile,
        run_id: str | None,
    ) -> WorkRunSpec:
        scope_payload: dict[str, object] = {"source_type": profile.source_type}
        if self.step_index is not None:
            scope_payload["step_index"] = self.step_index
        if self.step_title is not None:
            scope_payload["step_title"] = self.step_title
        if self.planned_constraint:
            scope_payload["planned_constraint"] = dict(self.planned_constraint)
        if self.audit_policy:
            scope_payload["audit_policy"] = dict(self.audit_policy)
        if self.plan_facts:
            scope_payload["plan_facts"] = dict(self.plan_facts)
        if self.step_facts:
            scope_payload["step_facts"] = dict(self.step_facts)
        return WorkRunSpec(
            run_id=run_id,
            method_id=self.method_id,
            plan_id=self.plan_id,
            step_id=self.step_id,
            run_event_payload={"source_type": profile.source_type},
            scope_event_payload=scope_payload,
        )

    def to_step_spec(self, *, profile: SessionWorkProfile) -> WorkStepSpec:
        if self.step_id is None:
            raise ValueError("a planned session turn requires step_id")
        return WorkStepSpec(
            step_id=self.step_id,
            payload=self.to_run_spec(
                profile=profile,
                run_id=None,
            ).scope_event_payload,
        )


SessionTurnHook = Callable[
    [SessionWorkTurn, int, int],
    Awaitable[None] | None,
]


@dataclass(frozen=True, slots=True)
class SessionTurnExecutor:
    """Execute prepared session turns and publish projected runtime facts."""

    session: SessionPromptPort
    profile: SessionWorkProfile
    project_event_facts: SessionEventFactProjector
    turn: SessionWorkTurn | None = None
    turns: tuple[SessionWorkTurn, ...] = ()
    before_turn: SessionTurnHook | None = None
    after_turn: SessionTurnHook | None = None

    async def execute(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> WorkCancellationOutcome:
        if (
            operation.kind != self.profile.operation_kind
            or operation.domain != self.profile.domain
        ):
            raise ValueError(
                "session Work executor cannot execute "
                f"{operation.domain}:{operation.kind}"
            )
        turn = self._resolve_turn(operation, context)

        async def listener(event: object) -> None:
            for fact in self.project_event_facts(event):
                context.publish(fact)

        unsubscribe = self.session.subscribe_runtime_events(listener)
        try:
            messages = (turn.text, *turn.follow_up_messages)
            for message_index, text in enumerate(messages):
                active_turn = turn if message_index == 0 else SessionWorkTurn(text=text)
                await _call_turn_hook(
                    self.before_turn,
                    active_turn,
                    message_index,
                    len(messages),
                )
                await _prompt_turn(self.session, active_turn)
                await _call_turn_hook(
                    self.after_turn,
                    active_turn,
                    message_index,
                    len(messages),
                )
        finally:
            unsubscribe()
        return WorkCancellationOutcome.settled()

    async def cancel_and_wait(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> WorkCancellationOutcome:
        del operation, context
        abort = getattr(self.session, "abort", None)
        if not callable(abort):
            return WorkCancellationOutcome.unsupported()
        result = abort()
        if inspect.isawaitable(result):
            await result
        wait_for_idle = getattr(self.session, "wait_for_idle", None)
        if callable(wait_for_idle):
            await wait_for_idle()
        return WorkCancellationOutcome.settled()

    def _resolve_turn(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> SessionWorkTurn:
        if self.turns:
            index = context.step_index
            if index is None or index < 0 or index >= len(self.turns):
                raise ValueError(
                    "session plan execution has no turn for the active step"
                )
            return self.turns[index]
        if self.turn is not None:
            return self.turn
        text = operation.payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"{self.profile.operation_kind} payload requires non-empty text"
            )
        streaming_behavior = operation.payload.get("streaming_behavior")
        if streaming_behavior is not None and (
            not isinstance(streaming_behavior, str) or not streaming_behavior
        ):
            raise ValueError("streaming_behavior must be a non-empty string when set")
        return SessionWorkTurn(
            text=text,
            streaming_behavior=streaming_behavior,
            source=self.profile.fallback_source,
        )


class _SessionExecutionResolver:
    def __init__(
        self,
        *,
        session: SessionPromptPort,
        profile: SessionWorkProfile,
        project_event_facts: SessionEventFactProjector,
    ) -> None:
        self._session = session
        self._profile = profile
        self._project_event_facts = project_event_facts
        self._prepared: dict[str, SessionTurnExecutor] = {}

    def prepare(self, operation_id: str, executor: SessionTurnExecutor) -> None:
        if operation_id in self._prepared:
            raise ValueError(
                f"session Work operation is already prepared: {operation_id}"
            )
        self._prepared[operation_id] = executor

    def discard(self, operation_id: str) -> None:
        self._prepared.pop(operation_id, None)

    def resolve(
        self,
        operation: WorkOperation,
        spec: WorkRunSpec,
    ) -> WorkExecutionBinding:
        del spec
        executor = self._prepared.pop(operation.operation_id, None)
        if executor is None:
            executor = SessionTurnExecutor(
                session=self._session,
                profile=self._profile,
                project_event_facts=self._project_event_facts,
            )
        return WorkExecutionBinding(executor=executor, cancellation=executor)


class SessionOperationInProgressError(RuntimeError):
    """Raised when one session attempts to own multiple active Work runs."""


class SessionWorkRuntime:
    """Session-scoped adapter over the canonical :class:`WorkRuntime`."""

    def __init__(
        self,
        *,
        session: SessionPromptPort,
        event_log: EventLogBackend,
        profile: SessionWorkProfile,
        project_event_facts: SessionEventFactProjector,
        session_id: SessionIdReader = lambda: "",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cancellation_timeout: float | None = 30.0,
    ) -> None:
        self.session = session
        self.event_log = event_log
        self.profile = profile
        self._session_id = session_id
        self._resolver = _SessionExecutionResolver(
            session=session,
            profile=profile,
            project_event_facts=project_event_facts,
        )
        self.work_runtime = WorkRuntime(
            resolver=self._resolver,
            event_log=event_log,
            clock=clock,
            cancellation_timeout=cancellation_timeout,
        )
        self._project_event_facts = project_event_facts

    async def accept_operation(
        self,
        operation: WorkOperation,
        *,
        spec: WorkRunSpec | None = None,
        executor: SessionTurnExecutor | None = None,
    ) -> WorkRun:
        if operation.session_id is None:
            operation = WorkOperation(
                operation_id=operation.operation_id,
                kind=operation.kind,
                session_id=self._session_id(),
                domain=operation.domain,
                payload=operation.payload,
                source=operation.source,
            )
        if self.work_runtime.active_runs():
            raise SessionOperationInProgressError(
                "the active session already has a Work operation"
            )
        if executor is not None:
            self._resolver.prepare(operation.operation_id, executor)
        try:
            return await self.work_runtime.accept(operation, spec=spec)
        finally:
            self._resolver.discard(operation.operation_id)

    async def submit_turn(
        self,
        turn: SessionWorkTurn,
        *,
        session_id: str,
        operation_id: str | None = None,
        run_id: str | None = None,
    ) -> WorkRun:
        operation = turn.to_operation(
            profile=self.profile,
            session_id=session_id,
            operation_id=operation_id or f"op-{uuid4().hex}",
        )
        executor = self._executor(turn=turn)
        accepted = await self.accept_operation(
            operation,
            spec=turn.to_run_spec(profile=self.profile, run_id=run_id),
            executor=executor,
        )
        return await self.work_runtime.wait(accepted.run_id)

    async def submit_plan(
        self,
        turns: Sequence[SessionWorkTurn],
        *,
        session_id: str,
        operation_id: str | None = None,
        run_id: str | None = None,
        before_turn: SessionTurnHook | None = None,
        after_turn: SessionTurnHook | None = None,
    ) -> WorkRun:
        resolved_turns = tuple(turns)
        if not resolved_turns:
            raise ValueError("a session plan requires at least one turn")
        first = resolved_turns[0]
        if first.plan_id is None:
            raise ValueError("a session plan requires plan_id")
        if any(turn.plan_id != first.plan_id for turn in resolved_turns):
            raise ValueError("all session plan turns must share plan_id")
        operation = first.to_operation(
            profile=self.profile,
            session_id=session_id,
            operation_id=operation_id or f"op-{uuid4().hex}",
        )
        operation = WorkOperation(
            operation_id=operation.operation_id,
            kind=operation.kind,
            session_id=operation.session_id,
            domain=operation.domain,
            payload={**operation.payload, "step_count": len(resolved_turns)},
            source=operation.source,
        )
        executor = self._executor(
            turns=resolved_turns,
            before_turn=before_turn,
            after_turn=after_turn,
        )
        first_spec = first.to_run_spec(profile=self.profile, run_id=run_id)
        spec = WorkRunSpec(
            run_id=run_id,
            method_id=first.method_id,
            plan_id=first.plan_id,
            run_event_payload=first_spec.run_event_payload,
            scope_event_payload=first_spec.scope_event_payload,
            steps=tuple(
                turn.to_step_spec(profile=self.profile) for turn in resolved_turns
            ),
        )
        accepted = await self.accept_operation(
            operation,
            spec=spec,
            executor=executor,
        )
        return await self.work_runtime.wait(accepted.run_id)

    async def dispose(self) -> None:
        await self.work_runtime.dispose()

    def _executor(
        self,
        *,
        turn: SessionWorkTurn | None = None,
        turns: tuple[SessionWorkTurn, ...] = (),
        before_turn: SessionTurnHook | None = None,
        after_turn: SessionTurnHook | None = None,
    ) -> SessionTurnExecutor:
        return SessionTurnExecutor(
            session=self.session,
            profile=self.profile,
            project_event_facts=self._project_event_facts,
            turn=turn,
            turns=turns,
            before_turn=before_turn,
            after_turn=after_turn,
        )


async def submit_session_turn(
    session: SessionPromptPort,
    turn: SessionWorkTurn,
    *,
    session_id: str = "",
    work_runtime: (SessionWorkRuntime | Callable[[], SessionWorkRuntime] | None) = None,
) -> WorkRun | None:
    """Submit directly to a session or record the turn through Work."""

    if work_runtime is None:
        await _prompt_turn(session, turn)
        return None
    resolved_runtime = work_runtime() if callable(work_runtime) else work_runtime
    return await resolved_runtime.submit_turn(turn, session_id=session_id)


class SessionWorkHostPort:
    """Bind generic host turn arguments to a session Work runtime."""

    def __init__(
        self,
        runtime: SessionWorkRuntime | Callable[[], SessionWorkRuntime],
    ) -> None:
        self._runtime_or_factory = runtime

    def _runtime(self) -> SessionWorkRuntime:
        runtime = self._runtime_or_factory
        return runtime() if callable(runtime) else runtime

    async def submit_turn(
        self,
        text: str,
        *,
        session_id: str,
        images: list[object] | None,
        include_work_metadata: bool,
        method_id: str | None,
        plan_id: str | None,
        step_id: str | None,
        step_index: int | None,
        step_title: str | None,
        planned_constraint: Mapping[str, object] | None,
        audit_policy: Mapping[str, object] | None,
        plan_facts: Mapping[str, object] | None,
        step_facts: Mapping[str, object] | None,
    ) -> None:
        await self._runtime().submit_turn(
            SessionWorkTurn(
                text=text,
                images=images,
                method_id=method_id if include_work_metadata else None,
                plan_id=plan_id if include_work_metadata else None,
                step_id=step_id if include_work_metadata else None,
                step_index=step_index if include_work_metadata else None,
                step_title=step_title if include_work_metadata else None,
                planned_constraint=(
                    planned_constraint if include_work_metadata else None
                ),
                audit_policy=audit_policy if include_work_metadata else None,
                plan_facts=plan_facts if include_work_metadata else None,
                step_facts=step_facts if include_work_metadata else None,
            ),
            session_id=session_id,
        )

    async def submit_plan(
        self,
        turns: Sequence[object],
        *,
        session_id: str,
        after_turn: Callable[[object, int, int], Awaitable[None]],
    ) -> None:
        await self._runtime().submit_plan(
            tuple(require_session_work_turn(turn) for turn in turns),
            session_id=session_id,
            after_turn=after_turn,
        )


def project_prepared_session_work_turns(
    prepared_turns: Sequence[PreparedSessionWorkTurn],
    *,
    images: Sequence[object] | None,
    follow_up_messages: tuple[str, ...],
) -> tuple[SessionWorkTurn, ...]:
    """Project prepared domain turns into the canonical session Work shape."""

    resolved_turns = tuple(prepared_turns)
    return tuple(
        SessionWorkTurn(
            text=turn.prepared_prompt,
            images=images if index == 0 else None,
            method_id=turn.method_id,
            plan_id=turn.plan_id,
            step_id=turn.step_id,
            step_index=turn.step_index,
            step_title=turn.step_title,
            planned_constraint=_prepared_turn_metadata(
                turn,
                "planned_constraint",
            ),
            audit_policy=_prepared_turn_metadata(turn, "audit_policy"),
            plan_facts=_prepared_turn_metadata(turn, "plan_facts"),
            step_facts=_prepared_turn_metadata(turn, "step_facts"),
            follow_up_messages=(
                follow_up_messages if index == len(resolved_turns) - 1 else ()
            ),
        )
        for index, turn in enumerate(resolved_turns)
    )


def require_session_work_turn(value: object) -> SessionWorkTurn:
    """Require the canonical turn shape at an untyped Product boundary."""

    if not isinstance(value, SessionWorkTurn):
        raise TypeError("planned execution requires SessionWorkTurn values")
    return value


def _prepared_turn_metadata(
    turn: PreparedSessionWorkTurn,
    key: str,
) -> Mapping[str, object] | None:
    value = turn.metadata.get(key)
    if isinstance(value, Mapping) and value:
        return dict(value)
    return None


async def _prompt_turn(
    session: SessionPromptPort,
    turn: SessionWorkTurn,
) -> None:
    if turn.streaming_behavior is not None or turn.source is not None:
        if turn.images is None:
            await session.prompt(
                turn.text,
                streaming_behavior=turn.streaming_behavior,
                source=turn.source,
            )
        else:
            await session.prompt(
                turn.text,
                images=turn.images,
                streaming_behavior=turn.streaming_behavior,
                source=turn.source,
            )
    elif turn.images is not None:
        await session.prompt(turn.text, images=turn.images)
    else:
        await session.prompt(turn.text)


async def _call_turn_hook(
    hook: SessionTurnHook | None,
    turn: SessionWorkTurn,
    turn_index: int,
    turn_count: int,
) -> None:
    if hook is None:
        return
    result = hook(turn, turn_index, turn_count)
    if inspect.isawaitable(result):
        await result


__all__ = [
    "PreparedSessionWorkTurn",
    "RuntimeEventListener",
    "SessionEventFactProjector",
    "SessionIdReader",
    "SessionOperationInProgressError",
    "SessionPromptPort",
    "SessionTurnExecutor",
    "SessionTurnHook",
    "SessionWorkHostPort",
    "SessionWorkProfile",
    "SessionWorkRuntime",
    "SessionWorkTurn",
    "project_prepared_session_work_turns",
    "require_session_work_turn",
    "submit_session_turn",
]
