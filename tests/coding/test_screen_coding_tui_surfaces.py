from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace

from loushang.ai import Model
from loushang.ai.model import ModelSelection
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.harness.multiagent import (
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    HostCaller,
    MultiAgentControl,
)
from loushang.harnesstui.conversation.fork import ForkPromptSurface
from loushang.harnesstui.multiagent import AgentTreeSurface
from loushang.harnesstui.selection.model import (
    ModelSelectorSurface as SharedModelSelectorSurface,
)
from loushang.harnesstui.status.provider import StatusProvider
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    ApprovalSurface,
    CommandSurface,
    CursorDeclaration,
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SurfaceHost,
)
from loushang.tui.cell_width import strip_control_sequences


class _CursorContent:
    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine("query")],
            constraints=constraints,
            cursor=CursorDeclaration(row=0, column=3),
        )


class _EditorTargetContent(_CursorContent):
    def __init__(self) -> None:
        self.target = object()

    def editor_input_target(self) -> object:
        return self.target


class _EscContent(_CursorContent):
    def handle_input(self, event: InputEvent) -> InputIntent | bool | None:
        if event.kind == "key" and event.key in {"esc", "escape"}:
            return InputIntent(kind="consumed", note="child_escape")
        return None


class _TallContent:
    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine(f"line {index}") for index in range(constraints.max_height)],
            constraints=constraints,
        )


def test_screen_surface_view_delegates_editor_input_target() -> None:
    content = _EditorTargetContent()
    view = ScreenSurfaceView(title="Settings", purpose="settings", content=content)

    assert view.editor_input_target() is content.target


def test_screen_surface_view_preserves_content_cursor_with_offset() -> None:
    view = ScreenSurfaceView(
        title="Settings", purpose="settings", content=_CursorContent(), footer=""
    )

    rendered = view.render(RenderConstraints(width=40, max_height=8))

    assert rendered.cursor == CursorDeclaration(row=2, column=3)


def test_screen_surface_view_delegates_escape_to_non_info_content_first() -> None:
    view = ScreenSurfaceView(
        title="Settings", purpose="settings", content=_EscContent()
    )

    assert view.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="consumed",
        note="child_escape",
    )


def test_screen_app_uses_active_surface_preferred_height_for_bottom_frame() -> None:
    app = _app()
    app.active_surface = ScreenSurfaceView(
        title="Settings",
        purpose="settings",
        content=_TallContent(),
        footer="",
        presentation="bottom-exclusive",
        preferred_height=22,
    )

    rendered = app.render(RenderConstraints(width=80, max_height=30))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert len(plain_lines) == 22
    assert plain_lines[0] == "Settings"
    assert plain_lines[-1] == "line 19"


def test_screen_surface_manager_opens_model_surface_and_selects_model() -> None:
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.title == "Select Model"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.active_surface.exclusive_bottom is True
    assert isinstance(app.active_surface.content, SharedModelSelectorSurface)
    assert app.active_surface.content.max_visible == 10

    rendered = app.active_surface.render(RenderConstraints(width=160, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert plain_lines[:3] == (
        "Select Model",
        "Access legacy models by running loushang --model <provider:model>.",
        "",
    )
    assert plain_lines[3].startswith("> 1. moonshot:test-endpoint:kimi-for-coding")
    assert plain_lines[3].endswith("current")
    assert plain_lines[-1] == "  Press number or enter to confirm or esc to go back"
    assert rendered.lines[3].text.startswith("\x1b[1;38;5;33m> 1.")

    assert app.active_surface.handle_input(InputEvent(kind="key", key="down")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="openai:test-endpoint:gpt-5.4")

    asyncio.run(manager.handle_surface_intent(intent))

    assert session.set_model_calls[-1] == ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert app.active_surface is None
    assert app.state.status_message == "Model set: openai:test-endpoint:gpt-5.4"
    assert app.state.model_label == "openai:test-endpoint:gpt-5.4"


def test_screen_surface_model_selector_displays_endpoint_and_selects_full_identity() -> (
    None
):
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="dashscope", model_id="qwen3.6-plus"
        ),
        ModelSelection(
            endpoint_id="test-endpoint", provider="dashscope", model_id="qwen3.6-plus"
        ),
    ]
    responses_model = Model(
        id="qwen3.6-plus",
        provider="dashscope",
        endpoint="openai-responses",
        name="Qwen 3.6 Plus",
    )
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

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=160, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert "openai-responses" in plain_lines[3]
    assert "openai-completions:cn" in plain_lines[4]
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(
        kind="select", text="dashscope:openai-responses:qwen3.6-plus"
    )

    asyncio.run(manager.handle_surface_intent(intent))

    selection = ModelSelection(
        provider="dashscope",
        model_id="qwen3.6-plus",
        endpoint_id="openai-responses",
    )
    assert session.set_model_calls[-1] == selection
    assert session.default_model_calls[-1] == (selection, "global")
    assert app.active_surface is None
    assert (
        app.state.status_message == "Model set: dashscope:openai-responses:qwen3.6-plus"
    )


