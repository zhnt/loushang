from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlaybackResult,
)
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.harnesstui.testing.screen_loop_playback import (
    BlockingPromptController,
    ConversationScreenLoopPlaybackResult,
)
from loushang.tui.playback_suite import PlaybackScenarioSpec


class LifecycleScenarioAppPort(ConversationScreenPort, Protocol):
    """Conversation mutations exercised by lifecycle playback recipes."""

    def begin_assistant(self) -> None: ...

    def append_assistant_chunk(self, chunk: str) -> None: ...


AppT = TypeVar("AppT", bound=LifecycleScenarioAppPort)


def lifecycle_scenarios(
    factory: ConversationScenarioFactory[AppT],
    contracts: ScenarioFrameContracts,
) -> tuple[PlaybackScenarioSpec, ...]:
    """Build queue, interruption, and follow-up lifecycle recipes."""

    recipes = _LifecycleRecipes(factory=factory, contracts=contracts)
    return (
        PlaybackScenarioSpec(
            name="idle-escape-clears-draft",
            description="Clear an idle composer draft with ESC without aborting a run.",
            run=recipes.idle_escape_clears_draft,
        ),
        PlaybackScenarioSpec(
            name="running-steer-queued",
            description="Queue a submitted steer while a prompt is running.",
            run=recipes.running_steer_queued,
        ),
        PlaybackScenarioSpec(
            name="running-escape-keeps-queued-steer",
            description="Abort a running prompt without dropping an existing queued steer.",
            run=recipes.running_escape_keeps_queued_steer,
        ),
        PlaybackScenarioSpec(
            name="idle-escape-pops-pending-steer",
            description="Pop and execute the first pending steer when ESC is pressed while idle.",
            run=recipes.idle_escape_pops_pending_steer,
        ),
        PlaybackScenarioSpec(
            name="escape-pending-steer",
            description="Exercise ESC with a queued steer through the screen loop.",
            run=recipes.escape_pending_steer,
        ),
        PlaybackScenarioSpec(
            name="escape-pending-steer-fifo",
            description="Preserve pending steer FIFO order when ESC interrupts a running prompt.",
            run=recipes.escape_pending_steer_fifo,
        ),
        PlaybackScenarioSpec(
            name="escape-pending-steer-preserves-draft",
            description="Run an interrupt pending steer without clearing an unsubmitted composer draft.",
            run=recipes.escape_pending_steer_preserves_draft,
        ),
        PlaybackScenarioSpec(
            name="screen-loop-ctrl-c-abort-running",
            description="Abort a running screen loop prompt via raw Ctrl-C without clearing the screen.",
            run=recipes.screen_loop_ctrl_c_abort_running,
        ),
        PlaybackScenarioSpec(
            name="running-follow-up-queued",
            description="Queue a follow-up while a prompt is running.",
            run=recipes.running_follow_up_queued,
        ),
        PlaybackScenarioSpec(
            name="keyboard-alt-enter-follow-up",
            description="Route raw Alt+Enter to follow-up submission while running.",
            run=recipes.keyboard_alt_enter_follow_up,
        ),
    )


