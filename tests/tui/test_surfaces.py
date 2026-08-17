from __future__ import annotations

from typing import Any

from loushang.tui import (
    ApprovalSurface,
    AutocompleteSurface,
    CommandSurface,
    DialogSurface,
    InputEvent,
    InputIntent,
    RenderConstraints,
    SelectionSurface,
    SelectItem,
    ThemeResolver,
    strip_control_sequences,
)


def rendered_text(surface: Any, *, width: int = 30, height: int = 5) -> tuple[str, ...]:
    result = surface.render(RenderConstraints(width=width, max_height=height))
    return tuple(line.text for line in result.lines)


def test_selection_surface_wraps_navigation_and_scrolls_selected_item_visible() -> None:
    surface = SelectionSurface(
        [
            SelectItem("one"),
            SelectItem("two"),
            SelectItem("three"),
            SelectItem("four"),
            SelectItem("five"),
        ],
        max_visible=3,
    )

    for _ in range(3):
        surface.handle_input(InputEvent(kind="key", key="down"))

    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "  three",
        "> four",
        "  five",
        "  (4/5)",
    )

    surface.handle_input(InputEvent(kind="key", key="down"))
    surface.handle_input(InputEvent(kind="key", key="down"))

    assert surface.selected_index == 0


def test_selection_surface_can_clamp_navigation_at_edges() -> None:
    surface = SelectionSurface(
        [SelectItem("one"), SelectItem("two"), SelectItem("three")],
        wrap_navigation=False,
    )

    surface.handle_input(InputEvent(kind="key", key="up"))
    assert surface.selected_index == 0

    surface.handle_input(InputEvent(kind="key", key="end"))
    surface.handle_input(InputEvent(kind="key", key="down"))
    surface.handle_input(InputEvent(kind="key", key="pageDown"))
    assert surface.selected_index == 2


def test_selection_surface_returns_select_and_close_intents() -> None:
    surface = SelectionSurface([SelectItem("Help", value="help")])

    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select", text="help"
    )
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="surface_close"
    )


def test_selection_surface_uses_pi_style_primary_column_and_description_layout() -> (
    None
):
    surface = SelectionSurface(
        [
            SelectItem("short", value="short", description="first line\nsecond line"),
            SelectItem(
                "a very long command name",
                value="long",
                description="Long description text",
            ),
        ],
        max_visible=4,
    )

    raw = rendered_text(surface, width=80, height=4)

    assert tuple(strip_control_sequences(line) for line in raw) == (
        "> " + "short" + (" " * 27) + "first line second line",
        "  " + "a very long command name" + (" " * 8) + "Long description text",
    )
    assert raw[0].startswith("\x1b[1;38;5;33m> short")
    assert raw[0].endswith("\x1b[22;39m")


def test_selection_surface_can_preserve_preformatted_description_spacing() -> None:
    surface = SelectionSurface(
        [
            SelectItem(
                "session",
                value="session",
                description="  1h ago · coding  · ready",
            )
        ],
        preserve_description_spacing=True,
    )

    raw = strip_control_sequences(rendered_text(surface, width=80, height=2)[0])

    assert raw == "> session                           1h ago · coding  · ready"


def test_selection_surface_selected_row_uses_theme_token_when_provided() -> None:
    surface = SelectionSurface(
        [SelectItem("Theme")],
        theme=ThemeResolver(
            defaults={"selection.selected": {"color": "cyan", "bold": True}}
        ),
    )

    raw = rendered_text(surface, width=24, height=3)[0]

    assert strip_control_sequences(raw) == "> Theme"
    assert raw.startswith("\x1b[1;36m> Theme")


def test_selection_surface_can_hide_scroll_info_for_product_selectors() -> None:
    surface = SelectionSurface(
        [SelectItem(f"{index + 1}. item-{index}") for index in range(8)],
        max_visible=3,
        show_scroll_info=False,
    )

    surface.handle_input(InputEvent(kind="key", key="pageDown"))

    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "  3. item-2",
        "> 4. item-3",
        "  5. item-4",
    )


