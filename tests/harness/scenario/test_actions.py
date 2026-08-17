from __future__ import annotations

import asyncio


def test_fake_backend_aborts_active_run_and_recovers_next_prompt(tmp_path) -> None:
    from loushang.harness.scenario import (
        AbortStep,
        PromptStep,
        WaitForStep,
        Workflow,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    adapter = FakeWorkflowAdapter()
    workflow = Workflow(
        name="abort",
        backend="fake",
        steps=(
            PromptStep(prompt="old task", hold=True),
            WaitForStep(event="run.started"),
            AbortStep(),
            WaitForStep(event="run.aborted"),
            PromptStep(prompt="你好"),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is True
    assert [event.type for event in result.events] == [
        "run.started",
        "run.aborted",
        "run.started",
        "assistant.message",
        "run.ended",
    ]
    assert [event.type for event in adapter.events()] == [
        "run.started",
        "run.aborted",
        "run.started",
        "assistant.message",
        "run.ended",
    ]
    assert adapter.events()[-2].text == "你好"


def test_fake_backend_records_steer_and_follow_up_queues(tmp_path) -> None:
    from loushang.harness.scenario import (
        FollowUpStep,
        PromptStep,
        SteerStep,
        WaitForStep,
        Workflow,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    adapter = FakeWorkflowAdapter()
    workflow = Workflow(
        name="queues",
        backend="fake",
        steps=(
            PromptStep(prompt="active task", hold=True),
            WaitForStep(event="run.started"),
            SteerStep(text="change direction"),
            FollowUpStep(text="next turn"),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is True
    assert adapter.queue_state().steering == ("change direction",)
    assert adapter.queue_state().follow_up == ("next turn",)
    assert [event.type for event in adapter.events()] == [
        "run.started",
        "queue.steer_added",
        "queue.follow_up_added",
    ]


def test_wait_step_sleeps_for_duration(monkeypatch, tmp_path) -> None:
    from loushang.harness.scenario import WaitStep, Workflow, run_workflow
    from loushang.harness.scenario import runner as runner_module
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    sleeps: list[float] = []

    async def fake_sleep(duration_s: float) -> None:
        sleeps.append(duration_s)

    monkeypatch.setattr(runner_module.asyncio, "sleep", fake_sleep)

    workflow = Workflow(
        name="wait",
        backend="fake",
        steps=(WaitStep(duration_s=0.25),),
    )

    result = asyncio.run(
        run_workflow(workflow, adapter=FakeWorkflowAdapter(), cwd=tmp_path)
    )

    assert result.ok is True
    assert sleeps == [0.25]
    assert result.step_results[0].prompt == "wait 0.25s"


def test_expect_step_checks_events_absence_and_queue_state(tmp_path) -> None:
    from loushang.harness.scenario import (
        AbortStep,
        EventPattern,
        ExpectStep,
        PromptStep,
        Workflow,
        WorkflowExpectation,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    adapter = FakeWorkflowAdapter()
    workflow = Workflow(
        name="expect",
        backend="fake",
        steps=(
            PromptStep(prompt="old task", hold=True),
            AbortStep(),
            PromptStep(prompt="你好"),
            ExpectStep(
                expect=WorkflowExpectation(
                    events=(EventPattern(event="assistant.message", contains="你好"),),
                    not_events=(
                        EventPattern(event="assistant.message", contains="old task"),
                    ),
                    queue={"steering": (), "follow_up": ()},
                )
            ),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is True
    assert result.step_results[-1].checks
    assert all(check.ok for check in result.step_results[-1].checks)


def test_expect_step_checks_session_state_snapshot(tmp_path) -> None:
    from loushang.harness.scenario import (
        ExpectStep,
        FollowUpStep,
        PromptStep,
        SteerStep,
        WaitForStep,
        Workflow,
        WorkflowExpectation,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    adapter = FakeWorkflowAdapter()
    workflow = Workflow(
        name="state",
        backend="fake",
        steps=(
            PromptStep(prompt="long", hold=True),
            WaitForStep(event="run.started"),
            SteerStep(text="change direction"),
            FollowUpStep(text="later"),
            ExpectStep(
                expect=WorkflowExpectation(
                    session_state={
                        "runStatus": "running",
                        "pendingMessageCount": 2,
                        "queue": {
                            "steering": ("change direction",),
                            "followUp": ("later",),
                        },
                    }
                )
            ),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is True
    assert [check.label for check in result.step_results[-1].checks] == [
        "session_state.runStatus",
        "session_state.pendingMessageCount",
        "session_state.queue.steering",
        "session_state.queue.followUp",
    ]


def test_expect_step_checks_session_stats_and_context_usage_snapshots(tmp_path) -> None:
    from loushang.harness.scenario import (
        ExpectStep,
        PromptStep,
        Workflow,
        WorkflowExpectation,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    adapter = FakeWorkflowAdapter()
    workflow = Workflow(
        name="facts",
        backend="fake",
        steps=(
            PromptStep(prompt="hello"),
            ExpectStep(
                expect=WorkflowExpectation(
                    session_stats={
                        "totalMessages": 1,
                        "tokens": {"total": 10},
                        "latestCompaction": None,
                    },
                    context_usage={
                        "messageCount": 1,
                        "estimatedContextTokens": 10,
                        "compactPercent": 80,
                    },
                )
            ),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is True
    assert [check.label for check in result.step_results[-1].checks] == [
        "session_stats.totalMessages",
        "session_stats.tokens.total",
        "session_stats.latestCompaction",
        "context_usage.messageCount",
        "context_usage.estimatedContextTokens",
        "context_usage.compactPercent",
    ]


def test_expect_step_reports_missing_event(tmp_path) -> None:
    from loushang.harness.scenario import (
        EventPattern,
        ExpectStep,
        Workflow,
        WorkflowExpectation,
        run_workflow,
    )
    from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter

    adapter = FakeWorkflowAdapter()
    workflow = Workflow(
        name="missing",
        backend="fake",
        steps=(
            ExpectStep(
                expect=WorkflowExpectation(
                    events=(EventPattern(event="assistant.message", contains="never"),),
                )
            ),
        ),
    )

    result = asyncio.run(run_workflow(workflow, adapter=adapter, cwd=tmp_path))

    assert result.ok is False
    assert result.step_results[0].checks[0].ok is False
    assert "missing event" in result.step_results[0].checks[0].detail
