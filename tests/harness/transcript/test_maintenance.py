from __future__ import annotations

import asyncio

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.events import (
    ContextCompactionCompleted,
    ContextCompactionStarted,
)
from loushang.harness.transcript import (
    AgentTranscriptCompactionRuntime,
    AgentTranscriptRecord,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    CompactionAborted,
    CompactionPreparation,
    CompactionResult,
    TranscriptCompactionPolicy,
    build_context_usage_snapshot,
    is_compaction_aborted,
)


def _model(*, context_window: int = 100) -> Model:
    return Model(
        id="test-model",
        name="Test",
        provider="test",
        endpoint="responses",
        capabilities=Capabilities(
            context_window=context_window,
            max_tokens=64,
        ),
    )


def _usage(total_tokens: int = 0) -> Usage:
    return Usage(
        input=total_tokens,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=total_tokens,
        cost=None,
    )


def test_compaction_abort_classification_is_type_based() -> None:
    assert is_compaction_aborted(CompactionAborted("Compaction cancelled")) is True
    assert is_compaction_aborted(RuntimeError("Compaction cancelled")) is False


def _assistant(
    *,
    text: str = "answer",
    total_tokens: int = 0,
    stop_reason: str = "stop",
    error_message: str | None = None,
    timestamp: float = 1.0,
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="responses",
        provider="test",
        model="test-model",
        response_id=None,
        usage=_usage(total_tokens),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=timestamp,
    )


async def _session() -> AgentTranscriptSession:
    store: MemoryConversationStore[ConversationHeader, AgentTranscriptRecord] = (
        MemoryConversationStore(record_id=lambda record: record.record_id)
    )
    transcript = await AgentTranscriptUnitOfWork.create(
        store,
        ConversationKey("test", "maintenance"),
        ConversationHeader(
            conversation_id="maintenance",
            version=1,
            created_at="2026-07-18T00:00:00Z",
        ),
        id_factory=iter(("user-1", "assistant-1", "checkpoint-1")).__next__,
    )
    return AgentTranscriptSession(transcript=transcript)


def test_context_usage_is_profile_owned_and_stales_at_checkpoint() -> None:
    async def scenario() -> None:
        session = await _session()
        user_id = await session.append_message(
            UserMessage(role="user", content="prompt", timestamp=0.0)
        )
        await session.append_message(_assistant(total_tokens=95))
        snapshot = build_context_usage_snapshot(
            session.build_context().messages,
            session.get_branch(),
            _model(),
            reserve_tokens=10,
        )
        assert snapshot.compactable is True
        assert snapshot.threshold_tokens == 90

        await session.append_compaction("summary", user_id, 95)
        stale = build_context_usage_snapshot(
            session.build_context().messages,
            session.get_branch(),
            _model(),
            reserve_tokens=10,
        )
        assert stale.stale_after_compaction is True
        assert stale.tokens is None

    asyncio.run(scenario())


def test_compaction_runtime_commits_checkpoint_and_publishes_common_events() -> None:
    async def scenario() -> None:
        session = await _session()
        user_id = await session.append_message(
            UserMessage(role="user", content="older", timestamp=0.0)
        )
        assistant_id = await session.append_message(_assistant(total_tokens=20))
        events: list[object] = []
        refreshed: list[bool] = []

        def prepare(entries, keep_recent_tokens):
            assert [entry.record_id for entry in entries] == [user_id, assistant_id]
            assert keep_recent_tokens == 4
            return CompactionPreparation(
                first_kept_entry_id=assistant_id,
                messages_to_summarize=[session.build_context().messages[0]],
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=20,
                details={"plan": "standard"},
            )

        async def execute(preparation, instructions):
            assert instructions == "retain decisions"
            return CompactionResult(
                summary="summary",
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
            )

        runtime = AgentTranscriptCompactionRuntime(
            transcript=session,
            get_policy=lambda: TranscriptCompactionPolicy(
                enabled=True,
                reserve_tokens=10,
                compact_percent=80,
                keep_recent_tokens=4,
            ),
            get_model=_model,
            get_context_messages=lambda: list(session.build_context().messages),
            refresh_context=lambda: refreshed.append(True),
            prepare_compaction=prepare,
            execute_compaction=execute,
            dispatch_event=lambda event: _append(events, event),
            has_queued_messages=lambda: False,
        )

        result = await runtime.compact(
            reason="manual",
            will_retry=False,
            custom_instructions="retain decisions",
        )

        assert result is not None
        assert session.get_entries()[-1].kind == "context.compaction_checkpoint"
        assert refreshed == [True]
        assert isinstance(events[0], ContextCompactionStarted)
        assert events[0].stage == "started"
        assert events[0].tokens_before == 20
        assert isinstance(events[-1], ContextCompactionCompleted)
        assert events[-1].stage == "committed"
        assert events[-1].checkpoint_record_id == session.get_entries()[-1].record_id
        assert events[-1].result == {
            "summary": "summary",
            "first_kept_entry_id": assistant_id,
            "tokens_before": 20,
            "details": {"plan": "standard"},
        }
        status = runtime.get_status()
        assert status.last_reason == "manual"
        assert status.last_stage == "committed"
        assert status.last_started_at is not None
        assert status.last_completed_at is not None
        assert status.last_tokens_before == 20
        assert status.last_tokens_after is None
        assert status.last_summary_mode == "complete"
        assert status.last_succeeded is True
        assert status.context_window == 100
        assert status.reserve_tokens == 10

    asyncio.run(scenario())


