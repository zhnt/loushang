from __future__ import annotations

import argparse
import asyncio
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loushang.coding.types import ModelSelection

from loushang.ai import Model, TextPart, UserMessage
from loushang.coding.ui import mode as ui_mode
from loushang.foundation.observability._router import (
    capture_observability,
    configure_observability,
    restore_observability,
)
from loushang.foundation.observability.debug_sink import DebugLogSink
from loushang.foundation.observability.trace_sink import TraceJSONLSink

CaseName = str

CASES: tuple[CaseName, ...] = (
    "follow-up",
    "steer",
    "active-follow-up",
    "abort-recovery",
    "provider-cancel-recovery",
    "tool-error-recovery",
)


class TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


@dataclass
class ScenarioSession:
    cwd: Path
    session_id: str = "scenario-session"
    session_name: str = "scenario-session"
    prompts: list[str] = field(default_factory=list)
    steers: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    listeners: list[Callable[[dict[str, object]], object]] = field(default_factory=list)
    set_model_calls: list[object] = field(default_factory=list)
    aborted: bool = False
    bash_aborted: bool = False
    unsubscribed: bool = False
    running: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    abort_signal: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.session_manager = SimpleNamespace(get_cwd=lambda: str(self.cwd))
        self.current_model: object = ModelSelection(provider="unknown", model_id="unknown")
        self.model_details = [
            Model(
                id="kimi-for-coding",
                provider="moonshot",
                endpoint="kimi-code-anthropic",
            )
        ]

    def get_model_selection(self) -> object:
        return self.current_model

    def get_available_model_details(self) -> list[object]:
        return self.model_details

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        if isinstance(selection, Model):
            self.current_model = ModelSelection(provider=selection.provider_id, model_id=selection.id)
        else:
            self.current_model = selection

    def subscribe(self, listener: Callable[[dict[str, object]], object]):
        self.listeners.append(listener)

        def unsubscribe() -> None:
            self.unsubscribed = True
            if listener in self.listeners:
                self.listeners.remove(listener)

        return unsubscribe

    def is_running(self) -> bool:
        return self.running

    async def prompt(self, text: str) -> None:
        self.prompts.append(text)
        self.running = True
        try:
            if text == "long":
                self.started.set()
                while not self.release.is_set():
                    if self.abort_signal.is_set():
                        raise RuntimeError("Request aborted by user")
                    await asyncio.sleep(0.01)
                await self._assistant("long done")
                return
            if text == "cancel":
                await self._user(text)
                raise asyncio.CancelledError
            if text == "tool-error":
                await self._user(text)
                await self._emit(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "write-empty",
                        "tool_name": "write",
                        "args": {},
                    }
                )
                await self._emit(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "write-empty",
                        "tool_name": "write",
                        "is_error": True,
                        "result": SimpleNamespace(
                            content=[
                                TextPart(
                                    type="text",
                                    text='Validation failed for tool "write"',
                                )
                            ]
                        ),
                    }
                )
                await self._assistant("tool error recovered")
                return
            await self._user(text)
            await self._assistant(f"response: {text}")
        finally:
            self.running = False

    async def steer(self, text: str) -> None:
        self.steers.append(text)

    async def follow_up(self, text: str) -> None:
        self.follow_ups.append(text)

    def abort(self) -> None:
        self.aborted = True
        self.abort_signal.set()

    def abort_bash(self) -> None:
        self.bash_aborted = True

    async def _user(self, text: str) -> None:
        await self._emit(
            {
                "type": "message_start",
                "message": UserMessage(
                    role="user",
                    content=[TextPart(type="text", text=text)],
                    timestamp=0.0,
                ),
            }
        )

    async def _assistant(self, text: str) -> None:
        await self._emit(
            {
                "type": "message_end",
                "message": SimpleNamespace(
                    role="assistant",
                    content=[TextPart(type="text", text=text)],
                ),
            }
        )

    async def _emit(self, event: dict[str, object]) -> None:
        for listener in list(self.listeners):
            result = listener(event)
            if inspect.isawaitable(result):
                await result


@dataclass(frozen=True)
class CaseResult:
    name: str
    passed: bool
    failures: tuple[str, ...]
    transcript: str
    stderr: str
    prompts: tuple[str, ...]
    steers: tuple[str, ...]
    follow_ups: tuple[str, ...]
    exit_code: int


async def _drive_follow_up(session: ScenarioSession, app: dict[str, Any]) -> int:
    await app["handle_prompt"]("hello")
    await app["handle_prompt"]("again")
    return await app["handle_prompt"]("/quit") or 0


async def _drive_steer(session: ScenarioSession, app: dict[str, Any]) -> int:
    session.started = asyncio.Event()
    session.release = asyncio.Event()
    task = asyncio.create_task(app["handle_prompt"]("long"))
    await session.started.wait()
    await app["handle_prompt"]("change tone")
    session.release.set()
    await task
    return await app["handle_prompt"]("/quit") or 0


