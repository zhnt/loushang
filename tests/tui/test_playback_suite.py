from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest

from loushang.tui.playback_suite import (
    PlaybackScenarioSpec,
    PlaybackSuite,
    normalized_tags,
    run_playback_cli,
    run_playback_scenarios,
)


def test_playback_suite_selects_named_and_tagged_scenarios() -> None:
    smoke = PlaybackScenarioSpec(
        name="smoke",
        description="Smoke scenario.",
        run=lambda: None,
        tags=(" Fast ", "terminal"),
    )
    slow = PlaybackScenarioSpec(
        name="slow",
        description="Slow scenario.",
        run=lambda: None,
        tags=("terminal",),
    )
    suite = PlaybackSuite((smoke, slow))

    assert suite.scenarios == (smoke, slow)
    assert suite.names() == ("smoke", "slow")
    assert suite.get("smoke") is smoke
    assert suite.selected((), tags=(" FAST ",)) == (smoke,)
    assert suite.selected(("slow", "smoke"), tags=("TERMINAL",)) == (
        slow,
        smoke,
    )
    assert normalized_tags((" Fast ", "", "FAST", " terminal ")) == {
        "fast",
        "terminal",
    }

    with pytest.raises(KeyError) as error:
        suite.get("missing")
    assert error.value.args == ("missing",)


@dataclass(frozen=True)
class _Artifacts:
    trace: Path
    screen: Path


def test_run_playback_scenarios_writes_success_artifacts(tmp_path: Path) -> None:
    calls: list[tuple[Path, str, bool]] = []

    class Result:
        def write_artifacts(
            self,
            directory: str | Path,
            *,
            basename: str,
            include_frames: bool,
        ) -> _Artifacts:
            output_dir = Path(directory)
            calls.append((output_dir, basename, include_frames))
            return _Artifacts(
                trace=output_dir / f"{basename}.jsonl",
                screen=output_dir / f"{basename}-screen.txt",
            )

    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="success",
                description="Successful scenario.",
                run=Result,
            ),
        )
    )

    results = run_playback_scenarios(
        suite=suite,
        artifacts_dir=tmp_path,
        include_frames=True,
    )

    assert calls == [(tmp_path, "success", True)]
    assert len(results) == 1
    assert results[0].name == "success"
    assert results[0].ok is True
    assert results[0].elapsed_ms >= 0
    assert results[0].artifacts == (
        tmp_path / "success.jsonl",
        tmp_path / "success-screen.txt",
    )
    assert results[0].error is None


def test_run_playback_scenarios_supports_legacy_artifact_writer(tmp_path: Path) -> None:
    calls: list[tuple[Path, str]] = []

    @dataclass(frozen=True)
    class Artifacts:
        trace: Path

    class Result:
        def write_artifacts(
            self,
            directory: str | Path,
            *,
            basename: str,
        ) -> Artifacts:
            output_dir = Path(directory)
            calls.append((output_dir, basename))
            return Artifacts(trace=output_dir / f"{basename}.jsonl")

    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="legacy",
                description="Legacy artifact writer.",
                run=Result,
            ),
        )
    )

    results = run_playback_scenarios(
        suite=suite,
        artifacts_dir=tmp_path,
        include_frames=True,
    )

    assert calls == [(tmp_path, "legacy")]
    assert results[0].artifacts == (tmp_path / "legacy.jsonl",)


def test_run_playback_scenarios_records_assertion_failure(tmp_path: Path) -> None:
    def fail() -> None:
        raise AssertionError("forced failure")

    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="failure",
                description="Failing scenario.",
                run=fail,
            ),
        )
    )

    results = run_playback_scenarios(suite=suite, artifacts_dir=tmp_path)

    assert len(results) == 1
    assert results[0].name == "failure"
    assert results[0].ok is False
    assert results[0].artifacts == (tmp_path / "failure-error.txt",)
    assert results[0].error == "forced failure"
    assert (tmp_path / "failure-error.txt").read_text(
        encoding="utf-8"
    ) == "forced failure\n"


def test_run_playback_scenarios_preserves_review_artifacts_on_failure(
    tmp_path: Path,
) -> None:
    class Result:
        def write_artifacts(
            self,
            directory: str | Path,
            *,
            basename: str,
            include_frames: bool,
        ) -> _Artifacts:
            assert include_frames is True
            output_dir = Path(directory)
            return _Artifacts(
                trace=output_dir / f"{basename}.jsonl",
                screen=output_dir / f"{basename}-screen.txt",
            )

    def fail() -> None:
        error = AssertionError("review failure")
        setattr(error, "playback_result", Result())
        raise error

    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="review",
                description="Reviewable failure.",
                run=fail,
            ),
        )
    )

    results = run_playback_scenarios(
        suite=suite,
        artifacts_dir=tmp_path,
        include_frames=True,
    )

    assert results[0].artifacts == (
        tmp_path / "review-error.txt",
        tmp_path / "review.jsonl",
        tmp_path / "review-screen.txt",
    )


def test_run_playback_scenarios_propagates_non_assertion_errors() -> None:
    def fail() -> None:
        raise RuntimeError("unexpected")

    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="failure",
                description="Unexpected failure.",
                run=fail,
            ),
        )
    )

    with pytest.raises(RuntimeError, match="unexpected"):
        run_playback_scenarios(suite=suite)


def test_run_playback_cli_lists_and_runs_an_injected_suite() -> None:
    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="smoke",
                description="Smoke scenario.",
                run=lambda: None,
                tags=("fast",),
            ),
        )
    )
    stdout = StringIO()

    assert run_playback_cli(suite, ["--list"], stdout=stdout) == 0
    assert stdout.getvalue() == "smoke\tSmoke scenario.\n"

    stdout = StringIO()
    assert run_playback_cli(suite, ["smoke"], stdout=stdout) == 0
    assert stdout.getvalue().startswith("PASS smoke (")


def test_run_playback_cli_reports_unknown_scenario_and_json() -> None:
    suite = PlaybackSuite(
        (
            PlaybackScenarioSpec(
                name="smoke",
                description="Smoke scenario.",
                run=lambda: None,
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    assert (
        run_playback_cli(
            suite,
            ["missing"],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )
    assert stderr.getvalue() == "Unknown scenario: missing\n"

    stdout = StringIO()
    assert run_playback_cli(suite, ["--json"], stdout=stdout) == 0
    assert '"name": "smoke"' in stdout.getvalue()
