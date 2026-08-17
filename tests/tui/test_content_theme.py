from __future__ import annotations

import sys
from typing import Any

import pytest

import loushang.tui.markdown.renderer as markdown_renderer_module
from loushang.tui import (
    CellDimensions,
    CodeBlock,
    CodeHighlighter,
    DiffBlock,
    Image,
    ImageBlock,
    ImageDimensions,
    MarkdownRenderer,
    PygmentsCodeHighlighter,
    RenderConstraints,
    TerminalCapabilities,
    TerminalRuntimeCapabilities,
    ThemeResolver,
    calculate_image_cell_size,
    delete_all_kitty_images,
    delete_kitty_image,
    detect_image_protocol,
    encode_iterm2_image,
    encode_kitty_image,
    get_gif_dimensions,
    get_image_dimensions,
    get_jpeg_dimensions,
    get_png_dimensions,
    get_webp_dimensions,
    hyperlink,
    is_terminal_image_line,
    render_terminal_image,
    set_ambiguous_width,
    strip_control_sequences,
    theme_capabilities_from_runtime,
    visible_width,
)


class FakeCodeHighlighter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def highlight(self, code: str, language: str) -> tuple[str, ...]:
        self.calls.append((code, language))
        return tuple(f"hl:{language}:{line}" for line in code.split("\n"))


def rendered_text(part: Any, *, width: int = 40, height: int = 20) -> tuple[str, ...]:
    result = part.render(RenderConstraints(width=width, max_height=height))
    return tuple(line.text for line in result.lines)


def test_markdown_renderer_handles_common_blocks_without_rich_or_pygments() -> None:
    for module_name in ("rich", "pygments"):
        sys.modules.pop(module_name, None)

    renderer = MarkdownRenderer("# Title\n\n- item\n\n[docs](https://example.com)\n`code`\n> quote\n---")

    assert rendered_text(renderer, width=30) == (
        "# Title",
        "",
        "- item",
        "",
        "docs (https://example.com)",
        "`code`",
        "",
        "│ quote",
        "",
        "-----------------------------",
    )
    assert "rich" not in sys.modules
    assert "pygments" not in sys.modules


def test_markdown_renderer_handles_headings_lists_fences_quotes_and_tables_as_blocks() -> None:
    renderer = MarkdownRenderer(
        "# Title\n\n"
        "Paragraph with `code` and **strong** text.\n\n"
        "- item one\n"
        "  continuation\n"
        "  - nested\n"
        "1. ordered\n"
        "- [x] done\n\n"
        "> quote\n"
        "> - quoted item\n\n"
        "```python\n"
        "print('hello')\n"
        "```\n\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| alpha | beta |\n"
    )

    assert rendered_text(renderer, width=50, height=30) == (
        "# Title",
        "",
        "Paragraph with `code` and **strong** text.",
        "",
        "- item one continuation",
        "    - nested",
        "1. ordered",
        "- [x] done",
        "",
        "│ quote",
        "│ - quoted item",
        "",
        "```python",
        "  print('hello')",
        "```",
        "",
        "┌───────┬───────┐",
        "│ Name  │ Value │",
        "├───────┼───────┤",
        "│ alpha │ beta  │",
        "└───────┴───────┘",
    )


def test_markdown_renderer_wraps_list_continuations_under_item_text() -> None:
    renderer = MarkdownRenderer("- alpha beta gamma delta")

    assert rendered_text(renderer, width=14) == (
        "- alpha beta",
        "  gamma",
        "  delta",
    )


def test_markdown_renderer_falls_back_to_raw_table_when_too_narrow() -> None:
    renderer = MarkdownRenderer("| Long | Value |\n| --- | --- |\n| alpha | beta |")

    assert rendered_text(renderer, width=8, height=6) == (
        "| Long",
        "| Value",
        "|",
        "| --- |",
        "--- |",
        "| alpha",
    )


