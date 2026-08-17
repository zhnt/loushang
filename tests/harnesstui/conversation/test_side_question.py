from __future__ import annotations

import asyncio

from loushang.harness.runtime import SideQuestionAnswer
from loushang.harnesstui.conversation.side_question import (
    SideQuestionSurface,
    build_side_question_surface_view,
)
from loushang.tui import InputEvent, RenderConstraints


def test_side_question_surface_renders_answer_and_scrolls() -> None:
    renders: list[None] = []

    async def ask(question: str, *, on_update=None) -> SideQuestionAnswer:
        assert question == "Explain"
        assert on_update is not None
        return SideQuestionAnswer("\n".join(f"line {index}" for index in range(8)))

    surface = SideQuestionSurface(
        question="Explain",
        ask=ask,
        cancel=lambda: None,
        request_render=lambda: renders.append(None),
    )

    asyncio.run(surface.start())
    result = surface.render(RenderConstraints(width=40, max_height=4))

    assert surface.status == "answered"
    assert renders == [None]
    assert len(result.lines) == 4
    assert "scroll" in surface.footer_help
    intent = surface.handle_input(InputEvent(kind="key", key="down"))
    assert intent is not None
    assert intent.kind == "consumed"


def test_side_question_surface_close_cancels_only_answering_request() -> None:
    cancellations: list[None] = []

    async def ask(question: str, *, on_update=None) -> SideQuestionAnswer:
        del question
        assert on_update is not None
        await asyncio.Future()
        raise AssertionError("unreachable")

    surface = SideQuestionSurface(
        question="Wait",
        ask=ask,
        cancel=lambda: cancellations.append(None),
        request_render=lambda: None,
    )

    surface.close()

    assert cancellations == [None]
    assert surface.status == "closed"


def test_side_question_surface_uses_a_full_screen_page() -> None:
    async def ask(question: str, *, on_update=None) -> SideQuestionAnswer:
        assert on_update is not None
        return SideQuestionAnswer(question)

    view = build_side_question_surface_view(
        question="Explain",
        ask=ask,
        cancel=lambda: None,
        request_render=lambda: None,
    )

    assert view.presentation == "page"
    assert view.preferred_height is None
    assert view.title == "/btw"
    assert view.subtitle == "Explain"
    assert view.theme is not None
    assert view.theme.resolve("surface.subtitle") == {
        "bold": True,
        "color": "bright_cyan",
    }


def test_side_question_surface_streams_themed_markdown() -> None:
    async def scenario() -> None:
        partial_ready = asyncio.Event()
        release = asyncio.Event()

        async def ask(question: str, *, on_update=None) -> SideQuestionAnswer:
            assert question == "Explain"
            assert on_update is not None
            on_update("A **partial** answer")
            partial_ready.set()
            await release.wait()
            return SideQuestionAnswer("A **complete** answer")

        surface = SideQuestionSurface(
            question="Explain",
            ask=ask,
            cancel=lambda: None,
            request_render=lambda: None,
        )
        task = asyncio.create_task(surface.start())
        await partial_ready.wait()

        result = surface.render(RenderConstraints(width=40, max_height=8))
        rendered = "\n".join(line.text for line in result.lines)
        assert "partial" in rendered
        assert "**" not in rendered
        assert "\x1b[1m" in rendered
        assert "Answering" in rendered

        release.set()
        await task
        assert surface.answer == "A **complete** answer"
        assert surface.status == "answered"

    asyncio.run(scenario())