def test_selection_surface_notifies_when_selection_changes() -> None:
    seen: list[SelectItem | None] = []
    surface = SelectionSurface(
        [SelectItem("Alpha", value="alpha"), SelectItem("Beta", value="beta")],
        on_selection_change=seen.append,
    )

    surface.handle_input(InputEvent(kind="key", key="down"))
    surface.handle_input(InputEvent(kind="key", key="down"))

    assert seen == [
        SelectItem("Beta", value="beta"),
        SelectItem("Alpha", value="alpha"),
    ]


def test_selection_surface_accepts_custom_layout_and_truncation_hooks() -> None:
    calls: list[tuple[str, int, str]] = []

    def truncate(text: str, max_width: int, ellipsis: str) -> str:
        calls.append((text, max_width, ellipsis))
        return text[:max_width]

    surface = SelectionSurface(
        [
            SelectItem(
                "long-command-name", value="long", description="Long description text"
            )
        ],
        primary_column_width=8,
        min_description_width=3,
        truncate_text=truncate,
    )

    assert (
        strip_control_sequences(rendered_text(surface, width=24, height=2)[0])
        == "> long-c  Long descri"
    )
    assert calls == [
        ("long-command-name", 6, ""),
        ("Long description text", 11, ""),
    ]


def test_selection_surface_search_input_filters_items_and_tracks_cursor() -> None:
    surface = SelectionSurface(
        [
            SelectItem("Alpha", value="alpha"),
            SelectItem("Model", value="model", description="Current model"),
            SelectItem("Memory", value="memory"),
        ],
        max_visible=4,
        enable_search=True,
        filter_mode="contains",
    )

    surface.handle_input(InputEvent(kind="text", text="mo"))
    result = surface.render(RenderConstraints(width=60, max_height=6))

    lines = tuple(strip_control_sequences(line.text) for line in result.lines)
    assert lines[:2] == ("Search: mo", "")
    assert lines[2].startswith("> Model")
    assert lines[2].endswith("Current model")
    assert lines[3] == "  Memory"
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, len("Search: mo"))

    surface.handle_input(InputEvent(kind="key", key="backspace"))

    lines = tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=60, height=6)
    )
    assert lines[:2] == ("Search: m", "")
    assert lines[2].startswith("> Model")
    assert lines[2].endswith("Current model")
    assert lines[3] == "  Memory"


def test_selection_surface_search_toolbar_compacts_then_wraps() -> None:
    surface = SelectionSurface(
        [SelectItem("Alpha", value="alpha")],
        enable_search=True,
        search_placeholder="Type to search",
        search_toolbar="Sort: [Updated] Created",
        search_toolbar_compact="Sort:[Updated]",
        search_min_input_width=20,
        filter_mode="contains",
    )

    wide = surface.render(RenderConstraints(width=60, max_height=6))
    wide_lines = tuple(strip_control_sequences(line.text) for line in wide.lines)
    assert wide_lines[0].startswith("Type to search")
    assert wide_lines[0].endswith("Sort: [Updated] Created")
    assert wide_lines[1:3] == ("", "> Alpha")
    assert wide.cursor is not None
    assert (wide.cursor.row, wide.cursor.column) == (0, 0)

    surface.handle_input(InputEvent(kind="text", text="a"))
    compact = surface.render(RenderConstraints(width=40, max_height=6))
    compact_lines = tuple(strip_control_sequences(line.text) for line in compact.lines)
    assert compact_lines[0].startswith("Search: a")
    assert compact_lines[0].endswith("Sort:[Updated]")

    narrow = surface.render(RenderConstraints(width=24, max_height=6))
    narrow_lines = tuple(strip_control_sequences(line.text) for line in narrow.lines)
    assert narrow_lines[:4] == (
        "Search: a",
        "Sort:[Updated]",
        "",
        "> Alpha",
    )


def test_selection_surface_search_can_use_fuzzy_filtering() -> None:
    surface = SelectionSurface(
        [
            SelectItem("Theme", value="theme"),
            SelectItem("Model Selection", value="model"),
        ],
        enable_search=True,
        filter_mode="fuzzy",
    )

    surface.handle_input(InputEvent(kind="text", text="ms"))

    lines = tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=40, height=5)
    )
    assert lines[:3] == ("Search: ms", "", "> Model Selection")


