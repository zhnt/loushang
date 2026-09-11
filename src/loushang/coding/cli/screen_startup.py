"""Coding ownership adapter for a screen displayed before Session bootstrap."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from pathlib import Path
from typing import Any, TextIO, cast

from loushang.coding.ui.mode import run_coding_tui
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harness.cli import run_agent_cli_application
from loushang.harness.cli.application import invoke_agent_cli_runtime_builder
from loushang.harness.cli.launch import cli_static_error, resolve_effective_tui
from loushang.harness.host.product_host import ProductHostLifecycle, stream_is_tty
from loushang.harnesstui.conversation.startup_host import (
    ScreenConversationStartup,
    join_screen_settlement,
    startup_failure_summary,
)
from loushang.tui import strip_control_sequences


class StartupOutput:
    """Bounded Product output with TTY routing metadata, but no terminal writes."""

    def __init__(self, original: TextIO, *, limit: int = 65_536) -> None:
        self.original = original
        self.limit = limit
        self._text = ""
        self._truncated = False

    @property
    def encoding(self) -> str:
        return self.original.encoding or "utf-8"

    def isatty(self) -> bool:
        return stream_is_tty(self.original)

    def writable(self) -> bool:
        return True

    def flush(self) -> None:
        """Product flush never writes over the live screen."""

    def write(self, text: str) -> int:
        available = max(0, self.limit - len(self._text))
        self._text += text[:available]
        self._truncated |= len(text) > available
        return len(text)

    def drain(self) -> None:
        text, truncated = self._text, self._truncated
        self._text, self._truncated = "", False
        if text:
            self.original.write(text)
        if truncated:
            self.original.write("\n[Startup output truncated]\n")
        self.original.flush()

    def diagnostic_text(self) -> str:
        return strip_control_sequences(self._text).strip()[-1000:]


def screen_startup_eligible(
    args: Any, plan: Any, *, stdin: TextIO, stdout: TextIO
) -> bool:
    """Only ordinary embedded conversations may acquire the early screen."""

    return bool(
        stream_is_tty(stdin)
        and stream_is_tty(stdout)
        and not args.help
        and not args.version
        and args.resume is not True
        and not plan.command_operation
        and not plan.prompt_requested
        and not plan.workflow_requested
        and not plan.message_input
        and not plan.file_input
        and not plan.follow_up_input
        and not plan.work_log_requested
        and not plan.method_requested
        and plan.mode == "text"
        and cli_static_error(plan) is None
        and resolve_effective_tui(plan, stdin_is_tty=True, stdout_is_tty=True)
    )


async def run_screen_first_cli(
    raw_argv: tuple[str, ...],
    *,
    binding: Any,
    host_binding: Any,
    host_runners: Any,
    project_root: Path,
    cwd: str | Path | None,
) -> int:
    streams = binding.host_lifecycle.streams
    output = StartupOutput(streams.stdout)
    errors = StartupOutput(streams.stderr)
    app = ScreenCodingTuiApp(
        model_label=None,
        cwd=str(project_root),
        branch=None,
        session_label=None,
    )
    owned_runtime: Any = None

    async def build_runtime(**kwargs: Any) -> Any:
        nonlocal owned_runtime
        result = invoke_agent_cli_runtime_builder(binding.runtime_builder, **kwargs)
        owned_runtime = await result if inspect.isawaitable(result) else result
        return owned_runtime

    async def run_tui(**kwargs: Any) -> int:
        return await run_coding_tui(
            **kwargs,
            startup_app=app,
            prepared_screen_runner=startup.attach,
        )

    async def prepare() -> int:
        primary_error: BaseException | None = None
        try:
            prepared_binding = replace(
                binding,
                runtime_builder=build_runtime,
                host_lifecycle=ProductHostLifecycle.resolve(
                    stdin=streams.stdin,
                    stdout=cast(TextIO, output),
                    stderr=cast(TextIO, errors),
                ),
                run_host=host_binding.bind(replace(host_runners, tui=run_tui)),
            )
            return await run_agent_cli_application(
                raw_argv, binding=prepared_binding, cwd=cwd
            )
        except BaseException as error:
            primary_error = error
            raise
        finally:
            startup.begin_cleanup()
            if owned_runtime is not None:
                # The Product runtime, not generic dispose(), owns Session shutdown.
                async def dispose() -> None:
                    try:
                        await owned_runtime.dispose_session_runtime()
                    except asyncio.CancelledError as error:
                        raise RuntimeError(
                            "Session runtime cleanup cancelled before settlement"
                        ) from error

                try:
                    await join_screen_settlement(asyncio.create_task(dispose()))
                except BaseException as cleanup_error:
                    if primary_error is not None:
                        raise BaseExceptionGroup(
                            "Session preparation and cleanup failed",
                            [primary_error, cleanup_error],
                        ) from None
                    raise

    def failure_summary(exit_code: int) -> str:
        # The existing launch shell reports non-verbose UI failures to stdout.
        parts = [stream.diagnostic_text() for stream in (output, errors)]
        detail = "\n".join(part[-500:] for part in parts if part)
        return detail or f"Session preparation failed (exit {exit_code})."

    startup = ScreenConversationStartup(app, prepare, failure_summary=failure_summary)
    try:
        return await startup.run(stdin=streams.stdin, stdout=streams.stdout)
    except (Exception, BaseExceptionGroup) as error:
        errors.write(f"Error: {startup_failure_summary(error)}\n")
        return 1
    finally:
        # All Product output, including the resume hint, follows terminal restore.
        try:
            output.drain()
        finally:
            errors.drain()


__all__ = ["StartupOutput", "run_screen_first_cli", "screen_startup_eligible"]
