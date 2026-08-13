from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime

from loushang.coding.adapters.harnesswork import create_coding_work_runtime
from loushang.harness.events import RuntimeEvent
from loushang.harnesswork.event_log import EventLogBackend
from loushang.harnesswork.integrations.session import (
    SessionWorkRuntime,
    SessionWorkTurn,
)


class FakePromptSession:
    def __init__(
        self, events: list[dict[str, object]], *, error: Exception | None = None
    ) -> None:
        self.events = events
        self.error = error
        self.prompts: list[str] = []
        self.listeners: list[
            Callable[[RuntimeEvent[object]], Awaitable[None] | None]
        ] = []

    def subscribe_runtime_events(
        self,
        listener: Callable[[RuntimeEvent[object]], Awaitable[None] | None],
    ) -> Callable[[], None]:
        self.listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self.listeners:
                self.listeners.remove(listener)

        return unsubscribe

    async def prompt(self, text: str) -> None:
        self.prompts.append(text)
        if self.error is not None:
            raise self.error
        for sequence, payload in enumerate(self.events, start=1):
            event = RuntimeEvent(
                event_id=f"event-{sequence}",
                kind=f"agent.{payload['type']}",
                stream_id="session:test",
                sequence=sequence,
                occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
                payload=payload,
            )
            for listener in list(self.listeners):
                result = listener(event)
                if result is not None:
                    await result


