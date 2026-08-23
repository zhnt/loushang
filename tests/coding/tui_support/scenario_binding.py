from __future__ import annotations

from collections.abc import Callable
from typing import TextIO, cast

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import (
    CODING_CANCELLATION_MESSAGE,
    CODING_INTERRUPTION_MESSAGE,
    CODING_SCREEN_RUN_PROFILE,
    build_screen_input_router,
)
from loushang.harnesstui.conversation.control import ConversationActionHost
from loushang.harnesstui.conversation.host import (
    run_action_host_conversation_screen,
)
from loushang.harnesstui.conversation.screen_runner import (
    AbortHandler,
    ConversationInputRouterFactoryPort,
    ConversationScreenPort,
    LocalCommandPredicate,
    PromptHandler,
    ShouldExit,
    SurfaceIntentHandler,
    TerminalModeFactory,
    TerminalSizeProvider,
    TextHandler,
)
from loushang.harnesstui.testing.action_host import CallbackConversationActionHost
from loushang.harnesstui.testing.ports import (
    ConversationPlaybackAppPort,
    ConversationPlaybackInputRouterPort,
)
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.terminal_input import InputChunkReader
from tests.coding.tui_support.scenarios.budgets import (
    INTERACTION_FRAME_BUDGET,
    LONG_TRANSCRIPT_FRAME_BUDGET,
)


def coding_scenario_input_router_factory(
    *,
    app: ConversationPlaybackAppPort,
    should_exit: ShouldExit,
    is_local_command: LocalCommandPredicate,
    keybindings: KeybindingManager | KeybindingConfig | None,
    width: int,
    height: int,
) -> ConversationPlaybackInputRouterPort:
    return cast(
        ConversationPlaybackInputRouterPort,
        build_screen_input_router(
            app=cast(ScreenCodingTuiApp, app),
            should_exit=should_exit,
            is_local_command=is_local_command,
            keybindings=keybindings,
            width=width,
            height=height,
        ),
    )


async def run_coding_test_screen(
    *,
    app: ScreenCodingTuiApp,
    stdin: TextIO,
    stdout: TextIO,
    action_host: ConversationActionHost,
    handle_local: TextHandler | None = None,
    handle_surface_intent: SurfaceIntentHandler | None = None,
    should_exit: ShouldExit,
    is_local_command: LocalCommandPredicate | None = None,
    keybindings: KeybindingManager | KeybindingConfig | None = None,
    terminal_mode_factory: TerminalModeFactory | None = None,
    terminal_size_provider: TerminalSizeProvider | None = None,
    input_chunk_reader: InputChunkReader | None = None,
) -> int:
    """Bind the Coding test profile directly to canonical screen owners."""

    return await run_action_host_conversation_screen(
        app=app,
        stdin=stdin,
        stdout=stdout,
        action_host=action_host,
        profile=CODING_SCREEN_RUN_PROFILE,
        handle_local=handle_local,
        handle_surface_intent=handle_surface_intent,
        should_exit=should_exit,
        is_local_command=is_local_command,
        keybindings=keybindings,
        terminal_mode_factory=terminal_mode_factory,
        terminal_size_provider=terminal_size_provider,
        input_chunk_reader=input_chunk_reader,
    )


async def run_coding_scenario_screen_loop(
    *,
    app: ConversationScreenPort,
    stdin: TextIO,
    stdout: TextIO,
    handle_prompt: PromptHandler,
    handle_local: TextHandler | None,
    handle_steer: TextHandler | None,
    handle_followup: TextHandler | None,
    handle_surface_intent: SurfaceIntentHandler | None,
    on_abort: AbortHandler,
    should_exit: ShouldExit,
    is_local_command: LocalCommandPredicate | None,
    terminal_mode_factory: TerminalModeFactory | None,
    terminal_size_provider: TerminalSizeProvider,
    interruption_message: str,
    cancellation_message: str,
    input_router_factory: ConversationInputRouterFactoryPort | None,
    input_chunk_reader: InputChunkReader | None,
) -> int:
    del input_router_factory
    if (
        interruption_message != CODING_INTERRUPTION_MESSAGE
        or cancellation_message != CODING_CANCELLATION_MESSAGE
    ):
        raise ValueError("Coding playback copy does not match the product adapter")
    return await run_coding_test_screen(
        app=cast(ScreenCodingTuiApp, app),
        stdin=stdin,
        stdout=stdout,
        action_host=CallbackConversationActionHost(
            submit=handle_prompt,
            steer=handle_steer,
            follow_up=handle_followup,
            abort=on_abort,
        ),
        handle_local=handle_local,
        handle_surface_intent=handle_surface_intent,
        should_exit=should_exit,
        is_local_command=is_local_command,
        terminal_mode_factory=terminal_mode_factory,
        terminal_size_provider=terminal_size_provider,
        input_chunk_reader=input_chunk_reader,
    )


def _coding_app_factory(*, now: Callable[[], float]) -> ScreenCodingTuiApp:
    return ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=now,
    )


CODING_SCENARIO_FACTORY = ConversationScenarioFactory(
    app_factory=_coding_app_factory,
    input_router_factory=coding_scenario_input_router_factory,
    screen_loop_runner=run_coding_scenario_screen_loop,
    interruption_message=CODING_INTERRUPTION_MESSAGE,
    cancellation_message=CODING_CANCELLATION_MESSAGE,
)

CODING_SCENARIO_FRAME_CONTRACTS = ScenarioFrameContracts(
    interaction=INTERACTION_FRAME_BUDGET,
    long_transcript=LONG_TRANSCRIPT_FRAME_BUDGET,
)


__all__ = [
    "CODING_CANCELLATION_MESSAGE",
    "CODING_INTERRUPTION_MESSAGE",
    "CODING_SCENARIO_FACTORY",
    "CODING_SCENARIO_FRAME_CONTRACTS",
    "coding_scenario_input_router_factory",
    "run_coding_scenario_screen_loop",
    "run_coding_test_screen",
]
