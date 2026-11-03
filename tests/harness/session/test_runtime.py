from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from loushang.agent import Agent
from loushang.harness.conversation import CommitReceipt
from loushang.harness.events import RuntimeEvent
from loushang.harness.session import (
    AfterTurnPolicyPort,
    SessionRuntime,
    TranscriptRuntimePort,
    TurnPolicyPort,
)
from loushang.harness.transcript import (
    ApplicationMessage,
    AutoCompactionOutcome,
    AutoRetryOutcome,
    CommitResult,
    CompactionResult,
)


@dataclass(frozen=True)
class _PreflightResult:
    text: str
    consumed: bool = False


class _RetryPort:
    async def finish_success_if_needed(self, assistant_message: object) -> None:
        del assistant_message

    def should_prepare_retry(self, assistant_message: object) -> bool:
        del assistant_message
        return False

    def ensure_future(self) -> None:
        return None

    def is_retryable_error(self, assistant_message: object) -> bool:
        del assistant_message
        return False

    async def handle_retryable_error(
        self, assistant_message: object
    ) -> AutoRetryOutcome:
        del assistant_message
        return AutoRetryOutcome()

    def continue_retry(self, continue_run: object) -> None:
        del continue_run


class _CompactionPort:
    def clear_overflow_recovery_attempted(self) -> None:
        return None


def test_session_runtime_owns_turn_input_and_direct_application_projection() -> None:
    async def scenario() -> None:
        agent = Agent()
        prompted: list[list[object]] = []
        refreshed = 0
        commit_observer = None
        events: list[RuntimeEvent[object]] = []

        async def prompt(messages: list[object], images: object = None) -> None:
            del images
            prompted.append(messages)

        async def commit_application_message(
            message: ApplicationMessage,
        ) -> CommitResult:
            assert message.application_message_id == "direct-1"
            return CommitResult(
                record_id="record-1",
                disposition="committed",
                receipt=None,
            )

        def refresh_context() -> None:
            nonlocal refreshed
            refreshed += 1

        def set_commit_observer(observer) -> None:
            nonlocal commit_observer
            commit_observer = observer

        async def preflight(text: str, **kwargs: object) -> _PreflightResult:
            del kwargs
            return _PreflightResult(text=f"prepared:{text}")

        async def no_compaction() -> AutoCompactionOutcome:
            return AutoCompactionOutcome()

        agent.prompt = prompt  # type: ignore[method-assign]
        runtime = SessionRuntime(
            agent=agent,
            transcript=TranscriptRuntimePort(
                session_id="session-1",
                append_message=lambda message: _append_message(message),
                commit_application_message=commit_application_message,
                refresh_context=refresh_context,
                set_commit_observer=set_commit_observer,
            ),
            turn_policy=TurnPolicyPort(
                get_extension_runner=lambda: None,
                get_cwd=lambda: "/tmp/project",
                extract_extension_command_invocation=lambda text: None,
                execute_command_async=lambda name, args: _execute_command(name, args),
                preflight_user_input=lambda text: _PreflightResult(text=text),
                reject_queued_extension_command=lambda text: None,
                preflight_user_input_async=preflight,
                before_agent_start_system_prompt_options=lambda: {},
                sync_extension_diagnostics=lambda **kwargs: None,
                compact_before_prompt_async=no_compaction,
            ),
            after_turn_policy=_after_turn_policy(),
        )
        runtime.subscribe(events.append)

        await runtime.prompt("hello")
        assert prompted[0][0].content[0].text == "prepared:hello"

        await runtime.application_inputs.deliver(
            ApplicationMessage(
                application_message_id="direct-1",
                custom_type="notice",
                content="saved directly",
                timestamp=0.0,
                origin="extension",
                delivery_mode="direct",
            )
        )

        assert refreshed == 1
        assert [event.kind for event in events] == [
            "agent.message_start",
            "agent.message_end",
        ]
        assert callable(commit_observer)

        await runtime.dispose()
        assert commit_observer is None

    asyncio.run(scenario())


