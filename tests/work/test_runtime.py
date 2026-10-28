from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from loushang.harnesswork import InMemoryEventLogBackend, WorkRuntime
from loushang.harnesswork.goal import (
    GoalAssessment,
    GoalController,
    GoalError,
    GoalHeader,
    Requirement,
    WorkCandidate,
)
from loushang.harnesswork.goal.records import (
    GoalRecord,
    UnsupportedGoalVersion,
    decode_record,
    encode_record,
    replay,
)
from loushang.harnesswork.types import WorkOperation, WorkRunSpec, WorkStepSpec


def _operation():
    from loushang.work import WorkOperation

    return WorkOperation(
        operation_id="op-1",
        kind="TestOperation",
        session_id="session-1",
        domain="test",
        payload={"input": "hello"},
    )


def _spec():
    from loushang.work import WorkRunSpec

    return WorkRunSpec(
        run_id="run-1",
        method_id="method-1",
        plan_id="plan-1",
        step_id="step-1",
        run_event_payload={"source_type": "test"},
        scope_event_payload={"step_index": 0, "step_title": "Test step"},
    )


def _clock():
    return datetime(2026, 7, 20, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "mode,status,reason,report",
    [
        ("none", "unsupported", "no_capability", None),
        ("settled", "settled", "domain_reported", "settled"),
        ("unsupported", "unsupported", "domain_reported", "unsupported"),
        ("failed", "failed", "domain_failure", "failed"),
        ("exception", "failed", "domain_exception", None),
        ("invalid", "failed", "invalid_return", None),
        ("self", "unknown", "executor_interrupted", None),
    ],
)
def test_cancellation_observation_preserves_control_and_replays(
    tmp_path, mode, status, reason, report
) -> None:
    from loushang.harnesswork import (
        JsonlEventLogBackend,
        WorkCancellationFailedError,
        WorkCancellationOutcome,
        WorkEventFact,
        WorkRunTerminalError,
        WorkRuntime,
        project_work_cancellations,
    )

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        context_ref = None
        domain_error = ValueError("binding failed")
        pending = []
        committed = []

        class Executor:
            async def execute(self, operation, context):
                nonlocal context_ref
                context_ref = context
                started.set()
                if mode == "self":
                    raise asyncio.CancelledError("self interrupt")
                await release.wait()

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                nonlocal calls
                calls += 1
                if mode == "exception":
                    raise domain_error
                if mode == "invalid":
                    return None
                if mode == "failed":
                    return WorkCancellationOutcome.failed(domain_error)
                if mode == "settled":
                    release.set()
                    return WorkCancellationOutcome.settled()
                return WorkCancellationOutcome.unsupported()

        path = tmp_path / "cancellation.jsonl"
        runtime = WorkRuntime(
            executor=Executor(),
            cancellation=None if mode == "none" else Cancellation(),
            event_log=JsonlEventLogBackend(path),
        )

        def listener(event):
            # Listener exceptions are intentionally suppressed by Runtime, so
            # collect evidence here and assert outside the callback.
            observation = runtime.get_cancellation(event.run_id)
            if event.kind == "WorkRunCancelling":
                pending.append(observation)
            if event.kind in {"WorkRunCancelled", "WorkRunFailed"}:
                rejected = False
                try:
                    context_ref.publish(WorkEventFact("TooLate", {}))
                except WorkRunTerminalError:
                    rejected = True
                committed.append((observation, rejected, event))

        runtime.subscribe_events(listener)
        run = await runtime.accept(_operation(), spec=_spec())
        accepted = runtime.get_cancellation(run.run_id)
        assert (
            accepted.basis,
            accepted.observed_sequence,
            accepted.source_event_id,
        ) == ("live", 0, None)
        await started.wait()
        if mode != "self":
            results = await asyncio.gather(
                runtime.cancel(run.run_id),
                runtime.cancel(run.run_id),
                return_exceptions=True,
            )
            if status == "failed":
                assert all(isinstance(result, Exception) for result in results)
                if mode in {"failed", "exception"}:
                    assert all(result is domain_error for result in results)
                else:
                    assert all(
                        isinstance(result, WorkCancellationFailedError)
                        for result in results
                    )
            else:
                assert all(result.status == "cancelled" for result in results)
        with pytest.raises((asyncio.CancelledError, Exception)) as caught:
            await runtime.wait(run.run_id)
        if mode == "self":
            assert caught.value.args == ("self interrupt",)
        assert calls == (0 if mode in {"none", "self"} else 1)
        record = runtime.get_cancellation(run.run_id)
        assert (record.status, record.reason_code, record.reported_status) == (
            status,
            reason,
            report,
        )
        assert pending and pending[0].status == "pending"
        assert pending[0].basis == "live" and pending[0].reported_status is None
        assert len(committed) == 1
        observed, late_rejected, event = committed[0]
        assert observed is record and late_rejected
        assert (record.observed_sequence, record.source_event_id) == (
            event.sequence,
            event.event_id,
        )
        assert "_harnesswork" not in event.payload
        entries = runtime.query()
        assert project_work_cancellations(entries) == (record,)
        reopened = WorkRuntime(
            executor=Executor(), event_log=JsonlEventLogBackend(path)
        )
        assert reopened.get_cancellation(run.run_id) == record
        from loushang.harnesswork import UnknownWorkRunError

        with pytest.raises(UnknownWorkRunError):
            await reopened.cancel(run.run_id)

    asyncio.run(scenario())


