from __future__ import annotations

from loushang.harnesstui.status.plain import (
    PlainToolbarSnapshot,
    render_plain_toolbar,
)


def test_render_plain_toolbar_omits_empty_fields() -> None:
    snapshot = PlainToolbarSnapshot(
        model="moonshot/kimi-for-coding",
        cwd="/repo",
        branch=None,
        session="254d6156",
        thinking="off",
        running=True,
    )

    assert render_plain_toolbar(snapshot) == (
        "model=moonshot/kimi-for-coding | cwd=/repo | "
        "session=254d6156 | thinking=off | running"
    )


def test_render_plain_toolbar_can_return_single_fixed_width_line() -> None:
    snapshot = PlainToolbarSnapshot(
        model="moonshot/kimi-for-coding",
        cwd="/a/very/long/repository/path",
        thinking="high",
        running=True,
    )

    rendered = render_plain_toolbar(snapshot, width=32)

    assert len(rendered) == 32
    assert rendered.startswith("model=moonshot/")
    assert rendered.endswith("...")
    assert "\x1b[7m" not in rendered