def test_compaction_runtime_counts_the_completed_message_before_context_refresh() -> (
    None
):
    async def scenario() -> None:
        session = await _session()
        user_id = await session.append_message(
            UserMessage(role="user", content="older", timestamp=0.0)
        )
        completed = _assistant(total_tokens=95)

        def prepare(entries, keep_recent_tokens):
            assert [entry.record_id for entry in entries] == [user_id]
            assert keep_recent_tokens == 0
            return CompactionPreparation(
                first_kept_entry_id=user_id,
                messages_to_summarize=list(session.build_context().messages),
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=95,
            )

        async def execute(preparation, instructions):
            assert instructions is None
            return CompactionResult(
                summary="summary",
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
            )

        runtime = AgentTranscriptCompactionRuntime(
            transcript=session,
            get_policy=lambda: TranscriptCompactionPolicy(
                enabled=True,
                reserve_tokens=10,
            ),
            get_model=_model,
            get_context_messages=lambda: list(session.build_context().messages),
            refresh_context=lambda: None,
            prepare_compaction=prepare,
            execute_compaction=execute,
            dispatch_event=lambda event: _append([], event),
            has_queued_messages=lambda: False,
        )

        outcome = await runtime.maybe_compact_after_turn(
            completed,
            is_context_overflow_fn=lambda message, context_window: False,
        )

        assert outcome.result is not None
        assert outcome.should_continue is False
        assert session.get_entries()[-1].kind == "context.compaction_checkpoint"

    asyncio.run(scenario())


def test_compaction_runtimes_keep_product_bindings_and_state_isolated() -> None:
    async def scenario() -> None:
        research = await _session()
        design = await _session()
        calls: list[tuple[str, str]] = []

        async def build_runtime(label: str, session: AgentTranscriptSession):
            await session.append_message(
                UserMessage(role="user", content=f"{label} prompt", timestamp=0.0)
            )
            assistant_id = await session.append_message(_assistant(total_tokens=20))

            def prepare(entries, keep_recent_tokens):
                assert keep_recent_tokens == (4 if label == "research" else 8)
                return CompactionPreparation(
                    first_kept_entry_id=assistant_id,
                    messages_to_summarize=[session.build_context().messages[0]],
                    turn_prefix_messages=[],
                    is_split_turn=False,
                    tokens_before=20,
                )

            async def execute(preparation, instructions):
                calls.append((label, "execute"))
                return CompactionResult(
                    summary=f"{label} summary",
                    first_kept_entry_id=preparation.first_kept_entry_id,
                    tokens_before=preparation.tokens_before,
                )

            async def before(request):
                calls.append((label, f"before:{request.reason}"))
                return None

            async def after(result, record_id, from_hook):
                del result, record_id, from_hook
                calls.append((label, "after"))

            return AgentTranscriptCompactionRuntime(
                transcript=session,
                get_policy=lambda: TranscriptCompactionPolicy(
                    enabled=True,
                    reserve_tokens=10,
                    keep_recent_tokens=4 if label == "research" else 8,
                ),
                get_model=_model,
                get_context_messages=lambda: list(session.build_context().messages),
                refresh_context=lambda: calls.append((label, "refresh")),
                prepare_compaction=prepare,
                execute_compaction=execute,
                dispatch_event=lambda event: _append([], event),
                has_queued_messages=lambda: False,
                before_compaction=before,
                after_compaction=after,
            )

        research_runtime = await build_runtime("research", research)
        design_runtime = await build_runtime("design", design)

        await research_runtime.compact(reason="manual", will_retry=False)
        await design_runtime.compact(reason="manual", will_retry=False)

        assert research.get_entries()[-1].payload.summary == "research summary"
        assert design.get_entries()[-1].payload.summary == "design summary"
        assert calls == [
            ("research", "before:manual"),
            ("research", "execute"),
            ("research", "refresh"),
            ("research", "after"),
            ("design", "before:manual"),
            ("design", "execute"),
            ("design", "refresh"),
            ("design", "after"),
        ]

    asyncio.run(scenario())


