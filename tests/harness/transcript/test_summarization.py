from __future__ import annotations

import asyncio

import pytest

import loushang.harness.transcript.summarization as summary_module
from loushang.ai import CallOptions, Context, PreparedRequestLimits
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    Usage,
    UserMessage,
)
from loushang.harness.context import SummaryProfile
from loushang.harness.transcript.maintenance import CompactionPreparation
from loushang.harness.transcript.summarization import (
    SUMMARY_MAX_BATCHES,
    SUMMARY_MAX_CANONICAL_BYTES,
    SummaryCapacityPlanError,
    SummaryImagePolicyError,
    default_summary_completer,
    execute_transcript_compaction,
    serialize_agent_conversation,
)


def _model(*, supports_stream: bool) -> Model:
    return Model(
        id="summary-model",
        name="Summary",
        provider="test-provider",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        capabilities=Capabilities(
            stream=supports_stream,
            context_window=1_024,
            max_tokens=128,
        ),
    )


def _message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="anthropic-messages",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="test-provider",
        model="summary-model",
        response_id="response-1",
        usage=Usage(
            input=1,
            output=1,
            cache_read=0,
            cache_write=0,
            total_tokens=2,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0,
    )


def _summary_profile() -> SummaryProfile:
    return SummaryProfile(
        profile_id="summary-test",
        system_prompt="Summarize safely.",
        prompts={
            "initial": "Create a summary.",
            "update": "Update a summary.",
            "turn-prefix": "Summarize the turn prefix.",
        },
    )


@pytest.mark.parametrize("supports_stream", [True, False])
def test_default_summary_completer_traces_selected_invocation_mode(
    monkeypatch: pytest.MonkeyPatch,
    supports_stream: bool,
) -> None:
    trace_events: list[dict[str, object]] = []
    calls: list[str] = []

    class _Stream:
        async def result(self) -> AssistantMessage:
            return _message("stream summary")

    async def fake_stream(*args, **kwargs):
        del args, kwargs
        calls.append("stream")
        return _Stream()

    async def fake_complete(*args, **kwargs):
        del args, kwargs
        calls.append("complete")
        return _message("complete summary")

    monkeypatch.setattr(summary_module, "stream", fake_stream)
    monkeypatch.setattr(summary_module, "complete", fake_complete)
    mode = "stream" if supports_stream else "complete"

    result = asyncio.run(
        default_summary_completer(
            _model(supports_stream=supports_stream),
            Context(),
            CallOptions(trace=trace_events.append),
        )
    )

    assert calls == [mode]
    assert result == f"{mode} summary"
    assert trace_events == [
        {
            "schema": "loushang.ai.trace.v1",
            "type": "summary:request",
            "source": "summary",
            "name": "request",
            "data": {
                "mode": mode,
                "api": "anthropic-messages",
                "provider": "test-provider",
                "endpoint": "anthropic-messages",
                "model": "summary-model",
            },
        }
    ]


def test_compaction_uses_bounded_request_and_explicit_image_placeholder() -> None:
    captured: dict[str, object] = {}
    image_data = "cHJpdmF0ZS1pbWFnZQ=="

    async def completer(
        model: object,
        context: Context,
        options: CallOptions | None,
    ) -> str:
        del model
        captured["context"] = context
        captured["options"] = options
        return "safe summary"

    result = asyncio.run(
        execute_transcript_compaction(
            preparation=CompactionPreparation(
                first_kept_entry_id="kept",
                messages_to_summarize=[
                    UserMessage(
                        role="user",
                        content=[
                            TextPart(type="text", text="inspect this image"),
                            ImagePart(
                                type="image",
                                data=image_data,
                                mime_type="image/png",
                            ),
                        ],
                        timestamp=0.0,
                    )
                ],
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=10,
            ),
            model=object(),
            compaction_profile=_summary_profile(),
            turn_prefix_profile=_summary_profile(),
            completer=completer,
            request_limits=PreparedRequestLimits(max_canonical_bytes=200_000),
        )
    )

    context = captured["context"]
    options = captured["options"]
    assert isinstance(context, Context)
    assert isinstance(options, CallOptions)
    assert options.request_limits is not None
    assert options.request_limits.max_canonical_bytes == 200_000
    prompt = context.messages[0].content[0].text
    assert image_data not in prompt
    assert (
        "[Image omitted from summary input: mime_type=image/png; "
        "base64_characters=20]"
    ) in prompt
    assert result.details == {
        "degradations": [{"code": "image_omitted", "count": 1}]
    }


