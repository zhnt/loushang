from __future__ import annotations

from collections.abc import Callable

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harnesstui.conversation.screen_runner import (
    AbortHandler as ScreenTuiAbortHandler,
)
from loushang.harnesstui.conversation.screen_runner import (
    PromptHandler as ScreenTuiHandler,
)
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlayback,
    ConversationInputPlaybackResult,
    ConversationInputScenario,
)
from loushang.harnesstui.testing.render_scenario import ConversationRenderScenario
from loushang.harnesstui.testing.screen_loop_playback import (
    ConversationScreenLoopArtifacts as ScreenTuiLoopArtifacts,
)
from loushang.harnesstui.testing.screen_loop_playback import (
    ConversationScreenLoopPlayback,
    ConversationScreenLoopPlaybackResult,
    ConversationScreenLoopScenario,
    ScriptedInputChunk,
)
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from tests.coding.tui_support.scenario_binding import (
    CODING_CANCELLATION_MESSAGE,
    CODING_INTERRUPTION_MESSAGE,
    CODING_SCENARIO_FACTORY,
    coding_scenario_input_router_factory,
    run_coding_scenario_screen_loop,
)

ScreenTuiInputPlaybackResult = ConversationInputPlaybackResult[ScreenCodingTuiApp]
ScreenTuiLoopPlaybackResult = ConversationScreenLoopPlaybackResult[ScreenCodingTuiApp]


def _app_factory(
    *,
    model_label: str,
    cwd: str,
    branch: str | None,
    session_label: str,
) -> Callable[..., ScreenCodingTuiApp]:
    def build(*, now: Callable[[], float]) -> ScreenCodingTuiApp:
        return ScreenCodingTuiApp(
            model_label=model_label,
            cwd=cwd,
            branch=branch,
            session_label=session_label,
            now=now,
        )

    return build


class ScreenTuiScenario(ConversationRenderScenario[ScreenCodingTuiApp]):
    def __init__(
        self,
        width: int = 80,
        height: int = 24,
        model_label: str = "kimi",
        cwd: str = "/repo",
        branch: str | None = "main",
        session_label: str = "abcd",
        now: float = 0.0,
    ) -> None:
        super().__init__(
            app_factory=_app_factory(
                model_label=model_label,
                cwd=cwd,
                branch=branch,
                session_label=session_label,
            ),
            width=width,
            height=height,
            now=now,
        )


class ScreenTuiInputPlayback(ConversationInputPlayback[ScreenCodingTuiApp]):
    def __init__(
        self,
        app: ScreenCodingTuiApp,
        *,
        columns: int = 80,
        rows: int = 12,
        should_exit: Callable[[str], bool] | None = None,
        is_local_command: Callable[[str], bool] | None = None,
        keybindings: KeybindingManager | KeybindingConfig | None = None,
    ) -> None:
        super().__init__(
            app,
            columns=columns,
            rows=rows,
            should_exit=should_exit,
            is_local_command=is_local_command,
            keybindings=keybindings,
            input_router_factory=coding_scenario_input_router_factory,
        )


class ScreenTuiInputScenario(ConversationInputScenario[ScreenCodingTuiApp]):
    def __init__(
        self,
        *,
        width: int = 80,
        height: int = 12,
        now: float = 0.0,
    ) -> None:
        self.width = width
        self.height = height
        self.now = now
        super().__init__(
            playback=ScreenTuiInputPlayback(
                CODING_SCENARIO_FACTORY.app_factory(now=lambda: self.now),
                columns=width,
                rows=height,
            )
        )

    def with_local_commands(self, *commands: str) -> ScreenTuiInputScenario:
        command_set = frozenset(commands)
        self.playback = ScreenTuiInputPlayback(
            self.app,
            columns=self.width,
            rows=self.height,
            is_local_command=command_set.__contains__,
        )
        return self


class ScreenTuiLoopPlayback(ConversationScreenLoopPlayback[ScreenCodingTuiApp]):
    def __init__(
        self,
        width: int = 80,
        height: int = 24,
        model_label: str = "kimi",
        cwd: str = "/repo",
        branch: str | None = "main",
        session_label: str = "abcd",
        now: float = 10.0,
    ) -> None:
        super().__init__(
            app_factory=_app_factory(
                model_label=model_label,
                cwd=cwd,
                branch=branch,
                session_label=session_label,
            ),
            interruption_message=CODING_INTERRUPTION_MESSAGE,
            cancellation_message=CODING_CANCELLATION_MESSAGE,
            width=width,
            height=height,
            now=now,
            runner=run_coding_scenario_screen_loop,
            input_router_factory=coding_scenario_input_router_factory,
        )


class ScreenTuiLoopScenario(ConversationScreenLoopScenario[ScreenCodingTuiApp]):
    def __init__(self) -> None:
        super().__init__(playback=ScreenTuiLoopPlayback())


__all__ = [
    "ScreenTuiAbortHandler",
    "ScreenTuiHandler",
    "ScreenTuiInputPlayback",
    "ScreenTuiInputPlaybackResult",
    "ScreenTuiInputScenario",
    "ScreenTuiLoopArtifacts",
    "ScreenTuiLoopPlayback",
    "ScreenTuiLoopPlaybackResult",
    "ScreenTuiLoopScenario",
    "ScreenTuiScenario",
    "ScriptedInputChunk",
]
