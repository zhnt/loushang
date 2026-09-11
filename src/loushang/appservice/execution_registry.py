"""Instance-local execution ownership, independent of communication Tasks.

The permanent submission ledger retains only bounded records and digests. Active
work has separate capacity; terminal legacy records use an evictable cache.
Only Product settlement releases an active slot. No transport lives here.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from hashlib import sha256
from secrets import token_hex

from loushang.appserver.execution.model import (
    ExecutionErrorCodeV1 as ExecutionErrorCodeV1,
)
from loushang.appserver.execution.model import (
    ExecutionRecordV1 as ExecutionRecordV1,
)
from loushang.appserver.execution.model import (
    ExecutionServiceErrorV1 as ExecutionServiceErrorV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppServiceError,
    SessionIdentityV1,
)

from .execution_contract import (
    ExecutionBindingViewV1,
    ExecutionObservationV1,
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionStateV1,
    ExecutionStatusV1,
    ExecutionUpdateV1,
    InterruptModeV1,
    _identifier,
)
from .execution_notifications import observe_execution_task as _observe
from .execution_ports import HostedExecutionPortV1

# Covers the maximum bounded identifiers, outcome and both indexes throughout
# the record's lifetime. Active request text is separately bounded by the port
# contract (262144 codepoints) and the active invocation count.
RECORD_RESERVATION_BYTES = 8192


@dataclass(frozen=True, slots=True)
class ExecutionLimitsV1:
    active: int = 32
    submissions: int = 1024
    ledger_bytes: int = 8_388_608
    recent_legacy: int = 128
    legacy_retention_seconds: float = 300

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.active, 64), (self.submissions, 65536),
            (self.ledger_bytes, 536_870_912), (self.recent_legacy, 1024),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid execution capacity")
        if type(self.legacy_retention_seconds) not in (int, float) or not (
            0 < self.legacy_retention_seconds <= 3600
        ):
            raise ValueError("invalid legacy execution retention")


@dataclass(eq=False, slots=True)
class _Invocation:
    record: ExecutionRecordV1
    binding: ExecutionBindingV1
    task: asyncio.Task[ExecutionOutcomeV1] | None = None
    started: bool = False
    observation: ExecutionObservationV1 | None = None


@dataclass(eq=False, slots=True)
class ExecutionBindingV1:
    port: HostedExecutionPortV1
    view: ExecutionBindingViewV1
    active: _Invocation | None = None
    closing: bool = False
    unsubscribe: Callable[[], None] = lambda: None
    listeners: set[Callable[[ExecutionUpdateV1], None]] = field(default_factory=set)

    def subscribe(self, listener: Callable[[ExecutionUpdateV1], None]) -> Callable[[], None]:
        if self.closing or len(self.listeners) >= 8:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)


def _canonical(identity: SessionIdentityV1) -> tuple[str, str, str]:
    return identity.product_id, identity.continuity_id, identity.session_id


class ExecutionRegistryV1:
    def __init__(
        self, *, application_id: str, service_instance_id: str,
        limits: ExecutionLimitsV1 = ExecutionLimitsV1(),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        _identifier(application_id)
        _identifier(service_instance_id)
        if type(limits) is not ExecutionLimitsV1:
            raise TypeError("invalid execution limits")
        self.application_id, self.service_instance_id = application_id, service_instance_id
        self.limits, self._clock = limits, clock
        self._ledger: dict[tuple[tuple[str, str, str], str], tuple[str, str]] = {}
        self._records: dict[str, ExecutionRecordV1] = {}
        self._active: dict[tuple[str, str, str], _Invocation] = {}
        self._legacy: OrderedDict[str, float] = OrderedDict()
        self._sequence = 0
        self._nonce = token_hex(12)
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def reserved_ledger_bytes(self) -> int:
        return len(self._ledger) * RECORD_RESERVATION_BYTES

    def require_instance(self, expected: str) -> None:
        _identifier(expected)
        if expected != self.service_instance_id:
            raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.INSTANCE_CHANGED)

    def bind(self, port: HostedExecutionPortV1) -> ExecutionBindingV1:
        for name in ("wait_execution", "retry_execution_settlement", "snapshot_execution"):
            if not inspect.iscoroutinefunction(getattr(port, name, None)):
                raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.UNSUPPORTED)
        for name in ("start_execution", "interrupt_execution", "subscribe_execution_content",
                     "subscribe_execution_observation"):
            callback = getattr(port, name, None)
            if not callable(callback) or inspect.iscoroutinefunction(callback):
                raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.UNSUPPORTED)
        binding = ExecutionBindingV1(
            port, ExecutionBindingViewV1(object(), port.identity, 0, ExecutionObservationV1())
        )
        binding.unsubscribe = port.subscribe_execution_observation(
            lambda observation: self._on_observation(binding, observation)
        )
        if not callable(binding.unsubscribe):
            raise TypeError("invalid execution observation subscription")
        return binding

    def submit(
        self, binding: ExecutionBindingV1, text: str, submission_id: str | None,
    ) -> ExecutionRecordV1:
        """Caller validates current authority immediately before this no-await cut.

        No Product method is called between deduplication and publication. Task
        construction failure rolls everything back before any execution effect.
        """
        if self._closed or binding.closing:
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
        ExecutionRequestV1("validation", text)
        identity = binding.view.identity
        key = _canonical(identity)
        digest = sha256(text.encode("utf-8")).hexdigest()
        if submission_id is not None:
            _identifier(submission_id)
            prior = self._ledger.get((key, submission_id))
            if prior is not None:
                if prior[0] != digest:
                    raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.SUBMISSION_CONFLICT)
                return self._records[prior[1]]
        if key in self._active or len(self._active) >= self.limits.active:
            raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.BUSY)
        if submission_id is not None and (
            len(self._ledger) >= self.limits.submissions
            or self.reserved_ledger_bytes + RECORD_RESERVATION_BYTES > self.limits.ledger_bytes
        ):
            raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.LEDGER_FULL)
        self._sequence += 1
        execution_id = f"exec-{self._nonce}-{self._sequence}"
        record = ExecutionRecordV1(
            self.service_instance_id, identity, submission_id,
            ExecutionStateV1(execution_id, ExecutionStatusV1.ACCEPTED, 1),
        )
        invocation = _Invocation(record, binding)
        published = asyncio.get_running_loop().create_future()

        async def invoke() -> ExecutionOutcomeV1:
            await published
            return await self._drive(invocation, text)

        operation = invoke()
        try:
            invocation.task = asyncio.create_task(operation)
        except BaseException:
            operation.close()
            raise
        invocation.task.add_done_callback(_observe)
        self._records[execution_id] = record
        self._active[key] = binding.active = invocation
        if submission_id is not None:
            self._ledger[key, submission_id] = digest, execution_id
        self._publish(invocation, record.state)
        published.set_result(None)
        return invocation.record

    def get(self, identity: SessionIdentityV1, execution_id: str) -> ExecutionRecordV1:
        _identifier(execution_id)
        self._expire_legacy()
        record = self._records.get(execution_id)
        if record is None or _canonical(record.identity) != _canonical(identity):
            raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.NOT_RETAINED)
        return record

    def find(self, identity: SessionIdentityV1, submission_id: str) -> ExecutionRecordV1 | None:
        _identifier(submission_id)
        prior = self._ledger.get((_canonical(identity), submission_id))
        return None if prior is None else self._records[prior[1]]

    def interrupt(self, binding: ExecutionBindingV1, execution_id: str) -> ExecutionRecordV1:
        record = self.get(binding.view.identity, execution_id)
        if record.state.status.terminal:
            return record
        invocation = binding.active
        if invocation is None or invocation.record.state.execution_id != execution_id:
            raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.NOT_RETAINED)
        if not record.state.interrupt_requested:
            if invocation.started:
                binding.port.interrupt_execution(execution_id, InterruptModeV1.WHOLE_EXECUTION)
            self._publish(invocation, replace(
                record.state, revision=record.state.revision + 1, interrupt_requested=True
            ))
        return invocation.record

    async def wait(self, binding: ExecutionBindingV1, record: ExecutionRecordV1) -> ExecutionOutcomeV1:
        invocation = binding.active
        if record.state.outcome is not None:
            return record.state.outcome
        if invocation is None or invocation.record.state.execution_id != record.state.execution_id:
            retained = self.get(record.identity, record.state.execution_id)
            assert retained.state.outcome is not None
            return retained.state.outcome
        task = invocation.task
        assert task is not None
        return await asyncio.shield(task)

    async def start_legacy(self, binding: ExecutionBindingV1, text: str) -> None:
        try:
            record = self.submit(binding, text, None)
        except ExecutionServiceErrorV1:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
        outcome = await self.wait(binding, record)
        if isinstance(outcome.legacy_result, AppFailureV1):
            raise AppServiceError(outcome.legacy_result.code)

    async def close_binding(self, binding: ExecutionBindingV1) -> None:
        binding.closing = True
        invocation = binding.active
        if invocation is not None:
            self.interrupt(binding, invocation.record.state.execution_id)
            task = invocation.task
            assert task is not None
            if task.done():
                # A failed waiter is cleanup debt, never permission to start B.
                operation = self._retry(invocation)
                try:
                    task = asyncio.create_task(operation)
                except BaseException:
                    operation.close()
                    raise
                invocation.task = task
                task.add_done_callback(_observe)
            await asyncio.shield(task)
        binding.unsubscribe()
        binding.unsubscribe = lambda: None
        binding.listeners.clear()

    def fence(self) -> None:
        self._closed = True

    async def _drive(self, invocation: _Invocation, text: str) -> ExecutionOutcomeV1:
        state, port = invocation.record.state, invocation.binding.port
        if state.interrupt_requested:
            return self._finish(invocation, ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED))
        try:
            port.start_execution(ExecutionRequestV1(state.execution_id, text))
        except Exception:
            return self._finish(invocation, ExecutionOutcomeV1(
                ExecutionStatusV1.FAILED, "execution_start_failed",
                AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE),
            ))
        invocation.started = True
        return self._finish(invocation, await port.wait_execution(state.execution_id))

    async def _retry(self, invocation: _Invocation) -> ExecutionOutcomeV1:
        if not invocation.started:
            return self._finish(invocation, ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED))
        port, execution_id = invocation.binding.port, invocation.record.state.execution_id
        await port.retry_execution_settlement(execution_id)
        return self._finish(invocation, await port.wait_execution(execution_id))

    def _on_observation(self, binding: ExecutionBindingV1, value: ExecutionObservationV1) -> None:
        invocation = binding.active
        if type(value) is not ExecutionObservationV1 or invocation is None or (
            value.execution_id != invocation.record.state.execution_id
        ):
            raise ValueError("unexpected Product execution observation")
        if value.status is ExecutionStatusV1.RUNNING:
            state = invocation.record.state
            if state.status is not ExecutionStatusV1.ACCEPTED:
                raise ValueError("duplicate Product execution entry")
            self._publish(invocation, replace(
                state, status=ExecutionStatusV1.RUNNING, revision=state.revision + 1
            ))
        elif invocation.record.state.status is not ExecutionStatusV1.RUNNING:
            raise ValueError("Product completed without execution entry")
        invocation.observation = value

    def _finish(self, invocation: _Invocation, outcome: ExecutionOutcomeV1) -> ExecutionOutcomeV1:
        if type(outcome) is not ExecutionOutcomeV1:
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        state, binding = invocation.record.state, invocation.binding
        observation = invocation.observation
        if invocation.started and observation is None and outcome.status is not (
            ExecutionStatusV1.INTERRUPTED
        ):
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        if state.status is ExecutionStatusV1.RUNNING:
            if observation is None or observation.status is not outcome.status:
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
            binding.view = replace(binding.view, quiescent=observation)
        state = replace(state, status=outcome.status, revision=state.revision + 1, outcome=outcome)
        self._publish(invocation, state)
        self._active.pop(_canonical(invocation.record.identity))
        binding.active = None
        if invocation.record.submission_id is None:
            self._legacy[state.execution_id] = self._clock() + self.limits.legacy_retention_seconds
            self._expire_legacy()
        return outcome

    def _publish(self, invocation: _Invocation, state: ExecutionStateV1) -> None:
        invocation.record = replace(invocation.record, state=state)
        self._records[state.execution_id] = invocation.record
        binding, prior = invocation.binding, invocation.binding.view
        binding.view = replace(
            prior, revision=prior.revision + 1,
            active=None if state.status.terminal else state,
            latest_terminal=state if state.status.terminal else prior.latest_terminal,
        )
        event = ExecutionUpdateV1(binding.view.revision, state)
        for listener in tuple(binding.listeners):
            try:
                listener(event)
            except (Exception, asyncio.CancelledError):
                binding.listeners.discard(listener)

    def _expire_legacy(self) -> None:
        now = self._clock()
        while self._legacy:
            execution_id, expires = next(iter(self._legacy.items()))
            if len(self._legacy) <= self.limits.recent_legacy and expires > now:
                break
            self._legacy.pop(execution_id)
            self._records.pop(execution_id, None)