def test_screen_surface_model_selector_marks_only_current_endpoint() -> None:
    session = _Session()
    responses_model = Model(
        id="qwen3.6-plus",
        provider="dashscope",
        endpoint="openai-responses",
        name="Qwen 3.6 Plus",
    )
    completions_model = Model(
        id="qwen3.6-plus",
        provider="dashscope",
        endpoint="openai-completions:cn",
        name="Qwen 3.6 Plus",
    )
    session.current_model = completions_model
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="dashscope", model_id="qwen3.6-plus"
        ),
        ModelSelection(
            endpoint_id="test-endpoint", provider="dashscope", model_id="qwen3.6-plus"
        ),
    ]
    session.model_details = [responses_model, completions_model]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=160, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    model_lines = [line for line in plain_lines if "dashscope:" in line]
    current_lines = [line for line in model_lines if "current" in line]
    assert len(current_lines) == 1
    assert current_lines[0].startswith(
        "> 1. dashscope:openai-completions:cn:qwen3.6-plus"
    )
    assert any(
        "dashscope:openai-responses:qwen3.6-plus" in line and "current" not in line
        for line in model_lines
    )


def test_screen_surface_model_selector_uses_agent_model_endpoint_for_current() -> None:
    session = _Session()
    coding_model = Model(
        id="kimi-for-coding",
        provider="moonshot",
        endpoint="coding",
        name="Kimi for Coding",
    )
    anthropic_model = Model(
        id="kimi-for-coding",
        provider="moonshot",
        endpoint="kimi-code-anthropic",
        name="Kimi for Coding",
    )
    session.current_model = ModelSelection(
        endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
    )
    session.agent = SimpleNamespace(model=anthropic_model)
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        ),
        ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        ),
    ]
    session.model_details = [coding_model, anthropic_model]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=160, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    model_lines = [line for line in plain_lines if "moonshot:" in line]
    current_lines = [line for line in model_lines if "current" in line]
    assert len(current_lines) == 1
    assert current_lines[0].startswith(
        "> 1. moonshot:kimi-code-anthropic:kimi-for-coding"
    )
    assert any(
        "moonshot:coding:kimi-for-coding" in line and "current" not in line
        for line in model_lines
    )


def test_screen_surface_model_selection_error_stays_in_tui() -> None:
    session = _FailingModelSession()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(
        kind="select", text="moonshot:test-endpoint:kimi-for-coding"
    )

    asyncio.run(manager.handle_surface_intent(intent))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.state.status_message == "Error: model switch failed"


def test_screen_surface_manager_opens_model_surface_in_bottom_frame_with_runtime_overlay_host() -> (
    None
):
    session = _Session()
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.title == "Select Model"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.surface_host.entries == []

    assert app.active_surface.handle_input(InputEvent(kind="key", key="down")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="openai:test-endpoint:gpt-5.4")

    asyncio.run(manager.handle_surface_intent(intent))

    assert app.active_surface is None
    assert session.set_model_calls[-1] == ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert app.state.model_label == "openai:test-endpoint:gpt-5.4"


def test_screen_surface_manager_opens_non_model_surfaces_in_runtime_overlay_host() -> (
    None
):
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, _Session())

    for command, expected_title in (
        ("/terminal", "Terminal"),
        ("/hotkeys", "Hotkeys"),
    ):
        asyncio.run(manager.handle_text(command))

        assert app.active_surface is None
        view = _only_overlay_view(app)
        assert view.title == expected_title

        manager.close_surface()
        assert app.surface_host.entries == []


