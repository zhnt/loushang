from __future__ import annotations

import pytest

from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent
from loushang.tui.ui_parts.text_pager import TextPager


def test_text_pager_exposes_all_text_and_tracks_contiguous_presentation():
    pager = TextPager("Details", "\n".join(f"line-{index:03}" for index in range(100)))
    constraints = RenderConstraints(width=30, max_height=8)
    first = pager.render(constraints)
    assert "line-000" in "\n".join(line.text for line in first.lines)
    assert not pager.fully_presented
    pager.handle_input(InputEvent(kind="key", key="end"))
    end = pager.render(constraints)
    assert "line-099" in "\n".join(line.text for line in end.lines)
    assert not pager.fully_presented  # Jumping to the end leaves unseen middle pages.
    pager.handle_input(InputEvent(kind="key", key="home"))
    seen = set()
    for _ in range(100):
        result = pager.render(constraints)
        result.validate(constraints)
        seen.update(line.text for line in result.lines if line.text.startswith("line-"))
        pager.handle_input(InputEvent(kind="key", key="pageDown"))
    assert seen == {f"line-{index:03}" for index in range(100)}
    assert pager.fully_presented


@pytest.mark.parametrize("width,height", [(1, 1), (2, 3), (8, 6), (40, 12)])
def test_text_pager_bounds_unicode_rows_and_ignores_non_navigation_input(width, height):
    pager = TextPager("Details", "中文参数\nsecond\tline")
    constraints = RenderConstraints(width=width, max_height=height)
    before = pager.render(constraints)
    before.validate(constraints)
    pager.handle_input(InputEvent(kind="paste", text="/approve\r"))
    after = pager.render(constraints)
    assert before.lines == after.lines
    assert not any("\t" in line.text for line in after.lines)
    if width < 3 or height < 3:
        assert not pager.fully_presented


def test_text_pager_reflow_invalidates_partial_presentation_and_limits_allocation():
    pager = TextPager("Details", "x" * 500)
    pager.render(RenderConstraints(width=50, max_height=5))
    pager.handle_input(InputEvent(kind="key", key="pageDown"))
    pager.render(RenderConstraints(width=10, max_height=5))
    assert not pager.fully_presented
    with pytest.raises(ValueError, match="pager_text_limit"):
        TextPager("Details", "x" * (1024 * 1024 + 1))


def test_text_pager_removes_raw_terminal_controls_from_title_and_body():
    pager = TextPager("Details\x07\x9b\x1b[31m", "body\x08\x1b[2J")
    constraints = RenderConstraints(width=40, max_height=6)
    result = pager.render(constraints)
    assert result.lines[0].text == "Details"
    assert result.lines[1].text == "body"
