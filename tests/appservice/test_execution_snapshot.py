from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionScopeV1,
    SessionSnapshotV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.appservice.execution_contract import (
    ExecutionBindingViewV1,
    ExecutionContentEventV1,
    ExecutionObservationV1,
    ExecutionOutcomeV1,
    ExecutionSourceSnapshotV1,
    ExecutionStateV1,
    ExecutionUpdateV1,
)
from loushang.appservice.execution_contract import (
    ExecutionStatusV1 as Status,
)
from loushang.appservice.execution_snapshot import (
    ExecutionSnapshotBufferV1,
    capture_execution_snapshot,
)

from .test_execution_guard import scenario

IDENTITY = SessionIdentityV1(
    "coding", "continuity", "session", SessionScopeV1.CWD, "a" * 64
)


def state(execution_id: str, status: Status) -> ExecutionStateV1:
    outcome = ExecutionOutcomeV1(status) if status.terminal else None
    return ExecutionStateV1(execution_id, status, 1, outcome=outcome)


def source(
    observation: ExecutionObservationV1 = ExecutionObservationV1(),
    *,
    cursor: int = 0,
    draft: str = "",
    truncated: bool = False,
) -> ExecutionSourceSnapshotV1:
    return ExecutionSourceSnapshotV1(
        SessionSnapshotV1(
            IDENTITY,
            "Product",
            cursor,
            cursor,
            observation.status is Status.RUNNING,
            (TranscriptRecordV1(TranscriptRecordKindV1.USER, "input"),),
        ),
        observation,
        draft,
        truncated,
    )


class Reader:
    def __init__(
        self, view: ExecutionBindingViewV1, snapshot: ExecutionSourceSnapshotV1
    ) -> None:
        self.view = view
        self.source = snapshot
        self.reads = 0
        self.captured = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.action = lambda: None

    def read_view(self) -> ExecutionBindingViewV1:
        return self.view

    async def snapshot_execution(self) -> ExecutionSourceSnapshotV1:
        value = self.source
        self.reads += 1
        self.captured.set()
        await self.release.wait()
        self.action()
        return value


def buffer(reader: Reader, capacity: int = 8) -> ExecutionSnapshotBufferV1:
    return ExecutionSnapshotBufferV1(reader.view.binding, IDENTITY, capacity=capacity)


@pytest.mark.parametrize("phase", [Status.ACCEPTED, Status.RUNNING])
def test_successive_executions_match_only_active_or_its_quiescent_baseline(
    phase: Status,
) -> None:
    async def run() -> None:
        completed_a = ExecutionObservationV1("A", Status.SUCCEEDED, 10)
        observation = (
            completed_a
            if phase is Status.ACCEPTED
            else ExecutionObservationV1("B", phase)
        )
        reader = Reader(
            ExecutionBindingViewV1(
                object(),
                IDENTITY,
                3,
                completed_a,
                state("B", phase),
                state("A", Status.SUCCEEDED),
            ),
            source(observation, cursor=10),
        )
        result = await capture_execution_snapshot(
            reader, reader.read_view, buffer(reader)
        )
        assert result.executions == reader.view
        assert reader.reads == 1

    asyncio.run(run())


@scenario
async def test_snapshot_retries_source_completion_before_registry_settlement() -> None:
    completed = ExecutionObservationV1("A", Status.SUCCEEDED, 4)
    reader = Reader(
        ExecutionBindingViewV1(
            object(), IDENTITY, 1, ExecutionObservationV1(), state("A", Status.RUNNING)
        ),
        source(completed, cursor=4),
    )

    def settle() -> None:
        reader.view = replace(
            reader.view,
            revision=2,
            active=None,
            quiescent=completed,
            latest_terminal=state("A", Status.SUCCEEDED),
        )

    reader.action = settle
    result = await capture_execution_snapshot(reader, reader.read_view, buffer(reader))
    assert result.executions.quiescent == completed
    assert reader.reads == 2


@scenario
async def test_service_only_cancellation_preserves_previous_source_completion() -> None:
    completed_a = ExecutionObservationV1("A", Status.SUCCEEDED, 8)
    reader = Reader(
        ExecutionBindingViewV1(
            object(),
            IDENTITY,
            5,
            completed_a,
            latest_terminal=state("B", Status.INTERRUPTED),
        ),
        source(completed_a, cursor=8),
    )
    result = await capture_execution_snapshot(reader, reader.read_view, buffer(reader))
    assert result.executions.latest_terminal.execution_id == "B"
    assert result.source.observation.execution_id == "A"


@scenario
async def test_reopen_ignores_historical_ledger_watermark_and_replaces_stream_domains() -> (
    None
):
    historical = {"A": state("A", Status.SUCCEEDED)}
    reader = Reader(
        ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
        source(),
    )
    result = await capture_execution_snapshot(reader, reader.read_view, buffer(reader))
    assert historical["A"].status is Status.SUCCEEDED
    assert result.source.source.cursor == result.executions.revision == 0
    assert result.executions.latest_terminal is None


