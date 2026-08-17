from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlaybackResult,
)
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.tui import SelectionSurface, SelectItem
from loushang.tui.playback_suite import PlaybackScenarioSpec

AppT = TypeVar("AppT", bound=ConversationScreenPort)


def surface_scenarios(
    factory: ConversationScenarioFactory[AppT],
    contracts: ScenarioFrameContracts,
) -> tuple[PlaybackScenarioSpec, ...]:
    """Build product-neutral active-surface routing recipes."""

    recipes = _SurfaceRecipes(factory=factory, contracts=contracts)
    return (
        PlaybackScenarioSpec(
            name="active-surface",
            description="Route enter to an active surface before the composer.",
            run=recipes.active_surface,
        ),
        PlaybackScenarioSpec(
            name="mouse-select-active-surface",
            description="Route raw SGR mouse press events to an active selection surface.",
            run=recipes.mouse_select_active_surface,
        ),
    )


@dataclass(frozen=True, slots=True)
class _SurfaceRecipes(Generic[AppT]):
    factory: ConversationScenarioFactory[AppT]
    contracts: ScenarioFrameContracts

    def active_surface(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_active_surface(
                SelectionSurface((SelectItem("Choose me", value="chosen"),))
            )
            .with_composer_text("draft")
            .render()
            .enter()
            .run()
        )
        result.assert_surface_intents(("select", "chosen"))
        result.assert_composer_text("draft")
        result.assert_visible_contains("Choose me")
        self._assert_interaction(result)
        return result

    def mouse_select_active_surface(
        self,
    ) -> ConversationInputPlaybackResult[AppT]:
        surface = SelectionSurface(
            (
                SelectItem("First option", value="first"),
                SelectItem("Second option", value="second"),
                SelectItem("Third option", value="third"),
            ),
            max_visible=3,
        )
        result = (
            self.factory.input(width=80, height=12)
            .with_active_surface(surface)
            .render()
            .key("\x1b[<0;1;2M")
            .enter()
            .run()
        )
        result.assert_surface_intents(("select", "second"))
        result.assert_composer_text("")
        result.assert_visible_contains("Second option")
        self._assert_interaction(result)
        return result

    def _assert_interaction(
        self,
        result: ConversationInputPlaybackResult[AppT],
    ) -> None:
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
        self.contracts.assert_interaction(result)


__all__ = ["surface_scenarios"]
