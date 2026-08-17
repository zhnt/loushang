from __future__ import annotations

from loushang.harnesstui.selection.model import ModelSelectorSurface
from loushang.harnesstui.surface.factory import (
    command_palette_surface_view,
    command_surface_view,
    info_surface_view,
    model_selector_surface_view,
)
from loushang.tui import (
    CommandPalette,
    CommandPaletteItem,
    CommandSurface,
    InfoPanel,
    SelectItem,
)


def test_info_surface_view_preserves_existing_coding_defaults() -> None:
    view = info_surface_view(title="Available Models", text="first\nsecond")

    assert view.title == "Available Models"
    assert view.purpose == "info"
    assert view.subtitle == ""
    assert view.footer == "Enter/Esc to close"
    assert view.presentation == "bottom"
    assert view.preferred_height is None
    assert view.content == InfoPanel(
        title="Available Models",
        text="first\nsecond",
        footer="",
    )


def test_info_surface_view_keeps_all_copy_and_layout_policy_caller_supplied() -> None:
    view = info_surface_view(
        title="Diagnostics",
        text="body",
        subtitle="Terminal state",
        footer="Esc to dismiss",
        presentation="bottom-exclusive",
        preferred_height=12,
        panel_title="Plain diagnostics",
        panel_footer="Stored output",
    )

    assert view.title == "Diagnostics"
    assert view.subtitle == "Terminal state"
    assert view.footer == "Esc to dismiss"
    assert view.presentation == "bottom-exclusive"
    assert view.preferred_height == 12
    assert view.content == InfoPanel(
        title="Plain diagnostics",
        text="body",
        footer="Stored output",
    )


def test_command_surface_view_preserves_existing_coding_palette_defaults() -> None:
    items = (
        SelectItem(label="/model", value="/model", description="Select a model"),
        SelectItem(label="/status", value="/status"),
    )

    view = command_surface_view(
        title="Commands",
        purpose="command",
        items=(item for item in items),
    )

    assert view.title == "Commands"
    assert view.purpose == "command"
    assert view.subtitle == ""
    assert view.footer == "Enter to select - Esc to close"
    assert view.presentation == "bottom"
    assert view.preferred_height is None
    assert isinstance(view.content, CommandSurface)
    assert view.content.items == list(items)
    assert view.content.max_visible == 8
    assert view.content.filter_text == ""


def test_command_surface_view_accepts_caller_surface_and_search_policy() -> None:
    view = command_surface_view(
        title="Models",
        purpose="model",
        items=(
            SelectItem(label="provider/first", value="first"),
            SelectItem(label="provider/second", value="second"),
        ),
        subtitle="Choose one",
        footer="Enter to use",
        presentation="bottom-exclusive",
        preferred_height=10,
        query="second",
        max_visible=3,
    )

    assert view.purpose == "model"
    assert view.subtitle == "Choose one"
    assert view.footer == "Enter to use"
    assert view.presentation == "bottom-exclusive"
    assert view.preferred_height == 10
    assert isinstance(view.content, CommandSurface)
    assert view.content.max_visible == 3
    assert view.content.filter_text == "second"
    assert view.content.selected_item() == SelectItem(
        label="provider/second",
        value="second",
    )


def test_command_palette_surface_view_projects_neutral_items_and_palette_title() -> (
    None
):
    palette = CommandPalette(
        items=(
            CommandPaletteItem(
                value="/model",
                label="/model <name>",
                description="Select a model",
                disabled=True,
            ),
            CommandPaletteItem(value="/status"),
        ),
        title="Available Commands",
    )

    view = command_palette_surface_view(palette)

    assert view.title == "Available Commands"
    assert view.purpose == "command"
    assert view.subtitle == ""
    assert view.footer == "Enter to select - Esc to close"
    assert view.presentation == "bottom"
    assert view.preferred_height is None
    assert isinstance(view.content, CommandSurface)
    assert view.content.items == [
        SelectItem(
            label="/model <name>",
            value="/model",
            description="Select a model",
        ),
        SelectItem(label="/status", value="/status"),
    ]
    assert view.content.max_visible == 8
    assert view.content.filter_text == ""


def test_command_palette_surface_view_accepts_copy_layout_and_search_policy() -> None:
    palette = CommandPalette(
        items=(CommandPaletteItem(value="first"), CommandPaletteItem(value="second")),
        title="Ignored",
    )

    view = command_palette_surface_view(
        palette,
        purpose="model",
        title="Choose",
        subtitle="Prepared choices",
        footer="Enter to use",
        presentation="bottom-exclusive",
        preferred_height=14,
        query="second",
        max_visible=4,
    )

    assert view.title == "Choose"
    assert view.purpose == "model"
    assert view.subtitle == "Prepared choices"
    assert view.footer == "Enter to use"
    assert view.presentation == "bottom-exclusive"
    assert view.preferred_height == 14
    assert isinstance(view.content, CommandSurface)
    assert view.content.max_visible == 4
    assert view.content.filter_text == "second"


def test_model_selector_surface_view_preserves_neutral_item_identity_and_defaults() -> (
    None
):
    all_item = SelectItem(label="provider/model", value="provider/model")
    scoped_item = SelectItem(label="recommended", value="provider/recommended")

    view = model_selector_surface_view(
        all_items=(item for item in (all_item,)),
        scoped_items=(item for item in (scoped_item,)),
        selected_value="provider/recommended",
    )

    assert view.title == "Select Model"
    assert view.purpose == "model"
    assert view.subtitle == ""
    assert view.footer == "Enter to select - Esc to close"
    assert view.presentation == "bottom"
    assert view.preferred_height is None
    assert isinstance(view.content, ModelSelectorSurface)
    assert view.content.all_items == (all_item,)
    assert view.content.all_items[0] is all_item
    assert view.content.scoped_items == (scoped_item,)
    assert view.content.scoped_items[0] is scoped_item
    assert view.content.selected_value == "provider/recommended"
    assert view.content.max_visible == 10


def test_model_selector_surface_view_accepts_all_copy_and_layout_policy() -> None:
    view = model_selector_surface_view(
        all_items=(SelectItem(label="first", value="first"),),
        title="Models",
        subtitle="Choose a model",
        footer="Press a number or enter",
        presentation="bottom-exclusive",
        preferred_height=18,
        max_visible=6,
    )

    assert view.title == "Models"
    assert view.purpose == "model"
    assert view.subtitle == "Choose a model"
    assert view.footer == "Press a number or enter"
    assert view.presentation == "bottom-exclusive"
    assert view.preferred_height == 18
    assert isinstance(view.content, ModelSelectorSurface)
    assert view.content.max_visible == 6
