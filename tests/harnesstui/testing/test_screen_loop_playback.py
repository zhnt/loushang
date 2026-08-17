from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.testing.screen_loop_playback import (
    BlockingPromptController,
    ConversationScreenLoopPlayback,
    ConversationScreenLoopScenario,
    ScriptedInputChunk,
)
from loushang.tui.core import RenderConstraints, RenderResult
from loushang.tui.framework import SurfaceHost
from loushang.tui.terminal_capabilities import TerminalRuntimeCapabilities
from loushang.tui.ui_parts.composer import Composer


@dataclass(slots=True)
class _ScreenApp:
    clock: object
    composer: Composer = field(default_factory=Composer)
    state: ScreenConversationState = field(default_factory=ScreenConversationState)
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None
    render_requester: object | None = None
    terminal_diagnostics_provider: object | None = None
    terminal_capabilities: TerminalRuntimeCapabilities | None = None
    errors: list[str] = field(default_factory=list)

    def now(self) -> float:
        assert callable(self.clock)
        return self.clock()

    def open_transcript_reader(self) -> bool:
        return False

    def start_prompt(self, text: str) -> None:
        self.state.start_prompt(text, started_at=self.now())
        self.composer.add_history(text)
        self.composer.clear()

    def start_pending_prompt(self, text: str) -> None:
        self.start_prompt(text)

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)

    def add_error(self, summary: str, diagnostics: str = "") -> None:
        del diagnostics
        self.errors.append(summary)

    def complete_run(self, *, elapsed_seconds: float | None = None) -> None:
        self.state.complete_run(elapsed_seconds=elapsed_seconds or 0.0)

    def elapsed_seconds(self) -> float:
        return 0.0

    def startup_welcome_panel(self) -> _ScreenApp:
        return self

    def render(self, constraints: RenderConstraints) -> RenderResult:
        del constraints
        return RenderResult(lines=())


def _app_factory(*, now):
    return _ScreenApp(clock=now)


def test_blocking_prompt_controller_settles_without_residual_task() -> None:
    controller = BlockingPromptController(timeout_seconds=0.1)

    async def run() -> None:
        with controller:
            waiter = asyncio.create_task(controller.wait_until_settled())
            await asyncio.sleep(0)
            assert controller.started
            controller.settle_on_abort()
            await waiter

    asyncio.run(run())
    assert controller.settled


def test_blocking_prompt_controller_fails_closed_on_missing_abort() -> None:
    controller = BlockingPromptController(timeout_seconds=0.001)

    with pytest.raises(AssertionError, match="not settled by abort"):
        asyncio.run(controller.wait_until_settled())


def test_blocking_prompt_controller_context_requires_completed_lifecycle() -> None:
    with pytest.raises(AssertionError, match="never started"):
        with BlockingPromptController():
            pass


@pytest.mark.parametrize("timeout", [0, float("inf"), float("nan")])
def test_blocking_prompt_controller_rejects_unbounded_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and greater than zero"):
        BlockingPromptController(timeout_seconds=timeout)


def test_screen_loop_playback_runs_scripted_chunks_through_shared_runner() -> None:
    prompts: list[str] = []
    playback = ConversationScreenLoopPlayback(
        app_factory=_app_factory,
        interruption_message="interrupted",
        cancellation_message="cancelled",
        width=40,
        height=8,
    )

    async def handle_prompt(text: str) -> None:
        prompts.append(text)

    result = playback.run(
        ScriptedInputChunk(0.0, "hello"),
        (0.0, "\r"),
        (0.01, ""),
        handle_prompt=handle_prompt,
    )

    result.assert_exit_code(0)
    result.assert_idle()
    result.assert_composer_text("")
    result.assert_no_clear_screen()
    assert prompts == ["hello"]
    assert result.state_snapshot["running"] is False


def test_screen_loop_scenario_builds_timed_input_recipe() -> None:
    prompts: list[str] = []
    scenario = ConversationScreenLoopScenario(
        playback=ConversationScreenLoopPlayback(
            app_factory=_app_factory,
            interruption_message="interrupted",
            cancellation_message="cancelled",
        )
    )

    async def handle_prompt(text: str) -> None:
        prompts.append(text)

    result = (
        scenario.type_chars("hi")
        .enter()
        .wait(0.01)
        .end_input()
        .run(handle_prompt=handle_prompt)
    )

    assert prompts == ["hi"]
    result.assert_exit_code(0)


def test_screen_loop_artifacts_separate_snapshot_and_result_payload(tmp_path) -> None:
    playback = ConversationScreenLoopPlayback(
        app_factory=_app_factory,
        interruption_message="interrupted",
        cancellation_message="cancelled",
        state_snapshot=lambda app: {"draft": app.composer.value},
        result_payload=lambda exit_code, _app: {"runner": {"exit": exit_code}},
    )

    result = playback.run()
    artifacts = result.write_artifacts(tmp_path, basename="loop")
    state = json.loads(artifacts.state.read_text(encoding="utf-8"))

    assert state == {
        "exit_code": 0,
        "conversation": {"draft": ""},
        "runner": {"exit": 0},
    }
