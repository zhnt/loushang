from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.ai import Model
from loushang.coding.types import ModelSelection
from loushang.coding.ui.native_app import NativeCodingTuiApp
from loushang.coding.ui.native_surfaces import NativeSurfaceManager, NativeSurfaceView
from loushang.coding.ui.status_provider import CodingTuiStatusProvider
from loushang.tui import (
    ApprovalSurface,
    DialogSurface,
    InputEvent,
    InputIntent,
    RenderConstraints,
    SurfaceHost,
)
from loushang.tui.cell_width import strip_control_sequences


def test_native_surface_manager_opens_model_surface_and_selects_model() -> None:
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.title == "Select Model"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.active_surface.exclusive_bottom is True

    rendered = app.active_surface.render(RenderConstraints(width=80, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert plain_lines[:3] == (
        "Select Model",
        "Access legacy models by running loushang --model <provider/model>.",
        "",
    )
    assert plain_lines[3].startswith("> 1. moonshot/kimi-for-coding")
    assert plain_lines[3].endswith("current")
    assert plain_lines[-1] == "  Press number or enter to confirm or esc to go back"
    assert rendered.lines[3].text.startswith("\x1b[1;38;5;33m> 1.")

    assert app.active_surface.handle_input(InputEvent(kind="key", key="down")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="openai/gpt-5.4")

    asyncio.run(manager.handle_surface_intent(intent))

    assert session.set_model_calls[-1] == ModelSelection(provider="openai", model_id="gpt-5.4")
    assert app.active_surface is None
    assert app.state.status_message == "Model set: openai/gpt-5.4"
    assert app.state.model_label == "openai/gpt-5.4"


def test_native_surface_model_selector_displays_endpoint_and_selects_full_identity() -> None:
    session = _Session()
    session.models = [
        ModelSelection(provider="dashscope", model_id="qwen3.6-plus"),
        ModelSelection(provider="dashscope", model_id="qwen3.6-plus"),
    ]
    responses_model = Model(id="qwen3.6-plus", provider="dashscope", endpoint="openai-responses", name="Qwen 3.6 Plus")
    completions_model = Model(
        id="qwen3.6-plus",
        provider="dashscope",
        endpoint="openai-completions:cn",
        name="Qwen 3.6 Plus",
    )
    session.model_details = [responses_model, completions_model]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=96, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert "openai-responses" in plain_lines[3]
    assert "openai-completions:cn" in plain_lines[4]
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="dashscope:openai-responses:qwen3.6-plus")

    asyncio.run(manager.handle_surface_intent(intent))

    assert session.set_model_calls[-1] is responses_model
    assert app.active_surface is None
    assert app.state.status_message == "Model set: dashscope/qwen3.6-plus (endpoint: openai-responses)"


def test_native_surface_model_selector_marks_only_current_endpoint() -> None:
    session = _Session()
    responses_model = Model(id="qwen3.6-plus", provider="dashscope", endpoint="openai-responses", name="Qwen 3.6 Plus")
    completions_model = Model(
        id="qwen3.6-plus",
        provider="dashscope",
        endpoint="openai-completions:cn",
        name="Qwen 3.6 Plus",
    )
    session.current_model = completions_model
    session.models = [
        ModelSelection(provider="dashscope", model_id="qwen3.6-plus"),
        ModelSelection(provider="dashscope", model_id="qwen3.6-plus"),
    ]
    session.model_details = [responses_model, completions_model]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    model_lines = [line for line in plain_lines if "dashscope/qwen3.6-plus" in line]
    current_lines = [line for line in model_lines if "current" in line]
    assert len(current_lines) == 1
    assert current_lines[0].startswith("> 1. dashscope/qwen3.6-plus")
    assert "endpoint: openai-completions:cn" in current_lines[0]
    assert any("endpoint: openai-responses" in line and "current" not in line for line in model_lines)


def test_native_surface_model_selector_uses_agent_model_endpoint_for_current() -> None:
    session = _Session()
    coding_model = Model(id="kimi-for-coding", provider="moonshot", endpoint="coding", name="Kimi for Coding")
    anthropic_model = Model(id="kimi-for-coding", provider="moonshot", endpoint="kimi-code-anthropic", name="Kimi for Coding")
    session.current_model = ModelSelection(provider="moonshot", model_id="kimi-for-coding")
    session.agent = SimpleNamespace(model=anthropic_model)
    session.models = [
        ModelSelection(provider="moonshot", model_id="kimi-for-coding"),
        ModelSelection(provider="moonshot", model_id="kimi-for-coding"),
    ]
    session.model_details = [coding_model, anthropic_model]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    model_lines = [line for line in plain_lines if "moonshot/kimi-for-coding" in line]
    current_lines = [line for line in model_lines if "current" in line]
    assert len(current_lines) == 1
    assert current_lines[0].startswith("> 1. moonshot/kimi-for-coding")
    assert "endpoint: kimi-code-anthropic" in current_lines[0]
    assert any("endpoint: coding" in line and "current" not in line for line in model_lines)


def test_native_surface_model_selection_error_stays_in_tui() -> None:
    session = _FailingModelSession()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="moonshot/kimi-for-coding")

    asyncio.run(manager.handle_surface_intent(intent))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.state.status_message == "Error: model switch failed"