def test_screen_surface_manager_opens_resume_as_full_screen_continuity_page() -> None:
    session = _Session()
    runtime = SimpleNamespace(current_session=session)
    app = _app()
    app.surface_host = SurfaceHost()
    manager = ScreenSurfaceManager(
        app=app,
        session=session,
        runtime=runtime,
        status_provider=_status_provider(app),
    )

    assert manager.is_local_command("/resume")
    assert not manager.is_local_command("/resume explicit")
    asyncio.run(manager.handle_text("/resume"))

    assert app.active_surface is None
    assert len(app.surface_host.entries) == 1
    surface = app.surface_host.entries[0].surface
    assert surface.presentation == "page"
    assert isinstance(surface.renderable, ScreenSurfaceView)
    assert surface.renderable.purpose == "session"


def test_screen_surface_manager_opens_live_agent_tree_page() -> None:
    async def scenario() -> None:
        session = _Session()
        control = MultiAgentControl(
            agent_types=AgentTypeRegistry(
                (AgentTypeSpec(name="reviewer", maximum_children=2),)
            )
        )
        session.multiagent_runtime = SimpleNamespace(
            control=control,
            list_agents=lambda *, caller: control.list_agents(caller=caller),
        )
        app = _app()
        manager = _manager(app, session)

        assert manager.is_local_command("/agents")
        await manager.handle_text("/agents")
        await asyncio.sleep(0)

        surface = app.active_surface
        assert isinstance(surface, ScreenSurfaceView)
        assert surface.purpose == "agent_tree"
        assert surface.presentation == "page"
        assert isinstance(surface.content, AgentTreeSurface)

        control.spawn(
            caller=HostCaller(),
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
        )
        plain = _surface_plain_lines(surface)
        assert any("reviewer  idle · reviewer" in line for line in plain)

        manager.close()

    asyncio.run(scenario())


def test_screen_surface_manager_forks_selected_prompt_and_restores_composer() -> None:
    session = _Session()
    session.fork_messages = [
        {"entry_id": "entry-1", "text": "first prompt"},
        {"entry_id": "entry-2", "text": "latest prompt"},
    ]

    class Runtime:
        def __init__(self) -> None:
            self.current_session = session
            self.calls: list[tuple[str, str]] = []

        async def fork_session_operation(self, entry_id: str, *, position: str):
            self.calls.append((entry_id, position))
            return SimpleNamespace(
                cancelled=False,
                current=self.current_session,
                payload="latest prompt",
            )

    async def scenario() -> None:
        runtime = Runtime()
        app = _app()
        app.surface_host = SurfaceHost()
        manager = ScreenSurfaceManager(
            app=app,
            session=session,
            runtime=runtime,
            status_provider=_status_provider(app),
        )

        assert manager.is_local_command("/fork")
        assert not manager.is_local_command("/fork entry-2 before")
        await manager.handle_text("/fork")

        view = _only_overlay_view(app)
        assert view.purpose == "fork"
        assert isinstance(view.content, ForkPromptSurface)
        assert view.content.selected_entry_id == "entry-2"
        intent = view.handle_input(InputEvent(kind="key", key="enter"))
        assert intent == InputIntent(kind="select", text="entry-2")

        await manager.handle_surface_intent(intent)
        task = manager._fork_activation_task
        assert task is not None
        await task

        assert runtime.calls == [("entry-2", "before")]
        assert app.composer.value == "latest prompt"
        assert app.state.status_message == "Forked from selected prompt"
        assert app.surface_host.entries == []

    asyncio.run(scenario())


def test_screen_surface_manager_opens_models_info_in_bottom_frame_with_runtime_overlay_host() -> (
    None
):
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/models"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.title == "Available Models"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.active_surface.exclusive_bottom is True
    assert app.surface_host.entries == []

    rendered = app.active_surface.render(RenderConstraints(width=160, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert plain_lines[0] == "Available Models"
    assert "Available models:" not in plain_lines
    assert any("moonshot:test-endpoint:kimi-for-coding" in line for line in plain_lines)
    assert plain_lines[-1] == "Enter/Esc to close"


def test_screen_surface_models_info_keeps_footer_when_content_overflows() -> None:
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        ),
        *(
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="provider",
                model_id=f"model-{index:02d}",
            )
            for index in range(12)
        ),
    ]
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/models"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=8))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert plain_lines[-2:] == ("", "Up/Down/Page to scroll - Enter/Esc to close")
    assert any("provider:test-endpoint:model-00" in line for line in plain_lines)
    assert not any("provider:test-endpoint:model-08" in line for line in plain_lines)


