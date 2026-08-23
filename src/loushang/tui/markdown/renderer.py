from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache, partial
from typing import Protocol, TypeAlias, cast

from markdown_it import MarkdownIt
from markdown_it.token import Token

from loushang.tui.cell_width import (
    ambiguous_width,
    autowrap_safe_width,
    max_display_cluster_width,
    normalize_box_drawing_diagram,
    truncate_to_width,
    visible_width,
    wrap_ansi,
    wrap_cells,
)
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.markdown.inline import (
    _inline_tokens_from_markdown_it,
    _inline_tokens_from_plain_text,
    _inline_tokens_to_plain_text,
    _render_inline,
    _render_inline_tokens,
)
from loushang.tui.markdown.style import (
    _apply_markdown_style,
    _has_background_style,
    _resolve_style,
)
from loushang.tui.markdown.types import (
    _InlineToken,
    _MarkdownBlock,
    _MarkdownKind,
    _TableAlignment,
    _TableCell,
    _TableRow,
)
from loushang.tui.terminal_capabilities import TerminalRuntimeCapabilities
from loushang.tui.terminal_image import (
    CellDimensions,
    ImageDimensions,
    ImageProtocolSelection,
    is_terminal_image_line,
    render_terminal_image_result,
)
from loushang.tui.theme import (
    TerminalCapabilities,
    ThemeResolver,
    ThemeStyle,
    apply_theme_style,
)

_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MARKDOWN_LINE_CACHE_SIZE = 2_048
_MARKDOWN_STABLE_BLOCK_CACHE_SIZE = 4_096
# A partial list marker can merge backward into the preceding top-level list.
_STREAMING_MARKDOWN_FRONTIER_GROUPS = 2
_MARKDOWN_PARSER = MarkdownIt("commonmark").enable("table").enable("strikethrough")
_QUOTE_MARKER = "│ "


class CodeHighlighter(Protocol):
    def highlight(self, code: str, language: str) -> Sequence[str]: ...


class CapabilityAwareCodeHighlighter(Protocol):
    def highlight(self, code: str, language: str, capabilities: TerminalCapabilities | None) -> Sequence[str]: ...


CodeHighlighterLike: TypeAlias = CodeHighlighter | CapabilityAwareCodeHighlighter