def _create_work_runtime(
    *,
    session: object,
    event_log: EventLogBackend,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SessionWorkRuntime:
    return create_coding_work_runtime(
        session=session,
        event_log=event_log,
        clock=clock,
    )


async def _submit_turn(
    runtime: SessionWorkRuntime,
    text: str,
    *,
    session_id: str,
    operation_id: str,
    run_id: str,
    images: Sequence[object] | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    planned_constraint: Mapping[str, object] | None = None,
    audit_policy: Mapping[str, object] | None = None,
    plan_facts: Mapping[str, object] | None = None,
    step_facts: Mapping[str, object] | None = None,
):
    return await runtime.submit_turn(
        SessionWorkTurn(
            text=text,
            images=images,
            method_id=method_id,
            plan_id=plan_id,
            step_id=step_id,
            step_index=step_index,
            step_title=step_title,
            planned_constraint=planned_constraint,
            audit_policy=audit_policy,
            plan_facts=plan_facts,
            step_facts=step_facts,
        ),
        session_id=session_id,
        operation_id=operation_id,
        run_id=run_id,
    )


def test_session_work_runtime_logs_coding_operation_and_projected_events() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(
            events=[
                {
                    "type": "message_update",
                    "message": {"role": "assistant"},
                    "assistant_message_event": {"type": "text_delta", "text": "done"},
                },
                {
                    "type": "tool_execution_end",
                    "tool_call_id": "tool-1",
                    "tool_name": "pytest",
                    "result": {"output": "passed"},
                    "is_error": False,
                },
            ],
        )
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "fix this bug",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        assert session.prompts == ["fix this bug"]
        assert run.status == "completed"
        assert len(session.listeners) == 0

        entries = event_log.query(run_id="run-1")
        assert [entry.entry_type for entry in entries] == [
            "operation",
            "event",
            "event",
            "event",
            "event",
        ]
        assert entries[0].payload == {
            "kind": "SubmitCodingTurn",
            "domain": "coding",
            "payload": {"text": "fix this bug"},
        }
        assert [entry.payload["kind"] for entry in entries[1:]] == [
            "WorkRunStarted",
            "ContentDelta",
            "ToolCallCompleted",
            "WorkRunCompleted",
        ]
        assert entries[2].payload["delivery_hint"] == "coalesce"
        assert entries[3].payload["delivery_hint"] == "coalesce"
        assert entries[4].payload["delivery_hint"] == "immediate"
        assert entries[2].payload["source_event_ref"] == "event-1"
        assert entries[3].payload["source_event_ref"] == "event-2"

    asyncio.run(scenario())


def test_session_work_runtime_projects_custom_messages_with_product_codec() -> None:
    from loushang.harness.transcript import ApplicationMessage
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        message = ApplicationMessage(
            application_message_id="application-1",
            custom_type="review-note",
            content="check this",
            display=True,
            details={"severity": "warning"},
            timestamp=1_780_309_800.0,
        )
        event_log = InMemoryEventLogBackend()
        work_runtime = _create_work_runtime(
            session=FakePromptSession(
                events=[{"type": "message_end", "message": message}]
            ),
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        await _submit_turn(
            work_runtime,
            "review",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        projected = event_log.query(run_id="run-1")[2]
        assert projected.payload["payload"]["message"] == {
            "role": "application",
            "applicationMessageId": "application-1",
            "customType": "review-note",
            "content": "check this",
            "display": True,
            "details": {"severity": "warning"},
            "timestamp": message.timestamp,
            "origin": "application",
            "deliveryMode": "direct",
        }

    asyncio.run(scenario())


def test_session_work_runtime_logs_tool_policy_and_approval_audit_events() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(
            events=[
                {
                    "type": "tool_policy_evaluated",
                    "tool_call_id": "tool-1",
                    "tool_name": "write",
                    "policy_disposition": "ask",
                    "policy_code": "tool_requires_approval",
                    "policy_reason": "Tool write requires approval",
                    "approval_required": True,
                    "argument_keys": ["content", "path"],
                    "path": "/repo/approved.txt",
                },
                {
                    "type": "tool_approval_requested",
                    "tool_call_id": "tool-1",
                    "tool_name": "write",
                    "action_id": "approval-1",
                    "policy_code": "tool_requires_approval",
                    "policy_reason": "Tool write requires approval",
                    "argument_keys": ["content", "path"],
                    "path": "/repo/approved.txt",
                },
                {
                    "type": "tool_approval_resolved",
                    "tool_call_id": "tool-1",
                    "tool_name": "write",
                    "action_id": "approval-1",
                    "approval_decision": "allow",
                    "policy_code": "tool_requires_approval",
                    "policy_reason": "Tool write requires approval",
                },
            ],
        )
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        await _submit_turn(
            work_runtime,
            "write approved file",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ToolPolicyEvaluated",
            "ToolApprovalRequested",
            "ToolApprovalResolved",
            "WorkRunCompleted",
        ]
        assert entries[2].payload["payload"]["tool_call_id"] == "tool-1"
        assert entries[2].payload["payload"]["policy_disposition"] == "ask"
        assert entries[3].payload["payload"]["action_id"] == "approval-1"
        assert entries[4].payload["payload"]["approval_decision"] == "allow"
        assert entries[2].payload["delivery_hint"] == "immediate"
        assert entries[3].payload["delivery_hint"] == "immediate"
        assert entries[4].payload["delivery_hint"] == "immediate"

    asyncio.run(scenario())


def test_session_work_runtime_jsonl_log_can_replay_persisted_turn(tmp_path) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.work import JsonlEventLogBackend

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )
    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="done")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    async def scenario() -> None:
        log_path = tmp_path / "events.jsonl"
        session = FakePromptSession(
            events=[
                {
                    "type": "message_update",
                    "message": {"role": "assistant"},
                    "assistant_message_event": {"type": "text_delta", "text": "done"},
                },
                {"type": "message_end", "message": assistant},
            ],
        )
        work_runtime = _create_work_runtime(
            session=session,
            event_log=JsonlEventLogBackend(log_path),
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "persist this turn",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        replayed = JsonlEventLogBackend(log_path).query(run_id=run.run_id)

        assert [entry.payload["kind"] for entry in replayed] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ContentDelta",
            "ContentDelta",
            "WorkRunCompleted",
        ]
        assert replayed[3].payload["payload"]["message"]["role"] == "assistant"
        assert replayed[4].payload["delivery_hint"] == "immediate"

    asyncio.run(scenario())


def test_session_work_runtime_records_method_id_as_metadata_only() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "fix this bug",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
            method_id="method:task:review",
        )

        assert session.prompts == ["fix this bug"]
        assert run.method_id == "method:task:review"

        entries = event_log.query(run_id="run-1")
        assert entries[0].payload["payload"]["method_id"] == "method:task:review"
        assert entries[1].payload["payload"]["method_id"] == "method:task:review"
        assert entries[2].payload["payload"]["method_id"] == "method:task:review"

    asyncio.run(scenario())