def test_session_runtime_schedules_explicit_auto_compaction_continuation() -> None:
    async def scenario() -> None:
        agent = Agent()
        continued: list[bool] = []
        result = CompactionResult(
            summary="summary",
            first_kept_entry_id="record-1",
            tokens_before=100,
        )

        async def continue_run(*, model_call_purpose="continuation") -> None:
            assert model_call_purpose == "continuation"
            continued.append(True)

        async def check_auto_compaction(message: object) -> AutoCompactionOutcome:
            del message
            return AutoCompactionOutcome(result=result, should_continue=True)

        agent.continue_run = continue_run  # type: ignore[method-assign]
        runtime = SessionRuntime(
            agent=agent,
            transcript=TranscriptRuntimePort(
                session_id="session-1",
                append_message=_append_message,
                commit_application_message=_commit_application_message,
                refresh_context=lambda: None,
                set_commit_observer=lambda observer: None,
            ),
            turn_policy=_turn_policy(),
            after_turn_policy=AfterTurnPolicyPort(
                emit_extension_agent_event=lambda event: _execute_command("", ""),
                record_tool_execution_error=lambda event: None,
                retry_controller=_RetryPort(),
                compaction_controller=_CompactionPort(),
                sync_extension_diagnostics=lambda **kwargs: None,
                record_assistant_response_error=lambda message: None,
                check_auto_compaction=check_auto_compaction,
            ),
        )

        assert await runtime.check_auto_compaction(object()) is result  # type: ignore[arg-type]
        await asyncio.sleep(0)
        await runtime.wait_for_idle()
        assert continued == [True]
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_runtime_publishes_transcript_commit_receipts_in_order() -> None:
    async def scenario() -> None:
        agent = Agent()
        commit_observer = None
        events: list[RuntimeEvent[object]] = []

        def set_commit_observer(observer) -> None:
            nonlocal commit_observer
            commit_observer = observer

        runtime = SessionRuntime(
            agent=agent,
            transcript=TranscriptRuntimePort(
                session_id="session-2",
                append_message=lambda message: _append_message(message),
                commit_application_message=lambda message: _commit_application_message(
                    message
                ),
                refresh_context=lambda: None,
                set_commit_observer=set_commit_observer,
            ),
            turn_policy=_turn_policy(),
            after_turn_policy=_after_turn_policy(),
        )
        runtime.subscribe(events.append)

        assert callable(commit_observer)
        commit_observer(
            CommitResult(
                record_id="record-2",
                disposition="committed",
                receipt=CommitReceipt(
                    revision=3,
                    committed_at=datetime.now(timezone.utc),
                    record_id="record-2",
                ),
            )
        )
        await asyncio.sleep(0)

        assert [(event.kind, event.source_record_id) for event in events] == [
            ("transcript.record_committed", "record-2")
        ]
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_runtime_removes_queued_application_message_when_agent_consumes_it() -> (
    None
):
    async def scenario() -> None:
        agent = Agent()
        runtime = SessionRuntime(
            agent=agent,
            transcript=TranscriptRuntimePort(
                session_id="session-queued-application",
                append_message=lambda message: _append_message(message),
                commit_application_message=lambda message: _commit_application_message(
                    message
                ),
                refresh_context=lambda: None,
                set_commit_observer=lambda observer: None,
            ),
            turn_policy=_turn_policy(),
            after_turn_policy=_after_turn_policy(),
        )
        message = ApplicationMessage(
            application_message_id="completion-1",
            custom_type="harness.multiagent.completion_notice",
            content="/root/reviewer completed (round 1).",
            timestamp=0.0,
            display=False,
            delivery_mode="steering",
        )

        await runtime.application_inputs.deliver(message)
        assert runtime.queue.get_steering_messages() == [message.content]

        await runtime.handle_agent_event(
            {"type": "message_start", "message": message},
            object(),
        )

        assert runtime.queue.get_steering_messages() == []
        assert runtime.queue.pending_message_count == 0
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_runtime_defers_continue_until_host_is_idle() -> None:
    async def scenario() -> None:
        agent = Agent()
        release = asyncio.Event()
        continued: list[bool] = []

        async def continue_run() -> None:
            continued.append(True)

        agent.continue_run = continue_run  # type: ignore[method-assign]
        runtime = SessionRuntime(
            agent=agent,
            transcript=TranscriptRuntimePort(
                session_id="session-3",
                append_message=lambda message: _append_message(message),
                commit_application_message=lambda message: _commit_application_message(
                    message
                ),
                refresh_context=lambda: None,
                set_commit_observer=lambda observer: None,
            ),
            turn_policy=_turn_policy(),
            after_turn_policy=_after_turn_policy(),
        )

        active = asyncio.create_task(
            runtime.host_runtime.run(lambda: release.wait())
        )
        await asyncio.sleep(0)
        deferred = asyncio.create_task(runtime.continue_run())
        await asyncio.sleep(0)
        assert not deferred.done()

        release.set()
        await active
        await deferred
        assert continued == [True]
        await runtime.dispose()

    asyncio.run(scenario())


def _turn_policy() -> TurnPolicyPort:
    async def preflight(text: str, **kwargs: object) -> _PreflightResult:
        del kwargs
        return _PreflightResult(text=text)

    return TurnPolicyPort(
        get_extension_runner=lambda: None,
        get_cwd=lambda: "/tmp/project",
        extract_extension_command_invocation=lambda text: None,
        execute_command_async=lambda name, args: _execute_command(name, args),
        preflight_user_input=lambda text: _PreflightResult(text=text),
        reject_queued_extension_command=lambda text: None,
        preflight_user_input_async=preflight,
        before_agent_start_system_prompt_options=lambda: {},
        sync_extension_diagnostics=lambda **kwargs: None,
    )


