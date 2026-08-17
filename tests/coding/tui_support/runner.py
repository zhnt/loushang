from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from loushang.tui.playback_suite import (
    PlaybackScenarioResult as ScreenPlaybackScenarioResult,
)
from loushang.tui.playback_suite import (
    PlaybackScenarioSpec as ScreenPlaybackScenarioSpec,
)
from loushang.tui.playback_suite import PlaybackSuite as ScreenPlaybackSuite
from loushang.tui.playback_suite import run_playback_cli as _run_playback_cli
from loushang.tui.playback_suite import (
    run_playback_scenarios as _run_playback_scenarios,
)
from tests.coding.tui_support.scenarios.command import COMMAND_ROUTING_SCENARIOS
from tests.coding.tui_support.scenarios.composer import COMPOSER_SCENARIOS
from tests.coding.tui_support.scenarios.lifecycle import LIFECYCLE_SCENARIOS
from tests.coding.tui_support.scenarios.multiagent import MULTIAGENT_SCENARIOS
from tests.coding.tui_support.scenarios.permissions import PERMISSION_SCENARIOS
from tests.coding.tui_support.scenarios.product import PRODUCT_SCENARIOS
from tests.coding.tui_support.scenarios.surface import SURFACE_SCENARIOS
from tests.coding.tui_support.scenarios.terminal import TERMINAL_SCENARIOS
from tests.coding.tui_support.scenarios.transcript import TRANSCRIPT_SCENARIOS

DEFAULT_SUITE = ScreenPlaybackSuite(
    (
        *COMPOSER_SCENARIOS,
        *LIFECYCLE_SCENARIOS,
        *MULTIAGENT_SCENARIOS,
        *PERMISSION_SCENARIOS,
        *PRODUCT_SCENARIOS,
        *COMMAND_ROUTING_SCENARIOS,
        *SURFACE_SCENARIOS,
        *TRANSCRIPT_SCENARIOS,
        *TERMINAL_SCENARIOS,
    )
)


def run_playback_scenarios(
    names: Sequence[str] = (),
    *,
    tags: Sequence[str] = (),
    suite: ScreenPlaybackSuite | None = None,
    artifacts_dir: str | Path | None = None,
    include_frames: bool = False,
) -> tuple[ScreenPlaybackScenarioResult, ...]:
    return _run_playback_scenarios(
        names,
        tags=tags,
        suite=DEFAULT_SUITE if suite is None else suite,
        artifacts_dir=artifacts_dir,
        include_frames=include_frames,
    )


def run_playback_cli(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    suite: ScreenPlaybackSuite | None = None,
) -> int:
    return _run_playback_cli(
        DEFAULT_SUITE if suite is None else suite,
        argv,
        stdout=stdout,
        stderr=stderr,
        prog="scripts/run_tui_playback.py",
        description="Run screen TUI playback regression scenarios.",
    )


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run_playback_cli(argv))


__all__ = [
    "DEFAULT_SUITE",
    "ScreenPlaybackScenarioResult",
    "ScreenPlaybackScenarioSpec",
    "ScreenPlaybackSuite",
    "run_playback_cli",
    "run_playback_scenarios",
]


if __name__ == "__main__":
    main()