def test_session_work_runtime_records_plan_and_step_lifecycle_events() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )
        plan_facts = {
            "plan_id": "plan:method:task:review",
            "method_id": "method:task:review",
            "mode": "fixed",
        }
        step_facts = {
            "step_id": "inspect",
            "title": "Inspect current changes",
            "step_index": 0,
            "step_count": 2,
        }

        run = await _submit_turn(
            work_runtime,
            "inspect current changes",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
            method_id="method:task:review",
            plan_id="plan:method:task:review",
            step_id="inspect",
            step_index=0,
            step_title="Inspect current changes",
            planned_constraint={"level": "reasoned", "requires_reason": True},
            audit_policy={"record": ["status", "reason"]},
            plan_facts=plan_facts,
            step_facts=step_facts,
        )

        assert run.status == "completed"
        assert run.method_id == "method:task:review"
        assert run.plan_id == "plan:method:task:review"
        assert run.current_step_id == "inspect"

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]
        assert entries[0].payload["payload"] == {
            "text": "inspect current changes",
            "method_id": "method:task:review",
            "plan_id": "plan:method:task:review",
            "step_id": "inspect",
            "step_index": 0,
            "step_title": "Inspect current changes",
            "planned_constraint": {"level": "reasoned", "requires_reason": True},
            "audit_policy": {"record": ["status", "reason"]},
            "plan_facts": plan_facts,
            "step_facts": step_facts,
        }
        assert entries[2].payload["delivery_hint"] == "coalesce"
        assert entries[3].payload["delivery_hint"] == "coalesce"
        assert entries[4].payload["delivery_hint"] == "coalesce"
        assert entries[5].payload["delivery_hint"] == "final_only"
        assert entries[3].payload["payload"] == {
            "source_type": "work_shell",
            "method_id": "method:task:review",
            "plan_id": "plan:method:task:review",
            "step_id": "inspect",
            "step_index": 0,
            "step_title": "Inspect current changes",
            "planned_constraint": {"level": "reasoned", "requires_reason": True},
            "audit_policy": {"record": ["status", "reason"]},
            "plan_facts": plan_facts,
            "step_facts": step_facts,
        }
        assert entries[2].payload["payload"]["plan_facts"] == plan_facts
        assert entries[2].payload["payload"]["step_facts"] == step_facts
        assert entries[4].payload["payload"]["plan_facts"] == plan_facts
        assert entries[4].payload["payload"]["step_facts"] == step_facts
        assert entries[5].payload["payload"]["plan_facts"] == plan_facts
        assert entries[5].payload["payload"]["step_facts"] == step_facts

    asyncio.run(scenario())


def test_session_work_runtime_always_emits_plan_boundaries_for_a_planned_run() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "verify current changes",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
            method_id="method:task:review",
            plan_id="plan:method:task:review",
            step_id="verify",
            step_index=1,
            step_title="Run focused checks",
        )

        assert run.status == "completed"
        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]

    asyncio.run(scenario())


def test_session_work_runtime_records_complete_plan_failure_lifecycle() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[], error=RuntimeError("middle step failed"))
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        try:
            await _submit_turn(
                work_runtime,
                "verify current changes",
                session_id="session-1",
                operation_id="op-1",
                run_id="run-1",
                method_id="method:task:review",
                plan_id="plan:method:task:review",
                step_id="verify",
                step_index=1,
                step_title="Run focused checks",
            )
        except RuntimeError as error:
            assert str(error) == "middle step failed"
        else:
            raise AssertionError("expected prompt failure")

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]

    asyncio.run(scenario())


def test_session_work_runtime_records_step_and_plan_failures_before_run_failure() -> (
    None
):
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[], error=RuntimeError("agent failed"))
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )
        plan_facts = {
            "plan_id": "plan:method:task:review",
            "method_id": "method:task:review",
        }
        step_facts = {"step_id": "inspect", "step_index": 0}

        try:
            await _submit_turn(
                work_runtime,
                "inspect current changes",
                session_id="session-1",
                operation_id="op-1",
                run_id="run-1",
                method_id="method:task:review",
                plan_id="plan:method:task:review",
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
                plan_facts=plan_facts,
                step_facts=step_facts,
            )
        except RuntimeError as error:
            assert str(error) == "agent failed"
        else:
            raise AssertionError("expected prompt failure")

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]
        assert entries[4].payload["delivery_hint"] == "immediate"
        assert entries[5].payload["delivery_hint"] == "immediate"
        assert entries[4].payload["payload"]["error"] == "agent failed"
        assert entries[5].payload["payload"]["error"] == "agent failed"
        assert entries[4].payload["payload"]["plan_facts"] == plan_facts
        assert entries[4].payload["payload"]["step_facts"] == step_facts
        assert entries[5].payload["payload"]["plan_facts"] == plan_facts
        assert entries[5].payload["payload"]["step_facts"] == step_facts
        assert entries[6].payload["payload"]["method_id"] == "method:task:review"
        assert entries[6].payload["payload"]["plan_id"] == "plan:method:task:review"
        assert entries[6].payload["payload"]["step_id"] == "inspect"

    asyncio.run(scenario())


