from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from loushang.coding.ui.completion import coding_inline_completion_provider
from loushang.coding.ui.perf_probe import build_synthetic_long_transcript_records
from loushang.coding.ui.playback import (
    NativeTuiInputPlaybackResult,
    NativeTuiInputScenario,
    NativeTuiLoopPlayback,
)
from loushang.coding.ui.playback_fakes import (
    AppleShiftEnterTerminalContext as _AppleShiftEnterTerminalContext,
)
from loushang.coding.ui.playback_fakes import (
    RecordingTerminalContext as _RecordingTerminalContext,
)
from loushang.coding.ui.playback_fakes import (
    RecordingTerminalMode as _RecordingTerminalMode,
)
from loushang.coding.ui.playback_fakes import (
    SessionCommandPlaybackSession as _SessionCommandSession,
)
from loushang.coding.ui.playback_fakes import (
    recording_drain as _recording_drain,
)
from loushang.coding.ui.playback_scenarios.budgets import (
    INTERACTION_FRAME_BUDGET,
    LONG_TRANSCRIPT_FRAME_BUDGET,
)
from loushang.coding.ui.playback_scenarios.command import COMMAND_ROUTING_SCENARIOS
from loushang.coding.ui.playback_scenarios.lifecycle import LIFECYCLE_SCENARIOS
from loushang.coding.ui.playback_scenarios.surface import SURFACE_SCENARIOS
from loushang.coding.ui.playback_suite import (
    NativePlaybackScenarioResult,
    NativePlaybackScenarioSpec,
    NativePlaybackSuite,
)
from loushang.coding.ui.playback_suite import (
    run_playback_scenarios as _run_playback_scenarios,
)
from loushang.tui import (
    SelectionSurface,
    SelectItem,
)
from loushang.tui.input import BRACKETED_PASTE_END, BRACKETED_PASTE_START
from loushang.tui.keyboard_protocol import (
    KITTY_DISABLE_SEQUENCE,
    KITTY_ENABLE_FLAGS_SEQUENCE,
    KITTY_QUERY_SEQUENCE,
)
from loushang.tui.terminal_capabilities import TerminalRuntimeCapabilities
from loushang.tui.terminal_session import (
    MOUSE_DISABLE_SEQUENCES,
    MOUSE_ENABLE_SEQUENCES,
    TerminalSession,
)
from loushang.tui.transcript import ToolExecutionRecord


def run_playback_scenarios(
    names: Sequence[str] = (),
    *,
    tags: Sequence[str] = (),
    suite: NativePlaybackSuite | None = None,
    artifacts_dir: str | Path | None = None,
    include_frames: bool = False,
) -> tuple[NativePlaybackScenarioResult, ...]:
    suite = DEFAULT_SUITE if suite is None else suite
    return _run_playback_scenarios(
        names,
        tags=tags,
        suite=suite,
        artifacts_dir=artifacts_dir,
        include_frames=include_frames,
    )


def run_playback_cli(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    suite: NativePlaybackSuite | None = None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    suite = DEFAULT_SUITE if suite is None else suite
    parser = _build_parser()
    raw_argv = sys.argv[1:] if argv is None else tuple(argv)
    args = parser.parse_args(raw_argv)
    tags = tuple(args.tag or ())
    if args.list:
        _write_scenario_list(suite, stdout, tags=tags)
        return 0

    try:
        results = run_playback_scenarios(
            args.scenarios,
            tags=tags,
            suite=suite,
            artifacts_dir=args.artifacts,
            include_frames=args.include_frames,
        )
    except KeyError as error:
        stderr.write(f"Unknown scenario: {error.args[0]}\n")
        return 2

    for result in results:
        if args.json:
            continue
        status = "PASS" if result.ok else "FAIL"
        stdout.write(f"{status} {result.name} ({result.elapsed_ms:.1f}ms)\n")
        if result.error:
            stderr.write(f"{result.name}: {result.error}\n")
    if args.json:
        stdout.write(json.dumps(_json_summary(results), ensure_ascii=False))
        stdout.write("\n")
    return 0 if all(result.ok for result in results) else 1


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run_playback_cli(argv))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m loushang.coding.ui.playback_runner",
        description="Run native TUI playback regression scenarios.",
    )
    parser.add_argument("scenarios", nargs="*", help="Scenario names to run. Defaults to all scenarios.")
    parser.add_argument("--list", action="store_true", help="List available scenarios.")
    parser.add_argument("--tag", action="append", default=None, help="Run or list scenarios matching this tag. Repeatable.")
    parser.add_argument("--artifacts", help="Directory for manual inspection artifacts.")
    parser.add_argument("--include-frames", action="store_true", help="Include visible frames in JSONL artifacts.")
    parser.add_argument("--json", action="store_true", help="Write a machine-readable JSON summary to stdout.")
    return parser