def test_markdown_renderer_reuses_cached_lines_for_same_markdown_and_width(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    original = markdown_renderer_module._render_markdown_blocks

    def render_markdown_blocks(blocks: tuple[markdown_renderer_module._MarkdownBlock, ...], *, width: int) -> tuple[str, ...]:
        calls.append(("|".join(block.text for block in blocks), width))
        return original(blocks, width=width)

    monkeypatch.setattr(markdown_renderer_module, "_render_markdown_blocks", render_markdown_blocks)

    assert rendered_text(MarkdownRenderer("one\ntwo"), width=30) == ("one", "two")
    assert rendered_text(MarkdownRenderer("one\ntwo"), width=30) == ("one", "two")
    assert calls == [("one\ntwo", 29)]

    assert rendered_text(MarkdownRenderer("one\ntwo"), width=20) == ("one", "two")
    assert calls == [("one\ntwo", 29), ("one\ntwo", 19)]


def test_markdown_renderer_reuses_themed_instance_cache_until_theme_changes(monkeypatch) -> None:
    calls: list[int] = []
    original = markdown_renderer_module._render_markdown_blocks

    def render_markdown_blocks(
        blocks: tuple[markdown_renderer_module._MarkdownBlock, ...],
        *,
        width: int,
        **kwargs: Any,
    ) -> tuple[str, ...]:
        calls.append(width)
        return original(blocks, width=width, **kwargs)

    monkeypatch.setattr(markdown_renderer_module, "_render_markdown_blocks", render_markdown_blocks)

    theme = ThemeResolver(defaults={"markdown.strong": {"bold": True}})
    renderer = MarkdownRenderer("one **two**", theme=theme)

    assert rendered_text(renderer, width=30) == ("one \x1b[1mtwo\x1b[22m",)
    assert rendered_text(renderer, width=30) == ("one \x1b[1mtwo\x1b[22m",)
    assert calls == [29]

    theme.update_overrides({"markdown.strong": {"bold": True, "color": "cyan"}})

    assert rendered_text(renderer, width=30) == ("one \x1b[1;36mtwo\x1b[22;39m",)
    assert calls == [29, 29]


@pytest.mark.tui_render_contract
def test_markdown_renderer_keeps_themed_instance_cache_bounded_to_current_render_key() -> None:
    renderer = MarkdownRenderer("one **two**", theme=ThemeResolver(defaults={"markdown.strong": {"bold": True}}))

    assert rendered_text(renderer, width=30) == ("one \x1b[1mtwo\x1b[22m",)
    assert rendered_text(renderer, width=40) == ("one \x1b[1mtwo\x1b[22m",)
    assert rendered_text(renderer, width=50) == ("one \x1b[1mtwo\x1b[22m",)
    assert len(renderer._render_cache) == 1


@pytest.mark.tui_render_contract
def test_markdown_renderer_reuses_shared_cache_for_stable_streaming_blocks() -> None:
    cache = markdown_renderer_module.MarkdownRenderCache()
    highlighter = FakeCodeHighlighter()
    stable_code = "```python\nprint('stable')\n```"

    assert rendered_text(
        MarkdownRenderer(
            f"Intro\n\n{stable_code}\n\nTail",
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=40,
    ) == (
        "Intro",
        "",
        "```python",
        "  hl:python:print('stable')",
        "```",
        "",
        "Tail",
    )
    assert rendered_text(
        MarkdownRenderer(
            f"Intro\n\n{stable_code}\n\nTail grows",
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=40,
    ) == (
        "Intro",
        "",
        "```python",
        "  hl:python:print('stable')",
        "```",
        "",
        "Tail grows",
    )

    assert highlighter.calls == [("print('stable')", "python")]


def test_markdown_renderer_computes_shared_cache_context_once_per_render(monkeypatch) -> None:
    calls = 0
    original = markdown_renderer_module._theme_cache_signature

    def theme_cache_signature(theme: ThemeResolver | None) -> tuple[object, ...] | None:
        nonlocal calls
        calls += 1
        return original(theme)

    monkeypatch.setattr(markdown_renderer_module, "_theme_cache_signature", theme_cache_signature)
    cache = markdown_renderer_module.MarkdownRenderCache()
    theme = ThemeResolver(defaults={"markdown.strong": {"bold": True}})

    rendered_text(
        MarkdownRenderer("Intro\n\nSecond\n\nTail", theme=theme, render_cache=cache),
        width=40,
    )
    rendered_text(
        MarkdownRenderer("Intro\n\nSecond\n\nTail grows", theme=theme, render_cache=cache),
        width=40,
    )
    assert calls == 2

    rendered_text(MarkdownRenderer("Tail", theme=theme, render_cache=cache), width=40)
    assert calls == 2


def test_markdown_renderer_does_not_reuse_shared_cache_for_unstable_tail_block() -> None:
    cache = markdown_renderer_module.MarkdownRenderCache()
    highlighter = FakeCodeHighlighter()

    assert rendered_text(
        MarkdownRenderer(
            "Intro\n\n```python\nprint('one')",
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=40,
    ) == (
        "Intro",
        "",
        "```python",
        "  hl:python:print('one')",
        "```",
    )
    assert rendered_text(
        MarkdownRenderer(
            "Intro\n\n```python\nprint('one')\nprint('two')",
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=40,
    ) == (
        "Intro",
        "",
        "```python",
        "  hl:python:print('one')",
        "  hl:python:print('two')",
        "```",
    )

    assert highlighter.calls == [
        ("print('one')", "python"),
        ("print('one')\nprint('two')", "python"),
    ]


def test_markdown_renderer_shared_cache_key_includes_width_and_theme_version() -> None:
    cache = markdown_renderer_module.MarkdownRenderCache()
    highlighter = FakeCodeHighlighter()
    theme = ThemeResolver(defaults={"markdown.code.fence": {"color": "red"}})
    stable_code = "```python\nprint('stable')\n```"

    rendered_text(
        MarkdownRenderer(
            f"Intro\n\n{stable_code}\n\nTail",
            theme=theme,
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=40,
    )
    rendered_text(
        MarkdownRenderer(
            f"Intro\n\n{stable_code}\n\nTail grows",
            theme=theme,
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=24,
    )
    theme.update_overrides({"markdown.code.fence": {"color": "cyan"}})
    themed_lines = rendered_text(
        MarkdownRenderer(
            f"Intro\n\n{stable_code}\n\nTail grows again",
            theme=theme,
            code_highlighter=highlighter,
            render_cache=cache,
        ),
        width=24,
    )

    assert highlighter.calls == [
        ("print('stable')", "python"),
        ("print('stable')", "python"),
        ("print('stable')", "python"),
    ]
    assert themed_lines[2].startswith("\x1b[36m```python")


def test_markdown_renderer_does_not_rewrite_inline_syntax_inside_code_fences() -> None:
    renderer = MarkdownRenderer("```md\n[docs](https://example.com)\n```\n\n[docs](https://example.com)")

    assert rendered_text(renderer, width=40) == (
        "```md",
        "  [docs](https://example.com)",
        "```",
        "",
        "docs (https://example.com)",
    )


def test_markdown_renderer_applies_block_theme_tokens_without_width_drift() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading.level2": {"bold": True, "color": "cyan"},
            "markdown.list.marker": {"color": "yellow"},
            "markdown.quote.marker": {"color": "green"},
            "markdown.code.fence": {"color": "bright_black"},
            "markdown.code.text": {"color": 252},
            "markdown.table.header": {"bold": True},
            "markdown.hr": {"dim": True},
        }
    )
    renderer = MarkdownRenderer(
        "## Heading\n"
        "- item\n"
        "> quote\n"
        "```python\n"
        "print('hi')\n"
        "```\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| alpha | beta |\n"
        "---",
        theme=theme,
    )

    lines = rendered_text(renderer, width=30, height=20)

    assert lines == (
        "\x1b[1;36mHeading\x1b[22;39m",
        "",
        "\x1b[33m- \x1b[39mitem",
        "\x1b[32m│ \x1b[39mquote",
        "",
        "\x1b[90m```python\x1b[39m",
        "\x1b[38;5;252m  print('hi')\x1b[39m",
        "\x1b[90m```\x1b[39m",
        "",
        "┌───────┬───────┐",
        "│ \x1b[1mName \x1b[22m │ \x1b[1mValue\x1b[22m │",
        "├───────┼───────┤",
        "│ alpha │ beta  │",
        "└───────┴───────┘",
        "",
        "\x1b[2m─────────────────────────────\x1b[22m",
    )
    assert tuple(strip_control_sequences(line) for line in lines) == (
        "Heading",
        "",
        "- item",
        "│ quote",
        "",
        "```python",
        "  print('hi')",
        "```",
        "",
        "┌───────┬───────┐",
        "│ Name  │ Value │",
        "├───────┼───────┤",
        "│ alpha │ beta  │",
        "└───────┴───────┘",
        "",
        "─────────────────────────────",
    )
    assert all(visible_width(line) <= 29 for line in lines)


def test_markdown_renderer_applies_inline_theme_tokens() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.inline_code": {"color": "yellow"},
            "markdown.strong": {"bold": True},
            "markdown.emphasis": {"italic": True},
            "markdown.strikethrough": {"strikethrough": True},
            "markdown.link": {"underline": True, "color": "blue"},
        }
    )
    renderer = MarkdownRenderer(
        "Use `code`, **strong**, *em*, ~~gone~~, and [docs](https://example.com).",
        theme=theme,
    )

    lines = rendered_text(renderer, width=120, height=3)

    assert lines == (
        "Use \x1b[33mcode\x1b[39m, "
        "\x1b[1mstrong\x1b[22m, "
        "\x1b[3mem\x1b[23m, "
        "\x1b[9mgone\x1b[29m, and "
        "\x1b[4;34mdocs\x1b[24;39m (https://example.com).",
    )
    assert strip_control_sequences(lines[0]) == "Use code, strong, em, gone, and docs (https://example.com)."
    assert visible_width(lines[0]) == len(strip_control_sequences(lines[0]))


def test_markdown_renderer_wraps_ansi_inline_styles_without_losing_active_style() -> None:
    theme = ThemeResolver(defaults={"markdown.inline_code": {"color": "yellow"}})
    renderer = MarkdownRenderer("`alpha beta gamma delta`", theme=theme)

    lines = rendered_text(renderer, width=14, height=5)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "alpha beta",
        "gamma delta",
    )
    assert all(line.startswith("\x1b[33m") for line in lines)
    assert all(visible_width(line) <= 13 for line in lines)


def test_markdown_renderer_recursively_styles_nested_inline_tokens_and_restores_heading_context() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading.level2": {"bold": True, "color": "cyan"},
            "markdown.inline_code": {"color": "yellow"},
            "markdown.strong": {"bold": True},
            "markdown.emphasis": {"italic": True},
        }
    )
    renderer = MarkdownRenderer("## Nested **strong `code` *em* tail** end", theme=theme)

    line = rendered_text(renderer, width=120, height=3)[0]

    assert strip_control_sequences(line) == "Nested strong code em tail end"
    assert "\x1b[33mcode\x1b[39m" in line
    assert "\x1b[3mem\x1b[23m" in line
    assert line.endswith(" end\x1b[22;39m")


def test_markdown_renderer_applies_pi_heading_and_hr_visual_defaults_with_theme() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading": {"color": "cyan"},
            "markdown.hr": {"dim": True},
        }
    )
    renderer = MarkdownRenderer("# One\n## Two\n### Three\n---", theme=theme)

    lines = rendered_text(renderer, width=90, height=10)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "One",
        "",
        "Two",
        "",
        "### Three",
        "",
        "─" * 80,
    )
    assert lines[0] == "\x1b[1;4;36mOne\x1b[22;24;39m"
    assert lines[2] == "\x1b[1;36mTwo\x1b[22;39m"
    assert lines[4] == "\x1b[1;36m### Three\x1b[22;39m"
    assert lines[6] == "\x1b[2m" + ("─" * 80) + "\x1b[22m"


