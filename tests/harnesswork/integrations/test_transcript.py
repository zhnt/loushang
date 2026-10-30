from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from loushang.harness.events import RuntimeEvent
from loushang.harness.transcript.source_reader import (
    TranscriptSourceBatch,
    TranscriptSourceRecord,
)
from loushang.harnesswork import (
    InMemoryEventLogBackend,
    WorkRunSpec,
    WorkRuntime,
    WorkStepSpec,
)
from loushang.harnesswork.integrations.session import (
    SessionTurnExecutor,
    SessionWorkProfile,
    SessionWorkRuntime,
    SessionWorkTurn,
    prepare_session_work_source,
)
from loushang.harnesswork.integrations.transcript import (
    HANDOFF_KIND,
    REFERENCE_KIND,
    WorkTranscriptError,
    WorkTranscriptExpired,
    WorkTranscriptSource,
    project_work_transcript,
    resolve_work_transcript,
)
from loushang.harnesswork.recording import (
    WorkRecordingUnavailable,
    project_work_recording,
)


class Reader:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = None
        self.digest = "a" * 64

    async def inspect_identity(self):
        return await self.read()

    async def read(self, ids=()):
        self.calls += 1
        if ids:
            self.started.set()
            if self.release is not None:
                await self.release.wait()
        return TranscriptSourceBatch(
            "store",
            "session",
            tuple(
                TranscriptSourceRecord(SimpleNamespace(record_id=i), self.digest)
                for i in dict.fromkeys(ids)
            ),
            100,
            len(set(ids)),
        )


class Session:
    def __init__(self):
        self.listeners = []
        self.prompts = []
        self.invalid = False
        self.aborted = False

    def subscribe_runtime_events(self, callback):
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    async def prompt(self, text, **kwargs):
        self.prompts.append(text)
        event = RuntimeEvent(
            event_id=f"event-{len(self.prompts)}",
            kind="message_end",
            stream_id="stream",
            sequence=len(self.prompts),
            occurred_at=datetime.now(UTC),
            payload={"type": "message_end"},
            session_id="session",
            source_record_id=None if self.invalid else f"record-{len(self.prompts)}",
        )
        for callback in tuple(self.listeners):
            await callback(event)

    def abort(self):
        self.aborted = True

    async def wait_for_idle(self):
        pass


async def prepare(*, log=None):
    reader, session = Reader(), Session()
    source = await WorkTranscriptSource.bind(
        reader,
        binding_id="source",
        retained_until=datetime.now(UTC) + timedelta(days=1),
    )
    log = log if log is not None else InMemoryEventLogBackend()
    runtime = SessionWorkRuntime(
        session=session,
        event_log=log,
        profile=SessionWorkProfile("test", "Prompt"),
        project_event_facts=lambda event: (),
        transcript_source=source,
    )
    return reader, session, source, log, runtime


def test_two_steps_followup_handoffs_cold_resolution_and_missing_whole_group():
    async def scenario():
        reader, session, source, log, runtime = await prepare()
        run = await runtime.submit_plan(
            [
                SessionWorkTurn("one", plan_id="p", step_id="one"),
                SessionWorkTurn(
                    "two", plan_id="p", step_id="two", follow_up_messages=("three",)
                ),
            ],
            session_id="session",
        )
        assert run.status == "completed" and session.prompts == ["one", "two", "three"]
        assert reader.calls == 4  # bind + one source read per prompt, never per message
        history = log.query()
        confirmation = runtime.work_runtime.get_recording(run.run_id)
        resolved = await resolve_work_transcript(confirmation, history, source=source)
        assert resolved.handoffs.complete and len(resolved.records) == 3
        assert reader.calls == 5  # all references resolved in one read
        cold = project_work_recording(history, run.run_id)
        assert project_work_transcript(cold, history) == resolved.handoffs

        def last_group(e):
            payload = e.payload.get("payload", {})
            return any(
                isinstance(v, dict) and v.get("handoff_id") == "1:1"
                for v in payload.values()
            )

        missing = [e for e in history if not last_group(e)]
        view = project_work_transcript(
            project_work_recording(missing, run.run_id), missing
        )
        assert view.missing_handoffs == ("1:1",) and not view.complete
        assert cold.run.status == "completed"
        reader.digest = "b" * 64
        with pytest.raises(WorkTranscriptError, match="digest"):
            await resolve_work_transcript(cold, history, source=source)
        with pytest.raises(WorkTranscriptError, match="frozen"):
            await resolve_work_transcript(
                cold,
                history,
                source=replace(
                    source, retained_until=source.retained_until - timedelta(hours=1)
                ),
            )

    asyncio.run(scenario())