@dataclass(frozen=True, slots=True)
class _LifecycleRecipes(Generic[AppT]):
    factory: ConversationScenarioFactory[AppT]
    contracts: ScenarioFrameContracts

    def idle_escape_clears_draft(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .type_text("draft")
            .escape()
            .run()
        )
        result.assert_composer_text("")
        result.assert_no_abort_requested()
        result.assert_visible_not_contains("draft")
        self._assert_interaction(result)
        return result

    def running_steer_queued(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_running_prompt("old")
            .render()
            .type_text("change")
            .enter()
            .run()
        )
        result.assert_steer_texts("change")
        result.assert_pending_steers("change")
        result.assert_composer_text("")
        result.assert_visible_contains("change")
        self._assert_interaction(result)
        return result

    def running_escape_keeps_queued_steer(
        self,
    ) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_running_prompt("old")
            .with_pending_steers("queued")
            .render()
            .escape()
            .run()
        )
        result.assert_abort_requested()
        result.assert_pending_steers("queued")
        result.assert_visible_contains("queued")
        self._assert_interaction(result)
        return result

    def idle_escape_pops_pending_steer(
        self,
    ) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_pending_steers("queued")
            .render()
            .escape()
            .run()
        )
        result.assert_steer_texts("queued")
        result.assert_pending_steers()
        self._assert_interaction(result)
        return result

    def escape_pending_steer(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        scenario = self.factory.loop_scenario()
        prompts: list[str] = []
        steers: list[str] = []
        blocking_prompt = BlockingPromptController()

        async def handle_prompt(text: str) -> None:
            prompts.append(text)
            scenario.app.begin_assistant()
            if text == "fresh":
                scenario.app.append_assistant_chunk("fresh response")
                return
            scenario.app.append_assistant_chunk("old response")
            await blocking_prompt.wait_until_settled()

        async def handle_steer(text: str) -> None:
            steers.append(text)

        with blocking_prompt:
            result = (
                scenario.type_text("old")
                .enter()
                .wait(0.01)
                .type_text("fresh")
                .enter()
                .wait(0.01)
                .escape()
                .wait(0.04)
                .end_input()
                .run(
                    handle_prompt=handle_prompt,
                    handle_steer=handle_steer,
                    on_abort=blocking_prompt.settle_on_abort,
                )
            )
        result.assert_exit_code(0)
        result.assert_text_contains("old")
        result.assert_text_contains("fresh")
        result.assert_text_contains("fresh response")
        result.assert_no_clear_screen()
        result.assert_idle()
        result.assert_pending_steers()
        result.assert_composer_text("")
        assert prompts == ["old", "fresh"]
        assert steers == ["fresh"]
        return result

    def escape_pending_steer_fifo(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        scenario = self.factory.loop_scenario().with_pending_steers("prequeued")
        prompts: list[str] = []
        steers: list[str] = []
        blocking_prompt = BlockingPromptController()

        async def handle_prompt(text: str) -> None:
            if text == "prequeued":
                prompts.append(text)
                return
            scenario.app.begin_assistant()
            scenario.app.append_assistant_chunk("working")
            await blocking_prompt.wait_until_settled()

        async def handle_steer(text: str) -> None:
            steers.append(text)

        with blocking_prompt:
            result = (
                scenario.type_text("start")
                .enter()
                .wait(0.01)
                .type_text("running steer")
                .enter()
                .wait(0.01)
                .escape()
                .wait(0.04)
                .end_input()
                .run(
                    handle_prompt=handle_prompt,
                    handle_steer=handle_steer,
                    on_abort=blocking_prompt.settle_on_abort,
                )
            )
        result.assert_exit_code(0)
        assert steers == ["running steer"]
        assert prompts == ["prequeued"]
        result.assert_pending_steers("running steer")
        result.assert_no_clear_screen()
        return result

    def escape_pending_steer_preserves_draft(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        scenario = self.factory.loop_scenario().with_pending_steers("queued")
        prompts: list[str] = []
        blocking_prompt = BlockingPromptController()

        async def handle_prompt(text: str) -> None:
            if text == "queued":
                prompts.append(text)
                return
            await blocking_prompt.wait_until_settled()

        with blocking_prompt:
            result = (
                scenario.type_text("start")
                .enter()
                .wait(0.01)
                .type_text("draft")
                .wait(0.01)
                .escape()
                .wait(0.04)
                .end_input()
                .run(
                    handle_prompt=handle_prompt,
                    on_abort=blocking_prompt.settle_on_abort,
                )
            )
        result.assert_exit_code(0)
        assert prompts == ["queued"]
        result.assert_composer_text("draft")
        result.assert_pending_steers()
        result.assert_no_clear_screen()
        return result

    def screen_loop_ctrl_c_abort_running(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        scenario = self.factory.loop_scenario()
        prompts: list[str] = []
        aborts: list[str] = []
        blocking_prompt = BlockingPromptController()

        async def handle_prompt(text: str) -> None:
            prompts.append(text)
            scenario.app.begin_assistant()
            scenario.app.append_assistant_chunk("working before ctrl-c")
            await blocking_prompt.wait_until_settled()

        async def on_abort() -> None:
            aborts.append("abort")
            blocking_prompt.settle_on_abort()

        with blocking_prompt:
            result = (
                scenario.type_text("long running")
                .enter()
                .wait(0.01)
                .ctrl_c()
                .wait(0.04)
                .end_input()
                .run(handle_prompt=handle_prompt, on_abort=on_abort)
            )
        result.assert_exit_code(0)
        assert prompts == ["long running"]
        assert aborts == ["abort"]
        result.assert_idle()
        result.assert_text_contains("long running")
        interruption_message = result.app.state.interruption_message
        assert interruption_message
        result.assert_text_contains(interruption_message)
        result.assert_no_clear_screen()
        return result

    def running_follow_up_queued(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_running_prompt("old")
            .render()
            .type_text("follow")
            .key("\x1b\r")
            .run()
        )
        result.assert_pending_followups("follow")
        result.assert_pending_steers()
        result.assert_composer_text("")
        result.assert_visible_contains("follow")
        self._assert_interaction(result)
        return result

    def keyboard_alt_enter_follow_up(
        self,
    ) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_running_prompt("active")
            .render()
            .type_text("follow-up through raw alt enter")
            .key("\x1b\r")
            .run()
        )
        result.assert_pending_followups("follow-up through raw alt enter")
        result.assert_pending_steers()
        result.assert_composer_text("")
        result.assert_visible_contains("follow-up through raw alt enter")
        self._assert_interaction(result)
        return result

    def _assert_interaction(
        self,
        result: ConversationInputPlaybackResult[AppT],
    ) -> None:
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
        self.contracts.assert_interaction(result)


__all__ = ["LifecycleScenarioAppPort", "lifecycle_scenarios"]