@pytest.mark.parametrize("late_report", [None, "settled", "unsupported", "failed"])
def test_cancellation_timeout_retains_real_late_report(late_report) -> None:
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkCancellationOutcome,
        WorkCancellationTimeoutError,
        WorkRuntime,
        project_work_cancellations,
    )

    async def scenario():
        started = asyncio.Event()

        class Executor:
            async def execute(self, operation, context):
                started.set()
                await asyncio.Event().wait()

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if late_report is None:
                        raise
                    if late_report == "failed":
                        return WorkCancellationOutcome.failed(
                            ValueError("late failure")
                        )
                    return WorkCancellationOutcome(status=late_report)

        runtime = WorkRuntime(
            executor=Executor(),
            cancellation=Cancellation(),
            event_log=InMemoryEventLogBackend(),
            cancellation_timeout=0.01,
        )
        run = await runtime.accept(_operation(), spec=_spec())
        await started.wait()
        with pytest.raises(WorkCancellationTimeoutError):
            await runtime.cancel(run.run_id)
        with pytest.raises(WorkCancellationTimeoutError):
            await runtime.wait(run.run_id)
        record = runtime.get_cancellation(run.run_id)
        assert (record.status, record.reason_code, record.reported_status) == (
            "failed",
            "domain_timeout",
            late_report,
        )
        assert runtime.get_run(run.run_id).status == "failed"
        assert project_work_cancellations(runtime.query()) == (record,)

    asyncio.run(scenario())


def test_execution_timeout_preserves_binding_report() -> None:
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkCancellationOutcome,
        WorkCancellationTimeoutError,
        WorkRuntime,
    )

    async def scenario():
        started = asyncio.Event()

        class Executor:
            async def execute(self, operation, context):
                started.set()
                await asyncio.Event().wait()

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                return WorkCancellationOutcome.settled()

        runtime = WorkRuntime(
            executor=Executor(),
            cancellation=Cancellation(),
            event_log=InMemoryEventLogBackend(),
            cancellation_timeout=0.01,
        )
        run = await runtime.accept(_operation(), spec=_spec())
        await started.wait()
        with pytest.raises(WorkCancellationTimeoutError):
            await runtime.cancel(run.run_id)
        record = runtime.get_cancellation(run.run_id)
        assert (record.status, record.reason_code, record.reported_status) == (
            "failed",
            "execution_timeout",
            "settled",
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("fails", [False, True])
def test_uncancelled_terminal_and_mutable_business_metadata(fails) -> None:
    from dataclasses import replace

    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        UnknownWorkRunError,
        WorkEventFact,
        WorkRuntime,
        project_work_cancellations,
    )

    async def scenario():
        business = {"_harnesswork": {"cancellation": {"status": "forged"}}}
        events = []
        failure = ValueError("ordinary failure")

        class Executor:
            async def execute(self, operation, context):
                context.publish(WorkEventFact("DomainFact", business))
                if fails:
                    raise failure

        runtime = WorkRuntime(executor=Executor(), event_log=InMemoryEventLogBackend())
        runtime.subscribe_events(events.append)
        run = await runtime.accept(
            replace(_operation(), payload=business),
            spec=replace(_spec(), run_event_payload=business),
        )
        assert runtime.get_cancellation(run.run_id).status == "not_requested"
        if fails:
            with pytest.raises(ValueError) as caught:
                await runtime.wait(run.run_id)
            assert caught.value is failure
        else:
            assert (await runtime.wait(run.run_id)).status == "completed"
        record = runtime.get_cancellation(run.run_id)
        assert (record.status, record.reason_code, record.reported_status) == (
            "not_requested",
            "none",
            None,
        )
        assert events[-1].payload == business | {
            "method_id": "method-1",
            "plan_id": "plan-1",
            "step_id": "step-1",
        }
        # Business keys remain ordinary mutable input, separate from the owner.
        business["_harnesswork"]["cancellation"]["status"] = "changed"
        assert runtime.get_cancellation(run.run_id) is record
        assert project_work_cancellations(runtime.query()) == (record,)
        with pytest.raises(UnknownWorkRunError):
            runtime.get_cancellation("missing")

    asyncio.run(scenario())


def test_live_observation_uses_run_local_ack_before_listener() -> None:
    from loushang.harnesswork import InMemoryEventLogBackend, WorkEventFact, WorkRuntime

    async def scenario():
        before_ack, after_ack = [], []
        started, release = asyncio.Event(), asyncio.Event()

        class Backend(InMemoryEventLogBackend):
            def append(self, entry):
                if entry.payload["kind"] == "DomainFact":
                    before_ack.append(runtime.get_cancellation(entry.run_id))
                return super().append(entry)

        class Executor:
            async def execute(self, operation, context):
                context.publish(WorkEventFact("DomainFact", {}))
                started.set()
                await release.wait()

        runtime = WorkRuntime(executor=Executor(), event_log=Backend())
        runtime.subscribe_events(
            lambda event: after_ack.append(
                (event, runtime.get_cancellation(event.run_id))
            )
        )
        run = await runtime.accept(_operation(), spec=_spec())
        await started.wait()
        fact, observation = next(
            pair for pair in after_ack if pair[0].kind == "DomainFact"
        )
        assert before_ack[0].observed_sequence == fact.sequence - 1
        assert observation.observed_sequence == fact.sequence
        assert observation.source_event_id == fact.event_id
        release.set()
        await runtime.wait(run.run_id)

    asyncio.run(scenario())


def test_jsonl_terminal_written_without_ack_is_not_live_confirmed(tmp_path) -> None:
    from loushang.harnesswork import (
        JsonlEventLogBackend,
        WorkCancellationObservationUnavailable,
        WorkRuntime,
        project_work_cancellations,
    )

    async def scenario():
        error = OSError("index update failed")

        class Backend(JsonlEventLogBackend):
            def _append_stored(self, entry):
                if entry.payload["kind"] == "WorkRunCompleted":
                    raise error
                return super()._append_stored(entry)

        class Executor:
            async def execute(self, operation, context):
                pass

        path = tmp_path / "work.jsonl"
        runtime = WorkRuntime(executor=Executor(), event_log=Backend(path))
        run = await runtime.accept(_operation(), spec=_spec())
        with pytest.raises(OSError) as caught:
            await runtime.wait(run.run_id)
        assert caught.value is error
        with pytest.raises(WorkCancellationObservationUnavailable):
            runtime.get_cancellation(run.run_id)
        assert runtime.query()[-1].payload["kind"] != "WorkRunCompleted"
        cold = JsonlEventLogBackend(path)
        (record,) = project_work_cancellations(cold.query())
        assert record.status == "not_requested" and record.basis == "journal"
        reopened = WorkRuntime(executor=Executor(), event_log=cold)
        assert reopened.get_cancellation(run.run_id) == record

    asyncio.run(scenario())


