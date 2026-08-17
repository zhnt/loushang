"""CLI entry helpers for Product-neutral scripted scenarios."""

from __future__ import annotations

import asyncio
import inspect
import json
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TextIO

from loushang.harness.scenario.fake_runtime import FakeWorkflowAdapter
from loushang.harness.scenario.loader import load_workflow, resolve_workflow_files
from loushang.harness.scenario.protocols import CommandRunner, WorkflowAdapter
from loushang.harness.scenario.runner import (
    AgentSessionWorkflowAdapter,
    run_workflow,
)
from loushang.harness.scenario.schema import WorkflowResult

WorkflowCliRunner = Callable[..., Awaitable[int]]
AgentSessionPreparer = Callable[[object], Awaitable[None]]


async def run_fake_workflow_cli(
    workflow_path: str,
    *,
    project_root: str | Path,
    runner: WorkflowCliRunner,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool,
    output_mode: str,
    format_error: Callable[[BaseException], str] = str,
) -> int | None:
    """Run an all-fake workflow before a Product runtime is constructed."""

    root = Path(project_root)
    try:
        workflow_files = resolve_workflow_files(root, workflow_path)
        workflows = [load_workflow(path) for path in workflow_files]
    except Exception as error:
        stderr.write(f"Error: {format_error(error)}\n")
        return 1
    if not workflows or any(workflow.backend != "fake" for workflow in workflows):
        return None
    return await runner(
        runtime=None,
        session=None,
        workflow_path=Path(workflow_path),
        cwd=root,
        stdout=stdout,
        stderr=stderr,
        verbose=verbose,
        output_mode=output_mode,
    )


async def run_workflow_cli(
    *,
    runtime: object | None,
    session: object | None,
    workflow_path: str | Path,
    cwd: str | Path,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool = False,
    default_step_timeout_s: float | None = 300.0,
    output_mode: str = "text",
    prepare_agent_session: AgentSessionPreparer | None = None,
    command_runner: CommandRunner | None = None,
) -> int:
    """Run a workflow matrix through the existing scenario runner."""

    exit_code = 0
    try:
        root = Path(cwd).resolve()
        workflow_files = resolve_workflow_files(root, workflow_path)
        results: list[WorkflowResult] = []
        passed = 0
        failed = 0
        for workflow_file in workflow_files:
            workflow = load_workflow(workflow_file)
            if output_mode != "json":
                stdout.write(f"workflow: {workflow.name}\n")
                stdout.flush()
            adapter = await resolve_standard_workflow_adapter(
                workflow.backend,
                session,
                prepare_agent_session=prepare_agent_session,
            )
            result = await run_workflow(
                workflow,
                adapter=adapter,
                cwd=root,
                default_step_timeout_s=default_step_timeout_s,
                on_step_start=(
                    None
                    if output_mode == "json"
                    else lambda index, total, step: _write_step_progress(
                        stdout, index, total, _step_progress_label(step)
                    )
                ),
                command_runner=command_runner,
            )
            results.append(result)
            if output_mode != "json":
                stdout.write(format_workflow_report(result, include_header=False))
            if result.ok:
                passed += 1
            else:
                failed += 1
        if output_mode == "json":
            stdout.write(format_workflow_json_report(tuple(results)))
        elif len(workflow_files) > 1:
            stdout.write(f"workflow summary: {passed} passed, {failed} failed\n")
        exit_code = 0 if failed == 0 else 1
    except asyncio.CancelledError:
        stderr.write("Interrupted.\n")
        exit_code = 130
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        if verbose:
            traceback.print_exception(
                type(error), error, error.__traceback__, file=stderr
            )
        exit_code = 1
    finally:
        try:
            await dispose_runtime_or_session(runtime, session)
        except Exception as error:
            stderr.write(f"Error: {error}\n")
            if verbose:
                traceback.print_exception(
                    type(error), error, error.__traceback__, file=stderr
                )
            exit_code = 1
    return exit_code


async def resolve_standard_workflow_adapter(
    backend: str | None,
    session: object | None,
    *,
    prepare_agent_session: AgentSessionPreparer | None = None,
) -> WorkflowAdapter:
    if backend == "fake":
        return FakeWorkflowAdapter()
    if backend is None:
        if session is None:
            raise RuntimeError("Agent workflow requires an active session")
        if prepare_agent_session is not None:
            await prepare_agent_session(session)
        return AgentSessionWorkflowAdapter(session)
    raise ValueError(f"Unknown workflow backend: {backend}")


def format_workflow_report(
    result: WorkflowResult,
    *,
    include_header: bool = True,
) -> str:
    lines = [f"workflow: {result.name}"] if include_header else []
    for step in result.step_results:
        status = "PASS" if step.ok else "FAIL"
        lines.append(f"[{step.index}] {status} {step.prompt}")
        if step.error:
            lines.append(f"  error: {step.error}")
        for check in step.checks:
            check_status = "ok" if check.ok else "fail"
            detail = f" - {check.detail}" if check.detail else ""
            lines.append(f"  {check_status}: {check.label}{detail}")
    lines.append("PASS" if result.ok else "FAIL")
    return "\n".join(lines) + "\n"


def format_workflow_json_report(
    results: tuple[WorkflowResult, ...],
) -> str:
    passed = sum(1 for result in results if result.ok)
    failed = len(results) - passed
    payload = {
        "ok": failed == 0,
        "passed": passed,
        "failed": failed,
        "workflows": [_workflow_result_payload(result) for result in results],
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


async def dispose_runtime_or_session(
    runtime: object | None,
    session: object | None,
) -> None:
    disposer = getattr(runtime, "dispose", None)
    if not callable(disposer):
        disposer = getattr(session, "dispose", None)
    if not callable(disposer):
        return
    result = disposer()
    if inspect.isawaitable(result):
        await result


def _write_step_progress(
    stdout: TextIO,
    index: int,
    total: int,
    prompt: str,
) -> None:
    stdout.write(f"[{index}/{total}] running: {prompt}\n")
    stdout.flush()


def _step_progress_label(step: object) -> str:
    for name in ("prompt", "text", "event", "kind"):
        value = getattr(step, name, None)
        if isinstance(value, str) and value:
            return value
    return step.__class__.__name__


def _workflow_result_payload(result: WorkflowResult) -> dict[str, object]:
    return {
        "name": result.name,
        "ok": result.ok,
        "events": [
            {
                "type": event.type,
                "text": event.text,
                "data": dict(event.data),
            }
            for event in result.events
        ],
        "steps": [
            {
                "index": step.index,
                "prompt": step.prompt,
                "ok": step.ok,
                "assistant_text": step.assistant_text,
                "error": step.error,
                "checks": [
                    {
                        "label": check.label,
                        "ok": check.ok,
                        "detail": check.detail,
                    }
                    for check in step.checks
                ],
            }
            for step in result.step_results
        ],
    }


__all__ = [
    "AgentSessionPreparer",
    "WorkflowCliRunner",
    "dispose_runtime_or_session",
    "format_workflow_json_report",
    "format_workflow_report",
    "resolve_standard_workflow_adapter",
    "run_fake_workflow_cli",
    "run_workflow_cli",
]