def test_session_work_runtime_unsubscribes_on_success_failure_and_cancellation() -> (
    None
):
    from loushang.work import InMemoryEventLogBackend

    class TrackingSession:
        def __init__(self, outcome: str) -> None:
            self.outcome = outcome
            self.listener = None
            self.prompt_started = asyncio.Event()
            self.unsubscribe_calls = 0

        def subscribe_runtime_events(self, listener):
            self.listener = listener

            def unsubscribe() -> None:
                self.unsubscribe_calls += 1
                self.listener = None

            return unsubscribe

        async def prompt(self, text: str, images=None) -> None:
            del text, images
            self.prompt_started.set()
            if self.outcome == "failure":
                raise RuntimeError("prompt failed")
            if self.outcome == "cancellation":
                await asyncio.Event().wait()

    async def scenario() -> None:
        for outcome in ("success", "failure", "cancellation"):
            event_log = InMemoryEventLogBackend()
            session = TrackingSession(outcome)
            work_runtime = _create_work_runtime(
                session=session,
                event_log=event_log,
            )
            task = asyncio.create_task(
                _submit_turn(
                    work_runtime,
                    outcome,
                    session_id="session-1",
                    operation_id=f"op-{outcome}",
                    run_id=f"run-{outcome}",
                )
            )
            await session.prompt_started.wait()
            if outcome == "cancellation":
                task.cancel()
            try:
                await task
            except RuntimeError:
                assert outcome == "failure"
            except asyncio.CancelledError:
                assert outcome == "cancellation"

            assert session.unsubscribe_calls == 1
            assert session.listener is None
            entries = event_log.query(run_id=f"run-{outcome}")
            terminal_kinds = {
                "WorkRunCompleted",
                "WorkRunFailed",
                "WorkRunCancelled",
            }
            assert (
                sum(entry.payload["kind"] in terminal_kinds for entry in entries) == 1
            )
            assert entries[-1].payload["kind"] in terminal_kinds

    asyncio.run(scenario())


def test_session_work_runtime_runs_method_plan_as_one_sequential_run() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
        )
        turns = (
            SessionWorkTurn(
                text="inspect",
                method_id="method-1",
                plan_id="plan-1",
                step_id="step-1",
                step_index=0,
                step_title="Inspect",
            ),
            SessionWorkTurn(
                text="verify",
                method_id="method-1",
                plan_id="plan-1",
                step_id="step-2",
                step_index=1,
                step_title="Verify",
            ),
        )

        run = await work_runtime.submit_plan(
            turns,
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        assert run.status == "completed"
        assert session.prompts == ["inspect", "verify"]
        entries = event_log.query(run_id="run-1")
        assert {entry.run_id for entry in entries} == {"run-1"}
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
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


def test_session_work_runtime_reuses_one_session_scoped_work_runtime() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
        )

        first = await _submit_turn(
            work_runtime,
            "first",
            session_id="session-1",
            operation_id="op-first",
            run_id="run-first",
        )
        second = await _submit_turn(
            work_runtime,
            "second",
            session_id="session-1",
            operation_id="op-second",
            run_id="run-second",
        )

        assert first.status == second.status == "completed"
        assert work_runtime.work_runtime.get_run_for_operation("op-first") == first
        assert work_runtime.work_runtime.get_run_for_operation("op-second") == second
        assert event_log.checkpoint().offset == 6

    asyncio.run(scenario())


def test_agent_start_and_end_are_non_terminal_invocation_facts() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        work_runtime = _create_work_runtime(
            session=FakePromptSession(
                events=[
                    {"type": "agent_start"},
                    {"type": "agent_end", "messages": []},
                ]
            ),
            event_log=event_log,
        )

        await _submit_turn(
            work_runtime,
            "run",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        kinds = [entry.payload["kind"] for entry in event_log.query(run_id="run-1")]
        assert kinds == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "AgentInvocationStarted",
            "AgentInvocationCompleted",
            "WorkRunCompleted",
        ]
        assert kinds.count("WorkRunStarted") == 1
        assert kinds.count("WorkRunCompleted") == 1

    asyncio.run(scenario())