def test_selection_surface_consumed_paths_return_true_without_intents() -> None:
    surface = SelectionSurface(
        [SelectItem("Alpha"), SelectItem("Model")],
        enable_search=True,
        filter_mode="contains",
    )

    assert surface.handle_input(InputEvent(kind="text", text="mo")) is True
    assert surface.handle_input(InputEvent(kind="key", key="backspace")) is True
    assert surface.handle_input(InputEvent(kind="key", key="down")) is True


def test_selection_surface_page_navigation_keeps_selected_item_visible() -> None:
    surface = SelectionSurface(
        [SelectItem(f"item-{index}") for index in range(8)], max_visible=3
    )

    surface.handle_input(InputEvent(kind="key", key="pageDown"))

    assert surface.selected_index == 3
    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "  item-2",
        "> item-3",
        "  item-4",
        "  (4/8)",
    )


def test_selection_surface_home_end_navigation_jumps_to_edges() -> None:
    surface = SelectionSurface(
        [SelectItem(f"item-{index}") for index in range(6)], max_visible=3
    )

    surface.handle_input(InputEvent(kind="key", key="end"))

    assert surface.selected_index == 5
    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "  item-3",
        "  item-4",
        "> item-5",
        "  (6/6)",
    )

    surface.handle_input(InputEvent(kind="key", key="home"))

    assert surface.selected_index == 0
    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "> item-0",
        "  item-1",
        "  item-2",
        "  (1/6)",
    )


def test_selection_surface_home_end_navigation_works_when_search_is_hidden() -> None:
    surface = SelectionSurface(
        [SelectItem(f"item-{index}") for index in range(6)],
        max_visible=3,
        enable_search=True,
        show_search_when_empty=False,
    )

    surface.handle_input(InputEvent(kind="key", key="end"))

    assert surface.selected_index == 5
    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "  item-3",
        "  item-4",
        "> item-5",
        "  (6/6)",
    )

    surface.handle_input(InputEvent(kind="key", key="home"))

    assert surface.selected_index == 0


def test_selection_surface_mouse_press_selects_visible_row_after_render() -> None:
    surface = SelectionSurface(
        [SelectItem(f"item-{index}") for index in range(6)], max_visible=3
    )
    surface.handle_input(InputEvent(kind="key", key="pageDown"))
    rendered_text(surface, width=20, height=4)

    intent = surface.handle_input(
        InputEvent(
            kind="mouse",
            mouse_button=0,
            mouse_column=2,
            mouse_row=2,
            mouse_action="press",
        )
    )

    assert intent is True
    assert surface.selected_index == 4
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select", text="item-4"
    )


def test_selection_surface_empty_state_ignores_enter_and_mouse() -> None:
    surface = SelectionSurface([], empty_text="No items")

    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == ("No items",)
    assert surface.handle_input(InputEvent(kind="key", key="enter")) is True
    assert (
        surface.handle_input(
            InputEvent(kind="mouse", mouse_button=0, mouse_row=0, mouse_action="press")
        )
        is True
    )
    assert surface.selected_item() is None


def test_autocomplete_surface_returns_completion_intent() -> None:
    surface = AutocompleteSurface([SelectItem("README.md", value="README.md")])

    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="complete", text="README.md"
    )


def test_command_surface_filters_and_returns_command_intent() -> None:
    surface = CommandSurface(
        [SelectItem("/help", value="help"), SelectItem("/model", value="model")],
        query="/h",
    )

    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=20, height=4)
    ) == (
        "Search: /h",
        "",
        "> /help",
    )
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="command", text="help"
    )


def test_command_surface_searches_from_typed_text() -> None:
    surface = CommandSurface(
        [
            SelectItem("/model", value="/model"),
            SelectItem("/status", value="/status"),
        ],
    )

    surface.handle_input(InputEvent(kind="text", text="sta"))

    assert tuple(
        strip_control_sequences(line)
        for line in rendered_text(surface, width=30, height=4)
    ) == (
        "Search: sta",
        "",
        "> /status",
    )
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="command", text="/status"
    )


