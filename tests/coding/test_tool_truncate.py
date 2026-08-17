from loushang.harness.tools.workspace.truncate import (
    TruncationResult,
    format_size,
    formatSize,
    truncate_head,
    truncate_line,
    truncate_tail,
    truncateHead,
    truncateLine,
    truncateTail,
)
from loushang.harness.workspace.truncation import (
    TruncationResult as HarnessTruncationResult,
)
from loushang.harness.workspace.truncation import (
    truncate_head as harness_truncate_head,
)
from loushang.harness.workspace.truncation import (
    truncate_tail as harness_truncate_tail,
)


def test_truncate_head_keeps_prefix_and_sets_metadata() -> None:
    text = "a\nb\nc\nd\n"
    result = truncate_head(text, max_lines=2, max_bytes=1024)
    assert result.content == "a\nb\n"
    assert result.truncated is True
    assert result.truncated_by == "lines"
    assert result.total_lines == 4
    assert result.total_bytes == len(text.encode("utf-8"))
    assert result.output_lines == 2
    assert result.output_bytes == len(result.content.encode("utf-8"))
    assert result.last_line_partial is False
    assert result.first_line_exceeds_limit is False
    assert result.max_lines == 2
    assert result.max_bytes == 1024


def test_truncate_tail_keeps_suffix_and_sets_metadata() -> None:
    text = "a\nb\nc\nd\n"
    result = truncate_tail(text, max_lines=2, max_bytes=1024)
    assert result.content == "c\nd\n"
    assert result.truncated is True
    assert result.truncated_by == "lines"
    assert result.total_lines == 4
    assert result.total_bytes == len(text.encode("utf-8"))
    assert result.output_lines == 2
    assert result.output_bytes == len(result.content.encode("utf-8"))
    assert result.last_line_partial is False
    assert result.first_line_exceeds_limit is False
    assert result.max_lines == 2
    assert result.max_bytes == 1024


def test_truncate_head_reports_first_line_exceeds_limit_without_partial_payload() -> (
    None
):
    text = "abcdef\n"
    result = truncate_head(text, max_lines=2000, max_bytes=3)
    assert result.content == ""
    assert result.truncated is True
    assert result.truncated_by == "bytes"
    assert result.first_line_exceeds_limit is True
    assert result.output_lines == 0
    assert result.output_bytes == 0


def test_truncate_tail_enforces_byte_limit() -> None:
    text = "abcdef\n"
    result = truncate_tail(text, max_lines=2000, max_bytes=3)
    assert len(result.content.encode("utf-8")) <= 3
    assert result.truncated is True
    assert result.truncated_by == "bytes"
    assert result.last_line_partial is True


def test_truncate_head_prefers_byte_metadata_when_kept_prefix_is_further_clipped() -> (
    None
):
    text = "ab\ncd\nef\n"
    result = truncate_head(text, max_lines=2, max_bytes=1)
    assert result.content == ""
    assert result.truncated is True
    assert result.truncated_by == "bytes"
    assert result.first_line_exceeds_limit is True


def test_truncate_tail_prefers_byte_metadata_when_kept_suffix_is_further_clipped() -> (
    None
):
    text = "ab\ncd\nef\n"
    result = truncate_tail(text, max_lines=2, max_bytes=1)
    assert result.content == "\n"
    assert result.truncated is True
    assert result.truncated_by == "bytes"
    assert result.last_line_partial is True


def test_truncate_head_byte_limit_keeps_only_complete_lines_after_first_line() -> None:
    text = "ab\ncd\nef\n"
    result = truncate_head(text, max_lines=2000, max_bytes=4)
    assert result.content == "ab\n"
    assert result.truncated is True
    assert result.truncated_by == "bytes"
    assert result.output_lines == 1
    assert result.output_bytes == 3
    assert result.first_line_exceeds_limit is False


def test_format_size_matches_tool_notice_units() -> None:
    assert format_size(12) == "12B"
    assert format_size(1536) == "1.5KB"
    assert format_size(2 * 1024 * 1024) == "2.0MB"
    assert formatSize(1536) == "1.5KB"


def test_truncate_line_returns_pi_style_suffix() -> None:
    result = truncate_line("abcdef", max_chars=3)
    assert result.text == "abc... [truncated]"
    assert result.was_truncated is True

    unchanged = truncate_line("abc", max_chars=3)
    assert unchanged.text == "abc"
    assert unchanged.was_truncated is False


def test_pi_style_truncation_aliases_delegate_to_python_helpers() -> None:
    assert (
        truncateHead("a\nb\n", max_lines=1).content
        == truncate_head("a\nb\n", max_lines=1).content
    )
    assert (
        truncateTail("a\nb\n", max_lines=1).content
        == truncate_tail("a\nb\n", max_lines=1).content
    )
    assert (
        truncateLine("abcdef", max_chars=3).text
        == truncate_line("abcdef", max_chars=3).text
    )


def test_coding_truncation_exports_preserve_harness_owner_identity() -> None:
    assert TruncationResult is HarnessTruncationResult
    assert truncate_head is harness_truncate_head
    assert truncate_tail is harness_truncate_tail
    assert TruncationResult.__module__ == "loushang.harness.workspace.truncation"