def _after_turn_policy() -> AfterTurnPolicyPort:
    async def emit_extension_agent_event(event: object) -> None:
        del event

    async def check_auto_compaction(message: object) -> AutoCompactionOutcome:
        del message
        return AutoCompactionOutcome()

    return AfterTurnPolicyPort(
        emit_extension_agent_event=emit_extension_agent_event,
        record_tool_execution_error=lambda event: None,
        retry_controller=_RetryPort(),
        compaction_controller=_CompactionPort(),
        sync_extension_diagnostics=lambda **kwargs: None,
        record_assistant_response_error=lambda message: None,
        check_auto_compaction=check_auto_compaction,
    )


async def _append_message(message: object) -> str:
    del message
    return "record"


async def _commit_application_message(message: ApplicationMessage) -> CommitResult:
    del message
    return CommitResult(
        record_id="application-record",
        disposition="committed",
        receipt=None,
    )


async def _execute_command(name: str, args: str) -> None:
    del name, args


def _admission_runtime(agent: Agent, *, turn_policy=None, application_committer=None, refresh=None) -> SessionRuntime:
    return SessionRuntime(
        agent=agent,
        transcript=TranscriptRuntimePort(
            session_id="shared-session", append_message=_append_message,
            commit_application_message=application_committer or _commit_application_message,
            refresh_context=refresh or (lambda: None), set_commit_observer=lambda observer: None,
        ),
        turn_policy=turn_policy or _turn_policy(), after_turn_policy=_after_turn_policy(),
    )


def test_prompt_preflight_invalidates_reserved_execution_and_clear_blocks_late_input():
    from dataclasses import replace

    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        agent = Agent()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def preflight(text, **kwargs):
            started.set()
            await release.wait()
            return _PreflightResult(text)

        async def prompt(messages, **kwargs):
            calls.append(messages)

        agent.prompt = prompt
        runtime = _admission_runtime(agent, turn_policy=replace(
            _turn_policy(), preflight_user_input_async=preflight,
        ))
        reservation = runtime.execution_admission.reserve("candidate-awaiting-prepare")
        ordinary = asyncio.create_task(runtime.prompt("ordinary", source="goal_planning"))
        await started.wait()
        assert reservation.state == "invalidated"
        with pytest.raises(SessionExecutionUnavailable):
            reservation.commit()
        reservation.release()
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve("cannot-overtake-preflight")
        runtime.queue.clear_queue()
        release.set()
        with pytest.raises(SessionExecutionUnavailable, match="cleared"):
            await ordinary
        assert calls == [] and runtime.queue.pending_message_count == 0
        later = runtime.execution_admission.reserve("after-clear")
        later.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_committed_execution_uses_original_host_and_holds_original_input_queue():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        agent = Agent()
        calls = []
        runtime = _admission_runtime(agent)

        async def prompt(messages, **kwargs):
            assert runtime.host_runtime.is_active
            calls.append(messages)

        agent.prompt = prompt
        permit = runtime.execution_admission.reserve("accepted-work")
        permit.commit()
        # Text source cannot confer authority, even before the Agent starts.
        await runtime.prompt("ordinary", source="goal_planning")
        assert runtime.queue.get_follow_up_messages() == ["ordinary"]
        assert not agent.has_queued_messages() and not calls
        with permit.executing():
            configuration = runtime.execution_configuration.install(permit)
            await runtime.prompt_in_execution(permit, "bound")
            with pytest.raises(SessionExecutionUnavailable, match="task"):
                await asyncio.create_task(runtime.prompt_in_execution(permit, "child"))
            configuration.release()
        assert len(calls) == 1
        assert [part.text for part in calls[0][0].content] == ["bound"]
        with pytest.raises(SessionExecutionUnavailable, match="settle"):
            permit.release()
        permit.begin_settling()
        permit.release()
        permit.release()
        assert agent.has_queued_messages()
        assert runtime.queue.get_follow_up_messages() == ["ordinary"]
        runtime.queue.clear_queue()
        await runtime.dispose()

    asyncio.run(scenario())


def test_clear_does_not_resurrect_delivery_when_execution_is_released():
    async def scenario():
        agent = Agent()
        runtime = _admission_runtime(agent)
        permit = runtime.execution_admission.reserve("accepted-work")
        permit.commit()
        await runtime.prompt("will-be-cleared")
        assert runtime.queue.pending_message_count == 1
        runtime.queue.clear_queue()
        permit.begin_settling()
        permit.release()
        assert runtime.queue.pending_message_count == 0
        assert not agent.has_queued_messages()
        await runtime.dispose()

    asyncio.run(scenario())