def test_approval_surface_returns_explicit_approval_or_rejection() -> None:
    surface = ApprovalSurface(action="Run command", risk="writes files")

    assert rendered_text(surface, width=56, height=10) == (
        "Action",
        "  Run command",
        "",
        "Risk",
        "  writes files",
        "",
        "› 1. Allow this action once (y)",
        "  2. Deny and let the agent continue (n)",
    )
    assert surface.handle_input(InputEvent(kind="key", key="y")) == InputIntent(
        kind="approval_decision", text="allow_once"
    )
    assert surface.handle_input(InputEvent(kind="key", key="n")) == InputIntent(
        kind="approval_decision", text="deny"
    )
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="approval_decision", text="abort"
    )
    assert surface.handle_input(InputEvent(kind="text", text="y")) == InputIntent(
        kind="approval_decision", text="allow_once"
    )
    assert surface.handle_input(InputEvent(kind="text", text="n")) == InputIntent(
        kind="approval_decision", text="deny"
    )
    assert surface.handle_input(InputEvent(kind="text", text="1")) == InputIntent(
        kind="approval_decision", text="allow_once"
    )
    assert surface.handle_input(InputEvent(kind="text", text="2")) == InputIntent(
        kind="approval_decision", text="deny"
    )


def test_approval_surface_renders_child_requester_provenance() -> None:
    surface = ApprovalSurface(
        action="Publish release",
        requester="/root/reviewer#2",
        risk="writes remote refs",
        cwd="/repo",
        environment="local",
    )

    assert rendered_text(surface, width=60, height=12) == (
        "Action",
        "  Publish release",
        "Requested by /root/reviewer#2",
        "Environment  local",
        "Directory    /repo",
        "",
        "Risk",
        "  writes remote refs",
        "",
        "› 1. Allow this action once (y)",
        "  2. Deny and let the agent continue (n)",
    )


def test_approval_surface_exposes_session_choice_only_when_policy_admits_it() -> (
    None
):
    surface = ApprovalSurface(
        action="Publish main to origin",
        action_id="git:push",
        allow_session=True,
        grant_summary="Allow non-force pushes to origin",
    )

    assert rendered_text(surface, width=80, height=8) == (
        "Action",
        "  Publish main to origin",
        "",
        "› 1. Allow this action once (y)",
        "  2. Allow non-force pushes to origin (a)",
        "  3. Deny and let the agent continue (n)",
    )
    assert surface.handle_input(InputEvent(kind="key", key="a")) == InputIntent(
        kind="approval_decision",
        text="allow_session",
        note="git:push",
    )
    assert surface.handle_input(InputEvent(kind="key", key="2")) == InputIntent(
        kind="approval_decision",
        text="allow_session",
        note="git:push",
    )
    assert surface.handle_input(InputEvent(kind="key", key="3")) == InputIntent(
        kind="approval_decision",
        text="deny",
        note="git:push",
    )
    assert ApprovalSurface(action="Delete cache").handle_input(
        InputEvent(kind="key", key="a")
    ) is None


def test_approval_surface_renders_policy_generated_persistent_choice() -> None:
    from loushang.tui import ApprovalChoice

    surface = ApprovalSurface(
        action="git push origin main",
        options=(
            ApprovalChoice("allow_once", "Allow this action once", "y"),
            ApprovalChoice(
                "allow_session",
                "Allow non-force pushes for this session",
                "s",
                "session",
            ),
            ApprovalChoice(
                "allow_project",
                "Always allow non-force pushes in this project",
                "p",
                "persistent",
            ),
            ApprovalChoice(
                "deny",
                "Deny and let the agent continue",
                "n",
                "deny",
            ),
        ),
    )

    assert rendered_text(surface, width=72, height=8)[3:] == (
        "› 1. Allow this action once (y)",
        "  2. Allow non-force pushes for this session (s)",
        "  3. Always allow non-force pushes in this project (p)",
        "  4. Deny and let the agent continue (n)",
    )
    assert surface.handle_input(InputEvent(kind="key", key="p")) == InputIntent(
        kind="approval_decision",
        text="allow_project",
    )


