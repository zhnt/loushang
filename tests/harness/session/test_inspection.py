from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model, ModelSelection
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    ConversationRecord,
    MemoryConversationStore,
)
from loushang.harness.session import AgentSessionInspector, AgentSessionState
from loushang.harness.session.inspection import _build_token_usage_totals
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    MODEL_CALL_ATTEMPT_USAGE_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_PREPARED_KIND,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    ModelCallAttemptUsage,
    ModelCallOutcome,
    ModelInputComponentReference,
    ModelInputSnapshot,
)


def _model() -> Model:
    return Model(
        id="test-model",
        name="Test",
        provider="test",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


def _assistant() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            TextPart(type="text", text="answer"),
            ToolCall(
                type="toolCall",
                id="tool-1",
                name="read",
                arguments={"path": "README.md"},
            ),
        ],
        api="responses",
        provider="test",
        model="test-model",
        response_id="response-1",
        usage=Usage(
            input=2,
            output=3,
            cache_read=0,
            cache_write=0,
            total_tokens=5,
            cost={},
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )


async def _inspector() -> AgentSessionInspector:
    store = MemoryConversationStore(record_id=lambda record: record.record_id)
    transcript = await AgentTranscriptUnitOfWork.create(
        store,
        ConversationKey("test", "inspection-1"),
        ConversationHeader(
            conversation_id="inspection-1",
            version=1,
            created_at="2026-07-18T00:00:00Z",
        ),
        id_factory=iter(("user-1", "assistant-1", "tool-1")).__next__,
    )
    session = AgentTranscriptSession(transcript=transcript)
    await session.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="hello")],
            timestamp=0.0,
        )
    )
    await session.append_message(_assistant())
    await session.append_message(
        ToolResultMessage(
            role="toolResult",
            tool_call_id="tool-1",
            tool_name="read",
            content=[TextPart(type="text", text="contents")],
            is_error=False,
            timestamp=2.0,
        )
    )
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "high"}
    )
    agent.state.set_messages(list(session.build_context().messages))
    return AgentSessionInspector(
        agent=agent,
        session=session,
        get_session_id=lambda: "inspection-1",
        get_session_name=lambda: "Inspection",
        get_active_tool_names=lambda: ["read", "bash"],
        is_retrying=lambda: True,
        is_compacting=lambda: False,
        get_last_diagnostics=lambda limit: [object()] if limit else [],
        get_model_selection=lambda: ModelSelection(
            endpoint_id="test-endpoint", provider="test", model_id="test-model"
        ),
    )


def test_agent_session_inspector_builds_product_neutral_state_and_usage() -> None:
    inspector = asyncio.run(_inspector())

    state = inspector.get_state(steering=["steer"], follow_up=["follow"])
    usage = inspector.get_context_usage()
    stats = inspector.build_session_stats()

    assert state == AgentSessionState(
        run=state.run,
        steering=["steer"],
        follow_up=["follow"],
        active_tool_names=["read", "bash"],
        is_compacting=False,
        is_retrying=True,
        thinking_level="high",
        model_selection=ModelSelection(
            endpoint_id="test-endpoint", provider="test", model_id="test-model"
        ),
    )
    assert state.run.status == "idle"
    assert usage.message_count == 3
    assert usage.user_message_count == 1
    assert usage.assistant_message_count == 1
    assert usage.tool_call_count == 1
    assert usage.tool_result_count == 1
    assert usage.tokens == 7
    assert usage.context_window == 128_000
    assert stats.session_id == "inspection-1"
    assert stats.session_name == "Inspection"
    assert stats.entry_count == 3
    assert stats.active_tool_count == 2
    assert stats.has_diagnostics is True


def test_agent_session_inspector_reads_fork_candidates_and_assistant_text() -> None:
    inspector = asyncio.run(_inspector())

    assert inspector.get_user_messages_for_forking() == [
        {"entry_id": "user-1", "text": "hello"}
    ]
    assert inspector.get_entry_text("user-1") == "hello"
    assert inspector.get_recent_assistant_texts() == ("answer",)
    assert inspector.get_last_assistant_text() == "answer"


def test_token_totals_prefer_outcomes_and_keep_uncovered_legacy_usage() -> None:
    legacy_usage = Usage(1, 2, 3, 4, 10, None)
    outcome_usage = Usage(10, 5, 2, 1, 18, None)
    cancelled_usage = Usage(7, 0, 0, 0, 7, None)
    records = [
        _record("legacy", AGENT_MESSAGE_KIND, _assistant_with_usage(legacy_usage)),
        _record(
            "snapshot",
            MODEL_INPUT_PREPARED_KIND,
            SimpleNamespace(snapshot_id="snapshot-1"),
        ),
        _record("projected", AGENT_MESSAGE_KIND, _assistant_with_usage(outcome_usage)),
        _record(
            "outcome",
            MODEL_CALL_OUTCOME_KIND,
            ModelCallOutcome(
                invocation_id="invocation-1",
                model_input_snapshot_ids=("snapshot-1",),
                disposition="completed",
                stop_reason="stop",
                usage=outcome_usage,
            ),
        ),
        _record(
            "cancelled",
            MODEL_CALL_OUTCOME_KIND,
            ModelCallOutcome(
                invocation_id="invocation-2",
                model_input_snapshot_ids=(),
                disposition="cancelled",
                stop_reason="aborted",
                usage=cancelled_usage,
            ),
        ),
        _record(
            "compaction",
            "context.compaction.checkpoint",
            SimpleNamespace(tokens_before=999_999),
        ),
    ]

    totals = _build_token_usage_totals(records)  # type: ignore[arg-type]

    assert totals.input == 18
    assert totals.output == 7
    assert totals.cache_read == 5
    assert totals.cache_write == 5
    assert totals.total == 35
    assert totals.source == "mixed_derived"
    assert totals.incomplete_attempts is True