@pytest.mark.parametrize("after_write", [False, True])
def test_cancelling_append_ack_failure_does_not_claim_missing_capability(after_write):
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkCancellationObservationUnavailable,
        WorkCancellationOutcome,
        WorkRunReplayError,
        WorkRuntime,
        project_work_cancellations,
    )

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        error = OSError("after cancelling write")

        class Backend(InMemoryEventLogBackend):
            def append(self, entry):
                if entry.payload["kind"] == "WorkRunCancelling":
                    if after_write:
                        super().append(entry)
                    raise error
                return super().append(entry)

        class Executor:
            async def execute(self, operation, context):
                started.set()
                await release.wait()

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                nonlocal calls
                calls += 1
                return WorkCancellationOutcome.settled()

        backend = Backend()
        runtime = WorkRuntime(
            executor=Executor(), cancellation=Cancellation(), event_log=backend
        )
        run = await runtime.accept(_operation(), spec=_spec())
        await started.wait()
        with pytest.raises(OSError) as caught:
            await runtime.cancel(run.run_id)
        assert caught.value is error
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await runtime.wait(run.run_id)
        assert calls == 0 and runtime.get_run(run.run_id).status == "cancelled"
        with pytest.raises(WorkCancellationObservationUnavailable):
            runtime.get_cancellation(run.run_id)
        # The original control path can still write; its cold evidence must be
        # honest about the existing capability that was never invoked.
        if after_write:
            (record,) = project_work_cancellations(backend.query())
            assert (record.status, record.reason_code, record.reported_status) == (
                "unknown",
                "cancellation_not_driven",
                None,
            )
        else:
            with pytest.raises(WorkRunReplayError):
                project_work_cancellations(backend.query())

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind",
    [
        "TestOperation",
        "WorkRunStarted",
        "WorkPlanStarted",
        "WorkStepStarted",
        "DomainFact",
        "WorkStepCompleted",
        "WorkPlanCompleted",
        "WorkRunCompleted",
        "WorkRunCancelling",
        "WorkStepCancelled",
        "WorkPlanCancelled",
        "WorkRunCancelled",
        "WorkStepFailed",
        "WorkPlanFailed",
        "WorkRunFailed",
    ],
)
@pytest.mark.parametrize("after_write", [False, True])
def test_append_failure_invalidates_only_new_observation(kind, after_write) -> None:
    from contextlib import suppress

    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkCancellationObservationUnavailable,
        WorkEventFact,
        WorkRuntime,
    )

    async def scenario():
        append_error = OSError("private backend details")
        seen = []
        propagated = []
        release, started = asyncio.Event(), asyncio.Event()

        class Backend(InMemoryEventLogBackend):
            def append(self, entry):
                if entry.payload["kind"] == kind and not seen:
                    seen.append(entry)
                    if after_write:
                        super().append(entry)
                    raise append_error
                return super().append(entry)

        class Executor:
            async def execute(self, operation, context):
                started.set()
                context.publish(WorkEventFact("DomainFact", {}))
                if kind.endswith("Failed"):
                    raise ValueError("executor failure")
                await release.wait()

        runtime = WorkRuntime(executor=Executor(), event_log=Backend())
        try:
            if kind == "TestOperation":
                with pytest.raises(OSError) as caught:
                    await runtime.accept(_operation(), spec=_spec())
                assert caught.value is append_error
                propagated.append(caught.value)
            else:
                await runtime.accept(_operation(), spec=_spec())
                if kind.endswith("Cancelled") or kind == "WorkRunCancelling":
                    await started.wait()
                    try:
                        await runtime.cancel("run-1")
                    except BaseException as error:
                        propagated.append(error)
                release.set()
                try:
                    await runtime.wait("run-1")
                except BaseException as error:
                    propagated.append(error)
            assert len(seen) == 1
            assert any(error is append_error for error in propagated)
            with pytest.raises(WorkCancellationObservationUnavailable) as caught:
                runtime.get_cancellation("run-1")
            assert str(caught.value) == "取消观察暂不可确认。"
            assert caught.value.__cause__ is None
            # Old query remains available; this is no global API fence.
            assert isinstance(runtime.query(), list)
        finally:
            release.set()
            if runtime.active_runs():
                with suppress(BaseException):
                    await runtime.wait("run-1")

    asyncio.run(scenario())


@dataclass
class _ControlledExecutor:
    started: asyncio.Event
    release: asyncio.Event
    context: object | None = None

    async def execute(self, operation, context):
        from loushang.work import WorkEventFact

        self.context = context
        context.publish(
            WorkEventFact(
                kind="DomainFact",
                payload={"operation_kind": operation.kind},
                source_event_ref="source-1",
            )
        )
        self.started.set()
        await self.release.wait()
        return {"ok": True}


def test_work_runtime_accepts_runs_and_owns_success_lifecycle() -> None:
    from loushang.work import InMemoryEventLogBackend, WorkEventFact, WorkRuntime

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        executor = _ControlledExecutor(started=started, release=release)
        runtime = WorkRuntime(
            executor=executor,
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )

        accepted = await runtime.accept(_operation(), spec=_spec())

        assert accepted.status == "accepted"
        assert runtime.get_run("run-1").status == "accepted"
        assert [entry.payload["kind"] for entry in runtime.query(run_id="run-1")] == [
            "TestOperation"
        ]

        await started.wait()
        assert runtime.get_run("run-1").status == "running"
        release.set()
        completed = await runtime.wait("run-1")

        assert completed.status == "completed"
        entries = runtime.query(run_id="run-1")
        assert [entry.sequence for entry in entries] == list(range(len(entries)))
        assert [entry.payload["kind"] for entry in entries] == [
            "TestOperation",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "DomainFact",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]
        assert entries[4].payload["source_event_ref"] == "source-1"
        assert entries[-1].payload["payload"] == {
            "source_type": "test",
            "method_id": "method-1",
            "plan_id": "plan-1",
            "step_id": "step-1",
        }

        assert executor.context is not None
        try:
            executor.context.publish(WorkEventFact(kind="LateFact", payload={}))
        except Exception as error:
            assert type(error).__name__ == "WorkRunTerminalError"
        else:
            raise AssertionError("expected terminal event rejection")
        assert runtime.query(run_id="run-1") == entries

    asyncio.run(scenario())