def test_native_surface_manager_opens_model_surface_in_bottom_frame_with_runtime_overlay_host() -> None:
    session = _Session()
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.title == "Select Model"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.surface_host.entries == []

    assert app.active_surface.handle_input(InputEvent(kind="key", key="down")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="openai/gpt-5.4")

    asyncio.run(manager.handle_surface_intent(intent))

    assert app.active_surface is None
    assert session.set_model_calls[-1] == ModelSelection(provider="openai", model_id="gpt-5.4")
    assert app.state.model_label == "openai/gpt-5.4"


def test_native_surface_manager_opens_non_model_surfaces_in_runtime_overlay_host() -> None:
    session = _Session()
    session.commands = [SimpleNamespace(name="status", description="Show status", source="core")]
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, session)

    for command, expected_title in (
        ("/status", "Status"),
        ("/command", "Commands"),
    ):
        asyncio.run(manager.handle_text(command))

        assert app.active_surface is None
        view = _only_overlay_view(app)
        assert view.title == expected_title

        manager.close_surface()
        assert app.surface_host.entries == []


def test_native_surface_manager_opens_settings_in_bottom_frame_with_runtime_overlay_host() -> None:
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.title == "Settings"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.surface_host.entries == []

    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=10))
    plain = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert plain.count("  Enter/Space to change - Esc to cancel") == 1
    assert "Enter/Space to change - Esc to close" not in plain
    assert "  show footer" not in plain


def test_native_surface_manager_runtime_overlay_escape_and_close_are_idempotent() -> None:
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/status"))
    assert len(app.surface_host.entries) == 1

    intents = app.surface_host.route_input(
        InputEvent(kind="key", key="escape"),
        close_on_intents=("surface_close", "dialog_cancel"),
    )

    assert intents == (InputIntent(kind="surface_close"),)
    assert app.surface_host.entries == []

    asyncio.run(manager.handle_surface_intent(intents[0]))
    manager.close_surface()

    assert app.active_surface is None
    assert app.surface_host.entries == []