def test_direct_runtime_source_uses_same_preparation_and_rejects_wrong_executor():
    async def scenario():
        reader, session, source, log, runtime = await prepare()
        turn = SessionWorkTurn("plan", plan_id="p", step_id="planning")
        operation = turn.to_operation(
            profile=runtime.profile, session_id="session", operation_id="direct"
        )
        spec = WorkRunSpec(plan_id="p", steps=(WorkStepSpec("planning"),))
        original = SessionTurnExecutor(
            session=session,
            profile=runtime.profile,
            project_event_facts=lambda event: (),
            turn=turn,
        )
        with pytest.raises(WorkTranscriptError, match="explicit turns"):
            prepare_session_work_source(
                operation, spec=spec, session=session, executor=original, source=source
            )
        original = replace(original, turn=None, turns=(turn,))
        with pytest.raises(WorkTranscriptError, match="standard executor"):
            prepare_session_work_source(
                operation,
                spec=spec,
                session=Session(),
                executor=original,
                source=source,
            )
        operation, executor = prepare_session_work_source(
            operation,
            spec=spec,
            session=session,
            executor=original,
            source=source,
        )
        with pytest.raises(WorkTranscriptError, match="reserved"):
            prepare_session_work_source(
                operation, spec=spec, session=session, executor=original, source=source
            )
        work = WorkRuntime(executor=executor, event_log=log, recording_version=1)
        run = await work.accept(operation, spec=spec)
        await work.wait(run.run_id)
        record = work.get_recording(run.run_id)
        resolved = await resolve_work_transcript(record, log.query(), source=source)
        assert record.run.status == "completed"
        assert session.prompts == ["plan"] and reader.calls == 3
        assert resolved.handoffs.complete
        assert {r.handoff_id for r in resolved.handoffs.references} == {"0:0"}

    asyncio.run(scenario())


def test_source_expiring_in_turn_hook_prevents_prompt_after_admission(monkeypatch):
    async def scenario():
        _, session, source, log, runtime = await prepare()
        expired = False
        check = WorkTranscriptSource.check

        def check_deadline(self):
            if expired:
                raise WorkTranscriptExpired("retention_expired")
            check(self)

        def before_turn(*args):
            nonlocal expired
            expired = True

        monkeypatch.setattr(WorkTranscriptSource, "check", check_deadline)
        turn = SessionWorkTurn("must not call the model")
        executor = SessionTurnExecutor(
            session=session,
            profile=runtime.profile,
            project_event_facts=lambda event: (),
            turn=turn,
            before_turn=before_turn,
        )
        operation = turn.to_operation(
            profile=runtime.profile, session_id="session", operation_id="expires"
        )
        run = await runtime.accept_operation(operation, executor=executor)
        with pytest.raises(WorkTranscriptExpired):
            await runtime.work_runtime.wait(run.run_id)
        record = runtime.work_runtime.get_recording(run.run_id)
        assert record.run.status == "failed" and not session.prompts
        assert project_work_transcript(record, log.query()).missing_handoffs == ("0:0",)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "bool",
        "flat",
        "foreign",
        "extra",
        "unknown_group",
        "duplicate",
        "mismatched_completion",
    ],
)
def test_source_format_rejects_ambiguous_or_foreign_facts(change):
    async def scenario():
        _, _, _, log, runtime = await prepare()
        run = await runtime.submit_turn(SessionWorkTurn("one"), session_id="session")
        history = log.query()
        target = next(
            e
            for e in history
            if e.payload.get("kind")
            == (HANDOFF_KIND if change == "mismatched_completion" else REFERENCE_KIND)
        )
        field = "handoff" if change == "mismatched_completion" else "transcript_source"
        raw = dict(target.payload["payload"][field])
        if change == "version":
            raw["version"] = 2
        elif change == "bool":
            raw["version"] = True
        elif change == "foreign":
            raw["store_identity"] = "other"
        elif change == "extra":
            raw["path"] = "/tmp/unauthorized"
        elif change == "unknown_group":
            raw["handoff_id"] = "9:9"
        elif change == "mismatched_completion":
            raw["record_ids"] = ["other"]
        payload = {field: raw}
        if change == "flat":
            payload["step_id"] = "GHOST"
        changed = replace(target, payload={**target.payload, "payload": payload})
        history = [changed if e == target else e for e in history]
        if change == "duplicate":
            index = history.index(changed)
            history.insert(index + 1, changed)
            history = [replace(e, sequence=i) for i, e in enumerate(history)]
        cold = project_work_recording(history, run.run_id)
        with pytest.raises(WorkTranscriptError):
            project_work_transcript(cold, history)

    asyncio.run(scenario())