def test_token_totals_prefer_complete_attempt_facts_across_retries() -> None:
    records = [
        _record(
            "snapshot-1", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-1", 1)
        ),
        _record(
            "usage-1",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _attempt_usage("snapshot-1", 1, input=10, terminal=True),
        ),
        _record(
            "snapshot-2", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-2", 2)
        ),
        _record(
            "usage-2",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _attempt_usage(
                "snapshot-2",
                2,
                input=20,
                output=5,
                terminal=True,
            ),
        ),
        _record(
            "outcome",
            MODEL_CALL_OUTCOME_KIND,
            ModelCallOutcome(
                invocation_id="invocation-1",
                model_input_snapshot_ids=("snapshot-1", "snapshot-2"),
                disposition="completed",
                stop_reason="stop",
                usage=Usage(20, 5, 0, 0, 25, None),
            ),
        ),
    ]

    totals = _build_token_usage_totals(records)  # type: ignore[arg-type]

    assert totals.input == 30
    assert totals.output == 5
    assert totals.total == 35
    assert totals.source == "attempt_usage_facts"
    assert totals.incomplete_attempts is False


def test_token_totals_mark_fact_and_outcome_fallback_as_mixed() -> None:
    records = [
        _record(
            "snapshot-1", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-1", 1)
        ),
        _record(
            "usage-1",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _attempt_usage("snapshot-1", 1, input=10, terminal=True),
        ),
        _record(
            "outcome-1",
            MODEL_CALL_OUTCOME_KIND,
            ModelCallOutcome(
                invocation_id="invocation-1",
                model_input_snapshot_ids=("snapshot-1",),
                disposition="completed",
                stop_reason="stop",
                usage=Usage(10, 0, 0, 0, 10, None),
            ),
        ),
        _record(
            "legacy-snapshot",
            MODEL_INPUT_PREPARED_KIND,
            _snapshot("legacy-snapshot", 1, invocation_id="legacy-invocation"),
        ),
        _record(
            "outcome-2",
            MODEL_CALL_OUTCOME_KIND,
            ModelCallOutcome(
                invocation_id="legacy-invocation",
                model_input_snapshot_ids=("legacy-snapshot",),
                disposition="completed",
                stop_reason="stop",
                usage=Usage(7, 2, 0, 0, 9, None),
            ),
        ),
    ]

    totals = _build_token_usage_totals(records)  # type: ignore[arg-type]

    assert totals.input == 17
    assert totals.output == 2
    assert totals.total == 19
    assert totals.source == "mixed_derived"
    assert totals.incomplete_attempts is True


def _assistant_with_usage(usage: Usage) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="answer")],
        api="responses",
        provider="test",
        model="test-model",
        response_id=None,
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )


def _attempt_usage(
    snapshot_id: str,
    attempt: int,
    *,
    input: int,
    output: int = 0,
    terminal: bool,
) -> ModelCallAttemptUsage:
    return ModelCallAttemptUsage(
        invocation_id="invocation-1",
        attempt=attempt,
        model_input_snapshot_id=snapshot_id,
        input=input,
        output=output,
        terminal=terminal,
    )


def _snapshot(
    snapshot_id: str,
    attempt: int,
    *,
    invocation_id: str = "invocation-1",
) -> ModelInputSnapshot:
    reference = ModelInputComponentReference(
        name="messages",
        record_id="component-record",
        content_hash="a" * 64,
    )
    return ModelInputSnapshot(
        snapshot_id=snapshot_id,
        invocation_id=invocation_id,
        attempt=attempt,
        purpose="main_turn",
        product_id="coding",
        runtime_id="runtime-1",
        mount_generation=1,
        profile_fingerprint="b" * 64,
        registration_revision="c" * 64,
        conversation_id="conversation-1",
        source_leaf_id="source-record",
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        model_id="model-1",
        api_id="api-1",
        endpoint_id="endpoint-1",
        logical_components=tuple(
            replace(reference, name=name)
            for name in ("system_prompt", "messages", "tools", "request_options")
        ),
        prepared_payload_components=(reference,),
        model_visible_headers_component=replace(
            reference, name="model_visible_headers"
        ),
        logical_input_hash="d" * 64,
        prepared_payload_hash="e" * 64,
    )


def _record(record_id: str, kind: str, payload: object) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=None,
        kind=kind,
        payload_version=1,
        created_at="2026-08-26T00:00:00Z",
        payload=payload,
    )