def test_markdown_renderer_preserves_named_ansi_colors_without_truecolor() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading": {"color": "yellow"},
            "markdown.link": {"color": "blue"},
        }
    )
    renderer = MarkdownRenderer(
        "### Heading\n\n[docs](https://example.com)",
        theme=theme,
        capabilities=TerminalCapabilities(truecolor=False, hyperlinks=False),
    )

    lines = rendered_text(renderer, width=90, height=10)

    assert lines[0] == "\x1b[1;33m### Heading\x1b[22;39m"
    assert "\x1b[34mdocs\x1b[39m" in lines[2]


def test_markdown_renderer_restores_default_text_style_inside_nested_inline_tokens() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.text": {"color": "white"},
            "markdown.bold": {"bold": True},
            "markdown.italic": {"italic": True},
            "markdown.code.inline": {"color": "yellow"},
        }
    )
    renderer = MarkdownRenderer("Plain **strong *em* `code` tail** done", theme=theme)

    line = rendered_text(renderer, width=120, height=3)[0]

    assert strip_control_sequences(line) == "Plain strong em code tail done"
    assert "\x1b[37mPlain " in line
    assert "\x1b[37mstrong " in line
    assert "\x1b[37mem\x1b[39m" in line
    assert "\x1b[33mcode\x1b[39m" in line
    assert line.endswith("\x1b[37m done\x1b[39m")


def test_markdown_renderer_adds_pi_like_spacing_after_structural_blocks_without_source_blank_lines() -> None:
    renderer = MarkdownRenderer("# Title\nParagraph\n```python\nprint('hi')\n```\nNext")

    assert rendered_text(renderer, width=50, height=10) == (
        "# Title",
        "",
        "Paragraph",
        "",
        "```python",
        "  print('hi')",
        "```",
        "",
        "Next",
    )


def test_markdown_renderer_uses_markdown_it_parser_for_setext_headings_and_reference_links() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading.level1": {"bold": True},
            "markdown.link": {"underline": True},
        }
    )
    renderer = MarkdownRenderer("Title\n=====\nSee [docs][d].\n\n[d]: https://example.com", theme=theme)

    assert rendered_text(renderer, width=50, height=10) == (
        "\x1b[1;4mTitle\x1b[22;24m",
        "",
        "See \x1b[4mdocs\x1b[24m (https://example.com).",
    )


def test_markdown_renderer_renders_osc8_links_when_terminal_supports_hyperlinks() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.link": {"underline": True, "color": "blue", "hyperlink": True},
            "markdown.linkUrl": {"color": "bright_black"},
        }
    )
    renderer = MarkdownRenderer(
        "[docs](https://example.com) and <https://example.com>",
        theme=theme,
        capabilities=TerminalCapabilities(hyperlinks=True),
    )

    line = rendered_text(renderer, width=120, height=3)[0]

    assert "\x1b]8;;https://example.com\x1b\\" in line
    assert strip_control_sequences(line) == "docs and https://example.com"
    assert " (https://example.com)" not in strip_control_sequences(line)


def test_markdown_renderer_linkifies_bare_urls_when_terminal_supports_hyperlinks() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.link": {"underline": True, "color": "blue", "hyperlink": True},
            "markdown.linkUrl": {"color": "bright_black"},
        }
    )
    renderer = MarkdownRenderer(
        "Visit https://example.com/docs, then mail user@example.com.",
        theme=theme,
        capabilities=TerminalCapabilities(hyperlinks=True),
    )

    line = rendered_text(renderer, width=120, height=3)[0]

    assert strip_control_sequences(line) == "Visit https://example.com/docs, then mail user@example.com."
    assert "\x1b]8;;https://example.com/docs\x1b\\" in line
    assert "\x1b]8;;mailto:user@example.com\x1b\\" in line
    assert " (https://example.com/docs)" not in strip_control_sequences(line)


def test_markdown_renderer_falls_back_to_visible_url_only_when_label_differs() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.link": {"underline": True, "color": "blue", "hyperlink": True},
            "markdown.linkUrl": {"color": "bright_black"},
        }
    )
    renderer = MarkdownRenderer(
        "[docs](https://example.com) <https://example.com> <user@example.com>",
        theme=theme,
        capabilities=TerminalCapabilities(hyperlinks=False),
    )

    line = rendered_text(renderer, width=160, height=3)[0]

    assert strip_control_sequences(line) == "docs (https://example.com) https://example.com user@example.com"
    assert "\x1b[90m (https://example.com)\x1b[39m" in line


def test_markdown_renderer_plain_link_fallback_matches_themed_url_visibility() -> None:
    renderer = MarkdownRenderer("[docs](https://example.com) <https://example.com> <user@example.com>")

    assert rendered_text(renderer, width=120, height=3) == (
        "docs (https://example.com) https://example.com user@example.com",
    )


def test_markdown_renderer_preserves_inline_styles_inside_nested_lists() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.list.marker": {"color": "yellow"},
            "markdown.strong": {"bold": True},
            "markdown.inline_code": {"color": "cyan"},
        }
    )
    renderer = MarkdownRenderer(
        "- parent **strong** text\n"
        "  - child `code` wraps around the available width\n"
        "    with continuation\n",
        theme=theme,
    )

    lines = rendered_text(renderer, width=32, height=10)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "- parent strong text",
        "    - child code wraps around",
        "      the available width with",
        "      continuation",
    )
    assert "\x1b[1mstrong\x1b[22m" in lines[0]
    assert "\x1b[36mcode\x1b[39m" in lines[1]


def test_markdown_renderer_recursively_renders_blocks_inside_list_items_like_pi() -> None:
    renderer = MarkdownRenderer(
        "- parent item\n\n"
        "  second paragraph\n\n"
        "  ```python\n"
        "  print('hi')\n"
        "  ```\n\n"
        "  > quoted child\n\n"
        "  - child `code`\n"
    )

    assert rendered_text(renderer, width=60, height=20) == (
        "- parent item",
        "",
        "  second paragraph",
        "",
        "  ```python",
        "    print('hi')",
        "  ```",
        "",
        "  │ quoted child",
        "",
        "    - child `code`",
    )


def test_markdown_renderer_wraps_code_blocks_inside_list_items_like_pi() -> None:
    renderer = MarkdownRenderer("- ```ts\n  alpha beta gamma delta epsilon zeta\n  ```")

    assert rendered_text(renderer, width=25, height=10) == (
        "- ```ts",
        "    alpha beta gamma",
        "  delta epsilon zeta",
        "  ```",
    )


def test_markdown_renderer_renders_blockquote_children_with_quote_prefix() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.quote.marker": {"color": "green"},
            "markdown.quote": {"italic": True},
            "markdown.list.marker": {"color": "yellow"},
            "markdown.inline_code": {"color": "cyan"},
        }
    )
    renderer = MarkdownRenderer(
        "> Quote with `code`\n"
        "> - first\n"
        "> - second item that wraps\n",
        theme=theme,
    )

    lines = rendered_text(renderer, width=24, height=10)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "│ Quote with code",
        "│ - first",
        "│ - second item that",
        "│   wraps",
    )
    assert all(line.startswith("\x1b[32m│ \x1b[39m") for line in lines)


def test_markdown_renderer_applies_quote_style_to_full_quote_line() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.quote.border": {"color": "green"},
            "markdown.quote.text": {"italic": True},
            "markdown.code.inline": {"color": "yellow"},
        }
    )
    renderer = MarkdownRenderer("> Quote `code` tail", theme=theme)

    line = rendered_text(renderer, width=80, height=5)[0]

    assert strip_control_sequences(line) == "│ Quote code tail"
    assert line.startswith("\x1b[32m│ \x1b[39m\x1b[3mQuote ")
    assert "\x1b[23m\x1b[33mcode" not in line
    assert "\x1b[33mcode\x1b[39m tail\x1b[23m" in line


def test_markdown_renderer_preserves_pi_spacing_inside_blockquote_children() -> None:
    renderer = MarkdownRenderer(
        "> Intro\n"
        "> ```python\n"
        "> print('hi')\n"
        "> ```\n"
        "> Next\n\n"
        "After"
    )

    assert rendered_text(renderer, width=60, height=20) == (
        "│ Intro",
        "│",
        "│ ```python",
        "│   print('hi')",
        "│ ```",
        "│",
        "│ Next",
        "",
        "After",
    )