def test_native_surface_manager_opens_terminal_diagnostics_surface() -> None:
    app = _app()
    app.surface_host = SurfaceHost()
    app.terminal_diagnostics_provider = lambda: (
        "keyboard_protocol_state: kitty\n"
        "image_protocol: kitty\n"
        "cell_size: 9x18\n"
        "multiplexer: false"
    )
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/terminal"))

    view = _only_overlay_view(app)
    rendered = view.render(RenderConstraints(width=80, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert view.title == "Terminal"
    assert "keyboard_protocol_state: kitty" in plain_lines
    assert "image_protocol: kitty" in plain_lines
    assert "cell_size: 9x18" in plain_lines


def test_native_surface_manager_routes_local_commands_through_command_catalog() -> None:
    from loushang.runtime.commands import CommandDef, CommandKind

    class Catalog:
        def __init__(self) -> None:
            self.lookups: list[str] = []

        def lookup(self, text: str) -> CommandDef | None:
            self.lookups.append(text)
            if text == "/status":
                return CommandDef(
                    id="coding.ui.status",
                    name="status",
                    kind=CommandKind.LOCAL_UI,
                    description="Show current status",
                )
            return None

    app = _app()
    app.surface_host = SurfaceHost()
    catalog = Catalog()
    manager = NativeSurfaceManager(
        app=app,
        session=_Session(),
        status_provider=_status_provider(app),
        command_catalog=catalog,
    )

    assert manager.is_local_command("/status") is True
    assert manager.is_local_command("/status extra") is False

    asyncio.run(manager.handle_text("/status"))

    view = _only_overlay_view(app)
    assert view.title == "Status"
    assert catalog.lookups == ["/status", "/status extra", "/status"]


def test_native_surface_model_selector_filters_by_typed_search() -> None:
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="gpt")) is None
    rendered = app.active_surface.render(RenderConstraints(width=80, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert "Search: gpt" in plain_lines
    assert any(line.startswith("> 2. openai/gpt-5.4") for line in plain_lines)
    assert not any("moonshot/kimi-for-coding" in line for line in plain_lines)

    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="openai/gpt-5.4")


def test_native_surface_model_selector_uses_model_detail_descriptions() -> None:
    session = _Session()
    session.model_details = [
        Model(id="gpt-5.4", provider="openai", endpoint="responses", name="Strong model for everyday coding."),
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert any(
        line.startswith("  2. openai/gpt-5.4") and line.endswith("Strong model for everyday coding.")
        for line in plain_lines
    )


def test_native_surface_model_selector_lists_current_model_first() -> None:
    session = _Session()
    session.current_model = ModelSelection(provider="openai", model_id="gpt-5.4")
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert plain_lines[3].startswith("> 1. openai/gpt-5.4")
    assert plain_lines[3].endswith("current")
    assert any(line.startswith("  2. moonshot/kimi-for-coding") for line in plain_lines)


def test_native_surface_model_selector_number_key_selects_current_scope_ordinal() -> None:
    session = _Session()
    session.models.append(ModelSelection(provider="anthropic", model_id="claude-sonnet"))
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="text", text="2"))

    assert intent == InputIntent(kind="select", text="openai/gpt-5.4")


def test_native_surface_model_selector_zero_key_selects_tenth_model() -> None:
    session = _Session()
    session.models = [
        ModelSelection(provider="p", model_id=f"model-{index}")
        for index in range(1, 12)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="text", text="0"))

    assert intent == InputIntent(kind="select", text="p/model-10")


def test_native_surface_model_selector_multidigit_number_selects_ordinal() -> None:
    session = _Session()
    session.models = [
        ModelSelection(provider="p", model_id=f"model-{index}")
        for index in range(1, 13)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="1")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="text", text="2"))

    assert intent == InputIntent(kind="select", text="p/model-12")


def test_native_surface_model_selector_enter_confirms_pending_single_digit_ordinal() -> None:
    session = _Session()
    session.models = [
        ModelSelection(provider="p", model_id=f"model-{index}")
        for index in range(1, 13)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="1")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="select", text="p/model-1")


def test_native_surface_model_selector_number_key_extends_active_search() -> None:
    session = _Session()
    session.models.append(ModelSelection(provider="openai", model_id="gpt-5.4-mini"))
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="gpt-")) is None
    assert app.active_surface.handle_input(InputEvent(kind="text", text="5")) is None
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=12))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert "Search: gpt-5" in plain_lines
    assert any("openai/gpt-5.4" in line for line in plain_lines)


def test_native_surface_model_selector_home_end_move_selection_before_search_is_visible() -> None:
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="key", key="end")) is None
    assert app.active_surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="select", text="openai/gpt-5.4")


def test_native_surface_model_selector_switches_between_scoped_and_all_models_with_tab() -> None:
    session = _Session()
    session.models.append(ModelSelection(provider="anthropic", model_id="claude-sonnet"))
    session.scoped_models = [
        {"model": ModelSelection(provider="moonshot", model_id="kimi-for-coding")},
        {"model": {"provider": "openai", "model_id": "gpt-5.4"}},
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    scoped_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(RenderConstraints(width=100, max_height=12)).lines
    )
    assert "Scope: scoped | all" in scoped_lines
    assert any("moonshot/kimi-for-coding" in line for line in scoped_lines)
    assert any("openai/gpt-5.4" in line for line in scoped_lines)
    assert not any("anthropic/claude-sonnet" in line for line in scoped_lines)

    assert app.active_surface.handle_input(InputEvent(kind="key", key="tab")) is None
    all_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(RenderConstraints(width=100, max_height=12)).lines
    )
    assert "Scope: all | scoped" in all_lines
    assert any("anthropic/claude-sonnet" in line for line in all_lines)