def test_work_runtime_records_cancellation_driver_failure_as_failed_terminal() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkCancellationOutcome,
        WorkRuntime,
    )

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class Executor:
            async def execute(self, operation, context):
                del operation, context
                started.set()
                await release.wait()

        failure = RuntimeError("abort transport failed")

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                del operation, context
                return WorkCancellationOutcome.failed(failure)

        runtime = WorkRuntime(
            executor=Executor(),
            cancellation=Cancellation(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())
        await started.wait()

        with pytest.raises(RuntimeError, match="abort transport failed"):
            await runtime.cancel("run-1")

        assert runtime.get_run("run-1").status == "failed"
        kinds = [entry.payload["kind"] for entry in runtime.query(run_id="run-1")]
        assert kinds[-4:] == [
            "WorkRunCancelling",
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]
        assert kinds.count("WorkRunFailed") == 1
        assert "WorkRunCancelled" not in kinds

    asyncio.run(scenario())


def test_work_runtime_times_out_cancellation_as_failed_terminal() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkCancellationTimeoutError,
        WorkRuntime,
    )

    async def scenario() -> None:
        started = asyncio.Event()
        never = asyncio.Event()

        class Executor:
            async def execute(self, operation, context):
                del operation, context
                started.set()
                await never.wait()

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                del operation, context
                await never.wait()
                raise AssertionError("unreachable")

        runtime = WorkRuntime(
            executor=Executor(),
            cancellation=Cancellation(),
            event_log=InMemoryEventLogBackend(),
            cancellation_timeout=0.01,
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())
        await started.wait()

        with pytest.raises(WorkCancellationTimeoutError, match="timed out"):
            await runtime.cancel("run-1")

        assert runtime.get_run("run-1").status == "failed"
        assert runtime.query(run_id="run-1")[-1].payload["kind"] == "WorkRunFailed"

    asyncio.run(scenario())


