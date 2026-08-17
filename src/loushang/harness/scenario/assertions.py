from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from pathlib import Path

from loushang.harness.scenario.events import WorkflowEvent, find_event
from loushang.harness.scenario.protocols import CommandRunner
from loushang.harness.scenario.schema import (
    CheckResult,
    CommandExpectation,
    StepExpectation,
    WorkflowExpectation,
)

_MISSING = object()


async def evaluate_expectations(
    expect: StepExpectation,
    *,
    assistant_text: str,
    cwd: Path,
    command_runner: CommandRunner | None = None,
) -> tuple[CheckResult, ...]:
    checks: list[CheckResult] = []
    checks.extend(_assistant_checks(expect, assistant_text))
    checks.extend(_file_checks(expect, cwd=cwd))
    if expect.command is not None:
        checks.extend(
            await _command_checks(
                expect.command,
                cwd=cwd,
                command_runner=command_runner,
            )
        )
    if expect.no_traceback:
        checks.append(
            CheckResult(
                label="assistant has no traceback",
                ok="Traceback (most recent call last)" not in assistant_text,
            )
        )
    return tuple(checks)


def evaluate_workflow_expectations(
    expect: WorkflowExpectation,
    *,
    events: tuple[WorkflowEvent, ...],
    queue_state: object | None = None,
    session_state: object | None = None,
    session_stats: object | None = None,
    context_usage: object | None = None,
) -> tuple[CheckResult, ...]:
    checks: list[CheckResult] = []
    for pattern in expect.events:
        matched = find_event(events, pattern)
        checks.append(
            CheckResult(
                label=f"event exists {pattern.event}",
                ok=matched is not None,
                detail="" if matched is not None else _missing_event_detail(pattern),
            )
        )
    for pattern in expect.not_events:
        matched = find_event(events, pattern)
        checks.append(
            CheckResult(
                label=f"event absent {pattern.event}",
                ok=matched is None,
                detail="" if matched is None else _unexpected_event_detail(pattern),
            )
        )
    for queue_name, expected in expect.queue.items():
        actual = _queue_items(queue_state, queue_name)
        checks.append(
            CheckResult(
                label=f"queue {queue_name}",
                ok=actual == expected,
                detail=""
                if actual == expected
                else f"expected {expected!r}, got {actual!r}",
            )
        )
    checks.extend(
        _session_state_checks(
            expect.session_state, session_state, path=("session_state",)
        )
    )
    checks.extend(
        _session_state_checks(
            expect.session_stats, session_stats, path=("session_stats",)
        )
    )
    checks.extend(
        _session_state_checks(
            expect.context_usage, context_usage, path=("context_usage",)
        )
    )
    return tuple(checks)


def _missing_event_detail(pattern) -> str:
    suffix = f" containing {pattern.contains!r}" if pattern.contains is not None else ""
    return f"missing event {pattern.event}{suffix}"


def _unexpected_event_detail(pattern) -> str:
    suffix = f" containing {pattern.contains!r}" if pattern.contains is not None else ""
    return f"unexpected event {pattern.event}{suffix}"


def _queue_items(queue_state: object | None, name: str) -> tuple[str, ...]:
    if queue_state is None:
        return ()
    value = getattr(queue_state, name, ())
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()