def test_reservation_identity_is_per_runtime_and_direct_runs_are_isolated():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        first, second = _admission_runtime(Agent()), _admission_runtime(Agent())
        permit = first.execution_admission.reserve("same-logical-session")
        permit.commit()
        with permit.executing():
            with pytest.raises(SessionExecutionUnavailable, match="foreign"):
                await second.prompt_in_execution(permit, "wrong-instance")
            with pytest.raises(SessionExecutionUnavailable, match="reserved"):
                await first.run_agent_prompt("side-question")
            pending = first.schedule_continue_run(model_call_purpose="retry")
            await asyncio.sleep(0)
            assert not pending.done() and not first.host_runtime.is_active
        first.execution_admission.close_admission()
        with pytest.raises(SessionExecutionUnavailable):
            await pending
        with pytest.raises(SessionExecutionUnavailable):
            await first.prompt("after-close")
        permit.begin_settling()
        permit.release()
        await first.dispose()
        await second.dispose()

    asyncio.run(scenario())


def test_next_turn_and_registered_deferred_runs_win_admission_priority():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        agent = Agent()
        calls = []

        async def continued(*, model_call_purpose="continuation"):
            calls.append(model_call_purpose)

        agent.continue_run = continued
        runtime = _admission_runtime(agent)
        runtime.queue.append_next_turn_message(object())
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve("cannot-overtake-next-turn")
        runtime.queue.drain_next_turn_messages()
        pending = runtime.schedule_continue_run(model_call_purpose="retry")
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve("cannot-overtake-registered-task")
        await pending
        permit = runtime.execution_admission.reserve("candidate")
        pending = runtime.schedule_continue_run(model_call_purpose="retry")
        with pytest.raises(SessionExecutionUnavailable):
            permit.commit()
        permit.release()
        await pending
        assert calls == ["retry", "retry"]
        await runtime.dispose()

    asyncio.run(scenario())


def test_failed_delivery_evidence_binding_retries_without_duplicate_delivery():
    import pytest

    class Evidence:
        fail = True
        bindings = []

        def bind(self, message, evidence, *, owner):
            self.bindings.append((message, owner))
            if self.fail:
                raise RuntimeError("partial evidence binding")

        def discard_owner(self, owner):
            self.bindings[:] = [item for item in self.bindings if item[1] is not owner]

    async def scenario():
        agent = Agent()
        runtime = _admission_runtime(agent)
        evidence = Evidence()
        runtime.queue.request_evidence = evidence
        permit = runtime.execution_admission.reserve("work")
        permit.commit()
        runtime.queue.queue_prepared_follow_up("same-message", request_evidence=object())
        queued_id = runtime.queue.get_queue_snapshot().follow_up[0].id
        permit.begin_settling()
        with pytest.raises(RuntimeError, match="partial evidence"):
            permit.release()
        assert permit.state == "settling" and len(agent.follow_up_queue._messages) == 1
        delivered = agent.follow_up_queue._messages[0]
        evidence.fail = False
        permit.release()
        assert len(agent.follow_up_queue._messages) == 1
        assert evidence.bindings == [(delivered, evidence.bindings[0][1])]
        assert runtime.queue.get_queue_snapshot().follow_up[0].id == queued_id
        runtime.queue.clear_queue()
        assert not evidence.bindings
        await runtime.dispose()

    asyncio.run(scenario())


def test_session_disposal_retains_execution_until_original_owner_releases():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        agent = Agent()
        runtime = _admission_runtime(agent)
        permit = runtime.execution_admission.reserve("work")
        permit.commit()
        runtime.queue.follow_up("held")
        with pytest.raises(SessionExecutionUnavailable, match="release"):
            await runtime.dispose()
        assert not runtime.host_runtime.is_disposed
        permit.begin_settling()
        permit.release()
        assert not agent.has_queued_messages()  # No delivery into a closing Session.
        await runtime.dispose()
        assert runtime.host_runtime.is_disposed

    asyncio.run(scenario())