def test_work_runtime_resolves_execution_capabilities_per_operation() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkExecutionBinding,
        WorkOperation,
        WorkRuntime,
    )

    calls: list[str] = []

    class Executor:
        def __init__(self, label: str) -> None:
            self.label = label

        async def execute(self, operation, context):
            del operation, context
            calls.append(self.label)

    class Resolver:
        def resolve(self, operation, spec):
            del spec
            return WorkExecutionBinding(executor=Executor(operation.operation_id))

    async def scenario() -> None:
        runtime = WorkRuntime(
            resolver=Resolver(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        first = await runtime.accept(
            WorkOperation("op-a", "DoWork", "session-1", "test", {})
        )
        await runtime.wait(first.run_id)
        second = await runtime.accept(
            WorkOperation("op-b", "DoWork", "session-1", "test", {})
        )
        await runtime.wait(second.run_id)

        assert calls == ["op-a", "op-b"]

    asyncio.run(scenario())


def test_work_runtime_orders_step_plan_and_run_failure_and_reraises() -> None:
    from loushang.work import InMemoryEventLogBackend, WorkRuntime

    class FailingExecutor:
        async def execute(self, operation, context):
            del operation, context
            raise RuntimeError("domain failed")

    async def scenario() -> None:
        runtime = WorkRuntime(
            executor=FailingExecutor(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())

        try:
            await runtime.wait("run-1")
        except RuntimeError as error:
            assert str(error) == "domain failed"
        else:
            raise AssertionError("expected domain failure")

        assert runtime.get_run("run-1").status == "failed"
        entries = runtime.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries][-3:] == [
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]
        assert entries[-3].payload["payload"]["error"] == "domain failed"
        assert (
            sum(
                entry.payload["kind"]
                in {"WorkRunCompleted", "WorkRunFailed", "WorkRunCancelled"}
                for entry in entries
            )
            == 1
        )

    asyncio.run(scenario())


def test_work_runtime_cancel_transitions_and_terminal_order_are_deterministic() -> None:
    from loushang.work import InMemoryEventLogBackend, WorkRuntime

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        runtime = WorkRuntime(
            executor=_ControlledExecutor(started=started, release=release),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())
        await started.wait()

        cancelled = await runtime.cancel("run-1")

        assert cancelled.status == "cancelled"
        assert [entry.payload["kind"] for entry in runtime.query(run_id="run-1")][
            -4:
        ] == [
            "WorkRunCancelling",
            "WorkStepCancelled",
            "WorkPlanCancelled",
            "WorkRunCancelled",
        ]
        try:
            await runtime.wait("run-1")
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("expected cancellation")

        entries = runtime.query(run_id="run-1")
        assert entries[-1].payload["kind"] == "WorkRunCancelled"
        assert (
            sum(entry.payload["kind"] == "WorkRunCancelled" for entry in entries) == 1
        )

    asyncio.run(scenario())


def test_work_runtime_uses_domain_cancel_and_settle_once_before_terminal() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkCancellationOutcome,
        WorkRuntime,
    )

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        settled = asyncio.Event()
        calls: list[str] = []

        class Executor:
            async def execute(self, operation, context):
                del operation, context
                started.set()
                try:
                    await release.wait()
                finally:
                    calls.append("executor_settled")
                    settled.set()

        class Cancellation:
            async def cancel_and_wait(self, operation, context):
                del operation, context
                calls.append("abort")
                release.set()
                await settled.wait()
                calls.append("waited")
                return WorkCancellationOutcome.settled()

        runtime = WorkRuntime(
            executor=Executor(),
            cancellation=Cancellation(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())
        await started.wait()

        first, second = await asyncio.gather(
            runtime.cancel("run-1"), runtime.cancel("run-1")
        )

        assert first.status == second.status == "cancelled"
        assert calls == ["abort", "executor_settled", "waited"]
        assert runtime.query(run_id="run-1")[-1].payload["kind"] == ("WorkRunCancelled")

    asyncio.run(scenario())


def test_work_runtime_executes_plan_steps_in_order_under_one_run() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkRunSpec,
        WorkRuntime,
        WorkStepSpec,
    )

    class Executor:
        def __init__(self) -> None:
            self.calls: list[tuple[str | None, int | None, object]] = []

        async def execute(self, operation, context):
            del operation
            self.calls.append(
                (context.step_id, context.step_index, context.step_payload["title"])
            )

    async def scenario() -> None:
        executor = Executor()
        runtime = WorkRuntime(
            executor=executor,
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        spec = WorkRunSpec(
            run_id="run-1",
            method_id="method-1",
            plan_id="plan-1",
            steps=(
                WorkStepSpec("step-1", {"title": "first"}),
                WorkStepSpec("step-2", {"title": "second"}),
            ),
        )
        accepted = await runtime.accept(_operation(), spec=spec)
        completed = await runtime.wait(accepted.run_id)

        assert completed.status == "completed"
        assert executor.calls == [
            ("step-1", 0, "first"),
            ("step-2", 1, "second"),
        ]
        kinds = [entry.payload["kind"] for entry in runtime.query(run_id="run-1")]
        assert kinds == [
            "TestOperation",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]

    asyncio.run(scenario())


def test_work_runtime_stops_plan_after_step_failure_and_orders_terminals() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkRunSpec,
        WorkRuntime,
        WorkStepSpec,
    )

    class Executor:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        async def execute(self, operation, context):
            del operation
            self.calls.append(context.step_id)
            if context.step_id == "step-2":
                raise RuntimeError("verification failed")

    async def scenario() -> None:
        executor = Executor()
        runtime = WorkRuntime(
            executor=executor,
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(
            _operation(),
            spec=WorkRunSpec(
                run_id="run-1",
                plan_id="plan-1",
                steps=(
                    WorkStepSpec("step-1"),
                    WorkStepSpec("step-2"),
                    WorkStepSpec("step-3"),
                ),
            ),
        )

        with pytest.raises(RuntimeError, match="verification failed"):
            await runtime.wait("run-1")

        assert executor.calls == ["step-1", "step-2"]
        kinds = [entry.payload["kind"] for entry in runtime.query(run_id="run-1")]
        assert kinds[-3:] == [
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]
        assert kinds.count("WorkRunFailed") == 1

    asyncio.run(scenario())


def test_work_runtime_cancel_before_executor_starts_still_follows_full_state_path() -> (
    None
):
    from loushang.work import InMemoryEventLogBackend, WorkRuntime

    async def scenario() -> None:
        runtime = WorkRuntime(
            executor=_ControlledExecutor(
                started=asyncio.Event(), release=asyncio.Event()
            ),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())

        cancelled = await runtime.cancel("run-1")

        assert cancelled.status == "cancelled"
        assert [entry.payload["kind"] for entry in runtime.query(run_id="run-1")] == [
            "TestOperation",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkRunCancelling",
            "WorkStepCancelled",
            "WorkPlanCancelled",
            "WorkRunCancelled",
        ]

    asyncio.run(scenario())


def test_executor_cancelled_error_is_a_cancelled_run_not_a_failure() -> None:
    from loushang.work import InMemoryEventLogBackend, WorkRuntime

    class CancelledExecutor:
        async def execute(self, operation, context):
            del operation, context
            raise asyncio.CancelledError("executor cancelled")

    async def scenario() -> None:
        runtime = WorkRuntime(
            executor=CancelledExecutor(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())

        try:
            await runtime.wait("run-1")
        except asyncio.CancelledError as error:
            assert error.args == ("executor cancelled",)
        else:
            raise AssertionError("expected cancellation")

        kinds = [entry.payload["kind"] for entry in runtime.query(run_id="run-1")]
        assert "WorkRunFailed" not in kinds
        assert kinds[-4:] == [
            "WorkRunCancelling",
            "WorkStepCancelled",
            "WorkPlanCancelled",
            "WorkRunCancelled",
        ]

    asyncio.run(scenario())


def test_domain_executor_cannot_publish_work_lifecycle_events() -> None:
    from loushang.work import InMemoryEventLogBackend, WorkEventFact, WorkRuntime

    class InvalidExecutor:
        async def execute(self, operation, context):
            del operation
            context.publish(WorkEventFact(kind="WorkRunCompleted", payload={}))

    async def scenario() -> None:
        runtime = WorkRuntime(
            executor=InvalidExecutor(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        await runtime.accept(_operation(), spec=_spec())

        try:
            await runtime.wait("run-1")
        except Exception as error:
            assert type(error).__name__ == "WorkLifecycleOwnershipError"
        else:
            raise AssertionError("expected lifecycle ownership failure")

        kinds = [entry.payload["kind"] for entry in runtime.query(run_id="run-1")]
        assert kinds.count("WorkRunCompleted") == 0
        assert kinds[-1] == "WorkRunFailed"

    asyncio.run(scenario())


def test_work_runtime_subscribe_replays_and_streams_runtime_owned_log() -> None:
    from loushang.work import InMemoryEventLogBackend, WorkRuntime

    class ImmediateExecutor:
        async def execute(self, operation, context):
            del operation, context
            return None

    async def scenario() -> None:
        runtime = WorkRuntime(
            executor=ImmediateExecutor(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        accepted = await runtime.accept(_operation(), spec=_spec())
        stream = runtime.subscribe(run_id=accepted.run_id)

        operation_entry = await asyncio.wait_for(anext(stream), timeout=0.1)
        assert operation_entry.payload["kind"] == "TestOperation"
        await runtime.wait(accepted.run_id)

        streamed = [
            await asyncio.wait_for(anext(stream), timeout=0.1) for _ in range(6)
        ]
        assert streamed[-1].payload["kind"] == "WorkRunCompleted"
        await stream.aclose()

    asyncio.run(scenario())


def test_work_runtime_allocates_unique_run_ids_and_rejects_duplicate_operations() -> (
    None
):
    from loushang.work import InMemoryEventLogBackend, WorkOperation, WorkRuntime
    from loushang.work.runtime import DuplicateWorkOperationError

    class ImmediateExecutor:
        async def execute(self, operation, context):
            del operation, context
            return None

    async def scenario() -> None:
        runtime = WorkRuntime(
            executor=ImmediateExecutor(),
            event_log=InMemoryEventLogBackend(),
            clock=_clock,
        )
        first_operation = _operation()
        second_operation = WorkOperation(
            operation_id="op-2",
            kind="TestOperation",
            session_id="session-1",
            domain="test",
            payload={},
        )

        first = await runtime.accept(first_operation)
        second = await runtime.accept(second_operation)

        assert first.run_id.startswith("run-")
        assert second.run_id.startswith("run-")
        assert first.run_id != second.run_id
        await runtime.wait(first.run_id)
        await runtime.wait(second.run_id)
        try:
            await runtime.accept(first_operation)
        except DuplicateWorkOperationError:
            pass
        else:
            raise AssertionError("expected duplicate operation rejection")

    asyncio.run(scenario())


# Reviewed optional Goal contracts and finite Coding acceptance.
def _run_goal_scenario(function):
    def test():
        asyncio.run(function())

    test.__name__ = function.__name__
    return test


class _GoalStore:
    def __init__(self, header):
        self.header, self.records = header, []
        self.fail = False

    def load(self):
        return self.header, tuple(self.records)

    def append(self, expected_sequence, record):
        assert expected_sequence == len(self.records)
        self.records.append(record)
        if self.fail:
            raise OSError("after append")
        return record.sequence


class _GoalPolicy:
    def confirm_resume(self, basis, facts):
        return True

    def __init__(self):
        self.calls = 0
        self.gate = None
        self.began = asyncio.Event()
        self.cleaned = False

    async def prepare(self, basis, facts):
        self.began.set()
        if self.gate:
            try:
                await self.gate.wait()
            finally:
                self.cleaned = True
        return WorkCandidate(
            basis,
            WorkOperation(f"op-{self.calls}", "task", "s", "test", {}),
            WorkRunSpec(plan_id="plan", steps=(WorkStepSpec("step"),)),
            {"version": 1},
        )

    def confirm_candidate(self, candidate):
        return True

    async def assess(self, basis, facts):
        current = [r for r in facts.runs if r.status == "completed"]
        return GoalAssessment(
            basis,
            "satisfied" if current else "more_evidence",
            "tests",
            ("R",) if current else (),
            tuple(r.operation_id for r in current),
            {"test": "proof"} if current else {},
        )

    def confirm_current(self, assessment):
        return True

    async def execute(self, operation, context):
        self.calls += 1


def _goal_setup():
    header = GoalHeader("scope", "s", "test-policy")
    store, policy = _GoalStore(header), _GoalPolicy()
    work = WorkRuntime(event_log=InMemoryEventLogBackend(), executor=policy)
    goal = GoalController(
        header=header, store=store, work=work, next_work=policy, acceptance=policy
    )
    goal.create("g", [Requirement("R", "requirement")], command_id="create", limit=3)
    return goal, store, work, policy


@_run_goal_scenario
async def test_real_work_once_completion_and_reopen_without_execution():
    goal, store, work, policy = _goal_setup()
    receipt = await goal.advance("g", command_id="advance", revision=1, epoch=1)
    assert receipt.outcome == "completed"
    assert policy.calls == 1
    assert goal.query("g").status == "completed"
    assert await goal.advance("g", command_id="advance", revision=1, epoch=1) == receipt
    reopened = GoalController(
        header=goal.header, store=store, work=work, next_work=policy, acceptance=policy
    )
    assert reopened.query("g") == goal.query("g")
    assert policy.calls == 1


@_run_goal_scenario
async def test_pause_during_prepare_rejects_late_candidate():
    goal, store, work, policy = _goal_setup()
    policy.gate = asyncio.Event()
    task = asyncio.create_task(
        goal.advance("g", command_id="advance", revision=1, epoch=1)
    )
    await policy.began.wait()
    goal.control("g", "pause", command_id="pause", revision=1, epoch=1, reason="user")
    policy.gate.set()
    assert (await task).outcome == "stale"
    assert not work.query_runs()
    assert goal.query("g").status == "paused"


@_run_goal_scenario
async def test_close_waits_for_callback_finally_before_retire():
    goal, store, work, policy = _goal_setup()
    policy.gate = asyncio.Event()
    task = asyncio.create_task(
        goal.advance("g", command_id="advance", revision=1, epoch=1)
    )
    await policy.began.wait()
    await goal.quiesce()
    assert task.cancelled() and policy.cleaned
    await goal.settle_work()
    goal.retire()
    assert goal.fenced
    assert policy.calls == 0


@_run_goal_scenario
async def test_append_error_after_bytes_fences_without_execution_or_false_ack():
    goal, store, work, policy = _goal_setup()
    store.fail = True
    with pytest.raises(OSError):
        await goal.advance("g", command_id="advance", revision=1, epoch=1)
    assert goal.fenced and policy.calls == 0
    with pytest.raises(GoalError, match="fenced"):
        goal.control(
            "g", "pause", command_id="pause", revision=1, epoch=1, reason="user"
        )
    assert replay(store.header, store.records).commands["advance"].outcome == "pending"


def test_command_conflict_and_revised_requirement_invalidate_old_control():
    goal, _, _, _ = _goal_setup()
    receipt = goal.revise(
        "g",
        [Requirement("R", "new")],
        command_id="revise",
        revision=1,
        epoch=1,
        reason="change",
    )
    assert goal.query("g").revision == 2
    assert goal.query("g").epoch == 2
    assert (
        goal.revise(
            "g",
            [Requirement("R", "new")],
            command_id="revise",
            revision=1,
            epoch=1,
            reason="change",
        )
        == receipt
    )
    with pytest.raises(GoalError, match="different content"):
        goal.revise(
            "g",
            [Requirement("R", "other")],
            command_id="revise",
            revision=1,
            epoch=1,
            reason="change",
        )
    with pytest.raises(GoalError, match="stale"):
        goal.control(
            "g", "pause", command_id="pause", revision=1, epoch=1, reason="user"
        )


@_run_goal_scenario
async def test_not_submitted_cold_replay_does_not_infer_unknown_from_empty_work():
    goal, store, work, policy = _goal_setup()
    checks = 0

    def confirm(candidate):
        nonlocal checks
        checks += 1
        return checks == 1

    policy.confirm_candidate = confirm
    assert (
        await goal.advance("g", command_id="advance", revision=1, epoch=1)
    ).outcome == "not_submitted"
    reopened = GoalController(
        header=goal.header, store=store, work=work, next_work=policy, acceptance=policy
    )
    assert reopened.facts().unresolved is False
    assert reopened.history.batches[0].not_submitted
    assert policy.calls == 0


@_run_goal_scenario
async def test_unknown_intent_blocks_resume_and_replacement_cannot_bypass():
    goal, store, work, policy = _goal_setup()
    original = work.accept

    async def lost(*args, **kwargs):
        raise OSError("outcome unknown")

    work.accept = lost
    assert (
        await goal.advance("g", command_id="advance", revision=1, epoch=1)
    ).outcome == "paused"
    assert goal.facts().unresolved
    state = goal.query("g")
    with pytest.raises(GoalError, match="unresolved"):
        goal.control(
            "g",
            "resume",
            command_id="resume",
            revision=1,
            epoch=state.epoch,
            reason="user",
        )
    goal.replace(
        "g",
        "g2",
        [Requirement("R", "replacement")],
        command_id="replace",
        revision=1,
        epoch=state.epoch,
        reason="user",
        limit=3,
    )
    with pytest.raises(GoalError, match="unresolved"):
        await goal.advance("g2", command_id="advance2", revision=1, epoch=1)
    work.accept = original


@pytest.mark.parametrize("bad", [True, 0, -1, 2])
def test_schema_version_is_exact_and_known(bad):
    record = {
        "version": bad,
        "sequence": 1,
        "scope_id": "scope",
        "goal_id": "g",
        "kind": "command_received",
        "command_id": "cmd",
        "data": {},
    }
    with pytest.raises(GoalError):
        decode_record(record)


def test_optional_fields_preserved_unknown_semantics_rejected_and_data_immutable():
    record = GoalRecord(1, "scope", "g", "command_received", "c", {"x": [1]})
    encoded = dict(encode_record(record), future_optional={"value": 1})
    assert encode_record(decode_record(encoded)) == encoded
    with pytest.raises(TypeError):
        record.data["x"] = 2
    with pytest.raises(UnsupportedGoalVersion):
        decode_record(dict(encoded, required_features=["new"]))
    with pytest.raises(UnsupportedGoalVersion):
        decode_record(dict(encoded, kind="unknown"))


def test_history_rejects_gaps_cross_scope_and_active_goal_duplication():
    goal, store, _, _ = _goal_setup()
    with pytest.raises(GoalError):
        replay(store.header, [replace(store.records[0], sequence=2)])
    with pytest.raises(GoalError):
        replay(store.header, [replace(store.records[0], scope_id="other")])
    with pytest.raises(GoalError, match="active"):
        goal.create("g2", [Requirement("R", "another")], command_id="create2", limit=3)


@_run_goal_scenario
async def test_goal_current_basis_cannot_reuse_old_epoch_success():
    from loushang.harnesswork.goal import GoalAssessment
    from loushang.harnesswork.goal.records import basis_data

    goal, store, work, policy = _goal_setup()

    async def no_completion(basis, facts):
        return GoalAssessment(basis, "more_evidence", "not_yet")

    policy.assess = no_completion
    await goal.advance("g", command_id="first", revision=1, epoch=1)
    goal.control("g", "pause", command_id="pause", revision=1, epoch=1, reason="user")
    goal.control("g", "resume", command_id="resume", revision=1, epoch=2, reason="user")

    async def stale_success(basis, facts):
        return GoalAssessment(
            basis, "satisfied", "old", ("R",), ("op-0",), {"proof": "old"}
        )

    policy.assess = stale_success
    with pytest.raises(GoalError, match="old Goal basis"):
        await goal.advance("g", command_id="second", revision=1, epoch=3)
    state = goal.query("g")
    record = GoalRecord(
        goal.history.sequence + 1,
        "scope",
        "g",
        "acceptance_decided",
        "second",
        {
            "basis": basis_data(goal.header, state, goal.history.sequence),
            "coverage": ["R"],
            "operations": ["op-0"],
            "proof": {"old": True},
        },
    )
    with pytest.raises(GoalError, match="old operation"):
        replay(goal.header, [*store.records, record])


@_run_goal_scenario
async def test_goal_cleanup_failure_keeps_borrowed_owner_fenced():
    goal, _, _, policy = _goal_setup()
    began = asyncio.Event()

    async def broken_finally(basis, facts):
        began.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise OSError("reader cleanup still pending")

    policy.prepare = broken_finally
    task = asyncio.create_task(
        goal.advance("g", command_id="advance", revision=1, epoch=1)
    )
    await began.wait()
    with pytest.raises(OSError, match="cleanup still pending"):
        await goal.quiesce()
    assert task.done() and goal.fenced
    with pytest.raises(OSError, match="cleanup still pending"):
        goal.retire()
    with pytest.raises(OSError, match="cleanup still pending"):
        await goal.quiesce()


def test_goal_replay_rejects_changed_effect_and_repeated_revision():
    from loushang.harnesswork.goal.records import canonical

    goal, store, _, _ = _goal_setup()
    seq = goal.history.sequence
    command = GoalRecord(
        seq + 1,
        "scope",
        "g",
        "command_received",
        "revise",
        {
            "request": canonical(
                {
                    "action": "revise",
                    "goal_id": "g",
                    "revision": 1,
                    "epoch": 1,
                    "data": {
                        "requirements": [{"id": "R", "text": "new"}],
                        "reason": "user",
                    },
                }
            )
        },
    )
    event = GoalRecord(
        seq + 2,
        "scope",
        "g",
        "requirements_revised",
        "revise",
        {"requirements": [{"id": "R", "text": "new"}], "reason": "user"},
    )
    with pytest.raises(GoalError, match="duplicate command effect"):
        replay(
            goal.header,
            [*store.records, command, event, replace(event, sequence=seq + 3)],
        )
    with pytest.raises(GoalError, match="differs from accepted"):
        replay(
            goal.header,
            [
                *store.records,
                command,
                replace(
                    event,
                    data={
                        "requirements": [{"id": "R", "text": "forged"}],
                        "reason": "user",
                    },
                ),
            ],
        )


@_run_goal_scenario
async def test_goal_failed_cancellation_is_not_an_ordinary_retryable_failed_work():
    from loushang.harnesswork import WorkCancellationOutcome

    goal, store, _, policy = _goal_setup()
    started = asyncio.Event()

    class FailedCancellation:
        async def cancel_and_wait(self, operation, context):
            return WorkCancellationOutcome.failed(RuntimeError("domain did not settle"))

    async def blocked(operation, context):
        started.set()
        await asyncio.Event().wait()

    policy.execute = blocked
    work = WorkRuntime(
        event_log=InMemoryEventLogBackend(),
        executor=policy,
        cancellation=FailedCancellation(),
    )
    goal = GoalController(
        header=goal.header, store=store, work=work, next_work=policy, acceptance=policy
    )
    advance = asyncio.create_task(
        goal.advance("g", command_id="advance", revision=1, epoch=1)
    )
    await started.wait()
    with pytest.raises(RuntimeError, match="did not settle"):
        await goal.request_cancel("g")
    await asyncio.gather(advance, return_exceptions=True)
    assert goal.facts().unresolved is True
    assert work.query_runs()[0].status == "failed"
    if goal.query("g").status == "active":
        goal.control(
            "g", "pause", command_id="pause", revision=1, epoch=1, reason="user"
        )
    state = goal.query("g")
    with pytest.raises(GoalError, match="unresolved"):
        goal.control(
            "g",
            "resume",
            command_id="resume",
            revision=state.revision,
            epoch=state.epoch,
            reason="user",
        )


@_run_goal_scenario
async def test_goal_retired_controller_never_calls_cancel_port():
    goal, _, _, _ = _goal_setup()
    await goal.quiesce()
    await goal.settle_work()
    goal.retire()
    goal.retire()  # Idempotent without consulting retired borrowed ports.
    with pytest.raises(GoalError, match="retired"):
        await goal.request_cancel("g")


def test_goal_header_optional_extensions_roundtrip_without_changing_authority():
    from loushang.harnesswork.goal.records import decode_header, encode_header

    header = GoalHeader("scope", "s", "test-policy")
    encoded = dict(encode_header(header), ui_label={"color": "blue"})
    restored = decode_header(encoded)
    assert encode_header(restored) == encoded
    assert restored == header
    with pytest.raises(GoalError):
        decode_header(dict(encoded, required_features=["future-semantics"]))


@_run_goal_scenario
async def test_goal_resume_requires_remaining_allowance_and_fresh_confirmation():
    goal, _, _, policy = _goal_setup()

    async def no_completion(basis, facts):
        from loushang.harnesswork.goal import GoalAssessment

        return GoalAssessment(basis, "more_evidence", "not_yet")

    policy.assess = no_completion
    await goal.advance("g", command_id="first", revision=1, epoch=1)
    goal.control(
        "g", "pause", command_id="pause", revision=1, epoch=1, reason="user", limit=1
    )
    with pytest.raises(GoalError, match="batch_limit"):
        goal.control(
            "g", "resume", command_id="resume", revision=1, epoch=2, reason="user"
        )
    assert goal.query("g").status == "paused"
    goal.control(
        "g",
        "pause",
        command_id="raise-limit",
        revision=1,
        epoch=2,
        reason="explicit new allowance",
        limit=3,
    )
    policy.confirm_resume = lambda basis, facts: False
    with pytest.raises(GoalError, match="resume_not_ready"):
        goal.control(
            "g", "resume", command_id="resume2", revision=1, epoch=3, reason="user"
        )
    assert goal.query("g").status == "paused"
    policy.confirm_resume = lambda basis, facts: True
    assert (
        goal.control(
            "g", "resume", command_id="resume3", revision=1, epoch=3, reason="user"
        ).outcome
        == "resume"
    )


def test_goal_invalid_primary_command_does_not_leave_a_pending_admission():
    goal, store, _, _ = _goal_setup()
    count = len(store.records)
    with pytest.raises(GoalError):
        goal.revise("g", [], command_id="empty", revision=1, epoch=1, reason="bad")
    assert len(store.records) == count
    assert "empty" not in goal.history.commands


@_run_goal_scenario
async def test_goal_fence_blocks_resume_readers_and_close_blocks_external_cancel_admission():
    goal, _, _, policy = _goal_setup()
    goal.control("g", "pause", command_id="pause", revision=1, epoch=1, reason="user")
    calls = []
    policy.confirm_resume = lambda basis, facts: calls.append("reader") or True
    goal.fence()
    with pytest.raises(GoalError, match="fenced"):
        goal.control(
            "g", "resume", command_id="resume", revision=1, epoch=2, reason="user"
        )
    assert calls == []
    goal.begin_close()
    with pytest.raises(GoalError, match="closing"):
        await goal.request_cancel("g")
    assert calls == []