def test_approval_surface_supports_arrow_selection_and_enter() -> None:
    surface = ApprovalSurface(
        action="Publish main",
        action_id="git:push",
        allow_session=True,
    )

    assert surface.handle_input(InputEvent(kind="key", key="down")) == InputIntent(
        kind="consumed",
        note="approval_selection",
    )
    assert surface.selected_index == 1
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="approval_decision",
        text="allow_session",
        note="git:push",
    )
    surface.handle_input(InputEvent(kind="key", key="end"))
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="approval_decision",
        text="deny",
        note="git:push",
    )


def test_approval_surface_keeps_shortcuts_visible_when_grant_summary_is_long() -> None:
    surface = ApprovalSurface(
        action="git push origin main",
        allow_session=True,
        grant_summary=(
            "Allow non-force refs to origin from this repository for this child session"
        ),
    )

    lines = rendered_text(surface, width=42, height=8)

    assert lines[4].endswith("(a)")
    assert len(strip_control_sequences(lines[4])) <= 41


def test_approval_surface_applies_semantic_theme_tokens() -> None:
    surface = ApprovalSurface(
        action="rm -rf -- /tmp/build",
        risk="Filesystem content would be deleted",
        theme=ThemeResolver(
            defaults={
                "approval.action.label": {"color": "yellow"},
                "approval.action": {"color": "white"},
                "approval.risk.label": {"color": "bright_red", "bold": True},
                "approval.risk": {"color": "red"},
                "approval.choice.allow": {"color": "green"},
                "approval.choice.deny": {"color": "red"},
                "approval.choice.selected": {"reverse": True, "bold": True},
            }
        ),
    )

    raw = rendered_text(surface, width=64, height=10)

    assert tuple(strip_control_sequences(line) for line in raw)[0:5] == (
        "Action",
        "  rm -rf -- /tmp/build",
        "",
        "Risk",
        "  Filesystem content would be deleted",
    )
    assert raw[0].startswith("\x1b[33mAction")
    assert raw[3].startswith("\x1b[1;91mRisk")
    assert "\x1b[1;7;32m› 1." in raw[6]
    assert raw[7].startswith("\x1b[31m  2. Deny")


def test_approval_primary_text_uses_terminal_adaptive_foreground() -> None:
    surface = ApprovalSurface(
        action="rm -r /tmp/approval-test",
        theme=ThemeResolver(
            defaults={
                "approval.action.label": {"bold": True},
                "approval.action": {"color": "default", "bold": True},
            }
        ),
    )

    raw = rendered_text(surface, width=64, height=6)

    assert raw[0].startswith("\x1b[1mAction")
    assert raw[1].startswith("\x1b[1;39m  rm -r /tmp/approval-test")
    assert "\x1b[93m" not in "".join(raw)
    assert "\x1b[97m" not in "".join(raw)


def test_approval_surface_handle_input_carries_action_id() -> None:
    surface = ApprovalSurface(action="Delete cache", action_id="cache:delete")

    assert surface.handle_input(InputEvent(kind="key", key="y")) == InputIntent(
        kind="approval_decision", text="allow_once", note="cache:delete"
    )
    assert surface.handle_input(InputEvent(kind="key", key="n")) == InputIntent(
        kind="approval_decision", text="deny", note="cache:delete"
    )
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="approval_decision", text="abort", note="cache:delete"
    )


def test_approval_surface_no_action_id_keeps_empty_note() -> None:
    surface = ApprovalSurface(action="Delete cache")

    assert surface.handle_input(InputEvent(kind="key", key="y")) == InputIntent(
        kind="approval_decision", text="allow_once", note=""
    )
    assert surface.handle_input(InputEvent(kind="key", key="n")) == InputIntent(
        kind="approval_decision", text="deny", note=""
    )
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="approval_decision", text="abort", note=""
    )


def test_dialog_surface_returns_confirm_cancel_and_escape_close_reasons() -> None:
    surface = DialogSurface(title="Switch model?", message="Unsaved draft remains")

    assert rendered_text(surface, width=40, height=4) == (
        "Switch model?",
        "Unsaved draft remains",
        "[enter] confirm  [esc] cancel",
    )
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="dialog_confirm"
    )
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="dialog_cancel"
    )