def test_existing_work_factory_reuses_session_backend_and_commits_at_original_resolver():
    from dataclasses import MISSING, fields

    import pytest

    from loushang.coding.adapters.harnesswork import create_coding_work_runtime
    from loushang.harness.session import SessionFacade
    from loushang.harnesswork import InMemoryEventLogBackend
    from loushang.harnesswork.ports import WorkExecutionBinding
    from loushang.harnesswork.types import WorkOperation

    async def scenario():
        agent = Agent()
        runtime = _admission_runtime(agent)
        calls = []

        async def prompt(messages, **kwargs):
            calls.append(messages)

        agent.prompt = prompt
        unused = {field.name: None for field in fields(SessionFacade)
                  if field.name != "runtime" and field.default is MISSING}
        facade = SessionFacade(runtime=runtime, **unused)
        log = InMemoryEventLogBackend()
        backend = create_coding_work_runtime(session=facade, event_log=log)
        assert create_coding_work_runtime(session=facade, event_log=log) is backend
        with pytest.raises(ValueError, match="configuration differs"):
            create_coding_work_runtime(session=facade, event_log=InMemoryEventLogBackend())
        permit = runtime.execution_admission.reserve("model-plan")

        class Executor:
            async def execute(self, operation, context):
                assert operation.operation_id == permit.operation_id
                with permit.executing():
                    handle = facade.configure_execution(permit)
                    try:
                        await facade.prompt_in_execution(permit, "bound original Work")
                    finally:
                        handle.release()

        backend.prepare_binding("model-plan", WorkExecutionBinding(Executor()), commit=permit.commit)
        run = await backend.work_runtime.accept(WorkOperation("model-plan", "DomainPlanning", "shared-session", "design", {}))
        assert permit.state == "committed"
        completed = await backend.work_runtime.wait(run.run_id)
        assert completed.status == "completed" and len(calls) == 1
        permit.begin_settling()
        permit.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_prepared_binding_commit_refusal_does_not_execute_or_lose_original_slot():
    import pytest

    from loushang.harnesswork import InMemoryEventLogBackend
    from loushang.harnesswork.integrations.session import (
        SessionWorkProfile,
        SessionWorkRuntime,
    )
    from loushang.harnesswork.ports import WorkExecutionBinding
    from loushang.harnesswork.types import WorkOperation

    async def scenario():
        called = []

        class Executor:
            async def execute(self, operation, context):
                called.append(operation.operation_id)

        def refuse():
            raise RuntimeError("input won admission")

        runtime = SessionWorkRuntime(
            session=object(), event_log=InMemoryEventLogBackend(),
            profile=SessionWorkProfile(domain="design", operation_kind="Turn"),
            project_event_facts=lambda event: (),
        )
        runtime.prepare_binding("candidate", WorkExecutionBinding(Executor()), commit=refuse)
        operation = WorkOperation("candidate", "Planning", "same-session", "design", {})
        with pytest.raises(RuntimeError, match="input won"):
            await runtime.work_runtime.accept(operation)
        assert not called and runtime.work_runtime.get_run_for_operation("candidate") is None
        with pytest.raises(ValueError, match="already prepared"):
            runtime.prepare_binding("candidate", WorkExecutionBinding(Executor()), commit=lambda: None)
        runtime.discard_binding("candidate")

    asyncio.run(scenario())


def _admission_response():
    from loushang.ai.event_stream.stream import AssistantMessageEventStream
    from loushang.ai.types import AssistantMessage, TextPart, Usage

    message = AssistantMessage(
        endpoint="offline", role="assistant", content=[TextPart(type="text", text="done")],
        api="anthropic-messages", provider="offline", model="offline", response_id=None,
        usage=Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}),
        stop_reason="stop", error_message=None, timestamp=0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "done", "reason": "stop", "message": message})
    stream.end()
    return stream


def test_configuration_uses_owned_agent_tasks_and_preserves_mailbox_and_baseline_updates():
    from loushang.ai.types import UserMessage

    async def scenario():
        model_inputs = []

        async def provider(model, context, options=None):
            model_inputs.append(context)
            if len(model_inputs) == 1:
                await runtime.prompt("ordinary during planning")
                runtime.queue.queue_mailbox_message(UserMessage(role="user", content="mailbox", timestamp=0))
                agent.system_prompt = "new legal baseline"
            return _admission_response()

        agent = Agent(stream_fn=provider)
        runtime = _admission_runtime(agent)
        permit = runtime.execution_admission.reserve("work")
        permit.commit()
        with permit.executing():
            handle = runtime.execution_configuration.install(permit)
            await runtime.prompt_in_execution(permit, "planning")
            assert agent.state.messages[-1].stop_reason == "stop"
            assert len(model_inputs) == 1 and agent.has_queued_messages()
            assert runtime.queue.get_follow_up_messages() == ["ordinary during planning"]
            assert agent.system_prompt == "new legal baseline" and agent.stream_fn is provider
            handle.release()
        permit.begin_settling()
        permit.release()
        await runtime.continue_run()
        assert len(model_inputs) > 1 and not agent.has_queued_messages()
        assert agent.system_prompt == "new legal baseline" and agent.stream_fn is provider
        await runtime.dispose()

    asyncio.run(scenario())


