from __future__ import annotations

import asyncio

import pytest

from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.transcript import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    TURN_AWARE_SUMMARY_VERSION,
    AgentTranscriptCompactionCapability,
    AgentTranscriptRecord,
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
    TranscriptCompactionConfiguration,
    create_agent_transcript_compaction_capability,
)


def _assistant(text: str, *, timestamp: float) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="responses",
        provider="test",
        model="test",
        response_id=None,
        usage=Usage(
            input=32,
            output=8,
            cache_read=0,
            cache_write=0,
            total_tokens=40,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=timestamp,
    )


async def _session() -> AgentTranscriptSession:
    store: MemoryConversationStore[ConversationHeader, AgentTranscriptRecord] = (
        MemoryConversationStore(record_id=lambda record: record.record_id)
    )
    transcript = await AgentTranscriptUnitOfWork.create(
        store,
        ConversationKey("test", "compaction-capability"),
        ConversationHeader(
            conversation_id="compaction-capability",
            version=1,
            created_at="2026-07-19T00:00:00Z",
        ),
        id_factory=iter(("user-1", "assistant-1", "user-2")).__next__,
    )
    return AgentTranscriptSession(transcript=transcript)


def _config(**overrides: object) -> dict[str, object]:
    return {
        "enabled": True,
        "compactPercent": 80.0,
        "reserveTokens": 8_192,
        "keepRecentTokens": 1,
        **overrides,
    }


def test_turn_aware_capability_validates_and_snapshots_configuration() -> None:
    capability = create_agent_transcript_compaction_capability(
        implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
        implementation_version=TURN_AWARE_SUMMARY_VERSION,
        config=_config(),
    )

    assert capability.policy.enabled is True
    assert capability.policy.compact_percent == 80.0
    assert capability.configuration.to_json() == _config()

    with pytest.raises(ValueError, match="unsupported fields"):
        create_agent_transcript_compaction_capability(
            implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
            implementation_version=TURN_AWARE_SUMMARY_VERSION,
            config=_config(extra=True),
        )
    with pytest.raises(ValueError, match="implementation version"):
        create_agent_transcript_compaction_capability(
            implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
            implementation_version=2,
            config=_config(),
        )
    with pytest.raises(TypeError, match="version must be an integer"):
        create_agent_transcript_compaction_capability(
            implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
            implementation_version=True,
            config=_config(),
        )
    with pytest.raises(TypeError, match="version must be an integer"):
        AgentTranscriptCompactionCapability(
            implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
            implementation_version=True,
            configuration=TranscriptCompactionConfiguration.from_json(_config()),
        )


def test_turn_aware_capability_prepares_a_tool_safe_transcript_plan() -> None:
    async def scenario() -> None:
        session = await _session()
        user_id = await session.append_message(
            UserMessage(role="user", content="older request", timestamp=0.0)
        )
        assistant_id = await session.append_message(
            _assistant("older reply", timestamp=1.0)
        )
        recent_user_id = await session.append_message(
            UserMessage(role="user", content="current request", timestamp=2.0)
        )
        capability = create_agent_transcript_compaction_capability(
            implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
            implementation_version=TURN_AWARE_SUMMARY_VERSION,
            config=_config(),
        )

        preparation = capability.prepare(session.get_branch())

        assert preparation.plan is not None
        assert preparation.plan.summarized_entry_ids == (user_id, assistant_id)
        assert preparation.plan.kept_entry_ids == (recent_user_id,)
        assert preparation.first_kept_entry_id == recent_user_id
        assert [message.role for message in preparation.messages_to_summarize] == [
            "user",
            "assistant",
        ]
        assert preparation.details == {
            "compactionPlan": {
                "previousCompactionId": None,
                "previousFirstKeptEntryId": None,
                "firstKeptEntryId": recent_user_id,
                "summarizedEntryIds": [user_id, assistant_id],
                "turnPrefixEntryIds": [],
                "keptEntryIds": [recent_user_id],
                "isSplitTurn": False,
                "tokensBefore": preparation.tokens_before,
                "keepRecentTokens": 1,
            }
        }

    asyncio.run(scenario())
