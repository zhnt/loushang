from __future__ import annotations

import asyncio

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding.session_manager import SessionManager


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(context_window=100, max_tokens=64),
    )


def _usage(total_tokens: int) -> Usage:
    return Usage(
        input=total_tokens,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=total_tokens,
        cost={},
    )


def _assistant(
    *, total_tokens: int, stop_reason: str = "stop", timestamp: float = 1.0
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="reply")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(total_tokens),
        stop_reason=stop_reason,
        error_message=None,
        timestamp=timestamp,
    )


def test_context_usage_snapshot_treats_length_usage_as_compactable() -> None:
    from loushang.harness.transcript import build_context_usage_snapshot

    snapshot = build_context_usage_snapshot(
        [_assistant(total_tokens=95, stop_reason="length")],
        [],
        _model(),
        reserve_tokens=10,
    )

    assert snapshot.tokens == 95
    assert snapshot.context_window == 100
    assert snapshot.threshold_tokens == 90
    assert snapshot.source == "assistant_usage"
    assert snapshot.compactable is True
    assert snapshot.stale_after_compaction is False


def test_context_usage_snapshot_uses_compact_percent_threshold() -> None:
    from loushang.harness.transcript import build_context_usage_snapshot

    snapshot = build_context_usage_snapshot(
        [_assistant(total_tokens=85, stop_reason="stop")],
        [],
        _model(),
        reserve_tokens=10,
        compact_percent=80,
    )

    assert snapshot.tokens == 85
    assert snapshot.threshold_tokens == 80
    assert snapshot.compactable is True


def test_context_usage_snapshot_exposes_compaction_budget_fields() -> None:
    from loushang.harness.transcript import build_context_usage_snapshot

    snapshot = build_context_usage_snapshot(
        [_assistant(total_tokens=85, stop_reason="stop")],
        [],
        _model(),
        reserve_tokens=10,
        compact_percent=80,
        keep_recent_tokens=32,
    )

    assert snapshot.compact_percent == 80
    assert snapshot.reserve_tokens == 10
    assert snapshot.keep_recent_tokens == 32
    assert snapshot.percent_threshold_tokens == 80
    assert snapshot.reserve_threshold_tokens == 90
    assert snapshot.threshold_tokens == 80
    assert snapshot.threshold_reason == "compact_percent"


def test_context_usage_snapshot_consumes_ai_usage_derived_from_raw_parts() -> None:
    from loushang.ai.event_stream import AssistantMessageEventStream, RawAssembler
    from loushang.harness.transcript import build_context_usage_snapshot

    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
    )
    assembler.feed({"type": "response_start", "response_id": "resp-1"})
    assembler.feed({"type": "usage_delta", "input": 80, "output": 10, "cache_read": 1})
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())
    snapshot = build_context_usage_snapshot([message], [], _model(), reserve_tokens=10)

    assert message.usage.total_tokens == 91
    assert snapshot.tokens == 91
    assert snapshot.compactable is True


def test_context_usage_snapshot_marks_pre_compaction_usage_stale(tmp_path) -> None:
    from loushang.harness.transcript import build_context_usage_snapshot

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="before")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant(total_tokens=95, timestamp=1.0)))
    first_kept_entry_id = manager.get_entries()[0].record_id
    asyncio.run(manager.append_compaction("summary", first_kept_entry_id, 95))
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="after")],
                timestamp=2.0,
            )
        )
    )

    snapshot = build_context_usage_snapshot(
        manager.build_session_context().messages,
        manager.get_branch(),
        _model(),
        reserve_tokens=10,
    )

    assert snapshot.tokens is None
    assert snapshot.context_window == 100
    assert snapshot.source == "unknown"
    assert snapshot.stale_after_compaction is True
    assert snapshot.compactable is False