def test_execution_recovery_requires_explicit_task_authority():
    async def scenario():
        runtime = _admission_runtime(Agent())
        permit = runtime.execution_admission.reserve("work")
        permit.commit()
        with permit.executing():
            handle = runtime.execution_configuration.install(permit, suppress_recovery=False)
            assert runtime.execution_configuration.recovery_allowed

            async def unrelated_task():
                return runtime.execution_configuration.recovery_allowed

            assert not await asyncio.create_task(unrelated_task())
            child_scope = runtime.execution_admission.execution_scope(permit)()

            async def delegated_task():
                with child_scope:
                    return runtime.execution_configuration.recovery_allowed

            assert await asyncio.create_task(delegated_task())
            handle.release()
        permit.begin_settling()
        permit.release()
        assert runtime.execution_configuration.recovery_allowed
        await runtime.dispose()

    asyncio.run(scenario())


def test_parent_release_settles_registered_work_and_retains_unknown_cleanup():
    from dataclasses import MISSING, fields

    import pytest

    from loushang.coding.adapters.harnesswork import create_coding_work_runtime
    from loushang.harness.session import SessionFacade
    from loushang.harnesswork import InMemoryEventLogBackend
    from loushang.harnesswork.ports import WorkExecutionBinding
    from loushang.harnesswork.types import WorkCancellationOutcome, WorkOperation

    async def scenario(supported):
        runtime = _admission_runtime(Agent())
        unused = {field.name: None for field in fields(SessionFacade)
                  if field.name != "runtime" and field.default is MISSING}
        facade = SessionFacade(runtime=runtime, **unused)
        backend = create_coding_work_runtime(session=facade, event_log=InMemoryEventLogBackend())
        started, stopped = asyncio.Event(), asyncio.Event()

        class Domain:
            async def execute(self, operation, context):
                started.set()
                await stopped.wait()

            async def cancel_and_wait(self, operation, context):
                if not supported:
                    return WorkCancellationOutcome.unsupported()
                stopped.set()
                return WorkCancellationOutcome.settled()

        domain = Domain()
        backend.prepare_binding("foreign-work", WorkExecutionBinding(domain, cancellation=domain), commit=lambda: None)
        run = await backend.work_runtime.accept(
            WorkOperation("foreign-work", "DomainWork", "shared-session", "design", {})
        )
        await started.wait()
        if supported:
            await asyncio.gather(facade.prepare_execution_release(), facade.prepare_execution_release())
            assert not backend.work_runtime.active_runs() and stopped.is_set()
            assert backend.work_runtime.get_cancellation(run.run_id).status == "settled"
            await runtime.dispose()
        else:
            for _ in range(2):
                with pytest.raises(RuntimeError, match="domain settlement"):
                    await facade.prepare_execution_release()
                assert not runtime.host_runtime.is_disposed
                assert backend._settling_runs == {run.run_id}
            # Test-only teardown: no domain task survives, but the production
            # cleanup handle correctly remains unresolved.
            assert not backend.work_runtime.active_runs()
            with pytest.raises(RuntimeError, match="domain settlement"):
                await runtime.dispose()
            with pytest.raises(RuntimeError, match="not ready for retirement"):
                runtime.close()
            assert runtime.execution_admission.backend is backend
            assert not runtime.host_runtime.is_disposed

    asyncio.run(scenario(True))
    asyncio.run(scenario(False))


def test_held_input_with_same_text_as_bound_prompt_keeps_original_queue_identity():
    async def scenario():
        async def provider(model, context, options=None):
            return _admission_response()

        runtime = _admission_runtime(Agent(stream_fn=provider))
        permit = runtime.execution_admission.reserve("work")
        permit.commit()
        await runtime.prompt("same text")
        held = runtime.queue.get_queue_snapshot()
        with permit.executing():
            handle = runtime.execution_configuration.install(permit)
            await runtime.prompt_in_execution(permit, "same text")
            handle.release()
        assert runtime.queue.get_queue_snapshot() == held
        assert runtime.queue.get_follow_up_messages() == ["same text"]
        permit.begin_settling()
        permit.release()
        await runtime.continue_run()
        assert not runtime.queue.has_pending_execution_input()
        await runtime.dispose()

    asyncio.run(scenario())


def test_scope_close_reports_interrupted_error_then_retries_original_cleanup():
    import pytest

    from loushang.harness.session.execution_scope import (
        ExecutionScopePorts,
        SessionExecutionScope,
    )

    async def scenario():
        runtime = _admission_runtime(Agent())
        started = asyncio.Event()
        stages = []

        def stage(name):
            async def run():
                stages.append(name)
            return run

        scope = SessionExecutionScope(runtime.execution_admission, ExecutionScopePorts(
            lambda: None, stage("quiesce"), stage("settle"), stage("release"), stage("finalize"),
        ))

        async def operation():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise RuntimeError("temporary invocation finalization failure")

        invocation = asyncio.create_task(scope.invoke(operation))
        await started.wait()
        with pytest.raises(RuntimeError, match="temporary invocation"):
            await scope.close()
        with pytest.raises(RuntimeError, match="temporary invocation"):
            await invocation
        assert stages == [] and not scope.closed
        await scope.close()
        assert stages == ["quiesce", "settle", "release", "finalize"] and scope.closed
        await runtime.dispose()

    asyncio.run(scenario())


