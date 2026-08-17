from __future__ import annotations

from collections.abc import Iterable

import pytest

from loushang.tui import (
    RenderConstraints,
    set_ambiguous_width,
    strip_control_sequences,
)
from loushang.tui.markdown import renderer as markdown_renderer

pytestmark = pytest.mark.tui_render_contract


def _assert_incremental_matches_full(
    chunks: Iterable[str],
) -> markdown_renderer._StreamingMarkdownParseState:
    state = markdown_renderer._StreamingMarkdownParseState()
    source = ""
    for chunk in chunks:
        source += chunk
        incremental = state.parse(source)
        canonical = markdown_renderer._parse_markdown_blocks(source)
        assert incremental == canonical
        assert markdown_renderer._render_markdown_blocks(
            incremental,
            width=51,
        ) == markdown_renderer._render_markdown_blocks(
            canonical,
            width=51,
        )
    return state


def test_streaming_markdown_parses_only_mutable_top_level_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_sources: list[tuple[str, int]] = []
    original = markdown_renderer._parse_markdown_groups

    def parse_groups(
        markdown: str,
        *,
        line_offset: int,
    ) -> tuple[tuple[markdown_renderer._ParsedMarkdownGroup, ...], bool]:
        parsed_sources.append((markdown, line_offset))
        return original(markdown, line_offset=line_offset)

    monkeypatch.setattr(markdown_renderer, "_parse_markdown_groups", parse_groups)

    _assert_incremental_matches_full(
        (
            "## Block 1\n\nfirst",
            "\n\n## Block 2",
            "\n\nsecond **bold**",
            " grows",
            "\n\n## Block 3\n\nthird",
        )
    )

    assert "Block 1" in parsed_sources[0][0]
    assert "Block 1" not in parsed_sources[-1][0]
    assert len(parsed_sources[-1][0]) < len(
        "".join(
            (
                "## Block 1\n\nfirst",
                "\n\n## Block 2",
                "\n\nsecond **bold**",
                " grows",
                "\n\n## Block 3\n\nthird",
            )
        )
    )
    assert parsed_sources[-1][1] > 0


def test_streaming_markdown_keeps_continuous_list_as_one_mutable_group() -> None:
    state = _assert_incremental_matches_full(
        (
            "Intro\n\n- one\n",
            "- two\n",
        )
    )

    assert state._stable_groups == []

    source = "Intro\n\n- one\n- two\n\nTail"
    blocks = state.parse(source)

    assert blocks == markdown_renderer._parse_markdown_blocks(source)
    assert [group.blocks[0].kind for group in state._stable_groups] == ["paragraph"]


@pytest.mark.parametrize(
    "source",
    (
        "Intro\n\n1. one\n2. two\n\n1.",
        "Intro\n\n1) one\n2) two\n\n1)",
        "Intro\n\n3. one\n4. two\n\n1.",
    ),
)
def test_streaming_markdown_keeps_one_group_of_lookbehind_for_ordered_list_frontier(
    source: str,
) -> None:
    state = markdown_renderer._StreamingMarkdownParseState()
    streamed = ""

    for character in source:
        streamed += character
        assert state.parse(streamed) == markdown_renderer._parse_markdown_blocks(streamed)


def test_streaming_markdown_keeps_growing_table_as_one_mutable_group() -> None:
    state = _assert_incremental_matches_full(
        (
            "Intro\n\n| A | B |\n",
            "|---|---|\n",
            "| 1 | 2 |\n",
        )
    )

    assert state._stable_groups == []

    source = "Intro\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nTail"
    blocks = state.parse(source)

    assert blocks == markdown_renderer._parse_markdown_blocks(source)
    assert [group.blocks[0].kind for group in state._stable_groups] == ["paragraph"]


def test_streaming_markdown_keeps_fence_mutable_until_a_later_top_level_block() -> None:
    fence = "`" * 3
    state = _assert_incremental_matches_full(
        (
            f"Intro\n\n{fence}py\nx = 1\n",
            f"{fence}\n",
        )
    )

    assert state._stable_groups == []

    source = f"Intro\n\n{fence}py\nx = 1\n{fence}\n\nTail"
    blocks = state.parse(source)

    assert blocks == markdown_renderer._parse_markdown_blocks(source)
    assert [group.blocks[0].kind for group in state._stable_groups] == ["paragraph"]