async def _drive_active_follow_up(session: ScenarioSession, app: dict[str, Any]) -> int:
    session.started = asyncio.Event()
    session.release = asyncio.Event()
    task = asyncio.create_task(app["handle_prompt"]("long"))
    await session.started.wait()
    await app["handle_follow_up"]("continue after this turn")
    session.release.set()
    await task
    return await app["handle_prompt"]("/quit") or 0


async def _drive_abort_recovery(session: ScenarioSession, app: dict[str, Any]) -> int:
    session.started = asyncio.Event()
    session.release = asyncio.Event()
    session.abort_signal = asyncio.Event()
    task = asyncio.create_task(app["handle_prompt"]("long"))
    await session.started.wait()
    await app["on_abort"]()
    await task
    await app["handle_prompt"]("hello")
    return await app["handle_prompt"]("/quit") or 0


async def _drive_provider_cancel_recovery(session: ScenarioSession, app: dict[str, Any]) -> int:
    await app["handle_prompt"]("cancel")
    await app["handle_prompt"]("hello")
    return await app["handle_prompt"]("/quit") or 0


async def _drive_tool_error_recovery(session: ScenarioSession, app: dict[str, Any]) -> int:
    await app["handle_prompt"]("tool-error")
    await app["handle_prompt"]("hello")
    return await app["handle_prompt"]("/quit") or 0


DRIVERS: dict[CaseName, Callable[[ScenarioSession, dict[str, Any]], Any]] = {
    "follow-up": _drive_follow_up,
    "steer": _drive_steer,
    "active-follow-up": _drive_active_follow_up,
    "abort-recovery": _drive_abort_recovery,
    "provider-cancel-recovery": _drive_provider_cancel_recovery,
    "tool-error-recovery": _drive_tool_error_recovery,
}


