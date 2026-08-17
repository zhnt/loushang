from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TextIO, TypeVar

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
)
from loushang.harnesstui.testing.screen_loop_playback import (
    ConversationScreenLoopPlaybackResult,
)
from loushang.tui.input import BRACKETED_PASTE_END, BRACKETED_PASTE_START
from loushang.tui.keyboard_protocol import (
    KITTY_DISABLE_SEQUENCE,
    KITTY_ENABLE_FLAGS_SEQUENCE,
    KITTY_QUERY_SEQUENCE,
)
from loushang.tui.playback_suite import PlaybackScenarioSpec
from loushang.tui.terminal_capabilities import TerminalRuntimeCapabilities
from loushang.tui.terminal_session import (
    MOUSE_DISABLE_SEQUENCES,
    MOUSE_ENABLE_SEQUENCES,
    TerminalSession,
)


class TerminalScenarioAppPort(ConversationScreenPort, Protocol):
    """Conversation mutations exercised by terminal-loop recipes."""

    def begin_assistant(self) -> None: ...

    def append_assistant_chunk(self, chunk: str) -> None: ...


AppT = TypeVar("AppT", bound=TerminalScenarioAppPort)


def terminal_scenarios(
    factory: ConversationScenarioFactory[AppT],
) -> tuple[PlaybackScenarioSpec, ...]:
    """Build raw-terminal and terminal-session recipes."""

    recipes = _TerminalRecipes(factory=factory)
    return (
        PlaybackScenarioSpec(
            name="screen-loop-split-bracketed-paste",
            description="Keep split screen bracketed paste atomic until the end marker arrives.",
            run=recipes.screen_loop_split_bracketed_paste,
        ),
        PlaybackScenarioSpec(
            name="terminal-control-response-hidden",
            description="Consume terminal control responses without echoing them as user input.",
            run=recipes.terminal_control_response_hidden,
        ),
        PlaybackScenarioSpec(
            name="screen-loop-terminal-session-cleanup",
            description="Run screen loop through TerminalSession startup, control responses, and cleanup.",
            run=recipes.screen_loop_terminal_session_cleanup,
        ),
        PlaybackScenarioSpec(
            name="apple-shift-enter-normalized",
            description="Normalize Apple Terminal Shift+Enter to a composer newline before submit.",
            run=recipes.apple_shift_enter_normalized,
        ),
    )