def test_native_surface_model_selector_preserves_search_when_scope_changes() -> None:
    session = _Session()
    session.models.extend(
        [
            ModelSelection(provider="openai", model_id="gpt-5.4-mini"),
            ModelSelection(provider="anthropic", model_id="claude-sonnet"),
        ]
    )
    session.scoped_models = [
        {"model": ModelSelection(provider="moonshot", model_id="kimi-for-coding")},
        {"model": {"provider": "openai", "model_id": "gpt-5.4"}},
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="gpt")) is None
    assert app.active_surface.handle_input(InputEvent(kind="key", key="tab")) is None
    all_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(RenderConstraints(width=100, max_height=12)).lines
    )
    assert "Search: gpt" in all_lines
    assert any("openai/gpt-5.4" in line for line in all_lines)
    assert any("openai/gpt-5.4-mini" in line for line in all_lines)
    assert not any("anthropic/claude-sonnet" in line for line in all_lines)


def test_native_surface_model_selector_switches_scope_with_left_and_right() -> None:
    session = _Session()
    session.models.append(ModelSelection(provider="anthropic", model_id="claude-sonnet"))
    session.scoped_models = [
        {"model": ModelSelection(provider="moonshot", model_id="kimi-for-coding")},
        {"model": {"provider": "openai", "model_id": "gpt-5.4"}},
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="key", key="right")) is None
    all_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(RenderConstraints(width=100, max_height=12)).lines
    )
    assert "Scope: all | scoped" in all_lines
    assert any("anthropic/claude-sonnet" in line for line in all_lines)

    assert app.active_surface.handle_input(InputEvent(kind="key", key="left")) is None
    scoped_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(RenderConstraints(width=100, max_height=12)).lines
    )
    assert "Scope: scoped | all" in scoped_lines
    assert not any("anthropic/claude-sonnet" in line for line in scoped_lines)


def test_native_surface_model_selector_aligns_multi_digit_ordinals() -> None:
    session = _Session()
    session.models = [
        ModelSelection(provider="p", model_id=f"model-{index}")
        for index in range(1, 12)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=16))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    first_model_line = next(line for line in plain_lines if "p/model-1" in line)
    tenth_model_line = next(line for line in plain_lines if "p/model-10" in line)
    assert first_model_line.index("p/model-1") == tenth_model_line.index("p/model-10")


def test_native_surface_view_translates_mouse_row_to_selection_content() -> None:
    from loushang.tui import SelectionSurface, SelectItem

    surface = SelectionSurface(
        [
            SelectItem("one"),
            SelectItem("two"),
            SelectItem("three"),
        ],
        max_visible=3,
    )
    view = NativeSurfaceView(title="Models", purpose="model", content=surface, footer="Enter")
    view.render(RenderConstraints(width=40, max_height=8))

    intent = view.handle_input(InputEvent(kind="mouse", mouse_button=0, mouse_row=3, mouse_action="press"))

    assert intent is None
    assert surface.selected_index == 1
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="select", text="two")


def test_native_surface_manager_opens_status_info_and_closes_with_escape() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/status"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=80, max_height=8))
    assert "Status" in rendered.lines[0].text
    assert any("moonshot/kimi-for-coding" in line.text for line in rendered.lines)

    intent = app.active_surface.handle_input(InputEvent(kind="key", key="escape"))
    assert intent == InputIntent(kind="surface_close")
    asyncio.run(manager.handle_surface_intent(intent))

    assert app.active_surface is None


def test_native_surface_manager_applies_settings_surface() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="setting", text="statusline", note="true")

    asyncio.run(manager.handle_surface_intent(intent))

    assert app.active_surface is None
    assert app.state.status_message == "Status line: off"
    rendered = tuple(strip_control_sequences(line.text) for line in app.render(RenderConstraints(width=100, max_height=12)).lines)
    assert not any("moonshot/kimi-for-coding | repo | main | abcd | idle" in line for line in rendered)


