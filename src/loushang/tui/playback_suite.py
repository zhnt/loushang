from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True, slots=True)
class PlaybackScenarioSpec:
    name: str
    description: str
    run: Callable[[], object]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlaybackScenarioResult:
    name: str
    ok: bool
    elapsed_ms: float
    artifacts: tuple[Path, ...] = ()
    error: str | None = None


class PlaybackSuite:
    def __init__(self, scenarios: Sequence[PlaybackScenarioSpec]) -> None:
        self._scenarios = tuple(scenarios)
        self._by_name = {scenario.name: scenario for scenario in self._scenarios}

    @property
    def scenarios(self) -> tuple[PlaybackScenarioSpec, ...]:
        return self._scenarios

    def names(self) -> tuple[str, ...]:
        return tuple(scenario.name for scenario in self._scenarios)

    def selected(
        self, names: Sequence[str], *, tags: Sequence[str] = ()
    ) -> tuple[PlaybackScenarioSpec, ...]:
        scenarios = (
            self._scenarios if not names else tuple(self.get(name) for name in names)
        )
        tag_filter = normalized_tags(tags)
        if not tag_filter:
            return scenarios
        return tuple(
            scenario
            for scenario in scenarios
            if tag_filter.issubset(normalized_tags(scenario.tags))
        )

    def get(self, name: str) -> PlaybackScenarioSpec:
        try:
            return self._by_name[name]
        except KeyError as error:
            raise KeyError(name) from error


def run_playback_scenarios(
    names: Sequence[str] = (),
    *,
    tags: Sequence[str] = (),
    suite: PlaybackSuite,
    artifacts_dir: str | Path | None = None,
    include_frames: bool = False,
) -> tuple[PlaybackScenarioResult, ...]:
    results: list[PlaybackScenarioResult] = []
    for scenario in suite.selected(tuple(names), tags=tuple(tags)):
        started = time.perf_counter()
        try:
            scenario_result = scenario.run()
            artifacts = _write_artifacts(
                scenario.name,
                scenario_result,
                artifacts_dir=artifacts_dir,
                include_frames=include_frames,
            )
            results.append(
                PlaybackScenarioResult(
                    name=scenario.name,
                    ok=True,
                    elapsed_ms=_elapsed_ms(started),
                    artifacts=artifacts,
                )
            )
        except AssertionError as error:
            artifacts = _write_error_artifacts(
                scenario.name,
                error,
                artifacts_dir=artifacts_dir,
                include_frames=include_frames,
            )
            results.append(
                PlaybackScenarioResult(
                    name=scenario.name,
                    ok=False,
                    elapsed_ms=_elapsed_ms(started),
                    artifacts=artifacts,
                    error=str(error),
                )
            )
    return tuple(results)


def run_playback_cli(
    suite: PlaybackSuite,
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    prog: str = "python -m loushang.tui.playback_suite",
    description: str = "Run terminal playback regression scenarios.",
) -> int:
    """Run an injected playback catalog through the shared command-line host."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = _playback_parser(prog=prog, description=description)
    args = parser.parse_args(sys.argv[1:] if argv is None else tuple(argv))
    tags = tuple(args.tag or ())
    if args.list:
        for scenario in suite.selected((), tags=tags):
            stdout.write(f"{scenario.name}\t{scenario.description}\n")
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

    if args.json:
        json.dump(_json_summary(results), stdout, ensure_ascii=False)
        stdout.write("\n")
    else:
        for result in results:
            status = "PASS" if result.ok else "FAIL"
            stdout.write(f"{status} {result.name} ({result.elapsed_ms:.1f}ms)\n")
            if result.error:
                stderr.write(f"{result.name}: {result.error}\n")
    return 0 if all(result.ok for result in results) else 1


def normalized_tags(tags: Sequence[str]) -> frozenset[str]:
    return frozenset(tag.strip().lower() for tag in tags if tag.strip())


def _playback_parser(
    *,
    prog: str,
    description: str,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "scenarios",
        nargs="*",
        help="Scenario names to run. Defaults to all scenarios.",
    )
    parser.add_argument("--list", action="store_true", help="List available scenarios.")
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        help="Run or list scenarios matching this tag. Repeatable.",
    )
    parser.add_argument("--artifacts", help="Directory for manual inspection artifacts.")
    parser.add_argument(
        "--include-frames",
        action="store_true",
        help="Include visible frames in JSONL artifacts.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write a machine-readable JSON summary to stdout.",
    )
    return parser


def _json_summary(
    results: Sequence[PlaybackScenarioResult],
) -> dict[str, object]:
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


def _write_artifacts(
    name: str,
    result: object,
    *,
    artifacts_dir: str | Path | None,
    include_frames: bool,
) -> tuple[Path, ...]:
    if artifacts_dir is None:
        return ()
    writer = getattr(result, "write_artifacts", None)
    if not callable(writer):
        return ()
    if "include_frames" in inspect.signature(writer).parameters:
        artifacts = writer(artifacts_dir, basename=name, include_frames=include_frames)
    else:
        artifacts = writer(artifacts_dir, basename=name)
    return tuple(Path(getattr(artifacts, field.name)) for field in fields(artifacts))


def _write_error_artifacts(
    name: str,
    error: AssertionError,
    *,
    artifacts_dir: str | Path | None,
    include_frames: bool,
) -> tuple[Path, ...]:
    if artifacts_dir is None:
        return ()
    output_dir = Path(artifacts_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}-error.txt"
    path.write_text(f"{error}\n", encoding="utf-8")
    playback_artifacts = _write_failure_playback_artifacts(
        name,
        error,
        artifacts_dir=artifacts_dir,
        include_frames=include_frames,
    )
    return (path, *playback_artifacts)


def _write_failure_playback_artifacts(
    name: str,
    error: AssertionError,
    *,
    artifacts_dir: str | Path,
    include_frames: bool,
) -> tuple[Path, ...]:
    result = getattr(error, "playback_result", None)
    if result is None:
        return ()
    return _write_artifacts(
        name,
        result,
        artifacts_dir=artifacts_dir,
        include_frames=include_frames,
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


__all__ = [
    "PlaybackScenarioResult",
    "PlaybackScenarioSpec",
    "PlaybackSuite",
    "normalized_tags",
    "run_playback_cli",
    "run_playback_scenarios",
]
