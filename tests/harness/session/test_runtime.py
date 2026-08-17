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