def test_markdown_renderer_matches_pi_quote_marker_and_lazy_continuation() -> None:
    renderer = MarkdownRenderer(">Foo\nbar")

    assert rendered_text(renderer, width=60, height=10) == (
        "│ Foo",
        "│ bar",
    )


def test_markdown_renderer_wraps_each_pi_quote_visual_line_with_border() -> None:
    renderer = MarkdownRenderer("> This is a very long blockquote line that should wrap to multiple visual lines")

    lines = rendered_text(renderer, width=30, height=10)

    assert lines == (
        "│ This is a very long",
        "│ blockquote line that should",
        "│ wrap to multiple visual",
        "│ lines",
    )


def test_markdown_renderer_matches_pi_code_fence_language_header() -> None:
    renderer = MarkdownRenderer("```python\nprint('hi')\n```")

    assert rendered_text(renderer, width=80, height=10) == (
        "```python",
        "  print('hi')",
        "```",
    )


def test_markdown_renderer_normalizes_box_drawing_diagrams_in_fenced_code() -> None:
    renderer = MarkdownRenderer(
        "```\n"
        "  ┌─────────────────────────────────────────────────────────┐\n"
        "  │  loushang-coding  (产品装配层 - CLI/TUI/Workflow)        │\n"
        "  │  loushang-channel (边界通信协议层)                        │\n"
        "  └─────────────────────────────────────────────────────────┘\n"
        "```"
    )

    lines = tuple(strip_control_sequences(line) for line in rendered_text(renderer, width=80, height=20))

    diagram = tuple(line for line in lines if "┌" in line or "│" in line or "└" in line)
    assert [visible_width(line) for line in diagram] == [63, 63, 63, 63]
    assert diagram[1].endswith("│")
    assert diagram[2].endswith("│")


def test_markdown_renderer_normalizes_box_drawing_diagrams_with_side_annotations() -> None:
    renderer = MarkdownRenderer(
        "```\n"
        "  ┌─────────────────────────────────────────┐\n"
        "  │  Layer 6: 应用层 (UI Parts / Surfaces)   │  Composer, TranscriptView, BottomFrame,\n"
        "  │                                         │  SelectionSurface, ApprovalSurface, ...\n"
        "  ├─────────────────────────────────────────┤\n"
        "  │  Layer 5: 组件框架 (Framework)           │  Renderable, Container, Surface, SurfaceHost,\n"
        "  │                                         │  ScreenRoot, Focusable\n"
        "  └─────────────────────────────────────────┘\n"
        "```"
    )

    lines = tuple(strip_control_sequences(line) for line in rendered_text(renderer, width=120, height=20))
    diagram = tuple(line for line in lines if "┌" in line or "│" in line or "├" in line or "└" in line)
    frames = tuple(line[: line.rindex("│") + 1] if "│" in line else line for line in diagram)

    assert [visible_width(frame) for frame in frames] == [47, 47, 47, 47, 47, 47, 47]
    assert "Layer 6: 应用层 (UI Parts / Surfaces)  │  Composer" in diagram[1]
    assert "Layer 5: 组件框架 (Framework)          │  Renderable" in diagram[4]


def test_markdown_renderer_preserves_box_drawing_internal_columns() -> None:
    renderer = MarkdownRenderer(
        "```\n"
        "  ┌─────────────────────────────────────────────────────────────┐\n"
        "  │      │              │               │             │           │\n"
        "  │   │建议 │  →   │需理由│   →   │需证据│  →  │需审批│ →  │必须 │\n"
        "  └─────────────────────────────────────────────────────────────┘\n"
        "```"
    )

    lines = tuple(strip_control_sequences(line) for line in rendered_text(renderer, width=120, height=20))

    assert any(line.startswith("    │      │              │") for line in lines)
    assert any(line.startswith("    │   │建议 │") for line in lines)
    assert not any("│                                                             │" in line for line in lines)


def test_markdown_result_skips_second_wrap_for_fitting_lines(monkeypatch) -> None:
    import loushang.tui.markdown.renderer as renderer

    def fail_wrap(_text: str, *, width: int) -> list[str]:
        raise AssertionError(f"fitting lines should not be rewrapped at width {width}")

    monkeypatch.setattr(renderer, "_wrap", fail_wrap)

    result = renderer._result(["plain", "中文"], RenderConstraints(width=10, max_height=10))

    assert [line.text for line in result.lines] == ["plain", "中文"]


def test_markdown_renderer_renders_pi_style_table_box_and_wraps_cells() -> None:
    theme = ThemeResolver(defaults={"markdown.table.header": {"bold": True}})
    renderer = MarkdownRenderer(
        "| Name | Detail |\n"
        "| --- | --- |\n"
        "| alpha | beta gamma delta epsilon |\n",
        theme=theme,
    )

    lines = rendered_text(renderer, width=32, height=20)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "┌───────┬─────────────────────┐",
        "│ Name  │ Detail              │",
        "├───────┼─────────────────────┤",
        "│ alpha │ beta gamma delta    │",
        "│       │ epsilon             │",
        "└───────┴─────────────────────┘",
    )
    assert all(visible_width(line) <= 31 for line in lines)


def test_markdown_renderer_applies_pi_table_alignment_markers() -> None:
    renderer = MarkdownRenderer(
        "| Left | Center | Right |\n"
        "| :--- | :---: | ---: |\n"
        "| A | B | C |\n"
    )

    lines = rendered_text(renderer, width=80, height=20)

    assert lines == (
        "┌──────┬────────┬───────┐",
        "│ Left │ Center │ Right │",
        "├──────┼────────┼───────┤",
        "│ A    │   B    │     C │",
        "└──────┴────────┴───────┘",
    )


def test_markdown_renderer_aligns_complex_unicode_cells_with_terminal_width() -> None:
    renderer = MarkdownRenderer(
        "| Key | Value |\n"
        "| --- | --- |\n"
        "| 1️⃣ | 中 |\n"
        "| ☕︎ | A |\n"
    )

    lines = rendered_text(renderer, width=30, height=20)

    assert lines == (
        "┌─────┬───────┐",
        "│ Key │ Value │",
        "├─────┼───────┤",
        "│ 1️⃣  │ 中    │",
        "├─────┼───────┤",
        "│ ☕︎  │ A     │",
        "└─────┴───────┘",
    )
    assert {visible_width(line) for line in lines} == {15}


def test_markdown_renderer_falls_back_when_wide_cells_cannot_fit_box_columns() -> None:
    markdown = (
        "| K | V |\n"
        "| --- | --- |\n"
        "| 中 | A |\n"
        "| 文 | B |\n"
    )

    narrow = tuple(
        strip_control_sequences(line)
        for line in rendered_text(MarkdownRenderer(markdown), width=10)
    )
    roomy = rendered_text(MarkdownRenderer(markdown), width=11)
    combining = rendered_text(
        MarkdownRenderer("| K | V |\n| --- | --- |\n| é | A |\n"),
        width=10,
    )

    assert not any(set(line) & set("┌─┬┐├┼┤│└┴┘") for line in narrow)
    assert all(visible_width(line) <= 9 for line in narrow)
    joined = "\n".join(narrow)
    assert all(joined.count(value) == 1 for value in ("中", "文", "A", "B"))
    assert {visible_width(line) for line in roomy} == {10}
    assert roomy[3] == "│ 中 │ A │"
    assert {visible_width(line) for line in combining} == {9}
    assert combining[3] == "│ é │ A │"


def test_markdown_renderer_falls_back_when_box_glyphs_are_ambiguous_wide() -> None:
    markdown = "| Ambiguous policy | Value |\n| --- | --- |\n| row | Ω |\n"
    try:
        set_ambiguous_width(1)
        renderer = MarkdownRenderer(markdown)
        narrow_policy_lines = rendered_text(renderer, width=40)
        assert any(set(line) & set("┌─┬┐├┼┤│└┴┘") for line in narrow_policy_lines)

        set_ambiguous_width(2)

        lines = rendered_text(renderer, width=40)

        assert not any(
            set(strip_control_sequences(line)) & set("┌─┬┐├┼┤│└┴┘")
            for line in lines
        )
        assert all(visible_width(line) <= 39 for line in lines)
        assert "Ω" in "\n".join(lines)
    finally:
        set_ambiguous_width(1)


