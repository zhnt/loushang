from __future__ import annotations

from loushang.harnesstui.selection.model import (
    MODEL_SELECTOR_SELECTED_STYLE,
    ModelSelectorSurface,
)
from loushang.tui import InputEvent, InputIntent, RenderConstraints, SelectItem
from loushang.tui.cell_width import strip_control_sequences


def _items(count: int) -> tuple[SelectItem, ...]:
    return tuple(
        SelectItem(label=f"{index}. model-{index}", value=f"model-{index}")
        for index in range(1, count + 1)
    )


def test_model_selector_surface_keeps_selected_item_and_style() -> None:
    surface = ModelSelectorSurface(_items(3), selected_value="model-2")

    intent = surface.handle_input(InputEvent(kind="key", key="enter"))
    rendered = surface.render(RenderConstraints(width=40, max_height=6))

    assert intent == InputIntent(kind="select", text="model-2")
    assert MODEL_SELECTOR_SELECTED_STYLE == {"color": 33, "bold": True}
    assert rendered.lines[1].text.startswith("\x1b[1;38;5;33m> 2. model-2")


def test_model_selector_surface_preserves_long_endpoint_identity_when_space_allows() -> (
    None
):
    identity = "1. dashscope:openai-completions:cn:qwen3.6-plus"
    surface = ModelSelectorSurface(
        (
            SelectItem(
                label=identity,
                value="dashscope:openai-completions:cn:qwen3.6-plus",
                description="current - Qwen 3.6 Plus",
            ),
        )
    )

    rendered = surface.render(RenderConstraints(width=120, max_height=3))
    lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert lines == (f"> {identity}  current - Qwen 3.6 Plus",)


def test_model_selector_surface_keeps_multidigit_ordinal_selection() -> None:
    surface = ModelSelectorSurface(_items(12))

    intent = surface.handle_input(InputEvent(kind="text", text="12"))

    assert intent == InputIntent(kind="select", text="model-12")


def test_model_selector_surface_preserves_filter_across_scope_changes() -> None:
    surface = ModelSelectorSurface(
        _items(3),
        scoped_items=(_items(3)[0], _items(3)[2]),
    )

    surface.handle_input(InputEvent(kind="text", text="model-3"))
    scoped = surface.render(RenderConstraints(width=50, max_height=8))
    surface.handle_input(InputEvent(kind="key", key="tab"))
    all_models = surface.render(RenderConstraints(width=50, max_height=8))

    scoped_lines = tuple(strip_control_sequences(line.text) for line in scoped.lines)
    all_lines = tuple(strip_control_sequences(line.text) for line in all_models.lines)
    assert scoped_lines[0] == "Scope: scoped | all"
    assert all_lines[0] == "Scope: all | scoped"
    assert any("model-3" in line for line in scoped_lines)
    assert any("model-3" in line for line in all_lines)
    assert not any("model-1" in line for line in scoped_lines[2:])
    assert not any("model-1" in line for line in all_lines[2:])
    assert surface.footer_help == "↑/↓ choose · Enter switch · Esc keep current"
    assert any(
        "\x1b[1;36mSearch: " in line.text for line in all_models.lines
    )


def test_model_selector_surface_unfiltered_footer_matches_available_shortcuts() -> (
    None
):
    surface = ModelSelectorSurface(_items(12))

    assert surface.footer_help == (
        "Type to filter · ↑/↓ choose · Enter switch · "
        "1–9 quick select · Esc keep current"
    )