def test_uncommitted_locator_fails_work_and_preserves_missing_handoff():
    async def scenario():
        _, session, _, log, runtime = await prepare()
        session.invalid = True
        with pytest.raises(WorkTranscriptError, match="locator"):
            await runtime.submit_turn(
                SessionWorkTurn("one"), session_id="session", run_id="failed"
            )
        record = runtime.work_runtime.get_recording("failed")
        assert record.run.status == "failed"
        assert project_work_transcript(record, log.query()).missing_handoffs == ("0:0",)
        assert not session.listeners

    asyncio.run(scenario())


def test_cancel_during_handoff_waits_and_does_not_publish_or_follow_up():
    async def scenario():
        reader, session, _, log, runtime = await prepare()
        reader.release = asyncio.Event()
        task = asyncio.create_task(
            runtime.submit_turn(
                SessionWorkTurn("one", follow_up_messages=("forbidden",)),
                session_id="session",
                run_id="cancel",
            )
        )
        await reader.started.wait()
        cancelling = asyncio.create_task(runtime.work_runtime.cancel("cancel"))
        while not session.aborted:
            await asyncio.sleep(0)
        assert not cancelling.done()
        reader.release.set()
        assert (await cancelling).status == "cancelled"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.prompts == ["one"] and not session.listeners
        assert not any(
            e.payload.get("kind") in {REFERENCE_KIND, HANDOFF_KIND} for e in log.query()
        )

    asyncio.run(scenario())


def test_ready_executor_observes_cancel_before_driver_runs():
    async def scenario():
        _, session, _, log, runtime = await prepare()
        entered, release = asyncio.Event(), asyncio.Event()

        async def before(*args):
            entered.set()
            await release.wait()

        task = asyncio.create_task(
            runtime.submit_plan(
                [SessionWorkTurn("forbidden", plan_id="p", step_id="s")],
                session_id="session",
                run_id="race",
                before_turn=before,
            )
        )
        await entered.wait()
        asyncio.get_running_loop().call_soon(release.set)
        cancel = asyncio.create_task(runtime.work_runtime.cancel("race"))
        assert (await cancel).status == "cancelled"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not session.prompts
        kinds = [e.payload.get("kind") for e in log.query()]
        assert "WorkStepCancelled" in kinds and "WorkStepCompleted" not in kinds

    asyncio.run(scenario())


@pytest.mark.parametrize("after_write", [False, True])
def test_reference_append_failure_invalidates_owner_without_reexecution(after_write):
    class FaultLog(InMemoryEventLogBackend):
        def append(self, entry):
            if entry.payload.get("kind") == REFERENCE_KIND:
                if after_write:
                    super().append(entry)
                raise OSError("injected source append")
            return super().append(entry)

    async def scenario():
        _, session, _, log, runtime = await prepare(log=FaultLog())
        with pytest.raises(OSError, match="injected"):
            await runtime.submit_turn(
                SessionWorkTurn("one"), session_id="session", run_id="fault"
            )
        with pytest.raises(WorkRecordingUnavailable):
            runtime.work_runtime.get_recording("fault")
        assert session.prompts == ["one"]
        view = project_work_transcript(
            project_work_recording(log.query(), "fault"), log.query()
        )
        assert view.missing_handoffs == ("0:0",)
        assert len(view.references) == int(after_write)

    asyncio.run(scenario())