def test_markdown_renderer_cached_paths_follow_ambiguous_width_policy() -> None:
    markdown = "| Cached | Value |\n| --- | --- |\n| row | Ω |\n"
    shared_cache = markdown_renderer_module.MarkdownRenderCache()
    renderers = (
        MarkdownRenderer(
            markdown + "\nThemed tail",
            theme=ThemeResolver(defaults={"markdown.table.header": {"bold": True}}),
        ),
        MarkdownRenderer(
            markdown + "\nShared tail",
            render_cache=shared_cache,
        ),
    )
    try:
        set_ambiguous_width(1)
        prewarmed = [rendered_text(renderer, width=40) for renderer in renderers]
        assert all(
            any("┌" in strip_control_sequences(line) for line in lines)
            for lines in prewarmed
        )

        set_ambiguous_width(2)
        rerendered = [rendered_text(renderer, width=40) for renderer in renderers]

        assert all(
            not any(
                set(strip_control_sequences(line)) & set("┌─┬┐├┼┤│└┴┘")
                for line in lines
            )
            for lines in rerendered
        )
    finally:
        set_ambiguous_width(1)


def test_markdown_renderer_rejects_unsafe_box_render_result(monkeypatch) -> None:
    unsafe_results = (
        ["┌─┐", "│ too wide │"],
        ["x" * 40, "y" * 40],
    )
    for index, unsafe in enumerate(unsafe_results):
        monkeypatch.setattr(
            markdown_renderer_module,
            "_render_box_table",
            lambda *_args, unsafe=unsafe, **_kwargs: unsafe,
        )
        marker = f"Guard{index}"
        renderer = MarkdownRenderer(
            f"| {marker} | Value |\n| --- | --- |\n| row | safe |\n"
        )

        lines = tuple(
            strip_control_sequences(line)
            for line in rendered_text(renderer, width=40)
        )

        assert not any(set(line) & set("┌─┬┐├┼┤│└┴┘") for line in lines)
        assert marker in "\n".join(lines)


def test_markdown_renderer_table_stress_cases_preserve_width_and_row_dividers() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.inline_code": {"color": "yellow"},
            "markdown.table.header": {"bold": True},
        }
    )
    renderer = MarkdownRenderer(
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| alpha | `averyveryveryverylongidentifier` |\n"
        "| beta | https://example.com/this/is/a/very/long/url/that/should/wrap |\n",
        theme=theme,
    )

    lines = rendered_text(renderer, width=32, height=30)
    plain = tuple(strip_control_sequences(line).rstrip() for line in lines)

    assert plain.count("├───────┼─────────────────────┤") == 2
    assert all(visible_width(line) <= 31 for line in lines)
    extracted = "".join(character for line in plain for character in line if character not in "┌┬┐├┼┤└┴┘│─ ")
    assert "averyveryveryverylongidentifier" in extracted
    assert "https://example.com/this/is/a/very/long/url/that/should/wrap" in extracted
    assert "\x1b[33m" in "\n".join(lines)


def test_markdown_renderer_applies_pi_style_default_thinking_context_without_leaking_to_quotes() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.inline_code": {"color": "yellow"},
            "markdown.strong": {"bold": True},
            "markdown.quote.text": {"italic": True},
        }
    )
    renderer = MarkdownRenderer(
        "Thinking with `inline code` and **bold text** after.\n\n"
        "> quoted text should use quote style",
        theme=theme,
        default_style={"color": "bright_black", "italic": True},
    )

    lines = rendered_text(renderer, width=120, height=10)

    assert strip_control_sequences(lines[0]) == "Thinking with inline code and bold text after."
    assert lines[0].startswith("\x1b[3;90mThinking with ")
    assert "\x1b[33minline code\x1b[39m" in lines[0]
    assert "\x1b[3;90m and " in lines[0]
    assert "\x1b[1m\x1b[3;90mbold text\x1b[23;39m\x1b[22m" in lines[0]
    assert lines[0].endswith("\x1b[3;90m after.\x1b[23;39m")
    assert strip_control_sequences(lines[2]) == "│ quoted text should use quote style"
    assert "\x1b[90mquoted text" not in lines[2]


def test_terminal_image_line_detection_matches_pi_protocol_prefixes() -> None:
    assert is_terminal_image_line("\x1b]1337;File=size=100,100;inline=1:data\x07")
    assert is_terminal_image_line("Some text \x1b]1337;File=inline=1:data\x07 more")
    assert is_terminal_image_line("\x1b_Ga=T,f=100,t=f,d=base64\x1b\\\x1b_Gm=i=1;\x1b\\")
    assert is_terminal_image_line("\x1b[31mError \x1b_Ga=T,f=100:data\x1b\\")
    assert not is_terminal_image_line("\x1b[31mRed text\x1b[0m")
    assert not is_terminal_image_line("/path/to/File_1337_backup/image.jpg")


def test_markdown_renderer_passes_terminal_image_lines_through_without_wrap_or_padding() -> None:
    image_line = "Read image file [image/jpeg]\x1b]1337;File=size=800,600;inline=1:" + ("A" * 160) + "\x07"
    theme = ThemeResolver(defaults={"markdown.background": {"bg": "blue"}})
    renderer = MarkdownRenderer(image_line, theme=theme, padding_x=2, padding_y=1)

    lines = rendered_text(renderer, width=30, height=5)

    assert lines == (
        "\x1b[44m" + (" " * 29) + "\x1b[49m",
        image_line,
        "\x1b[44m" + (" " * 29) + "\x1b[49m",
    )


def test_markdown_renderer_renders_html_like_model_artifacts_as_visible_text() -> None:
    renderer = MarkdownRenderer(
        "Before <thinking>hidden content</thinking> after\n\n"
        "<custom>\n"
        "block content\n"
        "</custom>\n\n"
        "```html\n"
        "<div>code content</div>\n"
        "```"
    )

    lines = rendered_text(renderer, width=120, height=20)
    joined = "\n".join(lines)

    assert "<thinking>hidden content</thinking>" in joined
    assert "<custom>" in joined
    assert "block content" in joined
    assert "</custom>" in joined
    assert "<div>code content</div>" in joined


def test_markdown_renderer_terminates_heading_style_before_following_terminal_text() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading.level1": {"color": "cyan"},
            "markdown.inline_code": {"color": "yellow"},
        }
    )
    rendered = MarkdownRenderer("# Important distinction from `open()`", theme=theme).render(
        RenderConstraints(width=80, max_height=3)
    )

    heading = rendered.lines[0].text

    assert strip_control_sequences(heading) == "Important distinction from open()"
    assert heading.endswith("\x1b[22;24;39m")
    assert "\x1b[4m" not in heading[heading.rfind("open()") :]


def test_markdown_renderer_supports_pi_style_theme_contract_aliases_and_default_text() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.text": {"color": "white"},
            "markdown.heading.3": {"bold": True, "color": "cyan"},
            "markdown.list.bullet": {"color": "yellow"},
            "markdown.quote.border": {"color": "green"},
            "markdown.quote.text": {"italic": True},
            "markdown.code.inline": {"color": "bright_yellow"},
            "markdown.code.block.border": {"color": "bright_black"},
            "markdown.code.block": {"color": 252},
            "markdown.link": {"underline": True, "color": "blue"},
            "markdown.link.url": {"color": "bright_black"},
            "markdown.bold": {"bold": True},
            "markdown.italic": {"italic": True},
        }
    )
    renderer = MarkdownRenderer(
        "### Heading\n"
        "Plain **strong** and *em* with `code` plus [docs](https://example.com).\n"
        "- item\n"
        "> quote\n"
        "```python\n"
        "print('hi')\n"
        "```",
        theme=theme,
        capabilities=TerminalCapabilities(hyperlinks=False),
    )

    lines = rendered_text(renderer, width=90, height=20)

    assert lines[0] == "\x1b[1;36m### Heading\x1b[22;39m"
    assert "\x1b[37mPlain " in lines[2]
    assert "\x1b[1m\x1b[37mstrong\x1b[39m\x1b[22m" in lines[2]
    assert "\x1b[3m\x1b[37mem\x1b[39m\x1b[23m" in lines[2]
    assert "\x1b[93mcode\x1b[39m" in lines[2]
    assert "\x1b[90m (https://example.com)\x1b[39m" in lines[2]
    assert lines[3].startswith("\x1b[33m- \x1b[39m")
    assert lines[4].startswith("\x1b[32m│ \x1b[39m")
    assert "\x1b[3mquote\x1b[23m" in lines[4]
    assert "\x1b[90m```python\x1b[39m" in lines
    assert "\x1b[38;5;252m  print('hi')\x1b[39m" in lines