@dataclass(frozen=True, slots=True)
class _TerminalRecipes(Generic[AppT]):
    factory: ConversationScenarioFactory[AppT]

    def screen_loop_split_bracketed_paste(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        playback = self.factory.loop(width=80, height=12)
        pasted = "alpha\nbeta\ngamma"
        prompts: list[str] = []

        async def handle_prompt(text: str) -> None:
            prompts.append(text)
            playback.app.begin_assistant()
            playback.app.append_assistant_chunk("split paste submitted once")

        result = playback.run(
            (0.00, BRACKETED_PASTE_START[:3]),
            (0.01, f"{BRACKETED_PASTE_START[3:]}alpha\n"),
            (0.02, f"beta\ngamma{BRACKETED_PASTE_END[:3]}"),
            (0.03, f"{BRACKETED_PASTE_END[3:]}"),
            (0.04, "\r"),
            (0.06, ""),
            handle_prompt=handle_prompt,
        )
        result.assert_exit_code(0)
        assert prompts == [pasted]
        result.assert_composer_text("")
        result.assert_text_contains("alpha")
        result.assert_text_contains("split paste submitted once")
        result.assert_no_clear_screen()
        return result

    def terminal_control_response_hidden(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        playback = self.factory.loop(width=80, height=12)
        contexts: list[_RecordingTerminalContext] = []
        prompts: list[str] = []

        async def handle_prompt(text: str) -> None:
            prompts.append(text)
            playback.app.begin_assistant()
            playback.app.append_assistant_chunk("terminal control response was hidden")

        def terminal_mode_factory(
            _stdin: TextIO,
            _stdout: TextIO,
        ) -> _RecordingTerminalContext:
            context = _RecordingTerminalContext()
            contexts.append(context)
            return context

        result = playback.run(
            (0.00, "\x1b[?7u"),
            (0.01, "\x1b[6;18;9t"),
            (0.02, "hello"),
            (0.02, "\r"),
            (0.04, ""),
            handle_prompt=handle_prompt,
            terminal_mode_factory=terminal_mode_factory,
        )
        result.assert_exit_code(0)
        assert prompts == ["hello"]
        assert contexts
        assert [(event.signal, event.text) for event in contexts[0].events] == [
            ("kitty_protocol", "7"),
            ("cell_size", "18;9"),
        ]
        assert "\x1b[?7u" not in result.output
        assert "\x1b[6;18;9t" not in result.output
        result.assert_text_not_contains("?7u")
        result.assert_text_not_contains("18;9")
        result.assert_text_contains("hello")
        result.assert_no_clear_screen()
        return result

    def screen_loop_terminal_session_cleanup(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        playback = self.factory.loop(width=80, height=12)
        prompts: list[str] = []
        cleanup_calls: list[str] = []
        mode = _RecordingTerminalMode(cleanup_calls)
        capabilities = TerminalRuntimeCapabilities(
            keyboard_protocol_strategy="kitty_then_modify_other_keys",
            enable_mouse=True,
            query_cell_size=True,
        )

        async def handle_prompt(text: str) -> None:
            prompts.append(text)
            playback.app.begin_assistant()
            playback.app.append_assistant_chunk("terminal session handled cleanup")

        def terminal_mode_factory(stdin: TextIO, stdout: TextIO) -> TerminalSession:
            return TerminalSession(
                stdin=stdin,
                stdout=stdout,
                capabilities=capabilities,
                mode_factory=lambda _stdin, _stdout, _capabilities: mode,
                drain_input_func=_recording_drain(cleanup_calls),
                now_ms=lambda: 1_000,
            )

        result = playback.run(
            (0.00, "\x1b[?7u"),
            (0.01, "\x1b[6;18;9t"),
            (0.02, "hello"),
            (0.03, "\r"),
            (0.05, ""),
            handle_prompt=handle_prompt,
            terminal_mode_factory=terminal_mode_factory,
        )
        output = result.output
        result.assert_exit_code(0)
        assert prompts == ["hello"]
        assert cleanup_calls == ["mode:enter", "drain", "mode:exit"]
        assert KITTY_QUERY_SEQUENCE in output
        assert KITTY_ENABLE_FLAGS_SEQUENCE in output
        assert KITTY_DISABLE_SEQUENCE in output
        assert all(sequence in output for sequence in MOUSE_ENABLE_SEQUENCES)
        assert all(sequence in output for sequence in MOUSE_DISABLE_SEQUENCES)
        assert "\x1b[16t" in output
        assert output.index(KITTY_QUERY_SEQUENCE) < output.index("hello")
        assert output.index("terminal session handled cleanup") < output.index(
            KITTY_DISABLE_SEQUENCE
        )
        assert output.index(KITTY_DISABLE_SEQUENCE) < output.index(
            MOUSE_DISABLE_SEQUENCES[0]
        )
        result.assert_text_contains("hello")
        result.assert_text_not_contains("?7u")
        result.assert_text_not_contains("18;9")
        result.assert_no_clear_screen()
        return result

    def apple_shift_enter_normalized(
        self,
    ) -> ConversationScreenLoopPlaybackResult[AppT]:
        playback = self.factory.loop(width=80, height=12)
        contexts: list[_AppleShiftEnterTerminalContext] = []
        prompts: list[str] = []

        async def handle_prompt(text: str) -> None:
            prompts.append(text)
            playback.app.begin_assistant()
            playback.app.append_assistant_chunk("apple shift enter inserted a newline")

        def terminal_mode_factory(
            _stdin: TextIO,
            _stdout: TextIO,
        ) -> _AppleShiftEnterTerminalContext:
            context = _AppleShiftEnterTerminalContext()
            contexts.append(context)
            return context

        result = playback.run(
            (0.00, "first"),
            (0.01, "\r"),
            (0.02, "second"),
            (0.03, "\r"),
            (0.05, ""),
            handle_prompt=handle_prompt,
            terminal_mode_factory=terminal_mode_factory,
        )
        result.assert_exit_code(0)
        assert prompts == ["first\nsecond"]
        assert contexts
        assert contexts[0].return_key_count == 2
        result.assert_text_contains("first")
        result.assert_text_contains("second")
        result.assert_text_not_contains("[13;2u")
        result.assert_no_clear_screen()
        return result


class _RecordingTerminalContext:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def __enter__(self) -> _RecordingTerminalContext:
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        return False

    def consume_control_events(self, events: tuple[object, ...]) -> None:
        self.events.extend(events)


class _AppleShiftEnterTerminalContext:
    def __init__(self) -> None:
        self.return_key_count = 0

    def __enter__(self) -> _AppleShiftEnterTerminalContext:
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        return False

    def normalize_input_chunk(self, data: str) -> str:
        if data != "\r":
            return data
        self.return_key_count += 1
        if self.return_key_count == 1:
            return "\x1b[13;2u"
        return data


class _RecordingTerminalMode:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def __enter__(self) -> _RecordingTerminalMode:
        self.calls.append("mode:enter")
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        self.calls.append("mode:exit")
        return False


def _recording_drain(calls: list[str]) -> Callable[..., str]:
    def drain(*_args: object, **_kwargs: object) -> str:
        calls.append("drain")
        return ""

    return drain


__all__ = ["TerminalScenarioAppPort", "terminal_scenarios"]