def test_summary_image_refusal_is_explicit_and_skips_model_call() -> None:
    calls = 0
    messages = [
        UserMessage(
            role="user",
            content=[
                ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png")
            ],
            timestamp=0.0,
        )
    ]

    async def completer(
        model: object,
        context: Context,
        options: CallOptions | None,
    ) -> str:
        del model, context, options
        nonlocal calls
        calls += 1
        return "unreachable"

    with pytest.raises(SummaryImagePolicyError, match="image policy is 'refuse'"):
        asyncio.run(
            execute_transcript_compaction(
                preparation=CompactionPreparation(
                    first_kept_entry_id="kept",
                    messages_to_summarize=messages,
                    turn_prefix_messages=[],
                    is_split_turn=False,
                    tokens_before=10,
                ),
                model=object(),
                compaction_profile=_summary_profile(),
                turn_prefix_profile=_summary_profile(),
                completer=completer,
                image_policy="refuse",
            )
        )

    assert calls == 0
    with pytest.raises(SummaryImagePolicyError):
        serialize_agent_conversation(messages, image_policy="refuse")


def test_compaction_batches_turns_and_merges_partials_with_bounded_calls() -> None:
    calls: list[tuple[Context, CallOptions]] = []

    async def completer(
        model: object,
        context: Context,
        options: CallOptions | None,
    ) -> str:
        del model
        assert isinstance(options, CallOptions)
        calls.append((context, options))
        return f"partial-{len(calls)}"

    messages = [
        UserMessage(
            role="user",
            content=f"turn-{index}:" + (character * 200_000),
            timestamp=float(index),
        )
        for index, character in enumerate(("a", "b", "c"), start=1)
    ]
    result = asyncio.run(
        execute_transcript_compaction(
            preparation=CompactionPreparation(
                first_kept_entry_id="kept",
                messages_to_summarize=messages,
                turn_prefix_messages=[],
                is_split_turn=False,
                tokens_before=150_000,
            ),
            model=object(),
            compaction_profile=_summary_profile(),
            turn_prefix_profile=_summary_profile(),
            completer=completer,
        )
    )

    assert len(calls) == 4
    assert result.summary == "partial-4"
    history_prompts = [
        call_context.messages[0].content[0].text
        for call_context, _options in calls[:3]
    ]
    for index in range(1, 4):
        assert sum(f"turn-{index}:" in prompt for prompt in history_prompts) == 1
    merge_prompt = calls[3][0].messages[0].content[0].text
    assert "[Partial summary 1]" in merge_prompt
    assert "partial-1" in merge_prompt
    assert "partial-3" in merge_prompt
    assert all(
        options.max_output_tokens == 8_192
        and options.request_limits is not None
        and options.request_limits.max_canonical_bytes
        == SUMMARY_MAX_CANONICAL_BYTES
        for _context, options in calls
    )


def test_compaction_rejects_a_plan_over_the_batch_limit_before_model_calls() -> None:
    calls = 0

    async def completer(
        model: object,
        context: Context,
        options: CallOptions | None,
    ) -> str:
        del model, context, options
        nonlocal calls
        calls += 1
        return "unreachable"

    messages = [
        UserMessage(
            role="user",
            content=f"turn-{index}:" + ("x" * 4_000),
            timestamp=float(index),
        )
        for index in range(SUMMARY_MAX_BATCHES + 1)
    ]
    with pytest.raises(
        SummaryCapacityPlanError,
        match=f"exceeds {SUMMARY_MAX_BATCHES} batches",
    ):
        asyncio.run(
            execute_transcript_compaction(
                preparation=CompactionPreparation(
                    first_kept_entry_id="kept",
                    messages_to_summarize=messages,
                    turn_prefix_messages=[],
                    is_split_turn=False,
                    tokens_before=20_000,
                ),
                model=object(),
                compaction_profile=_summary_profile(),
                turn_prefix_profile=_summary_profile(),
                completer=completer,
                request_limits=PreparedRequestLimits(max_canonical_bytes=70_000),
            )
        )

    assert calls == 0