def test_markdown_renderer_applies_padding_and_background_to_full_width() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.background": {"bg": "blue"},
            "markdown.inline_code": {"color": "yellow"},
        }
    )
    renderer = MarkdownRenderer("Hello `code`", theme=theme, padding_x=2, padding_y=1)

    lines = rendered_text(renderer, width=20, height=5)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        " " * 19,
        "  Hello code       ",
        " " * 19,
    )
    assert all(visible_width(line) == 19 for line in lines)
    assert all(line.startswith("\x1b[44m") for line in lines)
    assert "\x1b[33mcode\x1b[39m" in lines[1]


def test_markdown_renderer_uses_code_highlighter_adapter_for_fenced_code() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.code.block.border": {"color": "bright_black"},
            "markdown.code.block": {"color": 252},
        }
    )
    highlighter = FakeCodeHighlighter()
    renderer = MarkdownRenderer("```python\nprint('hi')\n```", theme=theme, code_highlighter=highlighter)

    lines = rendered_text(renderer, width=80, height=10)

    assert highlighter.calls == [("print('hi')", "python")]
    assert lines == (
        "\x1b[90m```python\x1b[39m",
        "\x1b[38;5;252m  hl:python:print('hi')\x1b[39m",
        "\x1b[90m```\x1b[39m",
    )


def test_code_block_uses_highlighter_adapter_without_owning_optional_imports() -> None:
    highlighter = FakeCodeHighlighter()
    block = CodeBlock("print('hello')", language="python", highlighter=highlighter)

    assert rendered_text(block, width=80) == (
        "```python",
        "  hl:python:print('hello')",
        "```",
    )
    assert highlighter.calls == [("print('hello')", "python")]


def test_code_block_uses_pi_style_code_theme_indent_and_wrapping() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.code.block.border": {"color": "bright_black"},
            "markdown.code.block": {"color": "green"},
            "markdown.code.indent": {"text": "    "},
        }
    )
    highlighter = FakeCodeHighlighter()
    block = CodeBlock(
        "alpha beta gamma delta epsilon",
        language="python",
        highlighter=highlighter,
        theme=theme,
    )

    lines = rendered_text(block, width=24, height=10)

    assert highlighter.calls == [("alpha beta gamma delta epsilon", "python")]
    assert tuple(strip_control_sequences(line) for line in lines) == (
        "```python",
        "    hl:python:alpha",
        "beta gamma delta",
        "epsilon",
        "```",
    )
    assert lines[0] == "\x1b[90m```python\x1b[39m"
    assert lines[-1] == "\x1b[90m```\x1b[39m"
    assert all("\x1b[32m" in line for line in lines[1:-1])


def test_pygments_highlighter_is_lazy_at_loushang_tui_import_boundary() -> None:
    sys.modules.pop("pygments", None)
    sys.modules.pop("pygments.lexers", None)
    sys.modules.pop("pygments.formatters", None)

    highlighter: CodeHighlighter = PygmentsCodeHighlighter()

    assert highlighter is not None
    assert "pygments" not in sys.modules


def test_markdown_renderer_preserves_inline_styles_inside_table_cells() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.table.header": {"bold": True},
            "markdown.bold": {"bold": True},
            "markdown.code.inline": {"color": "yellow"},
            "markdown.link": {"underline": True, "color": "blue", "hyperlink": True},
        }
    )
    renderer = MarkdownRenderer(
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| **bold** | `code` [docs](https://example.com) |\n",
        theme=theme,
        capabilities=TerminalCapabilities(hyperlinks=True),
    )

    lines = rendered_text(renderer, width=80, height=20)
    plain = tuple(strip_control_sequences(line) for line in lines)

    assert "│ bold │ code docs │" in plain
    row = next(line for line in lines if "docs" in strip_control_sequences(line))
    assert "\x1b[1mbold\x1b[22m" in row
    assert "\x1b[33mcode\x1b[39m" in row
    assert "\x1b]8;;https://example.com\x1b\\" in row


def test_markdown_renderer_recursively_renders_blockquote_code_and_table() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.quote.border": {"color": "green"},
            "markdown.quote.text": {"italic": True},
            "markdown.code.block.border": {"color": "bright_black"},
            "markdown.code.block": {"color": 252},
            "markdown.table.header": {"bold": True},
        }
    )
    renderer = MarkdownRenderer(
        "> ```python\n"
        "> print('hi')\n"
        "> ```\n"
        "> | A | B |\n"
        "> | --- | --- |\n"
        "> | one | two |\n",
        theme=theme,
    )

    lines = rendered_text(renderer, width=50, height=20)
    plain = tuple(strip_control_sequences(line) for line in lines)

    assert plain == (
        "│ ```python",
        "│   print('hi')",
        "│ ```",
        "│ ",
        "│ ┌─────┬─────┐",
        "│ │ A   │ B   │",
        "│ ├─────┼─────┤",
        "│ │ one │ two │",
        "│ └─────┴─────┘",
    )
    assert all(line.startswith("\x1b[32m│ \x1b[39m") for line in lines)
    assert "\x1b[90m```python\x1b[39m" in lines[0]


def test_markdown_renderer_applies_strict_strikethrough_and_task_marker_styles() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.strikethrough": {"strikethrough": True},
            "markdown.list.bullet": {"color": "yellow"},
            "markdown.task.marker.checked": {"color": "green"},
            "markdown.task.marker.unchecked": {"color": "bright_black"},
        }
    )
    renderer = MarkdownRenderer("- [x] ~~done~~\n- [ ] ~~ not strict ~~", theme=theme)

    lines = rendered_text(renderer, width=80, height=10)

    assert strip_control_sequences(lines[0]) == "- [x] done"
    assert strip_control_sequences(lines[1]) == "- [ ] ~~ not strict ~~"
    assert "\x1b[32m[x]\x1b[39m" in lines[0]
    assert "\x1b[90m[ ]\x1b[39m" in lines[1]
    assert "\x1b[9mdone\x1b[29m" in lines[0]
    assert "\x1b[9m not strict \x1b[29m" not in lines[1]


def test_code_block_renders_language_label_and_truncates_lines() -> None:
    block = CodeBlock("print('hello world')", language="python")

    assert rendered_text(block, width=16) == (
        "```python",
        "  print('hello",
        "world')",
        "```",
    )


def test_diff_block_preserves_line_identity_for_add_delete_context() -> None:
    diff = DiffBlock("@@ file\n-old\n+new\n same")

    assert rendered_text(diff, width=20) == (
        "@@ file",
        "-old",
        "+new",
        " same",
    )


def test_diff_block_applies_pi_style_line_classification_theme() -> None:
    theme = ThemeResolver(
        defaults={
            "diff.header": {"color": "bright_black"},
            "diff.hunk": {"color": "cyan"},
            "diff.addition": {"color": "green"},
            "diff.deletion": {"color": "red"},
            "diff.context": {"color": 252},
        }
    )
    diff = DiffBlock(
        "diff --git a/app.py b/app.py\n"
        "index 000..111\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old value\n"
        "+new value\n"
        " context line",
        theme=theme,
    )

    lines = rendered_text(diff, width=80, height=20)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "diff --git a/app.py b/app.py",
        "index 000..111",
        "--- a/app.py",
        "+++ b/app.py",
        "@@ -1,2 +1,2 @@",
        "-old value",
        "+new value",
        " context line",
    )
    assert lines[0].startswith("\x1b[90mdiff --git")
    assert lines[2].startswith("\x1b[90m--- a/app.py")
    assert lines[3].startswith("\x1b[90m+++ b/app.py")
    assert lines[4].startswith("\x1b[36m@@ -1,2 +1,2 @@")
    assert lines[5].startswith("\x1b[31m-old value")
    assert lines[6].startswith("\x1b[32m+new value")
    assert lines[7].startswith("\x1b[38;5;252m context line")