def test_screen_surface_models_info_scrolls_with_page_keys() -> None:
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        ),
        *(
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="provider",
                model_id=f"model-{index:02d}",
            )
            for index in range(12)
        ),
    ]
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/models"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    before = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=8)
        ).lines
    )
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="pageDown"))
    after = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=8)
        ).lines
    )

    assert intent == InputIntent(kind="consumed", note="info_scroll")
    assert any("provider:test-endpoint:model-00" in line for line in before)
    assert not any("provider:test-endpoint:model-00" in line for line in after)
    assert any("provider:test-endpoint:model-03" in line for line in after)
    assert after[-2:] == ("", "Up/Down/Page to scroll - Enter/Esc to close")


def test_screen_surface_models_info_cursor_stays_on_last_visible_body_line() -> None:
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        ),
        *(
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="provider",
                model_id=f"model-{index:02d}",
            )
            for index in range(12)
        ),
    ]
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/models"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    before = app.active_surface.render(RenderConstraints(width=100, max_height=8))
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="down"))
    after = app.active_surface.render(RenderConstraints(width=100, max_height=8))

    assert intent == InputIntent(kind="consumed", note="info_scroll")
    assert before.cursor is not None
    assert after.cursor is not None
    assert before.cursor.row == 5
    assert after.cursor.row == 5


def test_screen_surface_manager_opens_settings_in_bottom_frame_with_runtime_overlay_host() -> (
    None
):
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.title == "Settings"
    assert app.active_surface.presentation == "bottom-exclusive"
    assert app.surface_host.entries == []

    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=14))
    plain = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert any(
        "Status" in line
        and "Config" in line
        and "Model" in line
        and "Status Line" in line
        for line in plain
    )
    assert any("Search settings" in line for line in plain)
    assert not any("Status line" in line for line in plain[2:])
    assert "Enter/Space to change - Esc to close" not in plain
    assert "  show footer" not in plain


def test_screen_surface_manager_config_alias_opens_settings() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/config"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.title == "Settings"
    plain = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=14)
        ).lines
    )
    assert any("Search settings" in line for line in plain)


def test_screen_surface_manager_settings_page_submit_keeps_surface_open() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))
    assert isinstance(app.active_surface, ScreenSurfaceView)
    _focus_statusline_tab(app.active_surface)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(
        kind="setting", text="statusline.enabled", note="false"
    )
    asyncio.run(manager.handle_surface_intent(intent))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.state.statusline_visible is False
    assert app.state.statusline_settings.enabled is False
    assert manager.status_provider.statusline_settings().enabled is False
    assert app.state.status_message is None
    plain = _surface_plain_lines(app.active_surface)
    assert any("Status line: off" in line for line in plain)


def test_screen_surface_manager_settings_page_submit_mirrors_statusline_settings_into_app() -> (
    None
):
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))
    assert isinstance(app.active_surface, ScreenSurfaceView)
    _focus_statusline_tab(app.active_surface)
    assert (
        app.active_surface.content.handle_input(InputEvent(kind="text", text="style"))
        is True
    )
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="setting", text="statusline.style", note="muted")
    asyncio.run(manager.handle_surface_intent(intent))

    assert app.state.statusline_settings.style == "muted"
    assert manager.status_provider.statusline_settings().style == "muted"
    assert app.state.status_message is None
    plain = _surface_plain_lines(app.active_surface)
    assert any("Status line style: muted" in line for line in plain)


def test_screen_surface_manager_settings_page_statusline_submit_persists_settings(
    tmp_path,
) -> None:
    from loushang.coding.control import SettingsManager

    settings_path = tmp_path / "settings.json"
    settings_manager = SettingsManager(global_settings_path=settings_path)
    app = _app()
    manager = _manager(app, _Session(), settings_manager=settings_manager)

    asyncio.run(manager.handle_text("/settings"))
    assert isinstance(app.active_surface, ScreenSurfaceView)
    _focus_statusline_tab(app.active_surface)
    assert (
        app.active_surface.content.handle_input(InputEvent(kind="text", text="style"))
        is True
    )
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    asyncio.run(manager.handle_surface_intent(intent))

    reloaded = SettingsManager(global_settings_path=settings_path)
    assert settings_manager.get_statusline_settings().style == "muted"
    assert reloaded.get_statusline_settings().style == "muted"
    assert app.state.statusline_settings.style == "muted"


def test_screen_surface_manager_ignores_setting_submit_without_settings_page() -> None:
    app = _app()
    manager = _manager(app, _Session())
    generic_surface = ScreenSurfaceView(
        title="Settings",
        purpose="settings",
        content=_CursorContent(),
        presentation="bottom-exclusive",
    )
    app.active_surface = generic_surface

    asyncio.run(
        manager.handle_surface_intent(
            InputIntent(kind="setting", text="statusline", note="false")
        )
    )

    assert app.active_surface is generic_surface
    assert app.state.statusline_visible is True
    assert app.state.status_message is None


