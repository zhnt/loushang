from __future__ import annotations

import asyncio
from io import StringIO
from types import SimpleNamespace

from loushang.ai import Model
from loushang.ai.model import ModelSelection


class _TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _runtime_for(session: object) -> object:
    return SimpleNamespace(
        get_current_session=lambda: session,
        current_session=session,
    )


class _Session:
    def __init__(self) -> None:
        self.session_id = "254d6156"
        self.session_name = "254d6156"
        self.session_manager = SimpleNamespace(
            get_cwd=lambda: "/repo",
            get_branch=lambda: [],
        )
        self.settings_manager = None
        self.current_model: object = ModelSelection(
            endpoint_id="test-endpoint", provider="unknown", model_id="unknown"
        )
        self.model_details = [
            Model(
                id="kimi-for-coding",
                provider="moonshot",
                endpoint="kimi-code-anthropic",
            )
        ]
        self.set_model_calls: list[object] = []
        self.prompts: list[str] = []
        self.follow_ups: list[str] = []
        self.steers: list[str] = []
        self.listeners: list[object] = []
        self.unsubscribed = False
        self.session_control = self

    def get_tool_definition(self, _tool_name: str) -> None:
        return None

    def get_steering_messages(self) -> list[str]:
        return []

    def get_follow_up_messages(self) -> list[str]:
        return []

    def get_model_selection(self) -> object:
        return self.current_model

    def get_available_model_details(self) -> list[Model]:
        return self.model_details

    def get_available_models(self) -> list[ModelSelection]:
        return [
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
        ]

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        if isinstance(selection, Model):
            self.current_model = ModelSelection(
                endpoint_id="test-endpoint",
                provider=selection.provider_id,
                model_id=selection.id,
            )
        else:
            self.current_model = selection

    def subscribe(self, listener):
        self.listeners.append(listener)

        def unsubscribe() -> None:
            self.unsubscribed = True
            if listener in self.listeners:
                self.listeners.remove(listener)

        return unsubscribe

    async def prompt(
        self,
        text: str,
        *,
        streaming_behavior: str | None = None,
        source: str | None = None,
    ) -> None:
        del streaming_behavior, source
        self.prompts.append(text)

    def steer(self, text: str, *, images=None) -> None:
        del images
        self.steers.append(text)

    def follow_up(self, text: str, *, images=None) -> None:
        del images
        self.follow_ups.append(text)

    async def wait_for_idle(self) -> None:
        return None

    def clear_queue(self) -> None:
        return None

    def abort_bash(self) -> None:
        return None


def test_run_coding_tui_uses_screen_loop_for_interactive_terminal(monkeypatch) -> None:
    from dataclasses import replace

    from loushang.coding.ui import mode
    from loushang.coding.ui.screen_input import CODING_SCREEN_RUN_PROFILE

    session = _Session()
    captured: dict[str, object] = {}
    custom_profile = replace(
        CODING_SCREEN_RUN_PROFILE,
        interruption_message="Plugin interrupted",
        cancellation_message="Plugin cancelled",
    )

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        return 0

    async def fail_prompt_loop(**_kwargs):
        raise AssertionError(
            "interactive mode should not use non-interactive prompt loop"
        )

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)
    monkeypatch.setattr(mode, "run_non_interactive_prompt_loop", fail_prompt_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
            screen_run_profile=custom_profile,
        )
    )

    assert exit_code == 0
    assert captured["app"].__class__.__name__ == "ScreenCodingTuiApp"
    assert captured["action_host"].__class__.__name__ == (
        "PresentedConversationActionHost"
    )
    assert captured["profile"] is custom_profile
    assert callable(captured["handle_local"])
    assert callable(captured["handle_surface_intent"])


def test_run_coding_tui_non_interactive_keeps_plain_prompt_loop(monkeypatch) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    captured: dict[str, object] = {}

    async def fail_screen_loop(**_kwargs):
        raise AssertionError(
            "non-interactive mode should not enter screen terminal loop"
        )

    async def fake_prompt_loop(**kwargs):
        captured.update(kwargs)
        await kwargs["handle_prompt"]("hello")
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fail_screen_loop)
    monkeypatch.setattr(mode, "run_non_interactive_prompt_loop", fake_prompt_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=_runtime_for(session),
            session=session,
            stdin=StringIO("hello\n"),
            stdout=StringIO(),
            stderr=StringIO(),
        )
    )

    assert exit_code == 0
    assert session.prompts == ["hello"]
    assert set(captured) == {"stdin", "stdout", "handle_prompt"}


def test_run_coding_tui_handles_startup_error(monkeypatch) -> None:
    from loushang.coding.ui import mode

    async def fail_startup(**_kwargs):
        raise RuntimeError("startup exploded")

    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(mode, "load_coding_tui_startup_view", fail_startup)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=_Session(),
            stdin=_TTYStringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )

    assert exit_code == 1
    assert "■ Error: startup exploded" in stdout.getvalue()
    assert stderr.getvalue() == ""
