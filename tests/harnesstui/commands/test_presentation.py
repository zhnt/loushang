from __future__ import annotations

from types import SimpleNamespace

from loushang.harnesstui.commands.presentation import (
    command_completion_provider,
    command_palette,
    command_palette_select_items,
    format_commands,
    matching_command_items,
)
from loushang.tui import (
    CommandPalette,
    CommandPaletteItem,
    CommandSurface,
    CompletionItem,
    SelectItem,
)


def _commands() -> tuple[object, ...]:
    return (
        SimpleNamespace(
            name="settings",
            description="Open settings",
            source="local",
        ),
        SimpleNamespace(
            name="review",
            invocation_name="review:pr",
            argument_hint="<PR-URL>",
            description="Review a pull request",
            source="extension",
        ),
    )


def test_format_commands_projects_and_filters_descriptors() -> None:
    assert format_commands(_commands()) == (
        "Commands:\n"
        "/review:pr <PR-URL> - Review a pull request (extension)\n"
        "/settings - Open settings (local)"
    )
    assert format_commands(_commands(), query="pull REQUEST") == (
        "Commands:\n/review:pr <PR-URL> - Review a pull request (extension)"
    )
    assert format_commands(_commands(), query="missing") == "No commands match: missing"


def test_command_completion_projection_orders_product_commands_before_local() -> None:
    provider = command_completion_provider(_commands())

    assert provider.items == (
        CompletionItem(
            value="/review:pr",
            label="/review:pr <PR-URL>",
            description="Review a pull request (extension)",
        ),
        CompletionItem(
            value="/settings",
            label="/settings",
            description="Open settings (local)",
        ),
    )
    assert command_palette(_commands(), title="Actions") == CommandPalette(
        items=(
            CommandPaletteItem(
                value="/review:pr",
                label="/review:pr <PR-URL>",
                description="Review a pull request (extension)",
            ),
            CommandPaletteItem(
                value="/settings",
                label="/settings",
                description="Open settings (local)",
            ),
        ),
        title="Actions",
    )


def test_command_completion_projection_can_keep_session_alphabetical_order() -> None:
    commands = (
        SimpleNamespace(name="a-local", source="local"),
        SimpleNamespace(name="z-product", source="builtin"),
    )

    provider = command_completion_provider(commands, local_last=False)

    assert [item.value for item in provider.items] == ["/a-local", "/z-product"]


def test_command_palette_select_items_preserve_surface_fields_and_filtering() -> None:
    palette = CommandPalette(
        (
            CommandPaletteItem(
                value="/deploy",
                label="Deploy service",
                description="Run deployment pipeline",
            ),
            CommandPaletteItem(
                value="/archive",
                description="Unavailable action",
                disabled=True,
            ),
        )
    )

    items = command_palette_select_items(palette)

    assert items == [
        SelectItem(
            label="Deploy service",
            value="/deploy",
            description="Run deployment pipeline",
        ),
        SelectItem(
            label="/archive",
            value="/archive",
            description="Unavailable action",
        ),
    ]
    assert [item.selected_value for item in items] == ["/deploy", "/archive"]

    surface = CommandSurface(items)
    surface.set_filter("PIPELINE")
    assert surface.selected_item() == items[0]
    surface.set_filter("unavailable")
    assert surface.selected_item() == items[1]


def test_matching_commands_prefers_exact_value_or_label() -> None:
    provider = command_completion_provider(_commands())

    assert matching_command_items(provider, "/settings") == (provider.items[1],)
    assert matching_command_items(provider, "PR-URL") == (provider.items[0],)
    assert matching_command_items(provider, "open") == (provider.items[1],)