def test_screen_surface_manager_settings_page_model_submit_uses_model_selection() -> (
    None
):
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/settings"))
    asyncio.run(
        manager.handle_surface_intent(
            InputIntent(
                kind="setting",
                text="model.current",
                note="openai:test-endpoint:gpt-5.4",
            )
        )
    )

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert session.set_model_calls
    assert app.state.model_label == "openai:test-endpoint:gpt-5.4"


def test_screen_surface_manager_runtime_overlay_escape_and_close_are_idempotent() -> (
    None
):
    app = _app()
    app.surface_host = SurfaceHost()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/terminal"))
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


def test_screen_surface_manager_opens_terminal_diagnostics_surface() -> None:
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


def test_screen_surface_manager_routes_local_commands_through_command_catalog() -> None:
    from loushang.harness.commands import CommandDef, CommandKind

    class Catalog:
        def __init__(self) -> None:
            self.lookups: list[str] = []

        def lookup(self, text: str) -> CommandDef | None:
            self.lookups.append(text)
            if text == "/terminal":
                return CommandDef(
                    id="coding.ui.terminal",
                    name="terminal",
                    kind=CommandKind.LOCAL_UI,
                    description="Show terminal diagnostics",
                )
            return None

    app = _app()
    app.surface_host = SurfaceHost()
    catalog = Catalog()
    manager = ScreenSurfaceManager(
        app=app,
        session=_Session(),
        status_provider=_status_provider(app),
        command_catalog=catalog,
    )

    assert manager.is_local_command("/terminal") is True
    assert manager.is_local_command("/terminal extra") is False

    asyncio.run(manager.handle_text("/terminal"))

    view = _only_overlay_view(app)
    assert view.title == "Terminal"
    assert catalog.lookups == ["/terminal", "/terminal extra", "/terminal"]


def test_screen_surface_model_selector_filters_by_typed_search() -> None:
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="gpt")) is None
    rendered = app.active_surface.render(RenderConstraints(width=80, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert "Search: gpt" in plain_lines
    assert any(
        line.startswith("> 2. openai:test-endpoint:gpt-5.4") for line in plain_lines
    )
    assert not any(
        "moonshot:test-endpoint:kimi-for-coding" in line for line in plain_lines
    )

    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="select", text="openai:test-endpoint:gpt-5.4")


def test_screen_surface_model_selector_uses_model_detail_descriptions() -> None:
    session = _Session()
    session.model_details = [
        Model(
            id="gpt-5.4",
            provider="openai",
            endpoint="responses",
            name="Strong model for everyday coding.",
        ),
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert any(
        line.startswith("  2. openai:responses:gpt-5.4")
        and line.endswith("Strong model for everyday coding.")
        for line in plain_lines
    )


def test_screen_surface_model_selector_lists_current_model_first() -> None:
    session = _Session()
    session.current_model = ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=160, max_height=10))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert plain_lines[3].startswith("> 1. openai:test-endpoint:gpt-5.4")
    assert plain_lines[3].endswith("current")
    assert any(
        line.startswith("  2. moonshot:test-endpoint:kimi-for-coding")
        for line in plain_lines
    )


def test_screen_surface_model_selector_number_key_selects_current_scope_ordinal() -> (
    None
):
    session = _Session()
    session.models.append(
        ModelSelection(
            endpoint_id="test-endpoint", provider="anthropic", model_id="claude-sonnet"
        )
    )
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="text", text="2"))

    assert intent == InputIntent(kind="select", text="openai:test-endpoint:gpt-5.4")


def test_screen_surface_model_selector_zero_key_selects_tenth_model() -> None:
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="p", model_id=f"model-{index}"
        )
        for index in range(1, 12)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="text", text="0"))

    assert intent == InputIntent(kind="select", text="p:test-endpoint:model-10")


def test_screen_surface_model_selector_multidigit_number_selects_ordinal() -> None:
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="p", model_id=f"model-{index}"
        )
        for index in range(1, 13)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="1")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="text", text="2"))

    assert intent == InputIntent(kind="select", text="p:test-endpoint:model-12")


def test_screen_surface_model_selector_enter_confirms_pending_single_digit_ordinal() -> (
    None
):
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="p", model_id=f"model-{index}"
        )
        for index in range(1, 13)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="1")) is None
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="select", text="p:test-endpoint:model-1")


