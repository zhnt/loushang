from __future__ import annotations

from loushang.ai.types import AssistantMessage, ImagePart, TextPart, ThinkingPart, Usage
from loushang.ai.utils.overflow import get_overflow_patterns, is_context_overflow


def _assistant(
    *,
    stop_reason: str = "stop",
    error_message: str | None = None,
    usage: Usage | None = None,
    content: list[TextPart] | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=content or [],
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
        response_id=None,
        usage=usage
        or Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason=stop_reason,  # type: ignore[arg-type]
        error_message=error_message,
        timestamp=0.0,
    )


def test_error_message_overflow_detected() -> None:
    msg = _assistant(
        stop_reason="error",
        error_message="exceeded model token limit",
        usage=Usage(
            input=100, output=0, cache_read=0, cache_write=0, total_tokens=100, cost={}
        ),
    )
    assert is_context_overflow(msg, context_window=128000) is True


def test_error_message_no_overflow() -> None:
    msg = _assistant(
        stop_reason="error",
        error_message="rate limited",
        usage=Usage(
            input=100, output=0, cache_read=0, cache_write=0, total_tokens=100, cost={}
        ),
    )
    assert is_context_overflow(msg, context_window=128000) is False


def test_cerebras_status_without_body_is_context_overflow() -> None:
    msg = _assistant(
        stop_reason="error",
        error_message="413 status code (no body)",
    )

    assert is_context_overflow(msg, context_window=128000) is True


def test_silent_overflow_by_input_tokens() -> None:
    msg = _assistant(
        usage=Usage(
            input=130000,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=130000,
            cost={},
        ),
    )
    assert is_context_overflow(msg, context_window=128000) is True


def test_silent_overflow_by_input_plus_cache_read() -> None:
    msg = _assistant(
        usage=Usage(
            input=120000,
            output=0,
            cache_read=10000,
            cache_write=0,
            total_tokens=130000,
            cost={},
        ),
    )
    assert is_context_overflow(msg, context_window=128000) is True


def test_silent_overflow_by_total_tokens_for_empty_response() -> None:
    """An empty stop response over the window should trigger silent overflow recovery."""
    msg = _assistant(
        usage=Usage(
            input=50000,
            output=80000,
            cache_read=0,
            cache_write=0,
            total_tokens=130000,
            cost={},
        ),
        content=[],
    )
    assert is_context_overflow(msg, context_window=128000) is True


def test_silent_overflow_heuristic_empty_content_near_limit() -> None:
    """stop + empty content + total_tokens >= 95% context_window should trigger overflow."""
    context_window = 128000
    msg = _assistant(
        usage=Usage(
            input=122000,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=122000,
            cost={},
        ),
        content=[],
    )
    assert is_context_overflow(msg, context_window=context_window) is True


def test_silent_overflow_heuristic_not_triggered_with_content() -> None:
    """Near-limit but non-empty responses should not trigger the empty-response heuristic."""
    context_window = 128000
    msg = _assistant(
        usage=Usage(
            input=122000,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=122000,
            cost={},
        ),
        content=[TextPart(type="text", text="hello")],
    )
    assert is_context_overflow(msg, context_window=context_window) is False


def test_total_tokens_over_window_not_overflow_when_content_present() -> None:
    """A normal high-token answer with content should not be treated as overflow."""
    msg = _assistant(
        usage=Usage(
            input=50000,
            output=80000,
            cache_read=0,
            cache_write=0,
            total_tokens=130000,
            cost={},
        ),
        content=[TextPart(type="text", text="real answer")],
    )
    assert is_context_overflow(msg, context_window=128000) is False


def test_total_tokens_over_window_not_overflow_with_thinking_or_image_content() -> None:
    thinking_message = _assistant(
        usage=Usage(
            input=50000,
            output=80000,
            cache_read=0,
            cache_write=0,
            total_tokens=130000,
            cost={},
        ),
        content=[ThinkingPart(type="thinking", thinking="reasoning")],
    )
    image_message = _assistant(
        usage=Usage(
            input=50000,
            output=80000,
            cache_read=0,
            cache_write=0,
            total_tokens=130000,
            cost={},
        ),
        content=[ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png")],
    )

    assert is_context_overflow(thinking_message, context_window=128000) is False
    assert is_context_overflow(image_message, context_window=128000) is False


def test_silent_overflow_heuristic_not_triggered_below_threshold() -> None:
    """Empty content but total_tokens < 95% should NOT trigger."""
    context_window = 128000
    msg = _assistant(
        usage=Usage(
            input=100000,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=100000,
            cost={},
        ),
        content=[],
    )
    assert is_context_overflow(msg, context_window=context_window) is False


def test_no_overflow_when_well_below_limit() -> None:
    msg = _assistant(
        usage=Usage(
            input=1000,
            output=500,
            cache_read=0,
            cache_write=0,
            total_tokens=1500,
            cost={},
        ),
    )
    assert is_context_overflow(msg, context_window=128000) is False


def test_no_context_window_skips_silent_check() -> None:
    msg = _assistant(
        usage=Usage(
            input=999999,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=999999,
            cost={},
        ),
    )
    assert is_context_overflow(msg, context_window=None) is False


def test_get_overflow_patterns_returns_copy() -> None:
    patterns = get_overflow_patterns()

    assert patterns
    patterns.clear()
    assert get_overflow_patterns()