def _write_scenario_list(suite: NativePlaybackSuite, stdout: TextIO, *, tags: Sequence[str] = ()) -> None:
    for scenario in suite.selected((), tags=tags):
        stdout.write(f"{scenario.name}\t{scenario.description}\n")


def _json_summary(results: Sequence[NativePlaybackScenarioResult]) -> dict[str, object]:
    return {
        "ok": all(result.ok for result in results),
        "results": [
            {
                "name": result.name,
                "ok": result.ok,
                "elapsed_ms": result.elapsed_ms,
                "artifacts": [str(path) for path in result.artifacts],
                "error": result.error,
            }
            for result in results
        ],
    }


def _run_completion_tab() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_completion_items("/model", "/models")
        .render()
        .type_text("/mod")
        .tab()
        .run()
    )
    result.assert_composer_text("/model ")
    result.assert_visible_contains("› /model")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_completion_session_command() -> NativeTuiInputPlaybackResult:
    session = _SessionCommandSession()
    scenario = NativeTuiInputScenario(width=80, height=12)
    scenario.app.composer.set_completion_provider(asyncio.run(coding_inline_completion_provider(session)))

    result = scenario.render().type_text("/na").tab().run()

    result.assert_composer_text("/name ")
    result.assert_visible_contains("› /name")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    assert session.commands == []
    assert session.prompts == []
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_completion_navigation_priority() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_history("history prompt")
        .with_completion_items("/model", "/models")
        .render()
        .type_text("/mod")
        .key("\x1b[B")
        .tab()
        .run()
    )
    result.assert_composer_text("/models ")
    result.assert_visible_contains("› /models")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_history_navigation() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_history("first prompt", "second prompt")
        .render()
        .type_text("draft")
        .key("\x1b[A")
        .key("\x1b[A")
        .key("\x1b[B")
        .key("\x1b[B")
        .run()
    )
    assert [state["composer_text"] for state in result.step_coding_states[1:]] == [
        "draft",
        "second prompt",
        "first prompt",
        "second prompt",
        "draft",
    ]
    result.assert_composer_text("draft")
    result.assert_visible_contains("› draft")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_local_command() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_local_commands("/status")
        .render()
        .type_text("/status")
        .enter()
        .run()
    )
    result.assert_local_texts("/status")
    result.assert_prompt_texts()
    result.assert_composer_text("")
    result.assert_visible_not_contains("› /status")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_active_surface() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_active_surface(SelectionSurface([SelectItem("Choose me", value="chosen")]))
        .with_composer_text("draft")
        .render()
        .enter()
        .run()
    )
    result.assert_surface_intents(("select", "chosen"))
    result.assert_composer_text("draft")
    result.assert_visible_contains("Choose me")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_long_transcript_input() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=100, height=18)
        .with_records(build_synthetic_long_transcript_records(turns=40, tail_tool_output_lines=300))
        .render()
        .type_chars("fresh input")
        .run()
    )
    result.assert_composer_text("fresh input")
    result.assert_visible_contains("› fresh input")
    result.assert_no_clear_screen()
    LONG_TRANSCRIPT_FRAME_BUDGET.assert_result(result, skip_first=True)
    result.assert_screen_anchor_stable("›", occurrence="last")
    return result