def test_diff_block_styles_rename_binary_no_newline_and_stat_summary() -> None:
    theme = ThemeResolver(
        defaults={
            "diff.summary": {"bold": True, "color": "magenta"},
            "diff.header": {"color": "bright_black"},
            "diff.meta": {"color": "yellow"},
            "diff.addition": {"color": "green"},
            "diff.deletion": {"color": "red"},
        }
    )
    diff = DiffBlock(
        "diff --git a/old.py b/new.py\n"
        "similarity index 87%\n"
        "rename from old.py\n"
        "rename to new.py\n"
        "Binary files a/logo.png and b/logo.png differ\n"
        "-old\n"
        "+new\n"
        "\\ No newline at end of file",
        theme=theme,
        show_stats=True,
    )

    lines = rendered_text(diff, width=100, height=20)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "Diff +1 -1",
        "diff --git a/old.py b/new.py",
        "similarity index 87%",
        "rename from old.py",
        "rename to new.py",
        "Binary files a/logo.png and b/logo.png differ",
        "-old",
        "+new",
        "\\ No newline at end of file",
    )
    assert lines[0].startswith("\x1b[1;35mDiff +1 -1")
    assert lines[2].startswith("\x1b[90msimilarity index 87%")
    assert lines[3].startswith("\x1b[90mrename from old.py")
    assert lines[4].startswith("\x1b[90mrename to new.py")
    assert lines[5].startswith("\x1b[90mBinary files")
    assert lines[6].startswith("\x1b[31m-old")
    assert lines[7].startswith("\x1b[32m+new")
    assert lines[8].startswith("\x1b[33m\\ No newline")


def test_diff_block_wraps_long_lines_without_losing_diff_identity() -> None:
    diff = DiffBlock("+alpha beta gamma delta epsilon")

    assert rendered_text(diff, width=14, height=10) == (
        "+alpha beta",
        " gamma delta",
        " epsilon",
    )


def test_code_block_highlighter_can_receive_terminal_capabilities() -> None:
    class CapabilityHighlighter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool]] = []

        def highlight(self, code: str, language: str, capabilities: TerminalCapabilities | None) -> tuple[str, ...]:
            assert capabilities is not None
            self.calls.append((code, language, capabilities.truecolor))
            return (f"truecolor={capabilities.truecolor}",)

    theme = ThemeResolver(defaults={"markdown.code.block": {"color": "#00ff00"}})
    highlighter = CapabilityHighlighter()
    block = CodeBlock(
        "print('hello')",
        language="python",
        highlighter=highlighter,
        theme=theme,
        capabilities=TerminalCapabilities(truecolor=False),
    )

    lines = rendered_text(block, width=80, height=10)

    assert highlighter.calls == [("print('hello')", "python", False)]
    assert "\x1b[38;5;46m  truecolor=False\x1b[39m" in lines


def test_pygments_highlighter_switches_formatter_by_terminal_capabilities() -> None:
    highlighter = PygmentsCodeHighlighter(style="monokai")

    truecolor = "\n".join(
        highlighter.highlight("print('hello')", "python", TerminalCapabilities(truecolor=True))
    )
    ansi256 = "\n".join(
        highlighter.highlight("print('hello')", "python", TerminalCapabilities(truecolor=False))
    )

    assert "\x1b[38;2;" in truecolor
    assert "\x1b[38;5;" in ansi256
    assert "\x1b[38;2;" not in ansi256


def test_diff_block_wraps_add_delete_continuations_under_diff_marker() -> None:
    theme = ThemeResolver(
        defaults={
            "diff.addition": {"color": "green"},
            "diff.deletion": {"color": "red"},
        }
    )
    diff = DiffBlock("+alpha beta gamma delta\n-old beta gamma delta", theme=theme)

    lines = rendered_text(diff, width=14, height=10)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "+alpha beta",
        " gamma delta",
        "-old beta",
        " gamma delta",
    )
    assert all(line.startswith("\x1b[32m") for line in lines[:2])
    assert all(line.startswith("\x1b[31m") for line in lines[2:])


def test_image_block_has_text_fallback_without_terminal_image_protocol() -> None:
    image = ImageBlock(alt_text="screenshot", source="file://shot.png")

    assert rendered_text(image, width=40) == ("[image: screenshot] file://shot.png",)


def test_render_terminal_image_falls_back_without_data_or_protocol() -> None:
    line = render_terminal_image(alt_text="screenshot", source="file://shot.png")

    assert line == "[image: screenshot] file://shot.png"
    assert not is_terminal_image_line(line)