@dataclass(frozen=True, slots=True)
class _ParsedMarkdownGroup:
    start_line: int
    end_line: int
    blocks: tuple[_MarkdownBlock, ...]
    # Value equality is not enough for a streaming cache: two equal-looking
    # top-level groups may occur at different places in the same document.  A
    # group gets a fresh occurrence identity when it is parsed and keeps that
    # identity after it is promoted into the stable prefix.
    occurrence_id: object = field(default_factory=object, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class _StreamingMarkdownPartition:
    """The append-only parse result without flattening the stable prefix."""

    stable_groups: Sequence[_ParsedMarkdownGroup]
    frontier_groups: tuple[_ParsedMarkdownGroup, ...]
    generation: object
    revision: int
    full_blocks: tuple[_MarkdownBlock, ...] | None = None

    @property
    def segmented_safe(self) -> bool:
        return self.full_blocks is None


@dataclass(frozen=True, slots=True)
class MarkdownRenderedSegment:
    """A rendered semantic-group segment from an active Markdown stream."""

    lines: tuple[str, ...]
    identity: object
    revision: object
    stable: bool
    _has_nonblank: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            hash(self.identity)
        except TypeError as exc:
            raise TypeError("Markdown segment identity must be hashable") from exc
        object.__setattr__(self, "_has_nonblank", any(line != "" for line in self.lines))

    @property
    def has_nonblank(self) -> bool:
        return self._has_nonblank


@dataclass(frozen=True, slots=True)
class MarkdownSegmentedRenderResult:
    segments: tuple[MarkdownRenderedSegment, ...]


@dataclass(slots=True)
class _StreamingMarkdownParseState:
    _source: str = ""
    _stable_end_line: int = 0
    _stable_groups: list[_ParsedMarkdownGroup] = field(default_factory=list)
    _last_blocks: tuple[_MarkdownBlock, ...] = ()
    _last_blocks_revision: int = -1
    _last_partition: _StreamingMarkdownPartition | None = None
    _generation: object = field(default_factory=object)
    _revision: int = 0
    _initialized: bool = False
    _full_parse_only: bool = False

    def parse(self, markdown: str) -> tuple[_MarkdownBlock, ...]:
        partition = self.update(markdown)
        if self._last_blocks_revision == partition.revision:
            return self._last_blocks
        if partition.full_blocks is not None:
            self._last_blocks = partition.full_blocks
        else:
            self._last_blocks = _markdown_blocks_from_groups(
                (*partition.stable_groups, *partition.frontier_groups)
            )
        self._last_blocks_revision = partition.revision
        return self._last_blocks

    def update(self, markdown: str) -> _StreamingMarkdownPartition:
        """Update the streaming partition without flattening stable groups."""

        normalized = markdown.expandtabs(3)
        if self._initialized and normalized == self._source:
            assert self._last_partition is not None
            return self._last_partition
        if self._initialized and not normalized.startswith(self._source):
            self.reset()

        self._source = normalized
        self._initialized = True
        self._revision += 1
        if self._full_parse_only:
            partition = _StreamingMarkdownPartition(
                stable_groups=self._stable_groups,
                frontier_groups=(),
                generation=self._generation,
                revision=self._revision,
                full_blocks=_parse_normalized_markdown_blocks(normalized),
            )
            self._last_partition = partition
            self._last_blocks_revision = -1
            return partition

        source_lines = normalized.split("\n")
        tail_source = "\n".join(source_lines[self._stable_end_line :])
        tail_groups, has_references = _parse_markdown_groups(
            tail_source,
            line_offset=self._stable_end_line,
        )
        if has_references:
            self._stable_end_line = 0
            self._stable_groups.clear()
            self._full_parse_only = True
            partition = _StreamingMarkdownPartition(
                stable_groups=self._stable_groups,
                frontier_groups=(),
                generation=self._generation,
                revision=self._revision,
                full_blocks=_parse_normalized_markdown_blocks(normalized),
            )
            self._last_partition = partition
            self._last_blocks_revision = -1
            return partition

        promote_count = max(0, len(tail_groups) - _STREAMING_MARKDOWN_FRONTIER_GROUPS)
        if promote_count:
            promoted = tail_groups[:promote_count]
            self._stable_groups.extend(promoted)
            self._stable_end_line = promoted[-1].end_line
        frontier_groups = tail_groups[promote_count:]
        partition = _StreamingMarkdownPartition(
            stable_groups=self._stable_groups,
            frontier_groups=frontier_groups,
            generation=self._generation,
            revision=self._revision,
        )
        self._last_partition = partition
        self._last_blocks_revision = -1
        return partition

    def reset(self) -> None:
        self._source = ""
        self._stable_end_line = 0
        self._stable_groups.clear()
        self._last_blocks = ()
        self._last_blocks_revision = -1
        self._last_partition = None
        self._generation = object()
        self._revision = 0
        self._initialized = False
        self._full_parse_only = False


@dataclass(slots=True)
class MarkdownRenderCache:
    stable_entry_limit: int = _MARKDOWN_STABLE_BLOCK_CACHE_SIZE
    _stable_blocks: dict[tuple[object, ...], tuple[str, ...]] = field(default_factory=dict, init=False, repr=False)
    _streaming_key: object | None = field(default=None, init=False, repr=False)
    _streaming_parse_state: _StreamingMarkdownParseState | None = field(default=None, init=False, repr=False)
    _streaming_render_context: tuple[object, ...] | None = field(default=None, init=False, repr=False)
    _streaming_render_generation: object | None = field(default=None, init=False, repr=False)
    _streaming_rendered_stable: list[MarkdownRenderedSegment] = field(default_factory=list, init=False, repr=False)
    _streaming_rendered_frontier: MarkdownRenderedSegment | None = field(default=None, init=False, repr=False)

    @property
    def stable_entry_count(self) -> int:
        return len(self._stable_blocks)

    @property
    def stable_line_count(self) -> int:
        return sum(len(lines) for lines in self._stable_blocks.values())

    @property
    def stable_char_count(self) -> int:
        return sum(sum(len(line) for line in lines) for lines in self._stable_blocks.values())

    def clear(self) -> None:
        self._stable_blocks.clear()
        self.clear_streaming()

    def clear_streaming(self) -> None:
        self._streaming_key = None
        self._streaming_parse_state = None
        self._clear_streaming_rendered_segments()

    def parse_streaming(self, markdown: str, *, key: object) -> tuple[_MarkdownBlock, ...]:
        self._ensure_streaming_state(key)
        assert self._streaming_parse_state is not None
        return self._streaming_parse_state.parse(markdown)

    def update_streaming(self, markdown: str, *, key: object) -> _StreamingMarkdownPartition:
        self._ensure_streaming_state(key)
        assert self._streaming_parse_state is not None
        return self._streaming_parse_state.update(markdown)

    def _ensure_streaming_state(self, key: object) -> None:
        if self._streaming_key is key and self._streaming_parse_state is not None:
            return
        self._streaming_key = key
        self._streaming_parse_state = _StreamingMarkdownParseState()
        self._clear_streaming_rendered_segments()

    def _clear_streaming_rendered_segments(self) -> None:
        self._streaming_render_context = None
        self._streaming_render_generation = None
        self._streaming_rendered_stable.clear()
        self._streaming_rendered_frontier = None

    def get_or_render(self, key: tuple[object, ...], render: Callable[[], tuple[str, ...]]) -> tuple[str, ...]:
        cached = self._stable_blocks.get(key)
        if cached is not None:
            return cached
        rendered = render()
        limit = max(0, self.stable_entry_limit)
        if limit == 0:
            return rendered
        self._stable_blocks[key] = rendered
        while len(self._stable_blocks) > limit:
            self._stable_blocks.pop(next(iter(self._stable_blocks)))
        return rendered


@dataclass(frozen=True, slots=True)
class PygmentsCodeHighlighter:
    style: str = "default"

    def highlight(
        self,
        code: str,
        language: str,
        capabilities: TerminalCapabilities | None = None,
    ) -> tuple[str, ...]:
        pygments = importlib.import_module("pygments")
        formatters = importlib.import_module("pygments.formatters")
        lexers = importlib.import_module("pygments.lexers")
        util = importlib.import_module("pygments.util")

        try:
            lexer = lexers.get_lexer_by_name(language) if language else lexers.TextLexer()
        except util.ClassNotFound:
            lexer = lexers.TextLexer()
        capabilities = capabilities or TerminalCapabilities()
        formatter_class = formatters.TerminalTrueColorFormatter if capabilities.truecolor else formatters.Terminal256Formatter
        highlighted = pygments.highlight(code, lexer, formatter_class(style=self.style))
        return tuple(highlighted.rstrip("\n").split("\n")) or ("",)


@dataclass(slots=True)
class MarkdownRenderer:
    markdown: str
    theme: ThemeResolver | None = None
    capabilities: TerminalCapabilities | None = None
    code_highlighter: CodeHighlighterLike | None = None
    padding_x: int = 0
    padding_y: int = 0
    default_style: ThemeStyle | None = None
    render_cache: MarkdownRenderCache | None = None
    streaming_key: object | None = None
    _render_cache: dict[tuple[object, ...], tuple[str, ...]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.padding_x < 0:
            raise ValueError("padding_x must be non-negative")
        if self.padding_y < 0:
            raise ValueError("padding_y must be non-negative")

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        frame_style = _resolve_style(self.theme, "markdown.background", self.capabilities)
        framed = self.padding_x > 0 or self.padding_y > 0 or _has_background_style(frame_style)
        width = _markdown_frame_content_width(target_width, self.padding_x) if framed else target_width
        if self.render_cache is not None:
            blocks = (
                self.render_cache.parse_streaming(self.markdown, key=self.streaming_key)
                if self.streaming_key is not None
                else _parse_markdown_blocks(self.markdown)
            )
            raw_lines = list(
                _render_markdown_blocks(
                    blocks,
                    width=width,
                    theme=self.theme,
                    capabilities=self.capabilities,
                    code_highlighter=self.code_highlighter,
                    default_style=self.default_style,
                    render_cache=self.render_cache,
                )
            )
        elif self.theme is None and self.code_highlighter is None and self.default_style is None:
            raw_lines = list(_render_markdown_lines(self.markdown, width, ambiguous_width()))
        else:
            cache_key = _renderer_cache_key(
                markdown=self.markdown,
                width=width,
                theme=self.theme,
                capabilities=self.capabilities,
                code_highlighter=self.code_highlighter,
                default_style=self.default_style,
            )
            cached = self._render_cache.get(cache_key)
            if cached is None:
                cached = _render_markdown_blocks(
                    _parse_markdown_blocks(self.markdown),
                    width=width,
                    theme=self.theme,
                    capabilities=self.capabilities,
                    code_highlighter=self.code_highlighter,
                    default_style=self.default_style,
                )
                self._render_cache.clear()
                self._render_cache[cache_key] = cached
            raw_lines = list(cached)
        if framed:
            raw_lines = _apply_markdown_frame(
                raw_lines,
                target_width=target_width,
                padding_x=self.padding_x,
                padding_y=self.padding_y,
                frame_style=frame_style,
            )
        return _result(raw_lines, constraints)

    def render_streaming_segments(
        self,
        constraints: RenderConstraints,
    ) -> MarkdownSegmentedRenderResult | None:
        """Render an append-only stream as stable groups plus one frontier.

        Framing is intentionally excluded because padding and a background are
        whole-result operations.  Reference definitions also require a full
        parse, so callers should use :meth:`render` when this method returns
        ``None``.
        """

        if self.render_cache is None or self.streaming_key is None:
            return None

        target_width = autowrap_safe_width(constraints.width)
        frame_style = _resolve_style(self.theme, "markdown.background", self.capabilities)
        framed = self.padding_x > 0 or self.padding_y > 0 or _has_background_style(frame_style)
        if framed:
            return None

        partition = self.render_cache.update_streaming(
            self.markdown,
            key=self.streaming_key,
        )
        if not partition.segmented_safe:
            self.render_cache._clear_streaming_rendered_segments()
            return None

        context = (
            target_width,
            ambiguous_width(),
            _theme_cache_signature(self.theme),
            _capabilities_cache_signature(self.capabilities),
            id(self.code_highlighter) if self.code_highlighter is not None else None,
            _style_cache_signature(self.default_style),
        )
        segments = _render_streaming_markdown_partition(
            partition,
            constraints=constraints,
            width=target_width,
            context=context,
            theme=self.theme,
            capabilities=self.capabilities,
            code_highlighter=self.code_highlighter,
            default_style=self.default_style,
            render_cache=self.render_cache,
        )
        return MarkdownSegmentedRenderResult(
            segments=_limit_markdown_rendered_segments(
                segments,
                max_height=constraints.max_height,
            )
        )

    def invalidate(self) -> None:
        self._render_cache.clear()


@dataclass(slots=True)
class CodeBlock:
    code: str
    language: str = ""
    highlighter: CodeHighlighterLike | None = None
    theme: ThemeResolver | None = None
    capabilities: TerminalCapabilities | None = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        lines = _render_code_block(
            tuple(self.code.split("\n")),
            language=self.language,
            width=target_width,
            theme=self.theme,
            capabilities=self.capabilities,
            code_highlighter=self.highlighter,
        )
        return _result(lines, constraints)


@dataclass(slots=True)
class DiffBlock:
    diff: str
    theme: ThemeResolver | None = None
    capabilities: TerminalCapabilities | None = None
    show_stats: bool = False

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        return _result(
            _render_diff_block(
                self.diff.split("\n"),
                width=target_width,
                theme=self.theme,
                capabilities=self.capabilities,
                show_stats=self.show_stats,
            ),
            constraints,
        )


@dataclass(slots=True)
class ImageBlock:
    alt_text: str
    source: str = ""
    data: bytes | None = None
    protocol: ImageProtocolSelection | None = "auto"
    runtime_capabilities: TerminalRuntimeCapabilities | None = None
    mime_type: str = ""
    dimensions: ImageDimensions | None = None
    max_width_cells: int | None = None
    max_height_cells: int | None = None
    cell_dimensions: CellDimensions = CellDimensions()
    image_id: int | None = None
    fallback_style: Callable[[str], str] | None = None
    preserve_aspect_ratio: bool = True
    move_cursor: bool = True

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rendered = render_terminal_image_result(
            alt_text=self.alt_text,
            source=self.source,
            data=self.data,
            mime_type=self.mime_type,
            protocol=self.protocol,
            capabilities=self.runtime_capabilities,
            dimensions=self.dimensions,
            max_width_cells=self.max_width_cells,
            max_height_cells=self.max_height_cells,
            cell_dimensions=self.cell_dimensions,
            image_id=self.image_id,
            move_cursor=self.move_cursor,
            preserve_aspect_ratio=self.preserve_aspect_ratio,
        )
        lines = rendered.lines()
        if rendered.fallback and self.fallback_style is not None:
            lines = tuple(self.fallback_style(line) for line in lines)
        return _result(
            list(lines),
            constraints,
        )


def _renderer_cache_key(
    *,
    markdown: str,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    default_style: ThemeStyle | None,
) -> tuple[object, ...]:
    return (
        markdown,
        width,
        ambiguous_width(),
        _theme_cache_signature(theme),
        _capabilities_cache_signature(capabilities),
        id(code_highlighter) if code_highlighter is not None else None,
        _style_cache_signature(default_style),
    )


def _theme_cache_signature(theme: ThemeResolver | None) -> tuple[object, ...] | None:
    if theme is None:
        return None
    return (
        id(theme),
        theme.version,
        _style_mapping_cache_signature(theme.defaults),
        _style_mapping_cache_signature(theme.overrides),
    )


def _style_mapping_cache_signature(
    mapping: dict[str, ThemeStyle],
) -> tuple[tuple[str, tuple[tuple[str, str], ...] | None], ...]:
    return tuple((key, _style_cache_signature(value)) for key, value in sorted(mapping.items()))


def _style_cache_signature(style: ThemeStyle | None) -> tuple[tuple[str, str], ...] | None:
    if style is None:
        return None
    return tuple(sorted((str(key), repr(value)) for key, value in style.items()))


def _capabilities_cache_signature(capabilities: TerminalCapabilities | None) -> tuple[bool, bool] | None:
    if capabilities is None:
        return None
    return capabilities.truecolor, capabilities.hyperlinks


@lru_cache(maxsize=_MARKDOWN_LINE_CACHE_SIZE)
def _render_markdown_lines(
    markdown: str,
    width: int,
    _ambiguous_width: int,
) -> tuple[str, ...]:
    return _render_markdown_blocks(_parse_markdown_blocks(markdown), width=width)


def _parse_markdown_blocks(markdown: str) -> tuple[_MarkdownBlock, ...]:
    normalized = markdown.expandtabs(3)
    return _parse_normalized_markdown_blocks(normalized)


def _parse_normalized_markdown_blocks(normalized: str) -> tuple[_MarkdownBlock, ...]:
    blocks, _index = _parse_markdown_it_blocks(
        _MARKDOWN_PARSER.parse(normalized),
        0,
        stop_type=None,
        source_lines=normalized.split("\n"),
    )
    return tuple(blocks)


def _parse_markdown_groups(
    markdown: str,
    *,
    line_offset: int,
) -> tuple[tuple[_ParsedMarkdownGroup, ...], bool]:
    environment: dict[str, object] = {}
    tokens = _MARKDOWN_PARSER.parse(markdown, environment)
    if environment.get("references"):
        return (), True

    source_lines = markdown.split("\n")
    group_starts = [
        index
        for index, token in enumerate(tokens)
        if token.level == 0 and token.map is not None and token.nesting >= 0
    ]
    groups: list[_ParsedMarkdownGroup] = []
    for group_index, token_index in enumerate(group_starts):
        token = tokens[token_index]
        token_map = token.map
        if token_map is None:
            continue
        next_token_index = group_starts[group_index + 1] if group_index + 1 < len(group_starts) else len(tokens)
        group_blocks, _index = _parse_markdown_it_blocks(
            tokens[token_index:next_token_index],
            0,
            stop_type=None,
            source_lines=source_lines,
        )
        local_end_line = _token_end_line(token, token_map[1], source_lines)
        groups.append(
            _ParsedMarkdownGroup(
                start_line=line_offset + token_map[0],
                end_line=line_offset + (local_end_line if local_end_line is not None else token_map[1]),
                blocks=tuple(group_blocks),
            )
        )
    return tuple(groups), False


def _markdown_blocks_from_groups(groups: Sequence[_ParsedMarkdownGroup]) -> tuple[_MarkdownBlock, ...]:
    blocks: list[_MarkdownBlock] = []
    previous_end_line: int | None = None
    for group in groups:
        if (
            group.blocks
            and previous_end_line is not None
            and group.start_line > previous_end_line
            and blocks
            and blocks[-1].kind != "blank"
        ):
            blocks.append(_MarkdownBlock("blank"))
        blocks.extend(group.blocks)
        if group.blocks:
            previous_end_line = group.end_line
    return tuple(blocks)


def _parse_markdown_it_blocks(
    tokens: list[Token],
    index: int,
    *,
    stop_type: str | None,
    source_lines: list[str],
    list_depth: int = 0,
) -> tuple[list[_MarkdownBlock], int]:
    blocks: list[_MarkdownBlock] = []
    last_end_line: int | None = None
    while index < len(tokens):
        token = tokens[index]
        if token.type == stop_type:
            return blocks, index + 1

        if token.type == "heading_open":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            inline = _next_inline_token(tokens, index)
            inline_tokens = _inline_tokens_from_markdown_it(inline.children or ()) if inline is not None else ()
            level = int(token.tag[1:]) if token.tag.startswith("h") and token.tag[1:].isdigit() else 1
            blocks.append(
                _MarkdownBlock(
                    "heading",
                    text=_inline_tokens_to_plain_text(inline_tokens, preserve_markup=True, softbreak="\n"),
                    level=level,
                    inline=inline_tokens,
                )
            )
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            index = _skip_until_after(tokens, index + 1, "heading_close")
            continue

        if token.type == "paragraph_open":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            inline = _next_inline_token(tokens, index)
            inline_tokens = _inline_tokens_from_markdown_it(inline.children or ()) if inline is not None else ()
            blocks.append(
                _MarkdownBlock(
                    "paragraph",
                    text=_inline_tokens_to_plain_text(inline_tokens, preserve_markup=True, softbreak="\n"),
                    inline=inline_tokens,
                )
            )
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            index = _skip_until_after(tokens, index + 1, "paragraph_close")
            continue

        if token.type == "fence":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            blocks.append(
                _MarkdownBlock(
                    "code",
                    lines=tuple(_split_fence_lines(token.content)),
                    meta=token.info.strip(),
                )
            )
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            index += 1
            continue

        if token.type == "hr":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            blocks.append(_MarkdownBlock("hr"))
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            index += 1
            continue

        if token.type in {"bullet_list_open", "ordered_list_open"}:
            _append_source_blank_for_gap(blocks, token, last_end_line)
            list_blocks, index = _parse_markdown_it_list(
                tokens,
                index,
                depth=list_depth,
                source_lines=source_lines,
            )
            blocks.extend(list_blocks)
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            continue

        if token.type == "blockquote_open":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            quote_blocks, index = _parse_markdown_it_blocks(
                tokens,
                index + 1,
                stop_type="blockquote_close",
                source_lines=source_lines,
                list_depth=list_depth,
            )
            blocks.append(_MarkdownBlock("quote", children=tuple(quote_blocks)))
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            continue

        if token.type == "table_open":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            table_lines, table_rows, table_alignments, index = _parse_markdown_it_table(tokens, index)
            blocks.append(
                _MarkdownBlock(
                    "table",
                    lines=tuple(table_lines),
                    table_rows=table_rows,
                    table_alignments=table_alignments,
                )
            )
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            continue

        if token.type == "html_block" and token.content.strip():
            _append_source_blank_for_gap(blocks, token, last_end_line)
            blocks.append(_MarkdownBlock("paragraph", text=token.content.strip()))
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            index += 1
            continue

        if token.type == "inline":
            _append_source_blank_for_gap(blocks, token, last_end_line)
            inline_tokens = _inline_tokens_from_markdown_it(token.children or ())
            blocks.append(
                _MarkdownBlock(
                    "paragraph",
                    text=_inline_tokens_to_plain_text(inline_tokens, preserve_markup=True, softbreak="\n"),
                    inline=inline_tokens,
                )
            )
            last_end_line = _token_end_line(token, last_end_line, source_lines)
            index += 1
            continue

        index += 1

    return blocks, index


def _append_source_blank_for_gap(blocks: list[_MarkdownBlock], token: Token, previous_end_line: int | None) -> None:
    if token.map is None or previous_end_line is None:
        return
    if token.map[0] > previous_end_line and blocks and blocks[-1].kind != "blank":
        blocks.append(_MarkdownBlock("blank"))


def _token_end_line(token: Token, fallback: int | None, source_lines: list[str]) -> int | None:
    if token.map is None:
        return fallback
    start, end = token.map
    while end > start and end - 1 < len(source_lines) and source_lines[end - 1].strip() == "":
        end -= 1
    return end


def _next_inline_token(tokens: list[Token], index: int) -> Token | None:
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.type == "inline":
            return token
        if token.nesting < 0:
            return None
        index += 1
    return None


def _skip_until_after(tokens: list[Token], index: int, token_type: str) -> int:
    while index < len(tokens):
        if tokens[index].type == token_type:
            return index + 1
        index += 1
    return index


def _split_fence_lines(content: str) -> tuple[str, ...]:
    if content == "":
        return ("",)
    return tuple(content.rstrip("\n").split("\n"))


def _parse_markdown_it_list(
    tokens: list[Token],
    index: int,
    *,
    depth: int,
    source_lines: list[str],
) -> tuple[list[_MarkdownBlock], int]:
    open_token = tokens[index]
    ordered = open_token.type == "ordered_list_open"
    close_type = "ordered_list_close" if ordered else "bullet_list_close"
    item_number = int(open_token.attrs.get("start", 1)) if ordered and open_token.attrs else 1
    blocks: list[_MarkdownBlock] = []
    index += 1

    while index < len(tokens):
        token = tokens[index]
        if token.type == close_type:
            return blocks, index + 1
        if token.type != "list_item_open":
            index += 1
            continue

        marker = f"{item_number}. " if ordered else "- "
        item_number += 1
        indent = "    " * depth
        child_blocks, index = _parse_markdown_it_blocks(
            tokens,
            index + 1,
            stop_type="list_item_close",
            source_lines=source_lines,
            list_depth=depth + 1,
        )
        body_text, body_inline = _list_item_summary(child_blocks)
        blocks.append(
            _MarkdownBlock(
                "list_item",
                text=f"{indent}{marker}{body_text}",
                meta=f"{indent}{marker}",
                inline=body_inline,
                children=tuple(child_blocks),
            )
        )

    return blocks, index


def _list_item_summary(blocks: list[_MarkdownBlock]) -> tuple[str, tuple[_InlineToken, ...]]:
    for block in blocks:
        if block.kind == "paragraph":
            return block.text, block.inline or _inline_tokens_from_plain_text(block.text)
    return "", ()


def _parse_markdown_it_table(
    tokens: list[Token],
    index: int,
) -> tuple[list[str], tuple[_TableRow, ...], tuple[_TableAlignment, ...], int]:
    rows: list[list[str]] = []
    token_rows: list[list[_TableCell]] = []
    alignments: list[_TableAlignment] = []
    current_row: list[str] | None = None
    current_token_row: list[_TableCell] | None = None
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_close":
            return _table_rows_to_markdown_lines(rows), tuple(tuple(row) for row in token_rows), tuple(alignments), index + 1
        if token.type == "tr_open":
            current_row = []
            current_token_row = []
            index += 1
            continue
        if token.type in {"th_open", "td_open"} and current_row is not None and current_token_row is not None:
            if token.type == "th_open":
                alignments.append(_table_alignment_from_token(token))
            inline = _next_inline_token(tokens, index)
            inline_tokens = _inline_tokens_from_markdown_it(inline.children or ()) if inline is not None else ()
            current_row.append(_inline_tokens_to_plain_text(inline_tokens, preserve_markup=True, softbreak=" "))
            current_token_row.append(inline_tokens)
            index = _skip_until_after(tokens, index + 1, token.type.replace("_open", "_close"))
            continue
        if token.type == "tr_close":
            rows.append(current_row or [])
            token_rows.append(current_token_row or [])
            current_row = None
            current_token_row = None
            index += 1
            continue
        index += 1
    return _table_rows_to_markdown_lines(rows), tuple(tuple(row) for row in token_rows), tuple(alignments), index


def _table_alignment_from_token(token: Token) -> _TableAlignment:
    style = str(token.attrs.get("style", "")) if token.attrs else ""
    if "text-align:center" in style:
        return "center"
    if "text-align:right" in style:
        return "right"
    if "text-align:left" in style:
        return "left"
    return "default"


def _table_rows_to_markdown_lines(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    header = rows[0]
    column_count = max(1, len(header))
    lines = [_format_markdown_table_row(header)]
    lines.append(_format_markdown_table_row(["---"] * column_count))
    lines.extend(_format_markdown_table_row(row) for row in rows[1:])
    return lines


def _format_markdown_table_row(row: list[str]) -> str:
    return "| " + " | ".join(row) + " |"


def _render_markdown_blocks(
    blocks: tuple[_MarkdownBlock, ...],
    *,
    width: int,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    code_highlighter: CodeHighlighterLike | None = None,
    default_style: ThemeStyle | None = None,
    render_cache: MarkdownRenderCache | None = None,
) -> tuple[str, ...]:
    rendered: list[str] = []
    stable_block_count = max(0, len(blocks) - 1) if render_cache is not None else 0
    block_cache_context: tuple[object, ...] = ()
    if stable_block_count:
        block_cache_context = (
            width,
            ambiguous_width(),
            _theme_cache_signature(theme),
            _capabilities_cache_signature(capabilities),
            id(code_highlighter) if code_highlighter is not None else None,
            _style_cache_signature(default_style),
        )
    for index, block in enumerate(blocks):
        if render_cache is not None and index < stable_block_count:
            block_lines = render_cache.get_or_render(
                (block, *block_cache_context),
                partial(
                    _render_markdown_block,
                    block,
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                    default_style=default_style,
                ),
            )
        else:
            block_lines = _render_markdown_block(
                block,
                width=width,
                theme=theme,
                capabilities=capabilities,
                code_highlighter=code_highlighter,
                default_style=default_style,
            )
        rendered.extend(block_lines)
        next_kind = _next_markdown_block_kind(blocks, index + 1)
        if _needs_pi_style_blank_after(block.kind, next_kind):
            rendered.append("")
    return tuple(rendered)


def _render_streaming_markdown_partition(
    partition: _StreamingMarkdownPartition,
    *,
    constraints: RenderConstraints,
    width: int,
    context: tuple[object, ...],
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    default_style: ThemeStyle | None,
    render_cache: MarkdownRenderCache,
) -> tuple[MarkdownRenderedSegment, ...]:
    if (
        render_cache._streaming_render_context != context
        or render_cache._streaming_render_generation is not partition.generation
    ):
        render_cache._streaming_render_context = context
        render_cache._streaming_render_generation = partition.generation
        render_cache._streaming_rendered_stable.clear()
        render_cache._streaming_rendered_frontier = None

    stable_groups = partition.stable_groups
    rendered_stable = render_cache._streaming_rendered_stable

    # A generation is append-only.  Therefore the already-rendered prefix is
    # trusted and only newly promoted groups are visited here.
    for index in range(len(rendered_stable), len(stable_groups)):
        group = stable_groups[index]
        previous = stable_groups[index - 1] if index else None
        lines = _render_streaming_markdown_group_run(
            (group,),
            previous_group=previous,
            constraints=constraints,
            width=width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
            default_style=default_style,
            render_cache=render_cache,
        )
        segment = MarkdownRenderedSegment(
            lines=lines,
            identity=(
                "markdown-stable-group",
                partition.generation,
                group.occurrence_id,
                context,
            ),
            revision=0,
            stable=True,
        )
        rendered_stable.append(segment)

    frontier_identity = (
        "markdown-frontier",
        partition.generation,
        context,
    )
    frontier = render_cache._streaming_rendered_frontier
    if (
        frontier is None
        or frontier.identity != frontier_identity
        or frontier.revision != partition.revision
    ):
        previous = stable_groups[-1] if stable_groups else None
        frontier = MarkdownRenderedSegment(
            lines=_render_streaming_markdown_group_run(
                partition.frontier_groups,
                previous_group=previous,
                constraints=constraints,
                width=width,
                theme=theme,
                capabilities=capabilities,
                code_highlighter=code_highlighter,
                default_style=default_style,
                render_cache=render_cache,
            ),
            identity=frontier_identity,
            revision=partition.revision,
            stable=False,
        )
        render_cache._streaming_rendered_frontier = frontier

    segments = tuple(rendered_stable)
    if frontier.lines:
        segments = (*segments, frontier)
    return segments


def _render_streaming_markdown_group_run(
    groups: Sequence[_ParsedMarkdownGroup],
    *,
    previous_group: _ParsedMarkdownGroup | None,
    constraints: RenderConstraints,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    default_style: ThemeStyle | None,
    render_cache: MarkdownRenderCache,
) -> tuple[str, ...]:
    run_blocks: list[_MarkdownBlock] = []
    previous = previous_group if previous_group is not None and previous_group.blocks else None
    for group in groups:
        if not group.blocks:
            continue
        if previous is not None:
            source_gap = group.start_line > previous.end_line
            previous_kind = previous.blocks[-1].kind
            current_kind = group.blocks[0].kind
            if source_gap or _needs_pi_style_blank_after(previous_kind, current_kind):
                run_blocks.append(_MarkdownBlock("blank"))
        run_blocks.extend(group.blocks)
        previous = group
    if not run_blocks:
        return ()

    raw_lines = _render_markdown_blocks(
        tuple(run_blocks),
        width=width,
        theme=theme,
        capabilities=capabilities,
        code_highlighter=code_highlighter,
        default_style=default_style,
        render_cache=render_cache,
    )

    # Block rendering has already wrapped to the target width.  The ordinary
    # result finalizer is still used so rstrip/image handling stays identical;
    # the document-wide height cap is applied after descriptors are joined.
    unbounded_constraints = RenderConstraints(
        width=constraints.width,
        max_height=2_147_483_647,
        visible_height=constraints.visible_height,
    )
    rendered = _result(list(raw_lines), unbounded_constraints)
    return tuple(line.text for line in rendered.lines)


def _limit_markdown_rendered_segments(
    segments: tuple[MarkdownRenderedSegment, ...],
    *,
    max_height: int,
) -> tuple[MarkdownRenderedSegment, ...]:
    remaining = max_height
    limited: list[MarkdownRenderedSegment] = []
    for segment in segments:
        if remaining <= 0:
            break
        if len(segment.lines) <= remaining:
            limited.append(segment)
            remaining -= len(segment.lines)
            continue
        limited.append(
            MarkdownRenderedSegment(
                lines=segment.lines[:remaining],
                identity=("markdown-height-slice", segment.identity, remaining),
                revision=segment.revision,
                stable=segment.stable,
            )
        )
        remaining = 0
    return tuple(limited)


def _render_markdown_block(
    block: _MarkdownBlock,
    *,
    width: int,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    code_highlighter: CodeHighlighterLike | None = None,
    default_style: ThemeStyle | None = None,
) -> tuple[str, ...]:
    if block.kind == "blank":
        return ("",)
    if block.kind == "heading":
        heading_text = (
            _render_inline_tokens(block.inline, theme=theme, capabilities=capabilities)
            if block.inline
            else _render_inline(
                block.text,
                theme=theme,
                capabilities=capabilities,
            )
        )
        heading = f"{'#' * max(1, block.level)} {heading_text}" if theme is None or block.level >= 3 else heading_text
        return tuple(_wrap(apply_theme_style(heading, _heading_style(theme, block.level, capabilities)), width=width))
    if block.kind == "paragraph":
        paragraph = (
            _render_inline_tokens(
                block.inline,
                theme=theme,
                capabilities=capabilities,
                text_token="markdown.text",
                default_style=default_style,
            )
            if block.inline
            else apply_theme_style(
                _render_inline(
                    block.text,
                    theme=theme,
                    capabilities=capabilities,
                ),
                default_style,
            )
        )
        return tuple(_wrap(paragraph, width=width))
    if block.kind == "list_item":
        return tuple(
            _render_list_item(
                block,
                width=width,
                theme=theme,
                capabilities=capabilities,
                code_highlighter=code_highlighter,
                default_style=default_style,
            )
        )
    if block.kind == "quote":
        marker = _apply_markdown_style(_QUOTE_MARKER, "markdown.quote.marker", theme, capabilities)
        return tuple(
            _render_quote(
                block,
                marker=marker,
                width=width,
                theme=theme,
                capabilities=capabilities,
                code_highlighter=code_highlighter,
            )
        )
    if block.kind == "code":
        return tuple(
            _render_code_block(
                block.lines,
                language=block.meta,
                width=width,
                theme=theme,
                capabilities=capabilities,
                code_highlighter=code_highlighter,
            )
        )
    if block.kind == "hr":
        return (_render_hr(width=width, theme=theme, capabilities=capabilities),)
    if block.kind == "table":
        return tuple(
            _render_table(
                block.lines,
                table_rows=block.table_rows,
                table_alignments=block.table_alignments,
                width=width,
                theme=theme,
                capabilities=capabilities,
                default_style=default_style,
            )
        )
    return ()


def _render_code_block(
    lines: tuple[str, ...],
    *,
    language: str,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
) -> list[str]:
    header = "```" + language
    rendered = [_fit_styled(_apply_markdown_style(header, "markdown.code.fence", theme, capabilities), width)]
    code_lines = _highlight_code(normalize_box_drawing_diagram(lines), language, code_highlighter, capabilities)
    indent = _code_block_indent(theme, capabilities)
    for line in code_lines:
        rendered.extend(_wrap(_apply_markdown_style(f"{indent}{line}", "markdown.code.text", theme, capabilities), width=width))
    rendered.append(_fit_styled(_apply_markdown_style("```", "markdown.code.fence", theme, capabilities), width))
    return rendered


def _highlight_code(
    lines: Sequence[str],
    language: str,
    highlighter: CodeHighlighterLike | None,
    capabilities: TerminalCapabilities | None = None,
) -> tuple[str, ...]:
    if highlighter is None:
        return tuple(lines)
    if _highlighter_accepts_capabilities(highlighter):
        capability_highlighter = cast(CapabilityAwareCodeHighlighter, highlighter)
        return tuple(capability_highlighter.highlight("\n".join(lines), language, capabilities))
    standard_highlighter = cast(CodeHighlighter, highlighter)
    return tuple(standard_highlighter.highlight("\n".join(lines), language))


def _highlighter_accepts_capabilities(highlighter: CodeHighlighterLike) -> bool:
    try:
        signature = inspect.signature(highlighter.highlight)
    except (TypeError, ValueError):
        return False
    parameters = list(signature.parameters.values())
    return any(parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters) or len(parameters) >= 3


def _render_diff_block(
    lines: Sequence[str],
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    show_stats: bool = False,
) -> list[str]:
    rendered: list[str] = []
    if show_stats:
        stat = _diff_stat(lines)
        if stat is not None:
            rendered.extend(_wrap(_apply_markdown_style(f"Diff {stat}", "diff.summary", theme, capabilities), width=width))
    for line in lines:
        rendered.extend(_render_diff_line(line, width=width, theme=theme, capabilities=capabilities))
    return rendered


def _render_diff_line(
    line: str,
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
) -> list[str]:
    token = _diff_line_token(line)
    if token not in {"diff.addition", "diff.deletion"} or len(line) <= 1:
        return _wrap(_apply_markdown_style(line, token, theme, capabilities), width=width)

    marker = line[0]
    body = line[1:]
    body_width = max(1, width - visible_width(marker))
    wrapped_body = _wrap(body, width=body_width)
    if not wrapped_body:
        return [_apply_markdown_style(marker, token, theme, capabilities)]

    diff_lines = [marker + wrapped_body[0]]
    diff_lines.extend(" " + continuation for continuation in wrapped_body[1:])
    return [_apply_markdown_style(diff_line, token, theme, capabilities) for diff_line in diff_lines]


def _diff_line_token(line: str) -> str:
    if line.startswith("@@"):
        return "diff.hunk"
    if line.startswith(
        (
            "diff ",
            "index ",
            "--- ",
            "+++ ",
            "similarity index ",
            "dissimilarity index ",
            "rename from ",
            "rename to ",
            "new file mode ",
            "deleted file mode ",
            "old mode ",
            "new mode ",
            "Binary files ",
        )
    ):
        return "diff.header"
    if line.startswith("+"):
        return "diff.addition"
    if line.startswith("-"):
        return "diff.deletion"
    if line.startswith("\\"):
        return "diff.meta"
    return "diff.context"


def _diff_stat(lines: Sequence[str]) -> str | None:
    added = 0
    removed = 0
    for line in lines:
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    if added == 0 and removed == 0:
        return None
    return f"+{added} -{removed}"


def _code_block_indent(theme: ThemeResolver | None, capabilities: TerminalCapabilities | None) -> str:
    style = _resolve_style(theme, "markdown.code.indent", capabilities)
    value = style.get("text") if style else None
    return value if isinstance(value, str) else "  "


def _heading_style(
    theme: ThemeResolver | None,
    level: int,
    capabilities: TerminalCapabilities | None,
) -> ThemeStyle | None:
    if theme is None:
        return None
    normalized_level = max(1, level)
    base: ThemeStyle = {"bold": True}
    if normalized_level == 1:
        base["underline"] = True
    resolved = _resolve_style(theme, f"markdown.heading.level{normalized_level}", capabilities) or {}
    return {**base, **resolved}


def _render_hr(
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
) -> str:
    line = ("─" * max(1, min(width, 80))) if theme is not None else ("-" * max(1, width))
    return _apply_markdown_style(line, "markdown.hr", theme, capabilities)


def _wrap(text: str, *, width: int) -> list[str]:
    if is_terminal_image_line(text):
        return [text]
    return [line.rstrip() for line in wrap_ansi(text, width=max(1, width))]


def _wrap_list_item(
    text: str,
    *,
    width: int,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
) -> list[str]:
    match = re.match(r"^(\s*)((?:[-*+])|\d+[.)])\s+(.*)$", text)
    if match is None:
        return _wrap(_render_inline(text, theme=theme, capabilities=capabilities), width=width)

    indent = match.group(1)
    marker = match.group(2)
    body = match.group(3)
    first_prefix = f"{indent}{marker} "
    continuation_prefix = " " * visible_width(first_prefix)
    available_first = max(1, width - visible_width(first_prefix) - 1)
    available_next = max(1, width - visible_width(continuation_prefix) - 1)
    body_lines = _wrap_words(body, first_width=available_first, next_width=available_next)
    if not body_lines:
        return [_apply_markdown_style(first_prefix.rstrip(), "markdown.list.marker", theme, capabilities)]
    styled_prefix = _apply_markdown_style(first_prefix, "markdown.list.marker", theme, capabilities)
    rendered = [styled_prefix + _render_inline(body_lines[0], theme=theme, capabilities=capabilities)]
    rendered.extend(
        continuation_prefix + _render_inline(line, theme=theme, capabilities=capabilities) for line in body_lines[1:]
    )
    return rendered


def _render_list_item(
    block: _MarkdownBlock,
    *,
    width: int,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    code_highlighter: CodeHighlighterLike | None = None,
    default_style: ThemeStyle | None = None,
) -> list[str]:
    prefix = block.meta
    if not prefix:
        match = re.match(r"^(\s*(?:[-*+])|\s*\d+[.)])\s+", block.text)
        if match is not None:
            prefix = match.group(0)
    if not prefix:
        return _wrap_list_item(block.text, width=width, theme=theme, capabilities=capabilities)
    if block.children:
        return _render_list_item_children(
            block.children,
            prefix=prefix,
            width=width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
            default_style=default_style,
        )

    body = (
        _render_inline_tokens(
            block.inline,
            theme=theme,
            capabilities=capabilities,
            softbreak=" ",
            text_token="markdown.text",
            default_style=default_style,
        )
        if block.inline
        else apply_theme_style(_render_inline(block.text[len(prefix) :], theme=theme, capabilities=capabilities), default_style)
    )
    body = _style_task_marker(body, theme, capabilities)
    return _wrap_prefixed_body(
        prefix,
        body,
        width=width,
        prefix_token="markdown.list.marker",
        theme=theme,
        capabilities=capabilities,
    )


def _render_list_item_children(
    children: tuple[_MarkdownBlock, ...],
    *,
    prefix: str,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    default_style: ThemeStyle | None = None,
) -> list[str]:
    styled_prefix = _apply_markdown_style(prefix, "markdown.list.marker", theme, capabilities)
    continuation_prefix = " " * visible_width(prefix)
    item_width = max(1, width - visible_width(prefix) - 1)
    rendered: list[str] = []
    rendered_any_line = False
    for index, child in enumerate(children):
        if child.kind == "blank":
            if rendered_any_line:
                rendered.append("")
            continue
        if child.kind == "list_item":
            rendered.extend(
                _render_list_item(
                    child,
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                    default_style=default_style,
                )
            )
            rendered_any_line = True
            continue
        child_lines = _render_list_item_child_block(
            child,
            width=item_width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
            default_style=default_style,
        )
        for line in child_lines:
            line_prefix = styled_prefix if not rendered_any_line else continuation_prefix
            rendered.append(line_prefix + line)
            rendered_any_line = True
        next_kind = _next_markdown_block_kind(children, index + 1)
        if _needs_pi_style_blank_after(child.kind, next_kind):
            rendered.append("")
    return rendered or [styled_prefix.rstrip()]


def _render_list_item_child_block(
    block: _MarkdownBlock,
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    default_style: ThemeStyle | None = None,
) -> tuple[str, ...]:
    if block.kind != "paragraph":
        return _render_markdown_blocks(
            (block,),
            width=width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
            default_style=default_style,
        )
    body = (
        _render_inline_tokens(
            block.inline,
            theme=theme,
            capabilities=capabilities,
            softbreak=" ",
            text_token="markdown.text",
            default_style=default_style,
        )
        if block.inline
        else apply_theme_style(_render_inline(block.text, theme=theme, capabilities=capabilities), default_style)
    )
    body = _style_task_marker(body, theme, capabilities)
    return tuple(_wrap(body, width=width))


def _style_task_marker(
    body: str,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
) -> str:
    if body.startswith("[x]"):
        marker = _apply_markdown_style("[x]", "markdown.task.marker.checked", theme, capabilities)
        return marker + body[3:]
    if body.startswith("[ ]"):
        marker = _apply_markdown_style("[ ]", "markdown.task.marker.unchecked", theme, capabilities)
        return marker + body[3:]
    return body


def _render_quote(
    block: _MarkdownBlock,
    *,
    marker: str,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
) -> list[str]:
    marker_width = visible_width(marker)
    quote_width = max(1, width - marker_width)
    if block.children:
        inner_lines = _render_quote_children(
            block.children,
            width=quote_width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
        )
        while inner_lines and inner_lines[-1] == "":
            inner_lines.pop()
        return [marker + _apply_markdown_style(line, "markdown.quote.text", theme, capabilities) for line in inner_lines]
    if block.meta:
        list_block = _MarkdownBlock("list_item", text=block.text, meta=block.meta, inline=block.inline)
        inner_lines = _render_list_item(
            list_block,
            width=quote_width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
        )
    else:
        body = (
            _render_inline_tokens(
                block.inline,
                theme=theme,
                capabilities=capabilities,
                softbreak="\n",
                text_token="markdown.quote.text",
            )
            if block.inline
            else _render_inline(block.text, theme=theme, capabilities=capabilities)
        )
        inner_lines = _wrap(body, width=quote_width)
    return [marker + _apply_markdown_style(line, "markdown.quote.text", theme, capabilities) for line in inner_lines]


def _render_quote_children(
    children: tuple[_MarkdownBlock, ...],
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
) -> list[str]:
    rendered: list[str] = []
    for index, child in enumerate(children):
        if child.kind == "blank":
            if rendered:
                rendered.append("")
            continue
        if child.kind == "paragraph":
            body = _render_inline_tokens(
                child.inline,
                theme=theme,
                capabilities=capabilities,
                softbreak="\n",
                text_token=None,
            ) if child.inline else _render_inline(child.text, theme=theme, capabilities=capabilities)
            rendered.extend(_wrap(body, width=width))
        elif child.kind == "heading":
            rendered.extend(
                _render_markdown_blocks(
                    (child,),
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                )
            )
        elif child.kind == "list_item":
            rendered.extend(
                _render_list_item(
                    child,
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                )
            )
        elif child.kind == "code":
            rendered.extend(
                _render_code_block(
                    child.lines,
                    language=child.meta,
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                )
            )
        elif child.kind == "table":
            rendered.extend(
                _render_table(
                    child.lines,
                    table_rows=child.table_rows,
                    table_alignments=child.table_alignments,
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                )
            )
        elif child.kind == "hr":
            rendered.append(_render_hr(width=width, theme=theme, capabilities=capabilities))
        elif child.kind == "quote":
            marker = _apply_markdown_style(_QUOTE_MARKER, "markdown.quote.marker", theme, capabilities)
            rendered.extend(
                _render_quote(
                    child,
                    marker=marker,
                    width=width,
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                )
            )
        next_kind = _next_markdown_block_kind(children, index + 1)
        if _needs_pi_style_blank_after(child.kind, next_kind):
            rendered.append("")
    return rendered


def _wrap_prefixed_body(
    prefix: str,
    body: str,
    *,
    width: int,
    prefix_token: str,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
) -> list[str]:
    first_prefix = prefix
    continuation_prefix = " " * visible_width(first_prefix)
    available_first = max(1, width - visible_width(first_prefix) - 1)
    available_next = max(1, width - visible_width(continuation_prefix) - 1)
    body_lines = _wrap_ansi_with_continuation_widths(body, first_width=available_first, next_width=available_next)
    styled_prefix = _apply_markdown_style(first_prefix, prefix_token, theme, capabilities)
    if not body_lines:
        return [styled_prefix.rstrip()]
    rendered = [styled_prefix + body_lines[0]]
    rendered.extend(continuation_prefix + line for line in body_lines[1:])
    return rendered


def _wrap_ansi_with_continuation_widths(text: str, *, first_width: int, next_width: int) -> list[str]:
    lines: list[str] = []
    for logical_line in text.split("\n"):
        width = first_width if not lines else next_width
        wrapped = _wrap(logical_line, width=width)
        if not wrapped:
            lines.append("")
            continue
        lines.append(wrapped[0])
        for continuation in wrapped[1:]:
            if visible_width(continuation) <= next_width:
                lines.append(continuation)
            else:
                lines.extend(_wrap(continuation, width=next_width))
    return lines


def _wrap_words(text: str, *, first_width: int, next_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    current_width = 0
    limit = first_width

    for word in words:
        word_width = visible_width(word)
        if current and current_width + 1 + word_width > limit:
            lines.append(current)
            current = ""
            current_width = 0
            limit = next_width
        if current:
            current += " " + word
            current_width += 1 + word_width
        elif word_width > limit:
            broken = wrap_cells(word, width=max(1, limit))
            lines.extend(part.rstrip() for part in broken[:-1])
            current = broken[-1].rstrip()
            current_width = visible_width(current)
            limit = next_width
        else:
            current = word
            current_width = word_width
    if current or not lines:
        lines.append(current)
    return lines


def _render_table(
    lines: tuple[str, ...],
    *,
    table_rows: tuple[_TableRow, ...] = (),
    table_alignments: tuple[_TableAlignment, ...] = (),
    width: int,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    default_style: ThemeStyle | None = None,
) -> list[str]:
    rows = _render_table_rows(table_rows, theme=theme, capabilities=capabilities, default_style=default_style) if table_rows else [
        _split_table_row(line) for line in lines if not _TABLE_SEPARATOR_RE.match(line)
    ]
    if not rows:
        return []
    column_count = max(len(row) for row in rows)
    padded_rows = [row + [""] * (column_count - len(row)) for row in rows]
    column_widths = _table_column_widths(padded_rows, width)
    if column_widths is not None:
        boxed = _render_box_table(
            padded_rows,
            column_widths,
            table_alignments=table_alignments,
            theme=theme,
            capabilities=capabilities,
        )
        if _box_table_lines_are_safe(boxed, width=width):
            return boxed

    raw_lines: list[str] = []
    for line in lines:
        raw_lines.extend(wrapped.strip() for wrapped in _wrap(line.strip(), width=width))
    return raw_lines


def _table_column_widths(rows: list[list[str]], width: int) -> list[int] | None:
    column_count = max(len(row) for row in rows)
    if not _box_table_glyphs_are_single_cell():
        return None
    border_overhead = 3 * column_count + 1
    available_for_cells = width - border_overhead
    if available_for_cells < column_count:
        return None

    natural_widths = [
        max(visible_width(row[column]) for row in rows)
        for column in range(column_count)
    ]
    hard_min_widths = [
        max(1, max(max_display_cluster_width(row[column]) for row in rows))
        for column in range(column_count)
    ]
    min_widths = [
        max(
            hard_min_widths[column],
            max(_longest_word_width(row[column], max_width=30) for row in rows),
        )
        for column in range(column_count)
    ]
    min_total = sum(min_widths)
    if min_total > available_for_cells:
        widths = list(min_widths)
        while sum(widths) > available_for_cells:
            shrinkable = [
                index
                for index in range(column_count)
                if widths[index] > hard_min_widths[index]
            ]
            if not shrinkable:
                return None
            widest_index = max(shrinkable, key=lambda index: widths[index])
            widths[widest_index] -= 1
        if sum(widths) > available_for_cells:
            return None
        return widths

    natural_total = sum(natural_widths)
    if natural_total <= available_for_cells:
        return natural_widths

    extra = max(0, available_for_cells - min_total)
    grow_potential = [max(0, natural - minimum) for natural, minimum in zip(natural_widths, min_widths, strict=True)]
    total_potential = sum(grow_potential)
    widths = list(min_widths)
    if total_potential > 0:
        allocated = 0
        for index, potential in enumerate(grow_potential):
            grow = min(potential, int(extra * (potential / total_potential)))
            widths[index] += grow
            allocated += grow
        remaining = extra - allocated
        while remaining > 0:
            grew = False
            for index, potential in enumerate(grow_potential):
                if remaining <= 0:
                    break
                if widths[index] < min_widths[index] + potential:
                    widths[index] += 1
                    remaining -= 1
                    grew = True
            if not grew:
                break
    return widths


def _box_table_glyphs_are_single_cell() -> bool:
    return all(visible_width(glyph) == 1 for glyph in "┌─┬┐├┼┤│└┴┘")


def _box_table_lines_are_safe(lines: list[str], *, width: int) -> bool:
    line_widths = {visible_width(line) for line in lines}
    return len(line_widths) == 1 and next(iter(line_widths), width + 1) <= width


def _render_table_rows(
    rows: tuple[_TableRow, ...],
    *,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    default_style: ThemeStyle | None = None,
) -> list[list[str]]:
    return [
        [
            _render_inline_tokens(
                cell,
                theme=theme,
                capabilities=capabilities,
                softbreak=" ",
                text_token="markdown.text",
                default_style=default_style,
            )
            for cell in row
        ]
        for row in rows
    ]


def _render_box_table(
    rows: list[list[str]],
    column_widths: list[int],
    *,
    table_alignments: tuple[_TableAlignment, ...] = (),
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
) -> list[str]:
    rendered: list[str] = []
    top_border = "┌─" + "─┬─".join("─" * width for width in column_widths) + "─┐"
    separator = "├─" + "─┼─".join("─" * width for width in column_widths) + "─┤"
    bottom_border = "└─" + "─┴─".join("─" * width for width in column_widths) + "─┘"
    rendered.append(top_border)
    for row_index, row in enumerate(rows):
        wrapped_cells = [
            _wrap(cell, width=column_widths[column_index])
            for column_index, cell in enumerate(row)
        ]
        line_count = max(len(cell_lines) for cell_lines in wrapped_cells)
        for line_index in range(line_count):
            parts: list[str] = []
            for column_index, cell_lines in enumerate(wrapped_cells):
                cell = cell_lines[line_index] if line_index < len(cell_lines) else ""
                alignment = table_alignments[column_index] if column_index < len(table_alignments) else "default"
                padded = _align_table_cell(cell, column_widths[column_index], alignment)
                if row_index == 0:
                    padded = _apply_markdown_style(padded, "markdown.table.header", theme, capabilities)
                parts.append(padded)
            rendered.append("│ " + " │ ".join(parts) + " │")
        if row_index == 0 and len(rows) > 1:
            rendered.append(separator)
        elif row_index < len(rows) - 1:
            rendered.append(separator)
    rendered.append(bottom_border)
    return rendered


def _align_table_cell(cell: str, width: int, alignment: _TableAlignment) -> str:
    padding = max(0, width - visible_width(cell))
    if alignment == "right":
        return (" " * padding) + cell
    if alignment == "center":
        left = padding // 2
        return (" " * left) + cell + (" " * (padding - left))
    return cell + (" " * padding)


def _longest_word_width(text: str, *, max_width: int) -> int:
    words = [word for word in text.split() if word]
    if not words:
        return 1
    return min(max(visible_width(word) for word in words), max_width)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _next_markdown_block_kind(blocks: tuple[_MarkdownBlock, ...], start: int) -> _MarkdownKind | None:
    return blocks[start].kind if start < len(blocks) else None


def _needs_pi_style_blank_after(current: _MarkdownKind, next_kind: _MarkdownKind | None) -> bool:
    if next_kind is None or next_kind == "blank" or current == "blank":
        return False
    if current == "paragraph":
        return next_kind != "list_item"
    return current in {"heading", "code", "quote", "hr", "table"}


def _markdown_frame_widths(target_width: int, padding_x: int) -> tuple[int, int, int]:
    left = min(padding_x, max(0, target_width - 1))
    right = min(padding_x, max(0, target_width - left - 1))
    content = max(1, target_width - left - right)
    return left, right, content


def _markdown_frame_content_width(target_width: int, padding_x: int) -> int:
    _left, _right, content = _markdown_frame_widths(target_width, padding_x)
    return content


def _apply_markdown_frame(
    lines: Sequence[str],
    *,
    target_width: int,
    padding_x: int,
    padding_y: int,
    frame_style: ThemeStyle | None,
) -> list[str]:
    left, right, content_width = _markdown_frame_widths(target_width, padding_x)
    empty_line = _fit_markdown_frame_line("", target_width=target_width, frame_style=frame_style)
    framed_lines = [empty_line for _ in range(padding_y)]
    for line in lines:
        if is_terminal_image_line(line):
            framed_lines.append(line)
            continue
        content = truncate_to_width(line, max_width=content_width, ellipsis="", pad=True)
        framed_lines.append(
            _fit_markdown_frame_line(
                (" " * left) + content + (" " * right),
                target_width=target_width,
                frame_style=frame_style,
            )
        )
    framed_lines.extend(empty_line for _ in range(padding_y))
    return framed_lines


def _fit_markdown_frame_line(text: str, *, target_width: int, frame_style: ThemeStyle | None) -> str:
    line = truncate_to_width(text, max_width=target_width, ellipsis="", pad=True)
    return apply_theme_style(line, frame_style)


def _fit_styled(text: str, width: int) -> str:
    return truncate_to_width(text, max_width=max(1, width))


def _result(lines: list[str], constraints: RenderConstraints) -> RenderResult:
    target_width = autowrap_safe_width(constraints.width)
    rendered: list[RenderLine] = []
    for line in lines:
        if is_terminal_image_line(line):
            rendered.append(RenderLine(line))
            if len(rendered) >= constraints.max_height:
                return RenderResult(lines=tuple(rendered))
            continue
        candidate = line.rstrip()
        if visible_width(candidate) <= target_width:
            rendered.append(RenderLine(candidate))
            if len(rendered) >= constraints.max_height:
                return RenderResult.from_lines(rendered, constraints=constraints)
            continue
        for wrapped in _wrap(line, width=target_width):
            rendered.append(RenderLine(_truncate_line(wrapped, target_width)))
            if len(rendered) >= constraints.max_height:
                return RenderResult.from_lines(rendered, constraints=constraints)
    return RenderResult.from_lines(rendered, constraints=constraints)


def _line_result(lines: list[str], constraints: RenderConstraints) -> RenderResult:
    target_width = autowrap_safe_width(constraints.width)
    rendered = [
        RenderLine(truncate_to_width(line, max_width=target_width))
        for line in lines[: constraints.max_height]
    ]
    return RenderResult.from_lines(rendered, constraints=constraints)


def _truncate_line(line: str, width: int) -> str:
    if visible_width(line) <= width:
        return line
    return truncate_to_width(line, max_width=width)