@pytest.mark.parametrize(
    ("source", "kinds"),
    (
        ("Head\n\nTail", ["paragraph", "blank", "paragraph"]),
        ("Head\n\n\nTail", ["paragraph", "blank", "paragraph"]),
        ("# Head\nTail", ["heading", "paragraph"]),
    ),
)
def test_streaming_markdown_preserves_boundary_source_gap(source: str, kinds: list[str]) -> None:
    state = markdown_renderer._StreamingMarkdownParseState()

    blocks = state.parse(source)

    assert blocks == markdown_renderer._parse_markdown_blocks(source)
    assert [block.kind for block in blocks] == kinds


def test_streaming_markdown_rebases_repeated_tail_line_ranges() -> None:
    state = markdown_renderer._StreamingMarkdownParseState()

    for source, expected_starts in (
        ("A\n\nB", []),
        ("A\n\nB\n\nC", [0]),
        ("A\n\nB\n\nC\n\nD", [0, 2]),
    ):
        assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
        assert [group.start_line for group in state._stable_groups] == expected_starts


def test_streaming_markdown_falls_back_for_late_reference_definition() -> None:
    state = markdown_renderer._StreamingMarkdownParseState()
    source = "[go][id]\n\nMiddle\n\nTail"

    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
    assert state._stable_groups

    source += "\n\n[id]: https://example.com"
    blocks = state.parse(source)

    assert blocks == markdown_renderer._parse_markdown_blocks(source)
    assert state._full_parse_only is True
    assert state._stable_end_line == 0
    assert state._stable_groups == []
    assert any(token.kind == "link" and token.href == "https://example.com" for token in blocks[0].inline)

    source += "\n\nAfter"
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
    assert state._stable_end_line == 0


def test_streaming_markdown_resets_on_non_append_replacement() -> None:
    state = markdown_renderer._StreamingMarkdownParseState()
    state.parse("Alpha\n\nTail")

    replacement = "Beta\n\nTail"
    blocks = state.parse(replacement)

    assert blocks == markdown_renderer._parse_markdown_blocks(replacement)
    assert all("Alpha" not in block.text for block in blocks)


def test_markdown_render_cache_resets_streaming_state_for_new_key() -> None:
    cache = markdown_renderer.MarkdownRenderCache()
    first_key = object()
    second_key = object()
    cache.parse_streaming("Alpha\n\nTail", key=first_key)
    first_state = cache._streaming_parse_state

    blocks = cache.parse_streaming("Alpha\n\nTail grows", key=second_key)

    assert cache._streaming_parse_state is not first_state
    assert blocks == markdown_renderer._parse_markdown_blocks("Alpha\n\nTail grows")


def test_streaming_render_cache_context_follows_ambiguous_width_policy() -> None:
    source = (
        "| Stream | Value |\n"
        "| --- | --- |\n"
        "| row | Ω |\n\n"
        "First\n\nSecond\n\nThird"
    )
    cache = markdown_renderer.MarkdownRenderCache()
    renderer = markdown_renderer.MarkdownRenderer(
        source,
        render_cache=cache,
        streaming_key=object(),
    )
    constraints = RenderConstraints(width=40, max_height=100)
    try:
        set_ambiguous_width(1)
        narrow = renderer.render_streaming_segments(constraints)
        assert narrow is not None
        narrow_lines = [
            strip_control_sequences(line)
            for segment in narrow.segments
            for line in segment.lines
        ]
        assert any("┌" in line for line in narrow_lines)
        narrow_context = cache._streaming_render_context

        set_ambiguous_width(2)
        wide = renderer.render_streaming_segments(constraints)
        assert wide is not None
        wide_lines = [
            strip_control_sequences(line)
            for segment in wide.segments
            for line in segment.lines
        ]

        assert cache._streaming_render_context != narrow_context
        assert not any(set(line) & set("┌─┬┐├┼┤│└┴┘") for line in wide_lines)
    finally:
        set_ambiguous_width(1)
