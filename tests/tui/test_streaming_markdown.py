from __future__ import annotations

from collections.abc import Iterable

import pytest

from loushang.tui import (
    RenderConstraints,
    set_ambiguous_width,
    strip_control_sequences,
)
from loushang.tui.markdown import renderer as markdown_renderer
from loushang.tui.theme import ThemeResolver

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


def test_streaming_flat_bullet_list_reuses_completed_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_sources: list[str] = []
    original = markdown_renderer._parse_markdown_groups

    def parse_groups(
        markdown: str,
        *,
        line_offset: int,
    ) -> tuple[tuple[markdown_renderer._ParsedMarkdownGroup, ...], bool]:
        parsed_sources.append(markdown)
        return original(markdown, line_offset=line_offset)

    monkeypatch.setattr(markdown_renderer, "_parse_markdown_groups", parse_groups)
    source = ""
    state = markdown_renderer._StreamingMarkdownParseState()
    for index in range(60):
        source += f"- item {index} **bold** and `code` [link](https://example.com)\n"
        assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)

    parsed_sources.clear()
    source += "- final item"
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
    assert parsed_sources == []

    source += "\n\nTail"
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)


def test_streaming_independent_inline_bullet_burst_matches_commonmark_without_bulk_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_sources: list[str] = []
    original = markdown_renderer._parse_markdown_groups

    def parse_groups(
        markdown: str,
        *,
        line_offset: int,
    ) -> tuple[tuple[markdown_renderer._ParsedMarkdownGroup, ...], bool]:
        parsed_sources.append(markdown)
        return original(markdown, line_offset=line_offset)

    monkeypatch.setattr(markdown_renderer, "_parse_markdown_groups", parse_groups)
    source = "".join(
        f"- item {index} **bold** [link](https://example.com/{index})\n"
        for index in range(100)
    )
    state = markdown_renderer._StreamingMarkdownParseState()
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
    assert parsed_sources == []

    parsed_sources.clear()
    new_burst = "".join(f"- next {index} **bold**\n" for index in range(100))
    source += new_burst
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
    assert parsed_sources == []


@pytest.mark.parametrize(
    "body",
    (
        "**bold** text",
        "alpha *emphasis*",
        "`code` text",
        "[link](https://example.com)",
        "a ~~strike~~",
        r"a \*escaped*",
        "[x] task",
        "normal ![image](x.png)",
        "__bold__",
        "a [link](https://x \"title\")",
        "a &amp; b",
        "a 😀 中文",
    ),
)
def test_independent_inline_bullet_item_matches_commonmark(body: str) -> None:
    source = "".join(f"- {body}{index}\n" for index in range(12))
    expected, _index = markdown_renderer._parse_markdown_it_blocks(
        markdown_renderer._MARKDOWN_PARSER.parse(source),
        0,
        stop_type=None,
        source_lines=source.split("\n"),
    )
    state = markdown_renderer._StreamingMarkdownParseState()
    assert state.parse(source) == tuple(expected)


@pytest.mark.parametrize(
    "body",
    (
        "[id]: https://example.com",
        "# heading",
        "> quote",
        "- nested",
        "1. nested",
        "```python",
        "***",
        "___",
        "*",
        "<div>",
        "  indented",
        "ends with space ",
    ),
)
def test_independent_inline_bullet_item_rejects_block_or_reference_syntax(
    body: str,
) -> None:
    assert not markdown_renderer._independent_inline_bullet_item(f"- {body}")


def test_large_independent_list_delta_splits_without_changing_markdown() -> None:
    source = "".join(
        f"- **Line {index}**: [link](https://example.com/{index})\n"
        for index in range(2000)
    )
    chunks = markdown_renderer.split_independent_flat_bullet_delta(source)
    assert chunks is not None and len(chunks) > 1
    assert all(chunk.endswith("\n") for chunk in chunks)
    assert "".join(chunks) == source

    state = markdown_renderer._StreamingMarkdownParseState()
    streamed = ""
    for chunk in chunks:
        streamed += chunk
        state.parse(streamed)
    expected, _index = markdown_renderer._parse_markdown_it_blocks(
        markdown_renderer._MARKDOWN_PARSER.parse(source),
        0,
        stop_type=None,
        source_lines=source.split("\n"),
    )
    assert state.parse(streamed) == tuple(expected)
    assert markdown_renderer.split_independent_flat_bullet_delta(
        source + "- [ref]: https://example.com\n"
    ) is None