def test_screen_surface_model_selector_number_key_extends_active_search() -> None:
    session = _Session()
    session.models.append(
        ModelSelection(
            endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4-mini"
        )
    )
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="gpt-")) is None
    assert app.active_surface.handle_input(InputEvent(kind="text", text="5")) is None
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=12))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert "Search: gpt-5" in plain_lines
    assert any("openai:test-endpoint:gpt-5.4" in line for line in plain_lines)


def test_screen_surface_model_selector_home_end_move_selection_before_search_is_visible() -> (
    None
):
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="key", key="end")) is None
    assert app.active_surface.handle_input(
        InputEvent(kind="key", key="enter")
    ) == InputIntent(kind="select", text="openai:test-endpoint:gpt-5.4")


def test_screen_surface_model_selector_switches_between_scoped_and_all_models_with_tab() -> (
    None
):
    session = _Session()
    session.models.append(
        ModelSelection(
            endpoint_id="test-endpoint", provider="anthropic", model_id="claude-sonnet"
        )
    )
    session.scoped_models = [
        {
            "model": ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            )
        },
        {
            "model": {
                "provider": "openai",
                "endpoint_id": "test-endpoint",
                "model_id": "gpt-5.4",
            }
        },
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    scoped_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=160, max_height=12)
        ).lines
    )
    assert "Scope: scoped | all" in scoped_lines
    assert any(
        "moonshot:test-endpoint:kimi-for-coding" in line for line in scoped_lines
    )
    assert any("openai:test-endpoint:gpt-5.4" in line for line in scoped_lines)
    assert not any(
        "anthropic:test-endpoint:claude-sonnet" in line for line in scoped_lines
    )

    assert app.active_surface.handle_input(InputEvent(kind="key", key="tab")) is None
    all_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=12)
        ).lines
    )
    assert "Scope: all | scoped" in all_lines
    assert any("anthropic:test-endpoint:claude-sonnet" in line for line in all_lines)


def test_screen_surface_model_selector_preserves_search_when_scope_changes() -> None:
    session = _Session()
    session.models.extend(
        [
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4-mini"
            ),
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="anthropic",
                model_id="claude-sonnet",
            ),
        ]
    )
    session.scoped_models = [
        {
            "model": ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            )
        },
        {
            "model": {
                "provider": "openai",
                "endpoint_id": "test-endpoint",
                "model_id": "gpt-5.4",
            }
        },
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="text", text="gpt")) is None
    assert app.active_surface.handle_input(InputEvent(kind="key", key="tab")) is None
    all_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=12)
        ).lines
    )
    assert "Search: gpt" in all_lines
    assert any("openai:test-endpoint:gpt-5.4" in line for line in all_lines)
    assert any("openai:test-endpoint:gpt-5.4-mini" in line for line in all_lines)
    assert not any(
        "anthropic:test-endpoint:claude-sonnet" in line for line in all_lines
    )


def test_screen_surface_model_selector_switches_scope_with_left_and_right() -> None:
    session = _Session()
    session.models.append(
        ModelSelection(
            endpoint_id="test-endpoint", provider="anthropic", model_id="claude-sonnet"
        )
    )
    session.scoped_models = [
        {
            "model": ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            )
        },
        {
            "model": {
                "provider": "openai",
                "endpoint_id": "test-endpoint",
                "model_id": "gpt-5.4",
            }
        },
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.handle_input(InputEvent(kind="key", key="right")) is None
    all_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=12)
        ).lines
    )
    assert "Scope: all | scoped" in all_lines
    assert any("anthropic:test-endpoint:claude-sonnet" in line for line in all_lines)

    assert app.active_surface.handle_input(InputEvent(kind="key", key="left")) is None
    scoped_lines = tuple(
        strip_control_sequences(line.text)
        for line in app.active_surface.render(
            RenderConstraints(width=100, max_height=12)
        ).lines
    )
    assert "Scope: scoped | all" in scoped_lines
    assert not any(
        "anthropic:test-endpoint:claude-sonnet" in line for line in scoped_lines
    )