def _session_state_checks(
    expected: Mapping[str, object],
    actual: object | None,
    *,
    path: tuple[str, ...],
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for key, expected_value in expected.items():
        child_path = (*path, str(key))
        actual_value = _state_child(actual, str(key))
        if isinstance(expected_value, Mapping):
            checks.extend(
                _session_state_checks(expected_value, actual_value, path=child_path)
            )
            continue
        normalized_expected = _normalize_state_value(expected_value)
        normalized_actual = _normalize_state_value(actual_value)
        ok = normalized_actual == normalized_expected
        checks.append(
            CheckResult(
                label=".".join(child_path),
                ok=ok,
                detail=""
                if ok
                else f"expected {normalized_expected!r}, got {normalized_actual!r}",
            )
        )
    return checks


def _state_child(value: object | None, key: str) -> object:
    if value is None:
        return _MISSING
    if isinstance(value, Mapping):
        return value.get(key, _MISSING)
    return getattr(value, key, _MISSING)


def _normalize_state_value(value: object) -> object:
    if value is _MISSING:
        return "<missing>"
    if isinstance(value, Mapping):
        return {str(key): _normalize_state_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(_normalize_state_value(item) for item in value)
    return value


def _assistant_checks(
    expect: StepExpectation, assistant_text: str
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for expected in expect.assistant_contains:
        checks.append(
            CheckResult(
                label=f"assistant contains {expected!r}",
                ok=expected in assistant_text,
                detail="" if expected in assistant_text else "substring not found",
            )
        )
    if expect.assistant_contains_any:
        matched = [
            value for value in expect.assistant_contains_any if value in assistant_text
        ]
        checks.append(
            CheckResult(
                label="assistant contains any",
                ok=bool(matched),
                detail=""
                if matched
                else f"none found: {', '.join(repr(value) for value in expect.assistant_contains_any)}",
            )
        )
    for unexpected in expect.assistant_not_contains:
        checks.append(
            CheckResult(
                label=f"assistant does not contain {unexpected!r}",
                ok=unexpected not in assistant_text,
                detail="" if unexpected not in assistant_text else "substring found",
            )
        )
    return checks


def _file_checks(expect: StepExpectation, *, cwd: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for path_text in expect.files_exist:
        path = _resolve_workflow_path(cwd, path_text)
        checks.append(
            CheckResult(
                label=f"file exists {path_text}",
                ok=path.exists(),
                detail="" if path.exists() else f"missing: {path}",
            )
        )
    for path_text in expect.files_not_exist:
        path = _resolve_workflow_path(cwd, path_text)
        checks.append(
            CheckResult(
                label=f"file absent {path_text}",
                ok=not path.exists(),
                detail="" if not path.exists() else f"present: {path}",
            )
        )
    for path_text, expected in expect.files_contain.items():
        path = _resolve_workflow_path(cwd, path_text)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            checks.append(
                CheckResult(
                    label=f"file contains {path_text}",
                    ok=False,
                    detail=str(error),
                )
            )
            continue
        checks.append(
            CheckResult(
                label=f"file contains {path_text}",
                ok=expected in content,
                detail=""
                if expected in content
                else f"substring not found: {expected!r}",
            )
        )
    return checks


async def _command_checks(
    expect: CommandExpectation,
    *,
    cwd: Path,
    command_runner: CommandRunner | None,
) -> list[CheckResult]:
    if command_runner is None:
        return [
            CheckResult(
                label=f"command exits {expect.exit_code}",
                ok=False,
                detail="no command runner was supplied by the Product",
            )
        ]
    try:
        completed = command_runner(
            expect.run,
            cwd=cwd,
            timeout_s=expect.timeout_s,
        )
        if inspect.isawaitable(completed):
            completed = await completed
    except Exception as error:
        return [
            CheckResult(
                label=f"command exits {expect.exit_code}",
                ok=False,
                detail=f"command runner failed: {error}",
            )
        ]
    if completed.error is not None:
        return [
            CheckResult(
                label=f"command exits {expect.exit_code}",
                ok=False,
                detail=completed.error,
            )
        ]
    checks = [
        CheckResult(
            label=f"command exits {expect.exit_code}",
            ok=completed.exit_code == expect.exit_code,
            detail=""
            if completed.exit_code == expect.exit_code
            else f"exit code {completed.exit_code}",
        )
    ]
    for expected in expect.stdout_contains:
        checks.append(
            CheckResult(
                label=f"command stdout contains {expected!r}",
                ok=expected in completed.stdout,
                detail="" if expected in completed.stdout else "substring not found",
            )
        )
    for expected in expect.stderr_contains:
        checks.append(
            CheckResult(
                label=f"command stderr contains {expected!r}",
                ok=expected in completed.stderr,
                detail="" if expected in completed.stderr else "substring not found",
            )
        )
    for unexpected in expect.stderr_not_contains:
        checks.append(
            CheckResult(
                label=f"command stderr does not contain {unexpected!r}",
                ok=unexpected not in completed.stderr,
                detail="" if unexpected not in completed.stderr else "substring found",
            )
        )
    return checks


def _resolve_workflow_path(cwd: Path, path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path
    return cwd / path