def test_ordinary_command_invalidates_candidate_and_keeps_original_admission_busy():
    from dataclasses import MISSING, fields

    import pytest

    from loushang.harness.session import SessionFacade

    async def scenario():
        runtime = _admission_runtime(Agent())
        started, done = asyncio.Event(), asyncio.Event()

        class Command:
            async def execute(self, command, **kwargs):
                started.set()
                await done.wait()
                return {"output": "done"}

        unused = {field.name: None for field in fields(SessionFacade)
                  if field.name not in {"runtime", "command_execution"} and field.default is MISSING}
        facade = SessionFacade(runtime=runtime, command_execution=Command(), **unused)
        candidate = runtime.execution_admission.reserve("candidate")
        command = asyncio.create_task(facade.execute_bash("ordinary"))
        await started.wait()
        with pytest.raises(RuntimeError):
            candidate.commit()
        candidate.release()
        with pytest.raises(RuntimeError):
            runtime.execution_admission.reserve("while-command")
        done.set()
        assert await command == {"output": "done"}
        next_candidate = runtime.execution_admission.reserve("after-command")
        next_candidate.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_failed_configuration_publication_retains_original_handle_for_cleanup():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable
    from loushang.harness.session.execution_configuration import (
        ExecutionConfigurationError,
    )

    async def scenario():
        agent = Agent()
        runtime = _admission_runtime(agent)
        permit = runtime.execution_admission.reserve("work")
        permit.commit()

        def failed_renderer(names):
            assert not names
            raise RuntimeError("render publication failed")

        with permit.executing():
            with pytest.raises(ExecutionConfigurationError) as error:
                runtime.execution_configuration.install(permit, tool_names=(), render_prompt=failed_renderer)
            handle = error.value.handle
            assert not handle.published and not handle.released
            with pytest.raises(SessionExecutionUnavailable, match="retained"):
                runtime.execution_configuration.install(permit)
            handle.release()
            handle.release()
            valid = runtime.execution_configuration.install(permit)
            valid.release()
        permit.begin_settling()
        permit.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_configuration_release_failure_keeps_agent_dependencies_until_original_run_settles():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        handles = []

        async def provider(model, context, options=None):
            started.set()
            await finish.wait()
            return _admission_response()

        agent = Agent(stream_fn=provider)
        runtime = _admission_runtime(agent)
        permit = runtime.execution_admission.reserve("work")
        permit.commit()

        async def accepted_work():
            with permit.executing():
                handle = runtime.execution_configuration.install(permit)
                handles.append(handle)
                await runtime.prompt_in_execution(permit, "planning")
                handle.release()

        work = asyncio.create_task(accepted_work())
        await started.wait()
        with pytest.raises(SessionExecutionUnavailable, match="settle"):
            handles[0].release()
        assert not handles[0].released and runtime.execution_configuration.require(permit) is handles[0]
        finish.set()
        await work
        assert handles[0].released
        permit.begin_settling()
        permit.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_lifecycle_intent_blocks_commit_even_after_a_cancelled_transition():
    import pytest

    from loushang.harness.runtime import SessionTransitionHost
    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        runtime = _admission_runtime(Agent())
        host = SessionTransitionHost(runtime, dispose=lambda session: None)
        runtime.execution_admission.bind_lifecycle(
            is_current=lambda: host.current is runtime,
            transition_pending=lambda: host.has_pending_transitions,
            generation=lambda: host.transition_generation,
        )
        permit = runtime.execution_admission.reserve("candidate-before-new")
        async with host.transition():
            assert host.has_pending_transitions
            with pytest.raises(SessionExecutionUnavailable):
                permit.commit()
        assert not host.has_pending_transitions
        with pytest.raises(SessionExecutionUnavailable):
            permit.commit()
        permit.release()
        later = runtime.execution_admission.reserve("after-cancelled-transition")
        later.release()
        await host.replace(_admission_runtime(Agent()))
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve("old-instance")
        await runtime.dispose()
        await host.current.dispose()

    asyncio.run(scenario())


def test_immediate_application_input_invalidates_candidate_before_original_commit():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    from .test_application_input import _Committer, _message

    async def scenario():
        for mode in ("direct", "trigger_turn"):
            committer, prompts = _Committer(), []
            agent = Agent()

            async def prompt(message, target=prompts):
                target.append(message)

            agent.prompt = prompt
            runtime = _admission_runtime(agent, application_committer=committer.commit)
            candidate = runtime.execution_admission.reserve("candidate-before-input")
            message = _message("arrival", delivery_mode=mode)
            delivered = await runtime.application_inputs.deliver(message)
            if mode == "direct":
                assert delivered.disposition == "committed" and list(committer.persisted) == ["arrival"]
            else:
                assert delivered.disposition == "triggered" and prompts == [message]
            with pytest.raises(SessionExecutionUnavailable):
                candidate.commit()
            candidate.release()
            await runtime.dispose()

    asyncio.run(scenario())