def test_screen_surface_model_selector_aligns_multi_digit_ordinals() -> None:
    session = _Session()
    session.models = [
        ModelSelection(
            endpoint_id="test-endpoint", provider="p", model_id=f"model-{index}"
        )
        for index in range(1, 12)
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/model"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    rendered = app.active_surface.render(RenderConstraints(width=100, max_height=16))
    plain_lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    first_model_line = next(
        line for line in plain_lines if "p:test-endpoint:model-1" in line
    )
    tenth_model_line = next(
        line for line in plain_lines if "p:test-endpoint:model-10" in line
    )
    assert first_model_line.index("p:test-endpoint:model-1") == tenth_model_line.index(
        "p:test-endpoint:model-10"
    )


def test_screen_surface_view_translates_mouse_row_to_selection_content() -> None:
    from loushang.tui import SelectionSurface, SelectItem

    surface = SelectionSurface(
        [
            SelectItem("one"),
            SelectItem("two"),
            SelectItem("three"),
        ],
        max_visible=3,
    )
    view = ScreenSurfaceView(
        title="Models", purpose="model", content=surface, footer="Enter"
    )
    view.render(RenderConstraints(width=40, max_height=8))

    intent = view.handle_input(
        InputEvent(kind="mouse", mouse_button=0, mouse_row=3, mouse_action="press")
    )

    assert intent is None
    assert surface.selected_index == 1
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select", text="two"
    )


def test_screen_surface_manager_applies_settings_page_statusline_change() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    _focus_statusline_tab(app.active_surface)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(
        kind="setting", text="statusline.enabled", note="false"
    )

    asyncio.run(manager.handle_surface_intent(intent))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.state.status_message is None
    assert any(
        "Status line: off" in line for line in _surface_plain_lines(app.active_surface)
    )
    rendered = tuple(
        strip_control_sequences(line.text)
        for line in app.render(RenderConstraints(width=100, max_height=12)).lines
    )
    assert not any(
        "moonshot:test-endpoint:kimi-for-coding | repo | main | abcd | idle" in line
        for line in rendered
    )


def test_screen_surface_manager_command_surface_inserts_selected_command() -> None:
    class AsyncCommandSession(_Session):
        async def list_commands(self) -> list[object]:
            return self.commands

    session = AsyncCommandSession()
    session.commands = [
        SimpleNamespace(name="report", description="Show report", source="core"),
        SimpleNamespace(name="model", description="Switch model", source="core"),
    ]
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/command"))

    assert isinstance(app.active_surface, ScreenSurfaceView)
    assert app.active_surface.title == "Commands"
    assert app.active_surface.purpose == "command"
    assert app.active_surface.footer == "Enter to select - Esc to close"
    assert app.active_surface.presentation == "bottom"
    assert isinstance(app.active_surface.content, CommandSurface)
    assert app.active_surface.content.max_visible == 8
    assert (
        app.active_surface.handle_input(InputEvent(kind="text", text="report")) is None
    )
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))
    assert intent == InputIntent(kind="command", text="/report")

    asyncio.run(manager.handle_surface_intent(intent))

    assert app.active_surface is None
    assert app.composer.value == "/report "


def test_screen_surface_manager_handles_approval_submit() -> None:
    app = _app()
    events: list[dict[str, object]] = []

    async def on_approval(event: dict[str, object]) -> None:
        events.append(event)

    manager = ScreenSurfaceManager(
        app=app,
        session=_Session(),
        status_provider=_status_provider(app),
        on_approval=on_approval,
    )

    app.active_surface = ScreenSurfaceView(
        title="Approval",
        purpose="approval",
        content=ApprovalSurface(action="delete cache", action_id="clear-cache-01"),
        footer="",
    )

    asyncio.run(
        manager.handle_surface_intent(
            InputIntent(kind="approval_decision", text="allow_once")
        )
    )

    assert app.active_surface is None
    assert events == [
        {
            "action_id": "clear-cache-01",
            "action": "delete cache",
            "approved": True,
            "outcome": "allow_once",
            "scope": "once",
            "raw_note": "clear-cache-01",
        }
    ]


def test_screen_surface_manager_dismisses_timeout_and_cancelled_requests() -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    app = _app()
    manager = _manager(app, _Session())
    timeout_resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny"),
        timeout_seconds=0.001,
    )
    opened = asyncio.Event()

    def present(payload: dict[str, object]) -> None:
        action = payload.get("action")
        action_id = payload.get("action_id")
        manager.open_approval(
            action=action if isinstance(action, str) else "Approve",
            action_id=action_id if isinstance(action_id, str) else None,
        )
        opened.set()

    timeout_resolver.set_request_presenter(
        present,
        dismisser=manager.dismiss_approval,
    )
    cancel_resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    cancel_resolver.set_request_presenter(
        present,
        dismisser=manager.dismiss_approval,
    )

    async def run() -> None:
        timeout_decision = await timeout_resolver.resolve(
            ApprovalRequest(
                tool_name="write",
                arguments={},
                action_id="approval-timeout-ui",
            )
        )
        assert timeout_decision.disposition == "deny"
        assert app.active_surface is None

        opened.clear()
        cancelled = asyncio.create_task(
            cancel_resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="approval-cancel-ui",
                )
            )
        )
        await opened.wait()
        assert app.active_surface is not None
        cancelled.cancel()
        with suppress(asyncio.CancelledError):
            await cancelled
        assert app.active_surface is None

    asyncio.run(run())