def test_large_markdown_delta_splits_only_at_top_level_block_boundaries() -> None:
    source = "".join(
        f"## Section {index}\n\nParagraph {index} with **bold** and [link](https://example.com/{index}).\n\n"
        for index in range(500)
    )
    chunks = markdown_renderer.split_independent_markdown_block_delta(source)
    assert chunks is not None and len(chunks) > 1
    assert "".join(chunks) == source
    assert all(chunk.endswith("\n") for chunk in chunks)

    state = markdown_renderer._StreamingMarkdownParseState()
    streamed = ""
    for chunk in chunks:
        streamed += chunk
        state.parse(streamed)
    assert state.parse(streamed) == markdown_renderer._parse_markdown_blocks(source)


def test_large_markdown_delta_keeps_fences_and_references_atomic() -> None:
    source = "```python\n" + "print(1)\n" * 2_000 + "```\n"
    assert markdown_renderer.split_independent_markdown_block_delta(source) is None
    referenced = "[link][ref]\n\n" * 1_000 + "[ref]: https://example.com\n"
    assert markdown_renderer.split_independent_markdown_block_delta(referenced) is None


def test_atomic_large_table_worker_parse_matches_committed_renderer() -> None:
    source = "| Name | Value |\n| --- | --- |\n" + "".join(
        f"| row {index} | [link](https://example.com/{index}) |\n"
        for index in range(600)
    )
    analysis = markdown_renderer.analyze_large_markdown_delta(source)

    assert analysis.chunks is None
    assert analysis.prepared_table_blocks == markdown_renderer._parse_markdown_blocks(source)
    assert markdown_renderer.analyze_large_markdown_delta(
        source + "\n[link]: https://other.example\n"
    ).prepared_table_blocks is None

    cache = markdown_renderer.MarkdownRenderCache()
    assert analysis.prepared_table_blocks is not None
    cache.prepare_blocks(source, analysis.prepared_table_blocks)
    changed = source + "\nAfter the table.\n"
    assert cache.take_prepared_blocks(changed) is None
    assert cache.take_prepared_blocks(source) == analysis.prepared_table_blocks
    assert cache.take_prepared_blocks(source) is None
    cache.prepare_blocks(source, analysis.prepared_table_blocks)
    cache.clear()
    assert cache.take_prepared_blocks(source) is None


def test_prepared_table_render_reuses_exact_context_and_falls_back_after_resize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "| Name | Value |\n| --- | --- |\n| first | **bold** |\n"
    blocks = markdown_renderer._parse_markdown_blocks(source)
    theme = ThemeResolver()
    spec = markdown_renderer.atomic_markdown_render_spec(
        source, width=78, theme=theme, capabilities=None
    )
    prepared = markdown_renderer.render_prepared_atomic_markdown(source, blocks, spec)
    assert prepared == markdown_renderer.MarkdownRenderer(
        source, theme=theme
    ).render(spec.constraints)
    cache = markdown_renderer.MarkdownRenderCache()
    cache.prepare_blocks(source, blocks)
    cache.prepare_result(spec.cache_key, prepared)
    renderer = markdown_renderer.MarkdownRenderer(
        source, theme=theme, render_cache=cache
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            markdown_renderer,
            "_render_table",
            lambda *_args, **_kwargs: pytest.fail("prepared table was rerendered"),
        )
        assert renderer.render(spec.constraints) == prepared

    cache.prepare_blocks(source, blocks)
    cache.prepare_result(spec.cache_key, prepared)
    resized = RenderConstraints(
        width=spec.constraints.width - 10, max_height=spec.constraints.max_height
    )
    actual = renderer.render(resized)
    expected = markdown_renderer.MarkdownRenderer(
        source, theme=theme
    ).render(resized)
    assert actual == expected
    assert cache.take_prepared_result(spec.cache_key) is None

    cache.prepare_blocks(source, blocks)
    cache.prepare_result(spec.cache_key, prepared)
    theme.update_overrides({"markdown.table.header": {"foreground": "red"}})
    restyled = renderer.render(spec.constraints)
    canonical = markdown_renderer.MarkdownRenderer(
        source, theme=theme
    ).render(spec.constraints)
    assert restyled == canonical
    assert restyled != prepared


