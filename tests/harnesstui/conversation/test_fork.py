from __future__ import annotations

from loushang.harnesstui.conversation.fork import (
    ForkPromptCandidate,
    ForkPromptSurface,
    build_fork_prompt_surface_view,
)
from loushang.tui import InputEvent, InputIntent, RenderConstraints
from loushang.tui.cell_width import strip_control_sequences


def _candidates() -> tuple[ForkPromptCandidate, ...]:
    return (
        ForkPromptCandidate(entry_id="entry-first", text="first prompt"),
        ForkPromptCandidate(
            entry_id="entry-latest",
            text="latest prompt with\nmultiple lines",
        ),
    )


def _plain_lines(surface: ForkPromptSurface) -> tuple[str, ...]:
    rendered = surface.render(RenderConstraints(width=80, max_height=12))
    return tuple(strip_control_sequences(line.text) for line in rendered.lines)


def test_fork_prompt_surface_selects_recent_prompts_without_exposing_ids() -> None:
    surface = ForkPromptSurface(candidates=_candidates(), request_render=lambda: None)

    lines = _plain_lines(surface)

    assert surface.selected_entry_id == "entry-latest"
    assert any("latest prompt with multiple lines" in line for line in lines)
    assert all("entry-latest" not in line for line in lines)
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select",
        text="entry-latest",
    )

    surface.handle_input(InputEvent(kind="text", text="first"))
    assert surface.selected_entry_id == "entry-first"


def test_fork_prompt_surface_previews_selected_prompt_and_returns_to_list() -> None:
    renders: list[None] = []
    surface = ForkPromptSurface(
        candidates=_candidates(),
        request_render=lambda: renders.append(None),
    )

    assert surface.handle_input(InputEvent(kind="key", key="space")) == InputIntent(
        kind="consumed",
        note="fork_preview",
    )
    lines = _plain_lines(surface)
    assert "Prompt 2 of 2" in lines
    assert "latest prompt with" in lines
    assert "multiple lines" in lines
    assert "Space/Esc back" in surface.footer_help

    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select",
        text="entry-latest",
    )
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="consumed",
        note="fork_preview_close",
    )
    assert "Space preview" in surface.footer_help
    assert len(renders) == 2


def test_fork_prompt_surface_shows_one_activation_state_and_inline_failure() -> None:
    surface = ForkPromptSurface(candidates=_candidates(), request_render=lambda: None)

    assert surface.begin_activation() is True
    assert surface.begin_activation() is False
    assert surface.footer_help == ""
    lines = _plain_lines(surface)
    assert sum("Forking selected prompt" in line for line in lines) == 1
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="consumed",
        note="fork_activating",
    )

    surface.fail_activation(RuntimeError("fork denied"))
    lines = _plain_lines(surface)
    assert any("Error: fork denied" in line for line in lines)
    assert surface.begin_activation() is True


def test_fork_prompt_surface_handles_an_empty_conversation() -> None:
    view = build_fork_prompt_surface_view(
        candidates=(),
        request_render=lambda: None,
    )
    surface = view.content

    assert isinstance(surface, ForkPromptSurface)
    assert surface.selected_entry_id is None
    assert surface.begin_activation() is False
    rendered = view.render(RenderConstraints(width=80, max_height=12))
    lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert "No prompts to fork yet" in lines