def test_compaction_abort_cancels_executor_without_committing_checkpoint() -> None:
    async def scenario() -> None:
        session = await _session()
        user_id = await session.append_message(
            UserMessage(role="user", content="older", timestamp=0.0)
        )
        assistant_id = await session.append_message(_assistant(total_tokens=20))
        started = asyncio.Event()
        events: list[object] = []

        def prepare(entries, keep_recent_tokens):
            del entries, keep_recent_tokens
            return CompactionPreparation(
                first_kept_entry_id=assistant_id,
                messages_to_summarize=[session.build_context().messages[0]],
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=20,
            )

        async def execute(preparation, instructions):
            del preparation, instructions
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        runtime = AgentTranscriptCompactionRuntime(
            transcript=session,
            get_policy=lambda: TranscriptCompactionPolicy(
                enabled=True,
                reserve_tokens=10,
            ),
            get_model=_model,
            get_context_messages=lambda: list(session.build_context().messages),
            refresh_context=lambda: None,
            prepare_compaction=prepare,
            execute_compaction=execute,
            dispatch_event=lambda event: _append(events, event),
            has_queued_messages=lambda: False,
        )

        task = asyncio.create_task(runtime.compact(reason="manual", will_retry=False))
        await started.wait()
        runtime.abort()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert [entry.record_id for entry in session.get_entries()] == [
            user_id,
            assistant_id,
        ]
        assert isinstance(events[-1], ContextCompactionCompleted)
        assert events[-1].aborted is True
        assert events[-1].stage == "aborted"
        assert events[-1].duration_ms is not None
        assert runtime.get_status().is_compacting is False
        assert runtime.get_status().aborted is True

    asyncio.run(scenario())


def test_post_commit_failure_keeps_success_and_refreshed_context() -> None:
    async def scenario() -> None:
        session = await _session()
        await session.append_message(
            UserMessage(role="user", content="older", timestamp=0.0)
        )
        assistant_id = await session.append_message(_assistant(total_tokens=20))
        order: list[str] = []
        diagnostics: list[str] = []

        def prepare(entries, keep_recent_tokens):
            del entries, keep_recent_tokens
            return CompactionPreparation(
                first_kept_entry_id=assistant_id,
                messages_to_summarize=[session.build_context().messages[0]],
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=20,
            )

        async def execute(preparation, instructions):
            del instructions
            return CompactionResult(
                summary="committed",
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
            )

        async def after(result, record_id, from_hook):
            del result, record_id, from_hook
            order.append("after")
            raise RuntimeError("observer failed")

        events: list[object] = []
        runtime = AgentTranscriptCompactionRuntime(
            transcript=session,
            get_policy=lambda: TranscriptCompactionPolicy(
                enabled=True,
                reserve_tokens=10,
            ),
            get_model=_model,
            get_context_messages=lambda: list(session.build_context().messages),
            refresh_context=lambda: order.append("refresh"),
            prepare_compaction=prepare,
            execute_compaction=execute,
            dispatch_event=lambda event: _append(events, event),
            has_queued_messages=lambda: False,
            after_compaction=after,
            record_runtime_exception=lambda *, code, exc: diagnostics.append(
                f"{code}:{exc}"
            ),
            product_id="research",
            session_id="session-research",
        )

        result = await runtime.compact(reason="manual", will_retry=False)

        assert result is not None
        assert result.summary == "committed"
        assert order == ["refresh", "after"]
        assert diagnostics == ["compaction_post_commit_failed:observer failed"]
        assert session.get_entries()[-1].kind == "context.compaction_checkpoint"
        completed = events[-1]
        assert isinstance(completed, ContextCompactionCompleted)
        assert completed.stage == "post_hook_failed"
        assert completed.product_id == "research"
        assert completed.session_id == "session-research"
        assert completed.duration_ms is not None
        assert completed.duration_ms >= 0
        assert completed.tokens_before is not None
        assert completed.tokens_after is None
        assert completed.checkpoint_record_id == session.get_entries()[-1].record_id

    asyncio.run(scenario())


def test_abort_after_commit_does_not_cancel_post_commit_observer() -> None:
    async def scenario() -> None:
        session = await _session()
        await session.append_message(
            UserMessage(role="user", content="older", timestamp=0.0)
        )
        assistant_id = await session.append_message(_assistant(total_tokens=20))
        observer_started = asyncio.Event()
        release_observer = asyncio.Event()

        def prepare(entries, keep_recent_tokens):
            del entries, keep_recent_tokens
            return CompactionPreparation(
                first_kept_entry_id=assistant_id,
                messages_to_summarize=[session.build_context().messages[0]],
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=20,
            )

        async def execute(preparation, instructions):
            del instructions
            return CompactionResult(
                summary="committed",
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
            )

        async def after(result, record_id, from_hook):
            del result, record_id, from_hook
            observer_started.set()
            await release_observer.wait()

        runtime = AgentTranscriptCompactionRuntime(
            transcript=session,
            get_policy=lambda: TranscriptCompactionPolicy(
                enabled=True,
                reserve_tokens=10,
            ),
            get_model=_model,
            get_context_messages=lambda: list(session.build_context().messages),
            refresh_context=lambda: None,
            prepare_compaction=prepare,
            execute_compaction=execute,
            dispatch_event=lambda event: _append([], event),
            has_queued_messages=lambda: False,
            after_compaction=after,
        )

        task = asyncio.create_task(runtime.compact(reason="manual", will_retry=False))
        await observer_started.wait()
        assert runtime.is_compacting is False
        runtime.abort()
        release_observer.set()

        result = await task
        assert result is not None
        assert result.summary == "committed"
        assert runtime.get_status().aborted is False

    asyncio.run(scenario())


async def _append(values: list[object], value: object) -> None:
    values.append(value)