@scenario
async def test_binding_replacement_during_capture_requires_new_attachment() -> None:
    reader = Reader(
        ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
        source(),
    )
    reader.action = lambda: setattr(
        reader, "view", replace(reader.view, binding=object())
    )
    with pytest.raises(AppServiceError) as error:
        await capture_execution_snapshot(reader, reader.read_view, buffer(reader))
    assert error.value.code is AppErrorCodeV1.STALE_ATTACHMENT
    assert reader.reads == 1


@scenario
async def test_bounded_content_recovery_and_two_stream_cut_do_not_duplicate_output() -> (
    None
):
    observation = ExecutionObservationV1("A", Status.RUNNING)
    reader = Reader(
        ExecutionBindingViewV1(
            object(), IDENTITY, 2, ExecutionObservationV1(), state("A", Status.RUNNING)
        ),
        source(observation, cursor=7, draft="visible suffix", truncated=True),
    )
    mailbox = buffer(reader)

    def content(cursor: int, text: str) -> ExecutionContentEventV1:
        return ExecutionContentEventV1(
            SessionEventV1(
                IDENTITY.session_id, cursor, SessionEventKindV1.ASSISTANT_DELTA, text
            ),
            "A",
        )

    covered = content(7, "already in snapshot")
    after = content(8, "new suffix")
    mailbox.push(covered)
    mailbox.push(ExecutionUpdateV1(2, state("A", Status.RUNNING)))
    reader.release.clear()
    capture = asyncio.create_task(
        capture_execution_snapshot(reader, reader.read_view, mailbox)
    )
    await reader.captured.wait()
    mailbox.push(after)
    reader.release.set()
    result = await capture
    assert result.source.draft == "visible suffix"
    assert result.source.truncated
    assert mailbox.read() == (after,)
    assert mailbox.read() == ()


@scenario
async def test_metadata_does_not_consume_product_cursor_and_duplicates_are_ignored() -> (
    None
):
    reader = Reader(
        ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
        source(cursor=10),
    )
    mailbox = buffer(reader)
    await capture_execution_snapshot(reader, reader.read_view, mailbox)
    update = ExecutionUpdateV1(1, state("A", Status.ACCEPTED))
    content = ExecutionContentEventV1(
        SessionEventV1(IDENTITY.session_id, 11, SessionEventKindV1.STATUS, "queued")
    )
    mailbox.push(update)
    mailbox.push(update)
    mailbox.push(content)
    mailbox.push(content)
    assert mailbox.read() == (update, content)


@pytest.mark.parametrize("metadata", [False, True])
def test_gap_in_either_stream_requires_snapshot(metadata: bool) -> None:
    async def run() -> None:
        reader = Reader(
            ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
            source(),
        )
        mailbox = buffer(reader)
        await capture_execution_snapshot(reader, reader.read_view, mailbox)
        event = (
            ExecutionUpdateV1(2, state("A", Status.ACCEPTED))
            if metadata
            else ExecutionContentEventV1(
                SessionEventV1(IDENTITY.session_id, 2, SessionEventKindV1.STATUS, "gap")
            )
        )
        mailbox.push(event)
        with pytest.raises(AppServiceError) as error:
            mailbox.read()
        assert error.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED

    asyncio.run(run())


@scenario
async def test_snapshot_has_bounded_retry_and_no_lock_held_across_source_read() -> None:
    reader = Reader(
        ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
        source(),
    )
    reader.action = lambda: setattr(
        reader, "view", replace(reader.view, revision=reader.view.revision + 1)
    )
    with pytest.raises(AppServiceError) as error:
        await capture_execution_snapshot(reader, reader.read_view, buffer(reader))
    assert error.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
    assert reader.reads == 3


@scenario
async def test_overflow_during_snapshot_fails_instead_of_claiming_a_complete_view() -> (
    None
):
    reader = Reader(
        ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
        source(),
    )
    mailbox = buffer(reader, capacity=1)
    mailbox.push(ExecutionUpdateV1(1, state("A", Status.ACCEPTED)))
    mailbox.push(ExecutionUpdateV1(2, state("A", Status.RUNNING)))
    with pytest.raises(AppServiceError) as error:
        await capture_execution_snapshot(reader, reader.read_view, mailbox)
    assert error.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED


@scenario
async def test_authority_loss_after_source_read_is_not_hidden_by_retry() -> None:
    reader = Reader(
        ExecutionBindingViewV1(object(), IDENTITY, 0, ExecutionObservationV1()),
        source(),
    )
    authorized = True

    def read() -> ExecutionBindingViewV1:
        if not authorized:
            raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
        return reader.view

    def revoke() -> None:
        nonlocal authorized
        authorized = False

    reader.action = revoke
    with pytest.raises(AppServiceError) as error:
        await capture_execution_snapshot(reader, read, buffer(reader))
    assert error.value.code is AppErrorCodeV1.STALE_ATTACHMENT