def test_streaming_plain_bullet_burst_matches_commonmark_without_bulk_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "".join(f"- item {index} detail {index}\n" for index in range(512))
    expected, _index = markdown_renderer._parse_markdown_it_blocks(
        markdown_renderer._MARKDOWN_PARSER.parse(source),
        0,
        stop_type=None,
        source_lines=source.split("\n"),
    )
    monkeypatch.setattr(
        markdown_renderer,
        "_parse_markdown_groups",
        lambda *_args, **_kwargs: pytest.fail("plain items need no bulk parse"),
    )

    state = markdown_renderer._StreamingMarkdownParseState()
    assert state.parse(source) == tuple(expected)
    assert markdown_renderer._render_markdown_blocks(
        state.parse(source), width=51
    ) == markdown_renderer._render_markdown_blocks(tuple(expected), width=51)


@pytest.mark.parametrize(
    "source",
    (
        "- item 0 detail 0",
        "- item 0 detail 0\n- item 1 detail 1\n",
        "- Path /tmp/file.py:12, status 200\n- Next item (ok)\n",
        "- 1. nested ordered item\n- 2) next item\n",
        "- http://example.com\n- next item\n",
        "".join(f"- item {index} detail {index}\n" for index in range(128)),
    ),
)
def test_plain_bullet_completion_matches_commonmark_blocks(source: str) -> None:
    expected, _index = markdown_renderer._parse_markdown_it_blocks(
        markdown_renderer._MARKDOWN_PARSER.parse(source),
        0,
        stop_type=None,
        source_lines=source.split("\n"),
    )
    assert markdown_renderer._parse_markdown_blocks(source) == tuple(expected)


def test_streaming_flat_bullet_list_keeps_completed_render_segments() -> None:
    cache = markdown_renderer.MarkdownRenderCache()
    stream_key = object()
    constraints = RenderConstraints(width=80, max_height=1000)
    source = "".join(
        f"- item {index} **bold** and [link](https://example.com/{index})\n"
        for index in range(128)
    )

    def render(text: str):
        return markdown_renderer.MarkdownRenderer(
            text, render_cache=cache, streaming_key=stream_key
        ).render_streaming_segments(constraints)

    first = render(source)
    assert first is not None
    assert len(first.segments) >= 2
    assert all(segment.stable for segment in first.segments[:2])

    extended = source + "- final **item**\n"
    second = render(extended)
    assert second is not None
    assert second.segments[:2] == first.segments[:2]
    assert all(
        current is previous
        for current, previous in zip(
            second.segments[:2], first.segments[:2], strict=True
        )
    )
    expected = markdown_renderer.MarkdownRenderer(extended).render(constraints)
    assert tuple(
        line for segment in second.segments for line in segment.lines
    ) == tuple(line.text for line in expected.lines)


def test_streaming_flat_bullet_segments_reset_when_structure_changes() -> None:
    cache = markdown_renderer.MarkdownRenderCache()
    stream_key = object()
    constraints = RenderConstraints(width=80, max_height=1000)
    source = "".join(f"- item {index}\n" for index in range(128))
    first = markdown_renderer.MarkdownRenderer(
        source, render_cache=cache, streaming_key=stream_key
    ).render_streaming_segments(constraints)
    assert first is not None
    assert first.segments[0].stable

    changed = source + "\nTail paragraph"
    second = markdown_renderer.MarkdownRenderer(
        changed, render_cache=cache, streaming_key=stream_key
    ).render_streaming_segments(constraints)
    assert second is not None
    assert all(segment is not first.segments[0] for segment in second.segments)
    expected = markdown_renderer.MarkdownRenderer(changed).render(constraints)
    assert tuple(
        line for segment in second.segments for line in segment.lines
    ) == tuple(line.text for line in expected.lines)


@pytest.mark.parametrize(
    "suffix",
    (
        "- ```python\n- code",
        "- <div>\n- text",
        "- [id]: https://example.com\n- [id]",
        "\nTail",
        "* another marker",
    ),
)
def test_streaming_flat_bullet_list_falls_back_for_structural_changes(suffix: str) -> None:
    state = markdown_renderer._StreamingMarkdownParseState()
    source = "- [go][id]\n- **bold**\n"
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)
    source += suffix
    assert state.parse(source) == markdown_renderer._parse_markdown_blocks(source)


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
