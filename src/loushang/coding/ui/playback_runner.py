from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from loushang.coding.ui.perf_probe import build_synthetic_long_transcript_records
from loushang.coding.ui.playback import (
    NativeTuiInputPlaybackResult,
    NativeTuiInputScenario,
)
from loushang.coding.ui.playback_scenarios.budgets import (
    INTERACTION_FRAME_BUDGET,
    LONG_TRANSCRIPT_FRAME_BUDGET,
)
from loushang.coding.ui.playback_scenarios.command import COMMAND_ROUTING_SCENARIOS
from loushang.coding.ui.playback_scenarios.composer import COMPOSER_SCENARIOS
from loushang.coding.ui.playback_scenarios.lifecycle import LIFECYCLE_SCENARIOS
from loushang.coding.ui.playback_scenarios.surface import SURFACE_SCENARIOS
from loushang.coding.ui.playback_scenarios.terminal import TERMINAL_SCENARIOS
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


DEFAULT_SUITE = NativePlaybackSuite(
    (
        *COMPOSER_SCENARIOS,
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
        *TERMINAL_SCENARIOS,
        NativePlaybackScenarioSpec(
            name="mouse-select-active-surface",
            description="Route raw SGR mouse press events to an active selection surface.",
            run=_run_mouse_select_active_surface,
        ),
    )
)


if __name__ == "__main__":
    main()