def _run_tool_output_preview() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=100, height=16)
        .with_records(
            (
                ToolExecutionRecord(
                    name="bash pytest tests/coding -q",
                    state="completed",
                    elapsed_seconds=0.6,
                    output="\n".join(f"line {index}" for index in range(1, 13)),
                ),
            )
        )
        .render()
        .type_text("next")
        .run()
    )
    result.assert_visible_contains("  └ line 1")
    result.assert_visible_contains("    line 3")
    result.assert_visible_contains("    ... (6 hidden lines)")
    result.assert_visible_contains("    line 12")
    result.assert_visible_not_contains("    line 4")
    result.assert_visible_not_contains("    line 9")
    result.assert_visible_contains("› next")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_bracketed_paste_large_marker() -> NativeTuiInputPlaybackResult:
    pasted = "\n".join(f"line {index}" for index in range(10))
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .render()
        .key(f"{BRACKETED_PASTE_START}{pasted}{BRACKETED_PASTE_END}")
        .run()
    )
    result.assert_composer_text(pasted)
    result.assert_visible_contains("[paste #1 +10 lines]")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_native_loop_split_bracketed_paste() -> object:
    playback = NativeTuiLoopPlayback(width=80, height=12)
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
    result.assert_text_contains("› alpha")
    result.assert_text_contains("split paste submitted once")
    result.assert_no_clear_screen()
    return result


def _run_resize_reflow_stable() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .render()
        .type_text("resize keeps composer stable")
        .resize(width=42, height=8)
        .type_text(" after shrink")
        .resize(width=100, height=14)
        .type_text(" after grow")
        .run()
    )
    result.assert_composer_text("resize keeps composer stable after shrink after grow")
    result.assert_visible_contains("after grow")
    assert any(step.diagnostics.operation_class == "resize_repaint" for step in result.steps)
    result.assert_no_clear_scrollback()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_wide_char_input_cursor() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=32, height=10)
        .render()
        .type_chars("你好🙂 terminal")
        .run()
    )
    result.assert_composer_text("你好🙂 terminal")
    result.assert_visible_contains("你好🙂 terminal")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_keyboard_shift_enter_newline() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .render()
        .type_text("first line")
        .key("\x1b[13;2u")
        .type_text("second line")
        .enter()
        .run()
    )
    result.assert_prompt_texts("first line\nsecond line")
    result.assert_composer_text("")
    result.assert_visible_contains("› first line")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_mouse_select_active_surface() -> NativeTuiInputPlaybackResult:
    surface = SelectionSurface(
        [
            SelectItem("First option", value="first"),
            SelectItem("Second option", value="second"),
            SelectItem("Third option", value="third"),
        ],
        max_visible=3,
    )
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_active_surface(surface)
        .render()
        .key("\x1b[<0;1;2M")
        .enter()
        .run()
    )
    result.assert_surface_intents(("select", "second"))
    result.assert_composer_text("")
    result.assert_visible_contains("Second option")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_terminal_control_response_hidden() -> object:
    playback = NativeTuiLoopPlayback(width=80, height=12)
    contexts: list[_RecordingTerminalContext] = []
    prompts: list[str] = []

    async def handle_prompt(text: str) -> None:
        prompts.append(text)
        playback.app.begin_assistant()
        playback.app.append_assistant_chunk("terminal control response was hidden")

    def terminal_mode_factory(_stdin: object, _stdout: object) -> _RecordingTerminalContext:
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
    result.assert_text_contains("› hello")
    result.assert_no_clear_screen()
    return result


def _run_native_loop_terminal_session_cleanup() -> object:
    playback = NativeTuiLoopPlayback(width=80, height=12)
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

    def terminal_mode_factory(stdin: object, stdout: object) -> TerminalSession:
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
    assert output.index(KITTY_QUERY_SEQUENCE) < output.index("› hello")
    assert output.index("terminal session handled cleanup") < output.index(KITTY_DISABLE_SEQUENCE)
    assert output.index(KITTY_DISABLE_SEQUENCE) < output.index(MOUSE_DISABLE_SEQUENCES[0])
    result.assert_text_contains("› hello")
    result.assert_text_not_contains("?7u")
    result.assert_text_not_contains("18;9")
    result.assert_no_clear_screen()
    return result