def test_expired_binding_rejected_before_prompt():
    async def scenario():
        _, session, source, _, runtime = await prepare()
        runtime.transcript_source = replace(
            source, retained_until=datetime.now(UTC) - timedelta(seconds=1)
        )
        with pytest.raises(WorkTranscriptExpired):
            await runtime.submit_turn(
                SessionWorkTurn("forbidden"), session_id="session"
            )
        assert not session.prompts and not runtime.event_log.query()

    asyncio.run(scenario())


def test_standard_executor_reuse_after_cancel_does_not_suppress_next_run():
    from loushang.harnesswork import WorkOperation, WorkRunSpec, WorkRuntime
    from loushang.harnesswork.integrations.session import SessionTurnExecutor

    async def scenario():
        session = Session()
        entered, release = asyncio.Event(), asyncio.Event()

        async def before(*args):
            if not entered.is_set():
                entered.set()
                await release.wait()

        executor = SessionTurnExecutor(
            session,
            SessionWorkProfile("test", "Prompt"),
            lambda event: (),
            before_turn=before,
        )
        core = WorkRuntime(
            event_log=InMemoryEventLogBackend(),
            executor=executor,
            cancellation=executor,
        )
        await core.accept(
            WorkOperation("a", "Prompt", "session", "test", {"text": "cancelled"}),
            spec=WorkRunSpec(run_id="a"),
        )
        await entered.wait()
        asyncio.get_running_loop().call_soon(release.set)
        await core.cancel("a")
        await core.accept(
            WorkOperation("b", "Prompt", "session", "test", {"text": "required"}),
            spec=WorkRunSpec(run_id="b"),
        )
        assert (await core.wait("b")).status == "completed"
        assert session.prompts[-1] == "required" and not executor._cooperation

    asyncio.run(scenario())


def test_prompt_handoff_is_frozen_while_source_read_waits():
    async def scenario():
        reader, session, source, log, runtime = await prepare()
        reader.release = asyncio.Event()
        task = asyncio.create_task(
            runtime.submit_turn(
                SessionWorkTurn("one"), session_id="session", run_id="freeze"
            )
        )
        await reader.started.wait()
        late = RuntimeEvent(
            event_id="later-event",
            kind="message_end",
            stream_id="stream",
            sequence=2,
            occurred_at=datetime.now(UTC),
            payload={"type": "message_end"},
            session_id="session",
            source_record_id="later-record",
        )
        for listener in tuple(session.listeners):
            await listener(late)
        reader.release.set()
        assert (await task).status == "completed"
        result = await resolve_work_transcript(
            runtime.work_runtime.get_recording("freeze"), log.query(), source=source
        )
        assert result.handoffs.complete
        assert [r.record.record_id for r in result.records] == ["record-1"]

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["source_read", "after_turn"])
def test_cancel_during_planned_step_never_records_step_completed(phase):
    async def scenario():
        reader, session, _, log, runtime = await prepare()
        entered, release = asyncio.Event(), asyncio.Event()

        async def after(*args):
            if phase == "after_turn":
                entered.set()
                await release.wait()

        if phase == "source_read":
            reader.release = release
            entered = reader.started
        task = asyncio.create_task(
            runtime.submit_plan(
                [SessionWorkTurn("one", plan_id="p", step_id="s")],
                session_id="session",
                run_id="planned-cancel",
                after_turn=after,
            )
        )
        await entered.wait()
        cancelling = asyncio.create_task(runtime.work_runtime.cancel("planned-cancel"))
        while not session.aborted:
            await asyncio.sleep(0)
        release.set()
        assert (await cancelling).status == "cancelled"
        with pytest.raises(asyncio.CancelledError):
            await task
        kinds = [e.payload.get("kind") for e in log.query()]
        assert "WorkStepCancelled" in kinds and "WorkStepCompleted" not in kinds

    asyncio.run(scenario())
