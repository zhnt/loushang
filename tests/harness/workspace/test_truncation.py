from __future__ import annotations

import pytest

from loushang.harness.workspace.truncation import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    TruncationResult,
    truncate_head,
    truncate_tail,
)


def test_truncate_head_keeps_complete_prefix_lines_and_metadata() -> None:
    text = "a\nb\nc\nd\n"

    result = truncate_head(text, max_lines=2, max_bytes=1024)

    assert result == TruncationResult(
        content="a\nb\n",
        truncated=True,
        truncated_by="lines",
        total_lines=4,
        total_bytes=len(text.encode("utf-8")),
        output_lines=2,
        output_bytes=len("a\nb\n".encode("utf-8")),
        max_lines=2,
        max_bytes=1024,
    )


def test_truncate_head_reports_oversized_first_line_without_partial_output() -> None:
    result = truncate_head("abcdef\n", max_lines=DEFAULT_MAX_LINES, max_bytes=3)

    assert result.content == ""
    assert result.truncated_by == "bytes"
    assert result.first_line_exceeds_limit is True
    assert result.output_bytes == 0


def test_truncate_tail_keeps_suffix_and_utf8_byte_boundary() -> None:
    result = truncate_tail("prefix-你好\n", max_lines=DEFAULT_MAX_LINES, max_bytes=4)

    assert result.content == "好\n"
    assert len(result.content.encode("utf-8")) == 4
    assert result.truncated is True
    assert result.truncated_by == "bytes"
    assert result.last_line_partial is True


def test_truncate_tail_uses_shared_defaults_when_content_fits() -> None:
    result = truncate_tail("ok\n")

    assert result.content == "ok\n"
    assert result.truncated is False
    assert result.max_lines == DEFAULT_MAX_LINES == 2000
    assert result.max_bytes == DEFAULT_MAX_BYTES == 50 * 1024


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"max_lines": 0}, ValueError, "max_lines must be >= 1"),
        ({"max_lines": 1.5}, TypeError, "max_lines must be an integer"),
        ({"max_bytes": 0}, ValueError, "max_bytes must be >= 1"),
        ({"max_bytes": 1.5}, TypeError, "max_bytes must be an integer"),
    ],
)
def test_truncation_rejects_invalid_limits(
    kwargs: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        truncate_head("content", **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("prefix-你好\n", 5, "好\n"),
        ("prefix-你好\n", 6, "好\n"),
        ("prefix-😀\n", 4, "\n"),
        ("prefix-😀\n", 3, "\n"),
        (
            b"prefix-\xff\x80abc".decode("utf-8", errors="surrogateescape"),
            4,
            "\udc80abc",
        ),
    ],
)
def test_tail_clipping_keeps_original_character_boundaries_and_raw_byte_counts(
    text, limit, expected
):
    result = truncate_tail(text, max_bytes=limit)
    assert result.content == expected
    assert result.output_bytes == len(
        expected.encode("utf-8", errors="surrogateescape")
    )
    assert result.total_bytes == len(text.encode("utf-8", errors="surrogateescape"))
    assert result.truncated and result.last_line_partial