def test_immediate_application_commit_and_projection_hold_original_admission():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    from .test_application_input import _Committer, _message

    async def scenario():
        commit_started, commit_release = asyncio.Event(), asyncio.Event()
        project_started, project_release = asyncio.Event(), asyncio.Event()
        committer = _Committer()

        async def commit(message):
            commit_started.set()
            await commit_release.wait()
            return await committer.commit(message)

        runtime = _admission_runtime(Agent(), application_committer=commit)

        async def project(event):
            if event.kind == "agent.message_start":
                project_started.set()
                await project_release.wait()

        runtime.subscribe(project)
        delivery = asyncio.create_task(runtime.application_inputs.deliver(_message("saving")))
        await commit_started.wait()
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve_candidate()
        commit_release.set()
        await project_started.wait()
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve_candidate()
        project_release.set()
        await delivery
        candidate = runtime.execution_admission.reserve_candidate()
        candidate.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_immediate_application_input_refused_before_persistence_then_retried_once():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    from .test_application_input import _Committer, _message

    async def scenario():
        committer, refreshed = _Committer(), []
        runtime = _admission_runtime(Agent(), application_committer=committer.commit,
                                     refresh=lambda: refreshed.append(True))
        permit = runtime.execution_admission.reserve("planning")
        permit.commit()
        assert not runtime.agent.is_streaming
        message = _message("held-original-identity")
        with pytest.raises(SessionExecutionUnavailable):
            await runtime.application_inputs.deliver(message)
        assert not committer.persisted and not refreshed
        permit.begin_settling()
        permit.release()
        first = await runtime.application_inputs.deliver(message)
        retry = await runtime.application_inputs.deliver(message)
        assert first.disposition == "committed" and retry.disposition == "already_committed"
        assert list(committer.persisted) == ["held-original-identity"] and refreshed == [True]
        await runtime.dispose()

    asyncio.run(scenario())


def test_immediate_application_input_rejects_closed_or_stale_session():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    from .test_application_input import _Committer, _message

    async def scenario():
        for closed in (False, True):
            committer = _Committer()
            runtime = _admission_runtime(Agent(), application_committer=committer.commit)
            if closed:
                runtime.execution_admission.close_admission()
            else:
                runtime.execution_admission.bind_lifecycle(
                    is_current=lambda: False, transition_pending=lambda: False,
                )
            with pytest.raises(SessionExecutionUnavailable):
                await runtime.application_inputs.deliver(_message("stale"))
            assert not committer.persisted
            await runtime.dispose()

    asyncio.run(scenario())


def test_retry_capture_preserves_delay_and_original_recovery_blocks_new_goal():
    from dataclasses import replace

    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    async def scenario():
        calls = []
        recovery = True
        agent = Agent()

        async def continuation(*, model_call_purpose="continuation"):
            calls.append(model_call_purpose)

        agent.continue_run = continuation
        runtime = _admission_runtime(agent)
        runtime.after_turn_policy = replace(runtime.after_turn_policy, recovery_pending=lambda: recovery)
        captured = runtime.capture_continue_run(model_call_purpose="retry")
        turn = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(turn.set_result, None)
        await turn
        assert not calls and not runtime.host_runtime.has_pending_runs
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve_candidate()
        await captured()
        assert calls == ["retry"]
        recovery = False
        ready = runtime.execution_admission.reserve_candidate()
        ready.release()
        await runtime.dispose()

    asyncio.run(scenario())


def test_current_replacement_callback_can_commit_input_while_goal_admission_waits():
    import pytest

    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    from .test_application_input import _Committer, _message

    async def scenario():
        committer = _Committer()
        runtime = _admission_runtime(Agent(), application_committer=committer.commit)
        runtime.execution_admission.bind_lifecycle(
            is_current=lambda: True, transition_pending=lambda: True,
        )
        with pytest.raises(SessionExecutionUnavailable):
            runtime.execution_admission.reserve_candidate()
        await runtime.application_inputs.deliver(_message("new-session-callback"))
        assert list(committer.persisted) == ["new-session-callback"]
        runtime.execution_admission.bind_lifecycle(
            is_current=lambda: False, transition_pending=lambda: False,
        )
        with pytest.raises(SessionExecutionUnavailable):
            await runtime.application_inputs.deliver(_message("old-session-callback"))
        assert list(committer.persisted) == ["new-session-callback"]
        await runtime.dispose()

    asyncio.run(scenario())