def test_screen_surface_manager_does_not_confirm_stale_approval_result() -> None:
    app = _app()

    async def reject_stale(event: dict[str, object]) -> bool:
        del event
        return False

    manager = ScreenSurfaceManager(
        app=app,
        session=_Session(),
        status_provider=_status_provider(app),
        on_approval=reject_stale,
    )
    manager.open_approval(action="stale action", action_id="approval-stale")

    asyncio.run(
        manager.handle_surface_intent(
            InputIntent(kind="approval_decision", text="allow_once")
        )
    )

    assert app.state.status_message == "Approval request is no longer pending"


class _Session:
    def __init__(self) -> None:
        self.current_model: object = ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        )
        self.models = [
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
        ]
        self.set_model_calls: list[object] = []
        self.default_model_calls: list[tuple[ModelSelection | None, str]] = []
        self.settings_manager = self
        self.commands: list[object] = []
        self.model_details: list[Model] = []
        self.scoped_models: list[object] = []
        self.fork_messages: list[dict[str, str]] = []

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

    def set_default_model(
        self,
        selection: ModelSelection | None,
        *,
        scope: str = "session",
    ) -> None:
        self.default_model_calls.append((selection, scope))

    def list_commands(self) -> list[object]:
        return self.commands

    def get_user_messages_for_forking(self) -> list[dict[str, str]]:
        return list(self.fork_messages)


class _FailingModelSession(_Session):
    async def set_model(self, selection: object) -> None:
        raise ValueError("model switch failed")


def _app() -> ScreenCodingTuiApp:
    return ScreenCodingTuiApp(
        model_label="moonshot:test-endpoint:kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )


def _manager(
    app: ScreenCodingTuiApp,
    session: _Session,
    *,
    settings_manager: object | None = None,
) -> ScreenSurfaceManager:
    return ScreenSurfaceManager(
        app=app,
        session=session,
        status_provider=_status_provider(app, settings_manager=settings_manager),
    )


def _surface_plain_lines(
    surface: ScreenSurfaceView, *, width: int = 100, height: int = 24
) -> tuple[str, ...]:
    rendered = surface.render(RenderConstraints(width=width, max_height=height))
    return tuple(strip_control_sequences(line.text) for line in rendered.lines)


def _status_provider(
    app: ScreenCodingTuiApp,
    *,
    settings_manager: object | None = None,
) -> StatusProvider:
    from loushang.harnesstui.status.line import (
        status_line_settings_from_control,
        status_line_settings_to_patch,
    )

    statusline_settings = None
    on_statusline_settings_changed = None
    if settings_manager is not None:
        statusline_settings = status_line_settings_from_control(
            settings_manager.get_statusline_settings()
        )

        def on_statusline_settings_changed(settings) -> None:
            settings_manager.set_statusline_settings(
                status_line_settings_to_patch(settings),
                scope="global",
            )

    return StatusProvider(
        model_label=app.state.model_label,
        cwd=app.state.cwd,
        branch=app.state.branch,
        session_label=lambda: app.state.session_label,
        thinking_level=lambda: None,
        running=lambda: app.state.running,
        statusline_settings=statusline_settings,
        on_statusline_settings_changed=on_statusline_settings_changed,
    )


def _focus_statusline_tab(view: ScreenSurfaceView) -> None:
    assert view.content.handle_input(InputEvent(kind="key", key="up")) is True
    assert view.content.handle_input(InputEvent(kind="key", key="right")) is not None
    assert view.content.handle_input(InputEvent(kind="key", key="right")) is not None
    assert view.content.handle_input(InputEvent(kind="key", key="down")) is True


def _only_overlay_view(app: ScreenCodingTuiApp) -> ScreenSurfaceView:
    assert app.surface_host is not None
    assert len(app.surface_host.entries) == 1
    view = app.surface_host.entries[0].surface.renderable
    assert isinstance(view, ScreenSurfaceView)
    return view
