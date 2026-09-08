from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace

import pytest

from loushang.appserver.protocol import (
    SessionEventKindV1,
    SessionEventV1,
    SessionSnapshotV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.appservice.execution_contract import (
    ExecutionBindingViewV1,
    ExecutionContentEventV1,
    ExecutionObservationV1,
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionSourceSnapshotV1,
    ExecutionUpdateV1,
    InterruptModeV1,
)
from loushang.appservice.execution_contract import (
    ExecutionStatusV1 as Status,
)
from loushang.appservice.execution_guard import ExecutionControlV1, ExecutionGuardV1
from loushang.appservice.execution_ports import HostedExecutionPortV1
from loushang.appservice.execution_snapshot import (
    ExecutionSnapshotBufferV1,
    capture_execution_snapshot,
)

from .test_execution_guard import scenario
from .test_execution_snapshot import IDENTITY


class FakeProduct:
    """A real asynchronous fake port; production guard and barrier are not mocked."""

    identity = IDENTITY

    def __init__(self, *, model: bool) -> None:
        self.model = model
        self.cursor = 0
        self.guard = ExecutionGuardV1(source_cursor=lambda: self.cursor)
        self.draft = ""
        self.records: tuple[TranscriptRecordV1, ...] = ()
        self.entered, self.release, self.cleaning, self.quiesce = (
            asyncio.Event() for _ in range(4)
        )
        self.quiesce.set()
        self.listeners: list[Callable[[ExecutionContentEventV1], None]] = []
        self.turn_interrupted = False
        self.input = ""

    def start_execution(self, request: ExecutionRequestV1) -> None:
        # No Product effects in this synchronous call before guard ownership.
        self.guard.start(request, self)
        self.input = request.text

    async def wait_execution(self, execution_id: str) -> ExecutionOutcomeV1:
        return await self.guard.wait(execution_id)

    def interrupt_execution(self, execution_id: str, mode: InterruptModeV1) -> bool:
        return self.guard.interrupt(execution_id, mode)

    async def retry_execution_settlement(self, execution_id: str) -> None:
        await self.guard.retry_settlement(execution_id)

    def subscribe_execution_content(
        self, listener: Callable[[ExecutionContentEventV1], None]
    ) -> Callable[[], None]:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    async def snapshot_execution(self) -> ExecutionSourceSnapshotV1:
        # All fields captured synchronously, no yield between content and source fact.
        return ExecutionSourceSnapshotV1(
            SessionSnapshotV1(
                self.identity,
                "Model Product" if self.model else "Command Product",
                self.cursor,
                self.cursor,
                bool(self.model and self.draft),
                self.records,
            ),
            self.guard.observation,
            self.draft,
        )

    def emit(self, kind: SessionEventKindV1, text: str) -> None:
        self.cursor += 1
        event = ExecutionContentEventV1(
            SessionEventV1(self.identity.session_id, self.cursor, kind, text),
            self.guard.observation.execution_id,
        )
        for listener in tuple(self.listeners):
            listener(event)

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        if self.model:

            def abort_turn() -> bool:
                self.turn_interrupted = True
                self.release.set()
                return True

            control.bind_turn_interrupt(abort_turn)
            self.draft = "partial"
            self.emit(SessionEventKindV1.ASSISTANT_DELTA, self.draft)
        self.entered.set()
        await self.release.wait()
        return ExecutionOutcomeV1(
            Status.INTERRUPTED if self.turn_interrupted else Status.SUCCEEDED
        )

    async def settle(self) -> None:
        self.cleaning.set()
        await self.quiesce.wait()
        self.records = (
            TranscriptRecordV1(
                TranscriptRecordKindV1.ASSISTANT, "settled " + self.input
            ),
        )
        self.draft = ""
        self.emit(SessionEventKindV1.ASSISTANT_MESSAGE, self.records[0].text)


class ApplicationProjection:
    """Minimal test registry observer; no production deduplication claim."""

    def __init__(
        self, product: FakeProduct, view: ExecutionBindingViewV1 | None = None
    ) -> None:
        self.product = product
        self.view = view or ExecutionBindingViewV1(
            object(), product.identity, 0, ExecutionObservationV1()
        )
        self.mailbox = ExecutionSnapshotBufferV1(self.view.binding, product.identity)
        self.unsubscribe = product.subscribe_execution_content(self.mailbox.push)

    def consume_state(self) -> None:
        state = self.product.guard.state
        assert state is not None
        revision = self.view.revision + 1
        self.view = replace(
            self.view,
            revision=revision,
            active=None if state.status.terminal else state,
            latest_terminal=state
            if state.status.terminal
            else self.view.latest_terminal,
            quiescent=self.product.guard.observation
            if state.status.terminal
            else self.view.quiescent,
        )
        self.mailbox.push(ExecutionUpdateV1(revision, state))

    async def capture(self):
        return await capture_execution_snapshot(
            self.product, lambda: self.view, self.mailbox
        )


@pytest.mark.parametrize("model", [False, True])
def test_optional_port_complete_lifecycle_and_composite_projection(model: bool) -> None:
    async def run() -> None:
        product = FakeProduct(model=model)
        port: HostedExecutionPortV1 = product
        projection = ApplicationProjection(product)
        port.start_execution(ExecutionRequestV1("A", "input"))
        projection.consume_state()
        accepted = await projection.capture()
        assert accepted.executions.active.status is Status.ACCEPTED
        assert accepted.source.observation == ExecutionObservationV1()
        await product.entered.wait()
        projection.consume_state()
        events = projection.mailbox.read()
        assert any(
            isinstance(event, ExecutionUpdateV1)
            and event.execution.status is Status.RUNNING
            for event in events
        )
        if model:
            assert (
                next(
                    event
                    for event in events
                    if isinstance(event, ExecutionContentEventV1)
                ).execution_id
                == "A"
            )
        else:
            assert product.guard.observation.status is Status.RUNNING
            assert not (await port.snapshot_execution()).source.running
        product.release.set()
        outcome = await port.wait_execution("A")
        assert outcome.status is Status.SUCCEEDED
        projection.consume_state()
        tail = projection.mailbox.read()
        assert isinstance(tail[-1], ExecutionUpdateV1)
        assert tail[-1].execution.outcome == outcome
        projection.unsubscribe()
        reattached = ApplicationProjection(product, projection.view)
        snapshot = await reattached.capture()
        assert snapshot.source.draft == ""
        assert snapshot.source.source.records[0].text == "settled input"
        assert snapshot.executions.latest_terminal.outcome == outcome
        reattached.unsubscribe()

    asyncio.run(asyncio.wait_for(run(), 3))


@scenario
async def test_interrupted_port_remains_running_in_composite_until_cleanup_finishes() -> (
    None
):
    product = FakeProduct(model=False)
    port: HostedExecutionPortV1 = product
    projection = ApplicationProjection(product)
    product.quiesce.clear()
    port.start_execution(ExecutionRequestV1("A", "preflight"))
    await product.entered.wait()
    assert port.interrupt_execution("A", InterruptModeV1.LEGACY_TURN_ONLY) is False
    assert port.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
    await product.cleaning.wait()
    projection.consume_state()
    snapshot = await projection.capture()
    assert snapshot.executions.active.status is Status.RUNNING
    assert snapshot.executions.active.interrupt_requested
    assert snapshot.source.observation.status is Status.RUNNING
    product.quiesce.set()
    assert (await port.wait_execution("A")).status is Status.INTERRUPTED
    projection.consume_state()
    assert projection.mailbox.read()[-1].execution.status is Status.INTERRUPTED
    projection.unsubscribe()