def test_native_surface_manager_command_surface_inserts_selected_command() -> None:
    session = _Session()
    session.commands = [
        SimpleNamespace(name="status", description="Show status", source="core"),
        SimpleNamespace(name="model", description="Switch model", source="core"),
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/command"))

    assert isinstance(app.active_surface, NativeSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="command", text="/model")

    asyncio.run(manager.handle_surface_intent(intent))

    assert app.active_surface is None
    assert app.composer.value == "/model "


def test_native_surface_manager_handles_dialog_surface_confirm() -> None:
    app = _app()
    manager = _manager(app, _Session())

    app.active_surface = NativeSurfaceView(
        title="Confirm",
        purpose="dialog",
        content=DialogSurface(title="Confirm", message="Proceed?"),
        footer="",
    )

    asyncio.run(manager.handle_surface_intent(InputIntent(kind="dialog_confirm")))

    assert app.active_surface is None


def test_native_surface_manager_handles_approval_submit() -> None:
    app = _app()
    events: list[dict[str, object]] = []

    async def on_approval(event: dict[str, object]) -> None:
        events.append(event)

    manager = NativeSurfaceManager(
        app=app,
        session=_Session(),
        status_provider=_status_provider(app),
        on_approval=on_approval,
    )

    app.active_surface = NativeSurfaceView(
        title="Approval",
        purpose="approval",
        content=ApprovalSurface(action="delete cache", action_id="clear-cache-01"),
        footer="",
    )

    asyncio.run(manager.handle_surface_intent(InputIntent(kind="approve")))

    assert app.active_surface is None
    assert events == [
        {
            "action_id": "clear-cache-01",
            "action": "delete cache",
            "approved": True,
            "raw_note": "clear-cache-01",
        }
    ]


def test_native_surface_manager_handles_approval_reject() -> None:
    app = _app()
    events: list[dict[str, object]] = []

    async def on_approval(event: dict[str, object]) -> None:
        events.append(event)

    manager = NativeSurfaceManager(
        app=app,
        session=_Session(),
        status_provider=_status_provider(app),
        on_approval=on_approval,
    )

    app.active_surface = NativeSurfaceView(
        title="Approval",
        purpose="approval",
        content=ApprovalSurface(action="delete cache", action_id="clear-cache-01"),
        footer="",
    )

    asyncio.run(manager.handle_surface_intent(InputIntent(kind="reject")))

    assert app.active_surface is None
    assert events == [
        {
            "action_id": "clear-cache-01",
            "action": "delete cache",
            "approved": False,
            "raw_note": "clear-cache-01",
        }
    ]


def test_native_surface_manager_ignores_unmapped_surface_intent() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/status"))
    surface = app.active_surface
    assert surface is not None

    asyncio.run(manager.handle_surface_intent(InputIntent(kind="abort")))

    assert app.active_surface is surface


class _Session:
    def __init__(self) -> None:
        self.current_model: object = ModelSelection(provider="moonshot", model_id="kimi-for-coding")
        self.models = [
            ModelSelection(provider="moonshot", model_id="kimi-for-coding"),
            ModelSelection(provider="openai", model_id="gpt-5.4"),
        ]
        self.set_model_calls: list[object] = []
        self.commands: list[object] = []
        self.model_details: list[Model] = []
        self.scoped_models: list[object] = []

    def get_model_selection(self) -> object:
        return self.current_model

    def get_available_models(self) -> list[ModelSelection]:
        return self.models

    def get_available_model_details(self) -> list[Model]:
        return self.model_details

    @property
    def scopedModels(self) -> list[object]:
        return self.scoped_models

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        self.current_model = selection

    def list_commands(self) -> list[object]:
        return self.commands


class _FailingModelSession(_Session):
    async def set_model(self, selection: object) -> None:
        raise ValueError("model switch failed")


def _app() -> NativeCodingTuiApp:
    return NativeCodingTuiApp(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )


def _manager(app: NativeCodingTuiApp, session: _Session) -> NativeSurfaceManager:
    return NativeSurfaceManager(
        app=app,
        session=session,
        status_provider=_status_provider(app),
    )


def _status_provider(app: NativeCodingTuiApp) -> CodingTuiStatusProvider:
    return CodingTuiStatusProvider(
        model_label=app.state.model_label,
        cwd=app.state.cwd,
        branch=app.state.branch,
        session_label=lambda: app.state.session_label,
        thinking_level=lambda: None,
        running=lambda: app.state.running,
    )


def _only_overlay_view(app: NativeCodingTuiApp) -> NativeSurfaceView:
    assert app.surface_host is not None
    assert len(app.surface_host.entries) == 1
    view = app.surface_host.entries[0].surface.renderable
    assert isinstance(view, NativeSurfaceView)
    return view
