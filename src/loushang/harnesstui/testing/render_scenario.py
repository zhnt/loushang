from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

from loushang.harnesstui.testing.ports import (
    ConversationPlaybackAppFactoryPort,
    ConversationPlaybackAppPort,
)
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.playback import PlaybackStep
from loushang.tui.render_loop import RenderLoop, ScreenRoot
from loushang.tui.runtime import TuiRuntime
from loushang.tui.terminal import FakeTerminalPort, TerminalOperation, TerminalSize

AppT = TypeVar("AppT", bound=ConversationPlaybackAppPort)


@dataclass(slots=True)
class ConversationRenderScenario(Generic[AppT]):
    """Render one conversation app against a deterministic terminal and clock."""

    app_factory: ConversationPlaybackAppFactoryPort[AppT]
    width: int = 80
    height: int = 24
    now: float = 0.0
    app: AppT = field(init=False)
    port: FakeTerminalPort = field(init=False)
    runtime: TuiRuntime = field(init=False)

    def __post_init__(self) -> None:
        self.app = self.app_factory(now=lambda: self.now)
        self.port = FakeTerminalPort(
            size=TerminalSize(columns=self.width, rows=self.height)
        )
        self.runtime = TuiRuntime(
            render_loop=RenderLoop(cast(ScreenRoot, self.app)),
            terminal=self.port,
        )

    def render(self) -> PlaybackStep:
        return self.runtime.render_now()

    def type_text(self, text: str) -> ConversationRenderScenario[AppT]:
        self.app.composer.set_text(text)
        return self

    def advance_time(self, seconds: float) -> ConversationRenderScenario[AppT]:
        self.now += max(0.0, seconds)
        return self

    def visible_text(self) -> str:
        return strip_control_sequences("\n".join(self.port.screen.visible_lines))

    def assert_visible_contains(self, text: str) -> None:
        assert text in self.visible_text()

    def assert_visible_not_contains(self, text: str) -> None:
        assert text not in self.visible_text()

    def assert_operation_class(self, step: PlaybackStep, expected: str) -> None:
        step.assert_operation_class(expected)

    def assert_no_clear(self, step: PlaybackStep) -> None:
        step.assert_no_clear_scrollback()
        assert TerminalOperation.clear_screen() not in step.diagnostics.operations

    def assert_cursor_matches_diagnostics(self, step: PlaybackStep) -> None:
        assert step.frame is not None
        assert (
            step.frame.screen_after.cursor_row
            == step.diagnostics.hardware_cursor_row
        )
        assert (
            step.frame.screen_after.cursor_column
            == step.diagnostics.hardware_cursor_column
        )


__all__ = ["ConversationRenderScenario"]
