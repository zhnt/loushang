from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NativePlaybackScenarioSpec:
    name: str
    description: str
    run: Callable[[], object]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NativePlaybackScenarioResult:
    name: str
    ok: bool
    elapsed_ms: float
    artifacts: tuple[Path, ...] = ()
    error: str | None = None


class NativePlaybackSuite:
    def __init__(self, scenarios: Sequence[NativePlaybackScenarioSpec]) -> None:
        self._scenarios = tuple(scenarios)
        self._by_name = {scenario.name: scenario for scenario in self._scenarios}

    @property
    def scenarios(self) -> tuple[NativePlaybackScenarioSpec, ...]:
        return self._scenarios

    def names(self) -> tuple[str, ...]:
        return tuple(scenario.name for scenario in self._scenarios)

    def selected(self, names: Sequence[str], *, tags: Sequence[str] = ()) -> tuple[NativePlaybackScenarioSpec, ...]:
        scenarios = self._scenarios if not names else tuple(self.get(name) for name in names)
        tag_filter = normalized_tags(tags)
        if not tag_filter:
            return scenarios
        return tuple(scenario for scenario in scenarios if tag_filter.issubset(normalized_tags(scenario.tags)))

    def get(self, name: str) -> NativePlaybackScenarioSpec:
        try:
            return self._by_name[name]
        except KeyError as error:
            raise KeyError(name) from error


def run_playback_scenarios(
    names: Sequence[str] = (),
    *,
    tags: Sequence[str] = (),
    suite: NativePlaybackSuite,
    artifacts_dir: str | Path | None = None,
    include_frames: bool = False,
) -> tuple[NativePlaybackScenarioResult, ...]:
    results: list[NativePlaybackScenarioResult] = []
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
                NativePlaybackScenarioResult(
                    name=scenario.name,
                    ok=True,
                    elapsed_ms=_elapsed_ms(started),
                    artifacts=artifacts,
                )
            )
        except AssertionError as error:
            artifacts = _write_error_artifact(scenario.name, error, artifacts_dir=artifacts_dir)
            results.append(
                NativePlaybackScenarioResult(
                    name=scenario.name,
                    ok=False,
                    elapsed_ms=_elapsed_ms(started),
                    artifacts=artifacts,
                    error=str(error),
                )
            )
    return tuple(results)


def normalized_tags(tags: Sequence[str]) -> frozenset[str]:
    return frozenset(tag.strip().lower() for tag in tags if tag.strip())


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


def _write_error_artifact(
    name: str,
    error: AssertionError,
    *,
    artifacts_dir: str | Path | None,
) -> tuple[Path, ...]:
    if artifacts_dir is None:
        return ()
    output_dir = Path(artifacts_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}-error.txt"
    path.write_text(f"{error}\n", encoding="utf-8")
    return (path,)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


__all__ = [
    "NativePlaybackScenarioResult",
    "NativePlaybackScenarioSpec",
    "NativePlaybackSuite",
    "normalized_tags",
    "run_playback_scenarios",
]
