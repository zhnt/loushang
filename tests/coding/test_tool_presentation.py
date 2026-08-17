from __future__ import annotations

from loushang.ai.types import ImagePart, TextPart


def test_tool_presentation_extracts_normalized_text_and_image_fallbacks() -> None:
    from loushang.harness.tools.workspace import get_tool_text_output

    output = get_tool_text_output(
        [
            TextPart(type="text", text="hello\r\n\x1b[31mred\x1b[0m"),
            ImagePart(type="image", data="aGVsbG8=", mime_type="image/png"),
        ],
        show_images=False,
    )

    assert output == "hello\nred\n[Image: image/png]"


def test_tool_presentation_renders_truncation_and_artifact_notices() -> None:
    from loushang.harness.tools.workspace import render_tool_result_text

    output = render_tool_result_text(
        [TextPart(type="text", text="line")],
        {
            "matchLimitReached": 100,
            "linesTruncated": True,
            "truncation": {
                "truncated": True,
                "maxBytes": 50 * 1024,
            },
            "fullOutputPath": "/tmp/full.log",
        },
    )

    assert output == (
        "line\n"
        "[Truncated: 100 matches limit, 50.0KB limit, some lines truncated]\n"
        "[Full output: /tmp/full.log]"
    )


def test_tool_presentation_collapses_long_result_but_keeps_expanded_text() -> None:
    from loushang.harness.tools.workspace import render_tool_result_presentation

    rendered = render_tool_result_presentation(
        [TextPart(type="text", text="a\nb\nc\nd")],
        {},
        max_collapsed_lines=2,
    )

    assert rendered.expanded == "a\nb\nc\nd"
    assert rendered.collapsed == "a\nb\n... (2 more lines)"
    assert rendered.remaining_lines == 2
