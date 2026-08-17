from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from loushang.harnesstui.conversation.screen_runner import (
    ConversationInputRouterFactoryPort,
    ConversationScreenPort,
    LocalCommandPredicate,
    ShouldExit,
)
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlayback,
    ConversationInputScenario,
)
from loushang.harnesstui.testing.ports import (
    ConversationLoopResultPayloadPort,
    ConversationPlaybackAppFactoryPort,
    ConversationPlaybackInputRouterFactoryPort,
    ConversationResultPayloadPort,
    ConversationStateSnapshotPort,
)
from loushang.harnesstui.testing.render_scenario import ConversationRenderScenario
from loushang.harnesstui.testing.screen_loop_playback import (
    ConversationScreenLoopPlayback,
    ConversationScreenLoopRunnerPort,
    ConversationScreenLoopScenario,
)
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.playback import PlaybackFrameBudget, PlaybackResult

AppT = TypeVar("AppT", bound=ConversationScreenPort)


@dataclass(frozen=True, slots=True)
class ScenarioFrameContracts:
    """Product-supplied frame budgets exercised by neutral recipes."""

    interaction: PlaybackFrameBudget
    long_transcript: PlaybackFrameBudget

    def assert_interaction(
        self,
        result: PlaybackResult,
        *,
        skip_first: bool = True,
    ) -> None:
        self.interaction.assert_result(result, skip_first=skip_first)

    def assert_long_transcript(
        self,
        result: PlaybackResult,
        *,
        skip_first: bool = True,
    ) -> None:
        self.long_transcript.assert_result(result, skip_first=skip_first)


@dataclass(frozen=True, slots=True)
class ConversationScenarioFactory(Generic[AppT]):
    """Bind neutral playback recipes to one concrete conversation product.

    The factory is the sole product seam used by scenario modules.  A product
    supplies its real application, input-router adapter, and screen runner;
    recipes remain unaware of product modules and policy.
    """

    app_factory: ConversationPlaybackAppFactoryPort[AppT]
    input_router_factory: ConversationPlaybackInputRouterFactoryPort
    screen_loop_runner: ConversationScreenLoopRunnerPort
    interruption_message: str
    cancellation_message: str
    state_snapshot: ConversationStateSnapshotPort[AppT] | None = None
    input_result_payload: ConversationResultPayloadPort | None = None
    loop_result_payload: ConversationLoopResultPayloadPort[AppT] | None = None

    def render(
        self,
        *,
        width: int = 80,
        height: int = 24,
        now: float = 0.0,
    ) -> ConversationRenderScenario[AppT]:
        return ConversationRenderScenario(
            app_factory=self.app_factory,
            width=width,
            height=height,
            now=now,
        )

    def input(
        self,
        *,
        width: int = 80,
        height: int = 12,
        now: float = 0.0,
        should_exit: ShouldExit | None = None,
        is_local_command: LocalCommandPredicate | None = None,
        keybindings: KeybindingManager | KeybindingConfig | None = None,
    ) -> ConversationInputScenario[AppT]:
        app = self.app_factory(now=lambda: now)
        playback = self._build_input_playback(
            app,
            columns=width,
            rows=height,
            should_exit=should_exit,
            is_local_command=is_local_command,
            keybindings=keybindings,
        )
        return ConversationInputScenario(playback=playback)

    def loop(
        self,
        *,
        width: int = 80,
        height: int = 24,
        now: float = 0.0,
    ) -> ConversationScreenLoopPlayback[AppT]:
        return self._build_screen_loop_playback(
            width=width,
            height=height,
            now=now,
        )

    def loop_scenario(
        self,
        *,
        width: int = 80,
        height: int = 24,
        now: float = 0.0,
    ) -> ConversationScreenLoopScenario[AppT]:
        return ConversationScreenLoopScenario(
            playback=self.loop(width=width, height=height, now=now)
        )

    def _build_input_playback(
        self,
        app: AppT,
        *,
        columns: int,
        rows: int,
        should_exit: ShouldExit | None,
        is_local_command: LocalCommandPredicate | None,
        keybindings: KeybindingManager | KeybindingConfig | None,
    ) -> ConversationInputPlayback[AppT]:
        return ConversationInputPlayback(
            app,
            columns=columns,
            rows=rows,
            should_exit=should_exit,
            is_local_command=is_local_command,
            keybindings=keybindings,
            input_router_factory=self.input_router_factory,
            state_snapshot=self.state_snapshot,
            result_payload=self.input_result_payload,
        )

    def _build_screen_loop_playback(
        self,
        *,
        width: int,
        height: int,
        now: float,
    ) -> ConversationScreenLoopPlayback[AppT]:
        return ConversationScreenLoopPlayback(
            app_factory=self.app_factory,
            interruption_message=self.interruption_message,
            cancellation_message=self.cancellation_message,
            width=width,
            height=height,
            now=now,
            runner=self.screen_loop_runner,
            input_router_factory=cast(
                ConversationInputRouterFactoryPort,
                self.input_router_factory,
            ),
            state_snapshot=self.state_snapshot,
            result_payload=self.loop_result_payload,
        )


__all__ = ["ConversationScenarioFactory", "ScenarioFrameContracts"]
