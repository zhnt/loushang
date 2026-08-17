from __future__ import annotations

import asyncio

from loushang.agent.types import ThinkingLevel
from loushang.ai.model import Capabilities, Model, ModelSelection
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.events import BranchSummaryCompleted, BranchSummaryStarted
from loushang.harness.transcript import (
    CONTEXT_BRANCH_SUMMARY_KIND,
    AgentTranscriptInspector,
    AgentTranscriptNavigationRuntime,
    AgentTranscriptRecord,
    AgentTranscriptSelectionRuntime,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    BranchSummaryOutput,
    TranscriptForkCandidate,
)


def _model(model_id: str = "one", *, reasoning: bool = True) -> Model:
    return Model(
        id=model_id,
        name=model_id,
        provider="test",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=reasoning,
            input=("text",),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


def _assistant(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="responses",
        provider="test",
        model="one",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )


async def _session() -> AgentTranscriptSession:
    store: MemoryConversationStore[ConversationHeader, AgentTranscriptRecord] = (
        MemoryConversationStore(record_id=lambda record: record.record_id)
    )
    transcript = await AgentTranscriptUnitOfWork.create(
        store,
        ConversationKey("test", "conversation"),
        ConversationHeader(
            conversation_id="conversation",
            version=1,
            created_at="2026-07-18T00:00:00Z",
        ),
        id_factory=(
            iter(
                (
                    "user-1",
                    "assistant-1",
                    "user-2",
                    "assistant-2",
                    "summary-1",
                    "model-1",
                    "thinking-1",
                )
            ).__next__
        ),
    )
    return AgentTranscriptSession(
        transcript=transcript,
        application_message_id_factory=lambda: "application-1",
    )


def test_inspector_projects_standard_transcript_reads() -> None:
    async def scenario() -> None:
        session = await _session()
        user_id = await session.append_message(
            UserMessage(role="user", content="root", timestamp=1.0)
        )
        await session.append_message(_assistant("answer"))
        await session.append_custom_message_entry("note", "saved", display=True)

        inspector = AgentTranscriptInspector(session)

        assert inspector.fork_candidates() == (
            TranscriptForkCandidate(record_id=user_id, text="root"),
        )
        assert inspector.entry_text(user_id) == "root"
        assert inspector.recent_assistant_texts() == ("answer",)
        assert inspector.message_counts().application_message_count == 1
        assert inspector.branch_leaf_count() == 1

    asyncio.run(scenario())


def test_navigation_runtime_owns_branch_selection_summary_and_events() -> None:
    async def scenario() -> None:
        session = await _session()
        await session.append_message(
            UserMessage(role="user", content="root", timestamp=1.0)
        )
        assistant_id = await session.append_message(_assistant("answer one"))
        user_id = await session.append_message(
            UserMessage(role="user", content="draft", timestamp=2.0)
        )
        leaf_id = await session.append_message(_assistant("answer two"))
        contexts: list[list[str]] = []
        events: list[object] = []

        runtime = AgentTranscriptNavigationRuntime(
            session=session,
            apply_context=lambda: contexts.append(
                [
                    str(getattr(message, "role", ""))
                    for message in session.build_context().messages
                ]
            ),
            dispatch_event=events.append,
        )
        plan = runtime.prepare(user_id)
        assert plan is not None
        assert plan.new_leaf_id == assistant_id
        assert plan.editor_text == "draft"

        result = await runtime.navigate(plan)
        assert result.editor_text == "draft"
        assert session.get_leaf_id() == assistant_id
        assert contexts == [["user", "assistant"]]

        session.branch(leaf_id)
        summary_plan = runtime.prepare(assistant_id)
        assert summary_plan is not None

        async def summarize(records, signal):
            assert not signal.aborted
            assert [record.record_id for record in records] == [user_id, leaf_id]
            return BranchSummaryOutput(summary="branch summary")

        summary_result = await runtime.navigate(
            summary_plan,
            summarize=True,
            label="kept",
            summary_runner=summarize,
        )

        assert summary_result.summary_entry_id == "summary-1"
        assert session.get_leaf_id() == "model-1"
        assert session.get_label("summary-1") == "kept"
        assert isinstance(events[0], BranchSummaryStarted)
        assert isinstance(events[1], BranchSummaryCompleted)

    asyncio.run(scenario())


def test_navigation_runtime_cancel_and_wait_joins_active_summary() -> None:
    async def scenario() -> None:
        session = await _session()
        await session.append_message(
            UserMessage(role="user", content="root", timestamp=1.0)
        )
        target_id = await session.append_message(_assistant("target"))
        await session.append_message(
            UserMessage(role="user", content="divergent", timestamp=2.0)
        )
        await session.append_message(_assistant("leaf"))
        runtime = AgentTranscriptNavigationRuntime(
            session=session,
            apply_context=lambda: None,
        )
        plan = runtime.prepare(target_id)
        assert plan is not None
        started = asyncio.Event()

        async def summarize(records, signal):
            assert records
            started.set()
            while not signal.aborted:
                await asyncio.sleep(0)
            return BranchSummaryOutput(summary="must not commit")

        task = asyncio.create_task(
            runtime.navigate(plan, summarize=True, summary_runner=summarize)
        )
        await started.wait()

        await runtime.cancel_and_wait()

        assert task.done()
        result = await task
        assert result.cancelled is True
        assert result.aborted is True
        assert runtime.is_summarizing is False
        assert session.get_leaf_id() != target_id
        assert all(
            record.kind != CONTEXT_BRANCH_SUMMARY_KIND
            for record in session.get_entries()
        )

    asyncio.run(scenario())


def test_selection_runtime_uses_product_catalog_but_owns_persisted_state() -> None:
    class Catalog:
        def __init__(self, models: list[Model]) -> None:
            self.models = models

        def list_models(self) -> list[ModelSelection]:
            return [
                ModelSelection(
                    endpoint_id=model.endpoint_id,
                    provider=model.provider_id,
                    model_id=model.id,
                )
                for model in self.models
            ]

        def build_model(self, selection: ModelSelection) -> Model:
            return next(
                model
                for model in self.models
                if model.provider_id == selection.provider
                and model.id == selection.model_id
            )

    async def scenario() -> None:
        session = await _session()
        first = _model("one")
        second = _model("two")
        active_model = first
        active_thinking: ThinkingLevel = "low"
        runtime = AgentTranscriptSelectionRuntime(
            session=session,
            get_model=lambda: active_model,
            set_model=lambda model: _set_model(model),
            get_thinking_level=lambda: active_thinking,
            set_thinking_level_value=lambda level: _set_thinking(level),
            get_model_catalog=lambda: Catalog([first, second]),
        )

        def _set_model(model: Model) -> None:
            nonlocal active_model
            active_model = model

        def _set_thinking(level: ThinkingLevel) -> None:
            nonlocal active_thinking
            active_thinking = level

        selection = runtime.cycle_model_selection()
        assert selection == ModelSelection(
            endpoint_id="responses", provider="test", model_id="two"
        )
        assert selection is not None
        await runtime.apply_model(runtime.resolve_model(selection))
        await runtime.set_thinking_level("high")

        assert active_model == second
        assert active_thinking == "high"
        context = session.build_context()
        assert context.model == {
            "provider": "test",
            "endpoint_id": "responses",
            "model_id": "two",
        }
        assert context.thinking_level == "high"

    asyncio.run(scenario())