def test_terminal_image_dimension_parsers_support_common_formats() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (320).to_bytes(4, "big") + (180).to_bytes(4, "big")
    jpeg = (
        b"\xff\xd8"
        b"\xff\xe0\x00\x04xx"
        b"\xff\xc0\x00\x11\x08"
        + (240).to_bytes(2, "big")
        + (320).to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    gif = b"GIF89a" + (64).to_bytes(2, "little") + (32).to_bytes(2, "little")
    webp = (
        b"RIFF"
        + (22).to_bytes(4, "little")
        + b"WEBP"
        + b"VP8X"
        + b"\x0a\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + (99).to_bytes(3, "little")
        + (49).to_bytes(3, "little")
    )

    assert get_png_dimensions(png) == ImageDimensions(width_px=320, height_px=180)
    assert get_jpeg_dimensions(jpeg) == ImageDimensions(width_px=320, height_px=240)
    assert get_gif_dimensions(gif) == ImageDimensions(width_px=64, height_px=32)
    assert get_webp_dimensions(webp) == ImageDimensions(width_px=100, height_px=50)
    assert get_image_dimensions(png, "image/png") == ImageDimensions(width_px=320, height_px=180)
    assert get_image_dimensions(b"not an image", "image/png") is None


def test_terminal_image_calculates_cell_size_with_aspect_ratio() -> None:
    size = calculate_image_cell_size(
        ImageDimensions(width_px=1600, height_px=900),
        max_width_cells=80,
        max_height_cells=20,
        cell_dimensions=CellDimensions(width_px=10, height_px=20),
    )

    assert size.columns == 72
    assert size.rows == 20


def test_detect_image_protocol_from_terminal_environment() -> None:
    assert detect_image_protocol({"TERM": "xterm-kitty"}) == "kitty"
    assert detect_image_protocol({"TERM_PROGRAM": "iTerm.app"}) == "iterm2"
    assert detect_image_protocol({"TERM_PROGRAM": "WezTerm"}) == "kitty"
    assert detect_image_protocol({"WEZTERM_PANE": "12"}) == "kitty"
    assert detect_image_protocol({"GHOSTTY_RESOURCES_DIR": "/app/ghostty"}) == "kitty"
    assert detect_image_protocol({"TERM": "xterm-kitty", "TMUX": "/tmp/tmux.sock"}) is None
    assert detect_image_protocol({"WEZTERM_PANE": "12", "TMUX": "/tmp/tmux.sock"}) is None
    assert detect_image_protocol({"TERM_PROGRAM": "Apple_Terminal"}) is None


def _set_kitty_test_environment(monkeypatch: Any) -> None:
    for name in (
        "TERM_PROGRAM",
        "ITERM_SESSION_ID",
        "TMUX",
        "STY",
        "WEZTERM_PANE",
        "WEZTERM_EXECUTABLE",
        "GHOSTTY_RESOURCES_DIR",
        "LOUSHANG_TUI_TMUX_PASSTHROUGH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-kitty")


def test_render_terminal_image_defaults_to_auto_protocol_when_data_is_available(monkeypatch: Any) -> None:
    _set_kitty_test_environment(monkeypatch)

    line = render_terminal_image(alt_text="screenshot", source="shot.png", data=b"abc")

    assert line == "\x1b_Ga=T,f=100,t=d;YWJj\x1b\\"


def test_render_terminal_image_auto_protocol_detects_or_falls_back() -> None:
    kitty_line = render_terminal_image(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        protocol="auto",
        env={"TERM": "xterm-kitty"},
    )
    fallback_line = render_terminal_image(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        protocol="auto",
        env={},
    )

    assert kitty_line == "\x1b_Ga=T,f=100,t=d;YWJj\x1b\\"
    assert fallback_line == "[image: screenshot] shot.png"


def test_terminal_image_protocol_encoders_accept_size_and_identity_options() -> None:
    kitty = encode_kitty_image(b"abc", columns=12, rows=4, image_id=42, move_cursor=False)
    iterm2 = encode_iterm2_image(
        b"abc",
        name="shot.png",
        width=12,
        height="auto",
        preserve_aspect_ratio=False,
    )

    assert kitty == "\x1b_Ga=T,f=100,t=d,c=12,r=4,i=42,C=1;YWJj\x1b\\"
    assert delete_kitty_image(42) == "\x1b_Ga=d,d=I,i=42,q=2\x1b\\"
    assert delete_all_kitty_images() == "\x1b_Ga=d,d=A,q=2\x1b\\"
    assert iterm2 == "\x1b]1337;File=inline=1;width=12;height=auto;name=c2hvdC5wbmc=;preserveAspectRatio=0:YWJj\x07"


def test_terminal_image_hyperlink_helper_wraps_text_in_osc8() -> None:
    assert hyperlink("docs", "https://example.test/docs") == "\x1b]8;;https://example.test/docs\x1b\\docs\x1b]8;;\x1b\\"


def test_image_block_accounts_for_terminal_image_rows_and_styles_fallback() -> None:
    image = ImageBlock(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        mime_type="image/png",
        dimensions=ImageDimensions(width_px=100, height_px=100),
        protocol="kitty",
        max_width_cells=10,
        cell_dimensions=CellDimensions(width_px=10, height_px=20),
        image_id=7,
        move_cursor=False,
    )
    fallback = ImageBlock(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        protocol=None,
        mime_type="image/png",
        dimensions=ImageDimensions(width_px=100, height_px=50),
        fallback_style=lambda text: f"<dim>{text}</dim>",
    )

    lines = rendered_text(image, width=80, height=20)

    assert lines == (
        "\x1b_Ga=T,f=100,t=d,c=10,r=5,i=7,C=1;YWJj\x1b\\",
        "",
        "",
        "",
        "",
    )
    assert rendered_text(fallback, width=80) == ("<dim>[image: screenshot] shot.png [image/png] 100x50</dim>",)


def test_image_component_allocates_kitty_image_id_when_auto_detected(monkeypatch: Any) -> None:
    _set_kitty_test_environment(monkeypatch)
    image = Image(
        data=b"abc",
        mime_type="image/png",
        dimensions=ImageDimensions(width_px=20, height_px=20),
        max_width_cells=2,
    )

    lines = rendered_text(image, width=20)

    assert image.image_id is not None
    assert f"i={image.image_id}" in lines[0]
    assert lines == (
        f"\x1b_Ga=T,f=100,t=d,c=2,r=1,i={image.image_id},C=1;YWJj\x1b\\",
    )


def test_image_component_auto_protocol_prefers_runtime_capability_snapshot(monkeypatch: Any) -> None:
    monkeypatch.setenv("TERM", "xterm-kitty")
    disabled = Image(
        data=b"abc",
        alt_text="screenshot",
        source="shot.png",
        capabilities=TerminalRuntimeCapabilities(image_protocol="none"),
    )

    assert rendered_text(disabled, width=40) == ("[image: screenshot] shot.png",)
    assert disabled.image_id is None

    monkeypatch.delenv("TERM", raising=False)
    kitty = Image(
        data=b"abc",
        alt_text="screenshot",
        source="shot.png",
        capabilities=TerminalRuntimeCapabilities(image_protocol="kitty"),
    )

    lines = rendered_text(kitty, width=20)

    assert kitty.image_id is not None
    assert is_terminal_image_line(lines[0])
    assert f"i={kitty.image_id}" in lines[0]


def test_image_block_renders_kitty_protocol_line_when_data_and_protocol_are_available() -> None:
    image = ImageBlock(alt_text="screenshot", source="shot.png", data=b"abc", protocol="kitty")

    line = rendered_text(image, width=10)[0]

    assert is_terminal_image_line(line)
    assert line == "\x1b_Ga=T,f=100,t=d;YWJj\x1b\\"


def test_image_block_defaults_to_auto_protocol_when_data_is_available(monkeypatch: Any) -> None:
    _set_kitty_test_environment(monkeypatch)
    image = ImageBlock(alt_text="screenshot", source="shot.png", data=b"abc")

    line = rendered_text(image, width=10)[0]

    assert is_terminal_image_line(line)
    assert line == "\x1b_Ga=T,f=100,t=d;YWJj\x1b\\"


def test_image_block_renders_iterm2_protocol_line_when_selected() -> None:
    image = ImageBlock(alt_text="screenshot", source="shot.png", data=b"abc", protocol="iterm2")

    line = rendered_text(image, width=10)[0]

    assert is_terminal_image_line(line)
    assert line == "\x1b]1337;File=inline=1;name=c2hvdC5wbmc=:YWJj\x07"


def test_theme_resolver_merges_tokens_and_degrades_capabilities_without_layout_change() -> None:
    resolver = ThemeResolver(
        defaults={"status.model": {"color": "#ff0000", "bold": True}, "markdown.link": {"hyperlink": True}},
        overrides={"status.model": {"color": "#00ff00"}},
    )

    truecolor = resolver.resolve("status.model", TerminalCapabilities(truecolor=True, hyperlinks=True))
    degraded = resolver.resolve("status.model", TerminalCapabilities(truecolor=False, hyperlinks=False))
    link = resolver.resolve("markdown.link", TerminalCapabilities(truecolor=False, hyperlinks=False))

    assert truecolor == {"color": "#00ff00", "bold": True}
    assert degraded == {"color": 46, "bold": True}
    assert link == {"hyperlink": False}

    old_version = resolver.version
    resolver.update_overrides({"status.model": {"color": "#0000ff"}})

    assert resolver.version == old_version + 1


def test_theme_capabilities_can_be_adapted_from_runtime_capabilities() -> None:
    runtime = TerminalRuntimeCapabilities(truecolor=False, hyperlinks=False)
    capabilities = theme_capabilities_from_runtime(runtime)
    resolver = ThemeResolver(defaults={"accent": {"color": "#00ff00"}, "markdown.link": {"hyperlink": True}})

    assert capabilities == TerminalCapabilities(truecolor=False, hyperlinks=False)
    assert resolver.resolve("accent", capabilities)["color"] == 46
    assert resolver.resolve("markdown.link", capabilities)["hyperlink"] is False


def test_render_terminal_image_auto_protocol_uses_runtime_capability_snapshot() -> None:
    no_images = TerminalRuntimeCapabilities(image_protocol="none")
    kitty = TerminalRuntimeCapabilities(image_protocol="kitty")

    fallback = render_terminal_image(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        protocol="auto",
        env={"TERM": "xterm-kitty"},
        capabilities=no_images,
    )
    sequence = render_terminal_image(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        protocol="auto",
        capabilities=kitty,
    )

    assert fallback == "[image: screenshot] shot.png"
    assert sequence == "\x1b_Ga=T,f=100,t=d;YWJj\x1b\\"


def test_render_terminal_image_wraps_protocol_sequence_for_tmux_passthrough() -> None:
    capabilities = TerminalRuntimeCapabilities(image_protocol="kitty", tmux_passthrough=True)

    sequence = render_terminal_image(
        alt_text="screenshot",
        source="shot.png",
        data=b"abc",
        protocol="auto",
        capabilities=capabilities,
    )

    assert sequence == "\x1bPtmux;\x1b\x1b_Ga=T,f=100,t=d;YWJj\x1b\x1b\\\x1b\\"
