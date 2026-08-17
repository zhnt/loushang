from __future__ import annotations

import asyncio

import pytest

from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding.session_manager import SessionManager
from loushang.harness.transcript import build_agent_transcript_session_context


def _assistant(text: str, timestamp: float) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="responses",
        provider="faux",
        model="alpha",
        response_id=None,
        usage=Usage(
            input=1,
            output=1,
            cache_read=0,
            cache_write=0,
            total_tokens=2,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=timestamp,
    )


def _context_text(messages: object) -> str:
    text: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            text.append(content)
            continue
        if isinstance(content, list):
            text.extend(part.text for part in content if isinstance(part, TextPart))
    return "\n".join(text)


def test_build_session_context_uses_selected_native_branch(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(tmp_path, cwd="/tmp/project", persist=False)
    )
    root_id = asyncio.run(
        manager.append_message(UserMessage(role="user", content="root", timestamp=1.0))
    )
    branch_a_id = asyncio.run(
        manager.append_custom_message_entry(
            custom_type="branch-a",
            content="A",
            display=True,
        )
    )
    manager.branch(root_id)
    asyncio.run(
        manager.append_custom_message_entry(
            custom_type="branch-b",
            content="B",
            display=True,
        )
    )

    context = build_agent_transcript_session_context(
        manager.get_entries(), leaf_id=branch_a_id
    )

    assert [message.role for message in context.messages] == ["user", "application"]
    assert "A" in _context_text(context.messages)
    assert "B" not in _context_text(context.messages)


def test_build_session_context_uses_latest_compaction_checkpoint(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(tmp_path, cwd="/tmp/project", persist=False)
    )
    first_user_id = asyncio.run(
        manager.append_message(UserMessage(role="user", content="first", timestamp=1.0))
    )
    asyncio.run(manager.append_message(_assistant("first answer", 2.0)))
    asyncio.run(manager.append_compaction("old summary", first_user_id, 100))
    second_user_id = asyncio.run(
        manager.append_message(
            UserMessage(role="user", content="second", timestamp=3.0)
        )
    )
    asyncio.run(manager.append_message(_assistant("second answer", 4.0)))
    asyncio.run(manager.append_compaction("new summary", second_user_id, 200))
    asyncio.run(
        manager.append_message(UserMessage(role="user", content="after", timestamp=5.0))
    )

    context = manager.build_session_context()
    rendered = _context_text(context.messages)

    assert [message.role for message in context.messages] == [
        "user",
        "user",
        "assistant",
        "user",
    ]
    assert "new summary" in rendered
    assert "old summary" not in rendered
    assert "first answer" not in rendered
    assert "second answer" in rendered


def test_build_session_context_preserves_state_across_compaction(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(manager.append_thinking_level_change("high"))
    asyncio.run(
        manager.append_model_change("openai", "gpt-5.4", endpoint_id="openai-responses")
    )
    kept_id = asyncio.run(
        manager.append_message(UserMessage(role="user", content="kept", timestamp=1.0))
    )
    asyncio.run(manager.append_compaction("summary", kept_id, 50))

    context = manager.build_session_context()

    assert context.thinking_level == "high"
    assert context.model == {
        "provider": "openai",
        "endpoint_id": "openai-responses",
        "model_id": "gpt-5.4",
    }
    assert "summary" in _context_text(context.messages)
    assert "kept" in _context_text(context.messages)


def test_build_session_context_unknown_or_empty_leaf_is_empty(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(UserMessage(role="user", content="root", timestamp=1.0))
    )

    assert (
        build_agent_transcript_session_context(
            manager.get_entries(), leaf_id=None
        ).messages
        == ()
    )
    assert (
        build_agent_transcript_session_context(
            manager.get_entries(), leaf_id="missing"
        ).messages
        == ()
    )


def test_append_compaction_rejects_blank_boundary(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(UserMessage(role="user", content="old", timestamp=1.0))
    )

    with pytest.raises(ValueError, match="first kept record id"):
        asyncio.run(manager.append_compaction("summary", "", 10))