def _run_apple_shift_enter_normalized() -> object:
    playback = NativeTuiLoopPlayback(width=80, height=12)
    contexts: list[_AppleShiftEnterTerminalContext] = []
    prompts: list[str] = []

    async def handle_prompt(text: str) -> None:
        prompts.append(text)
        playback.app.begin_assistant()
        playback.app.append_assistant_chunk("apple shift enter inserted a newline")

    def terminal_mode_factory(_stdin: object, _stdout: object) -> _AppleShiftEnterTerminalContext:
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
    result.assert_text_contains("› first")
    result.assert_text_contains("second")
    result.assert_text_not_contains("[13;2u")
    result.assert_no_clear_screen()
    return result


DEFAULT_SUITE = NativePlaybackSuite(
    (
        NativePlaybackScenarioSpec(
            name="completion-tab",
            description="Apply tab completion without clearing or repainting the screen.",
            run=_run_completion_tab,
        ),
        NativePlaybackScenarioSpec(
            name="completion-session-command",
            description="Apply session command completion without executing the selected command.",
            run=_run_completion_session_command,
            tags=("completion", "command", "session"),
        ),
        NativePlaybackScenarioSpec(
            name="completion-navigation-priority",
            description="Route completion navigation before history navigation.",
            run=_run_completion_navigation_priority,
        ),
        NativePlaybackScenarioSpec(
            name="history-navigation",
            description="Browse prompt history from a non-empty draft and restore the draft.",
            run=_run_history_navigation,
        ),
        NativePlaybackScenarioSpec(
            name="local-command",
            description="Route a local command without echoing it as a prompt.",
            run=_run_local_command,
            tags=("command", "local"),
        ),
        NativePlaybackScenarioSpec(
            name="active-surface",
            description="Route enter to an active surface before the composer.",
            run=_run_active_surface,
        ),
        *LIFECYCLE_SCENARIOS,
        *COMMAND_ROUTING_SCENARIOS,
        *SURFACE_SCENARIOS,
        NativePlaybackScenarioSpec(
            name="long-transcript-input",
            description="Echo input after a long transcript using bounded frame updates.",
            run=_run_long_transcript_input,
        ),
        NativePlaybackScenarioSpec(
            name="tool-output-preview",
            description="Render long tool output as head, hidden-count, and tail without flicker.",
            run=_run_tool_output_preview,
        ),
        NativePlaybackScenarioSpec(
            name="bracketed-paste-large-marker",
            description="Render a large bracketed paste as a stable composer marker.",
            run=_run_bracketed_paste_large_marker,
        ),
        NativePlaybackScenarioSpec(
            name="native-loop-split-bracketed-paste",
            description="Keep split native bracketed paste atomic until the end marker arrives.",
            run=_run_native_loop_split_bracketed_paste,
        ),
        NativePlaybackScenarioSpec(
            name="resize-reflow-stable",
            description="Keep composer text and cursor stable across terminal resizes.",
            run=_run_resize_reflow_stable,
        ),
        NativePlaybackScenarioSpec(
            name="wide-char-input-cursor",
            description="Keep CJK and emoji input cursor diagnostics aligned.",
            run=_run_wide_char_input_cursor,
        ),
        NativePlaybackScenarioSpec(
            name="keyboard-shift-enter-newline",
            description="Route raw Shift+Enter to composer newline before submission.",
            run=_run_keyboard_shift_enter_newline,
        ),
        NativePlaybackScenarioSpec(
            name="mouse-select-active-surface",
            description="Route raw SGR mouse press events to an active selection surface.",
            run=_run_mouse_select_active_surface,
        ),
        NativePlaybackScenarioSpec(
            name="terminal-control-response-hidden",
            description="Consume terminal control responses without echoing them as user input.",
            run=_run_terminal_control_response_hidden,
        ),
        NativePlaybackScenarioSpec(
            name="native-loop-terminal-session-cleanup",
            description="Run native loop through TerminalSession startup, control responses, and cleanup.",
            run=_run_native_loop_terminal_session_cleanup,
        ),
        NativePlaybackScenarioSpec(
            name="apple-shift-enter-normalized",
            description="Normalize Apple Terminal Shift+Enter to a composer newline before submit.",
            run=_run_apple_shift_enter_normalized,
        ),
    )
)


if __name__ == "__main__":
    main()
