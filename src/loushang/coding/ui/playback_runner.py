from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from loushang.coding.ui.playback_scenarios.command import COMMAND_ROUTING_SCENARIOS
from loushang.coding.ui.playback_scenarios.composer import COMPOSER_SCENARIOS
from loushang.coding.ui.playback_scenarios.lifecycle import LIFECYCLE_SCENARIOS
from loushang.coding.ui.playback_scenarios.surface import SURFACE_SCENARIOS
from loushang.coding.ui.playback_scenarios.terminal import TERMINAL_SCENARIOS
from loushang.coding.ui.playback_scenarios.transcript import TRANSCRIPT_SCENARIOS
from loushang.coding.ui.playback_suite import (
    NativePlaybackScenarioResult,
    NativePlaybackScenarioSpec,
    NativePlaybackSuite,
)
from loushang.coding.ui.playback_suite import (
    run_playback_scenarios as _run_playback_scenarios,
)

__all__ = [
    "DEFAULT_SUITE",
    "NativePlaybackScenarioResult",
    "NativePlaybackScenarioSpec",
    "NativePlaybackSuite",
    "run_playback_cli",
    "run_playback_scenarios",
]


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


DEFAULT_SUITE = NativePlaybackSuite(
    (
        *COMPOSER_SCENARIOS,
        *LIFECYCLE_SCENARIOS,
        *COMMAND_ROUTING_SCENARIOS,
        *SURFACE_SCENARIOS,
        *TRANSCRIPT_SCENARIOS,
        *TERMINAL_SCENARIOS,
    )
)


if __name__ == "__main__":
    main()