async def run_case(name: CaseName, *, cwd: Path) -> CaseResult:
    session = ScenarioSession(cwd=cwd)
    stdout = TTYStringIO()
    stderr = StringIO()
    original_inline = ui_mode.run_inline_prompt_app

    async def fake_inline_prompt_app(**kwargs: Any) -> int:
        return await DRIVERS[name](session, kwargs)

    ui_mode.run_inline_prompt_app = fake_inline_prompt_app
    try:
        exit_code = await ui_mode.run_coding_tui(
            runtime=SimpleNamespace(get_cwd=lambda: str(cwd)),
            session=session,
            stdin=TTYStringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        ui_mode.run_inline_prompt_app = original_inline

    transcript = stdout.getvalue()
    error_output = stderr.getvalue()
    failures = _validate_case(
        name,
        session=session,
        transcript=transcript,
        stderr=error_output,
        exit_code=exit_code,
    )
    return CaseResult(
        name=name,
        passed=not failures,
        failures=tuple(failures),
        transcript=transcript,
        stderr=error_output,
        prompts=tuple(session.prompts),
        steers=tuple(session.steers),
        follow_ups=tuple(session.follow_ups),
        exit_code=exit_code,
    )


def _validate_case(
    name: CaseName,
    *,
    session: ScenarioSession,
    transcript: str,
    stderr: str,
    exit_code: int,
) -> list[str]:
    failures: list[str] = []
    if exit_code != 0:
        failures.append(f"exit code was {exit_code}")
    if stderr:
        failures.append(f"stderr was not empty: {stderr.strip()}")
    if "Traceback" in transcript or "Traceback" in stderr:
        failures.append("traceback was printed")
    if session.running:
        failures.append("session was still running")
    if not session.unsubscribed:
        failures.append("session listener was not unsubscribed")

    if name == "follow-up":
        _expect_equal(failures, "prompts", session.prompts, ["hello", "again"])
        if "• response: hello" not in transcript or "• response: again" not in transcript:
            failures.append("follow-up assistant responses were missing")
    elif name == "steer":
        _expect_equal(failures, "prompts", session.prompts, ["long"])
        _expect_equal(failures, "steers", session.steers, ["change tone"])
        _expect_equal(failures, "follow_ups", session.follow_ups, [])
        if "• long done" not in transcript:
            failures.append("steered run did not finish")
    elif name == "active-follow-up":
        _expect_equal(failures, "prompts", session.prompts, ["long"])
        _expect_equal(failures, "steers", session.steers, [])
        _expect_equal(failures, "follow_ups", session.follow_ups, ["continue after this turn"])
        if "Follow-up queued." not in transcript:
            failures.append("follow-up queued status was missing")
        if "• long done" not in transcript:
            failures.append("run did not finish after follow-up")
    elif name == "abort-recovery":
        _expect_equal(failures, "prompts", session.prompts, ["long", "hello"])
        if session.steers:
            failures.append(f"unexpected steering after abort: {session.steers!r}")
        if not session.aborted or not session.bash_aborted:
            failures.append("abort did not call both abort hooks")
        if transcript.count("Conversation interrupted") != 1:
            failures.append("interruption block was not rendered exactly once")
        if "■ Error: Request aborted by user" in transcript:
            failures.append("aborted request error was not suppressed")
        if "• response: hello" not in transcript:
            failures.append("follow-up prompt after abort did not complete")
    elif name == "provider-cancel-recovery":
        _expect_equal(failures, "prompts", session.prompts, ["cancel", "hello"])
        if transcript.count("■ Error: Request cancelled.") != 1:
            failures.append("provider cancellation error was not rendered exactly once")
        if "• response: hello" not in transcript:
            failures.append("follow-up prompt after provider cancellation did not complete")
    elif name == "tool-error-recovery":
        _expect_equal(failures, "prompts", session.prompts, ["tool-error", "hello"])
        if 'Validation failed for tool "write"' not in transcript:
            failures.append("tool validation error summary was missing")
        if "• tool error recovered" not in transcript or "• response: hello" not in transcript:
            failures.append("tool-error recovery responses were missing")
    return failures


def _expect_equal(failures: list[str], label: str, actual: object, expected: object) -> None:
    if actual != expected:
        failures.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")


async def run_scenarios(args: argparse.Namespace) -> int:
    cases = CASES if args.case == "all" else (args.case,)
    cwd = Path(args.cwd).expanduser().resolve(strict=False)
    cwd.mkdir(parents=True, exist_ok=True)
    snapshot = capture_observability()
    try:
        _configure_observability(args, cwd)
        results = [await run_case(case, cwd=cwd) for case in cases]
    finally:
        restore_observability(snapshot)

    for result in results:
        _print_result(result, show_transcript=args.show_transcript)
    failed = [result for result in results if not result.passed]
    if failed:
        print("\nFAIL")
        return 1
    print("\nPASS")
    return 0


def _configure_observability(args: argparse.Namespace, cwd: Path) -> None:
    debug_scopes = _scope_list(args.debug)
    trace_scopes = _scope_list(args.trace)
    kwargs: dict[str, object] = {}
    if args.debug_file:
        debug_path = _resolve_path(args.debug_file, cwd)
        kwargs["debug_sink"] = DebugLogSink(debug_path, latest_path=debug_path.parent / "latest")
        kwargs["debug_scopes"] = debug_scopes or frozenset({"tui"})
        print(f"debug_file: {debug_path}")
    if args.trace_file:
        trace_path = _resolve_path(args.trace_file, cwd)
        kwargs["trace_sink"] = TraceJSONLSink(trace_path, latest_path=trace_path.parent / "latest")
        kwargs["trace_scopes"] = trace_scopes or frozenset({"tui"})
        print(f"trace_file: {trace_path}")
    if kwargs:
        configure_observability(**kwargs)


def _scope_list(raw: str | None) -> frozenset[str]:
    return frozenset(item.strip() for item in (raw or "").split(",") if item.strip())


def _resolve_path(raw: str, cwd: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve(strict=False)
    return (cwd / path).resolve(strict=False)


def _print_result(result: CaseResult, *, show_transcript: bool) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"\n[{status}] {result.name}")
    print(f"  exit_code: {result.exit_code}")
    print(f"  prompts: {', '.join(result.prompts) or 'none'}")
    print(f"  steers: {', '.join(result.steers) or 'none'}")
    print(f"  follow_ups: {', '.join(result.follow_ups) or 'none'}")
    if result.failures:
        for failure in result.failures:
            print(f"  failure: {failure}")
    if show_transcript:
        print("  transcript:")
        for line in result.transcript.splitlines():
            print(f"    {line}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic TUI lifecycle scenarios without calling a real model."
    )
    parser.add_argument("--case", choices=("all", *CASES), default="all")
    parser.add_argument(
        "--cwd",
        default="/tmp/loushang-tui-lifecycle",
        help="Scenario workspace used for cwd/status/debug paths.",
    )
    parser.add_argument(
        "--debug",
        nargs="?",
        const="tui",
        default="",
        help="Comma-separated debug scopes for --debug-file. Defaults to tui when used without a value.",
    )
    parser.add_argument("--debug-file", help="Write human-readable debug log to PATH.")
    parser.add_argument(
        "--trace",
        nargs="?",
        const="tui",
        default="",
        help="Comma-separated trace scopes for --trace-file. Defaults to tui when used without a value.",
    )
    parser.add_argument("--trace-file", help="Write structured trace JSONL to PATH.")
    parser.add_argument("--show-transcript", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(run_scenarios(args))


if __name__ == "__main__":
    raise SystemExit(main())
