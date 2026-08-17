from __future__ import annotations

from dataclasses import dataclass, field

from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.testing.render_scenario import ConversationRenderScenario
from loushang.tui.core import CURSOR_MARKER, RenderConstraints, RenderResult
from loushang.tui.framework import SurfaceHost
from loushang.tui.ui_parts.composer import Composer


@dataclass(slots=True)
class _RenderApp:
    now: object
    composer: Composer = field(default_factory=Composer)
    state: ScreenConversationState = field(default_factory=ScreenConversationState)
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None

    def open_transcript_reader(self) -> bool:
        return False

    def start_prompt(self, text: str) -> None:
        self.state.start_prompt(text, started_at=1.0)

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_text(
            f"› {self.composer.value}{CURSOR_MARKER}",
            constraints=constraints,
        )


def test_render_scenario_owns_shared_terminal_and_clock_fixture() -> None:
    scenario = ConversationRenderScenario(
        app_factory=lambda *, now: _RenderApp(now=now),
        width=40,
        height=8,
        now=3.0,
    )

    first = scenario.type_text("hello").render()
    scenario.advance_time(2.0)
    second = scenario.render()

    scenario.assert_visible_contains("hello")
    scenario.assert_cursor_matches_diagnostics(second)
    scenario.assert_no_clear(second)
    assert scenario.app.now() == 5.0
    assert first.frame is not None
