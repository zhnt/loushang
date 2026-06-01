from __future__ import annotations

import asyncio
import inspect
import shutil
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any, TextIO

from loushang.ai.types import ImagePart
from loushang.coding.ui.native_app import NativeCodingTuiApp
from loushang.coding.ui.native_input import NativeInputRouter
from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputIntent, InputReader
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.render_loop import RenderLoop
from loushang.tui.runtime import TuiRuntime
from loushang.tui.scheduler import RenderRequestKind
from loushang.tui.terminal import ProcessTerminalPort, TerminalOperation, TerminalSize
from loushang.tui.terminal_capabilities import format_terminal_capability_diagnostics
from loushang.tui.terminal_input import (
    read_input_chunk_or_render_tick,
)
from loushang.tui.terminal_session import TerminalSession

PromptHandler = Callable[..., Awaitable[int | None] | int | None]
TextHandler = Callable[..., Awaitable[int | None] | int | None]
SurfaceIntentHandler = Callable[[InputIntent], Awaitable[int | None] | int | None]
AbortHandler = Callable[[], Awaitable[object] | object]
ShouldExit = Callable[[str], bool]
LocalCommandPredicate = Callable[[str], bool]
TerminalModeFactory = Callable[[TextIO, TextIO], AbstractContextManager[object]]
TerminalSizeProvider = Callable[[], TerminalSize]


async def run_native_coding_tui(
    *,
    app: NativeCodingTuiApp,
    stdin: TextIO,
    stdout: TextIO,
    handle_prompt: PromptHandler,
    handle_local: TextHandler | None = None,
    handle_steer: TextHandler | None = None,
    handle_followup: TextHandler | None = None,
    handle_surface_intent: SurfaceIntentHandler | None = None,
    on_abort: AbortHandler,
    should_exit: ShouldExit,
    is_local_command: LocalCommandPredicate | None = None,
    keybindings: KeybindingManager | KeybindingConfig | None = None,
    terminal_mode_factory: TerminalModeFactory | None = None,
    terminal_size_provider: TerminalSizeProvider | None = None,
) -> int:
    reader = InputReader()
    size_provider = terminal_size_provider or _terminal_size
    initial_size = size_provider()
    router = NativeInputRouter(
        app,
        should_exit=should_exit,
        is_local_command=is_local_command or (lambda _text: False),
        keybindings=keybindings,
        width=initial_size.columns,
    )
    runtime = TuiRuntime(
        render_loop=RenderLoop(app),
        terminal=ProcessTerminalPort(output=stdout, size_provider=size_provider, track_screen=False),
    )
    app.surface_host = runtime.overlay_host()
    mode_factory = terminal_mode_factory or (lambda input_stream, output_stream: TerminalSession(stdin=input_stream, stdout=output_stream))
    active_task: asyncio.Task[int | None] | None = None
    active_prompt_started_at: float | None = None
    queued_steers_while_running: list[str] = []
    render_wakeup = asyncio.Event()
    previous_render_requester = app.render_requester
    previous_terminal_diagnostics_provider = app.terminal_diagnostics_provider
    previous_terminal_capabilities = app.terminal_capabilities

    def request_app_render(kind: RenderRequestKind) -> None:
        if previous_render_requester is not None:
            previous_render_requester(kind)
        runtime.request_render(kind)
        render_wakeup.set()

    app.render_requester = request_app_render
    try:
        _write_startup_welcome(app=app, runtime=runtime, stdout=stdout)
        with mode_factory(stdin, stdout) as terminal_context:
            app.terminal_diagnostics_provider = lambda context=terminal_context: _format_terminal_diagnostics(context)
            _configure_runtime_for_terminal_context(runtime, app, terminal_context)
            runtime.render_now()
            while True:
                if active_task is not None and active_task.done():
                    exit_code = await _finish_active_task(
                        app=app,
                        active_task=active_task,
                        started_at=active_prompt_started_at,
                    )
                    active_task = None
                    active_prompt_started_at = None
                    queued_steers_while_running = []
                    runtime.render_now()
                    if exit_code is not None:
                        return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=exit_code)

                data = await read_input_chunk_or_render_tick(
                    stdin,
                    runtime=runtime,
                    active_task=active_task,
                    render_wakeup=render_wakeup,
                    pending_input_idle_ms=10 if reader.has_pending else None,
                    idle_wakeup_ms=_terminal_runtime_wakeup_ms(terminal_context),
                )
                input_events: tuple[Any, ...]
                if data is None:
                    _poll_terminal_runtime(terminal_context)
                    if not reader.has_pending:
                        continue
                    input_events = _flush_pending_input(reader, terminal_context=terminal_context)
                elif data == "" and reader.has_pending:
                    input_events = _flush_pending_input(reader, terminal_context=terminal_context)
                elif data == "":
                    if active_task is not None:
                        exit_code = await _finish_active_task(
                            app=app,
                            active_task=active_task,
                            started_at=active_prompt_started_at,
                        )
                        runtime.render_now()
                        return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=exit_code if exit_code is not None else 0)
                    runtime.render_now()
                    return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=0)
                else:
                    input_events = _input_events_for_chunk(reader, data, terminal_context=terminal_context)

                for event in input_events:
                    result = router.handle(event)
                    if result.exit_code is not None:
                        runtime.render_now()
                        return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=result.exit_code)
                    if result.abort_requested:
                        queued_steers_while_running = []
                        interrupt_pending_steer = _pop_interrupt_pending_steer(app)
                        await _abort_active(app=app, active_task=active_task, on_abort=on_abort)
                        active_task = None
                        active_prompt_started_at = None
                        runtime.render_now()
                        if interrupt_pending_steer is not None:
                            app.start_pending_prompt(interrupt_pending_steer)
                            active_task = asyncio.create_task(_run_prompt_handler(handle_prompt, interrupt_pending_steer))
                            active_prompt_started_at = app.state.active_started_at
                            runtime.render_now()
                        continue
                    if result.prompt_text is not None:
                        active_prompt_started_at = app.state.active_started_at
                        active_task = asyncio.create_task(
                            _run_prompt_handler(handle_prompt, result.prompt_text, images=result.prompt_images)
                        )
                        queued_steers_while_running = []
                    if result.local_text is not None and handle_local is not None:
                        exit_code = await _run_text_handler(handle_local, result.local_text)
                        if exit_code is not None:
                            runtime.render_now()
                            return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=exit_code)
                    if result.steer_text is not None and handle_steer is not None:
                        was_running = active_task is not None
                        exit_code = await _run_text_handler(handle_steer, result.steer_text, images=result.steer_images)
                        if was_running:
                            queued_steers_while_running.append(result.steer_text)
                        if exit_code is not None:
                            runtime.render_now()
                            return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=exit_code)
                    if result.followup_text is not None and handle_followup is not None:
                        exit_code = await _run_text_handler(handle_followup, result.followup_text, images=result.followup_images)
                        if exit_code is not None:
                            runtime.render_now()
                            return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=exit_code)
                    if result.surface_intent is not None and handle_surface_intent is not None:
                        exit_code = await _run_surface_intent_handler(handle_surface_intent, result.surface_intent)
                        if exit_code is not None:
                            runtime.render_now()
                            return _finish_tui_exit(runtime=runtime, stdout=stdout, exit_code=exit_code)
                    if result.render_requested:
                        _request_runtime_render(runtime, "input")
    finally:
        app.surface_host = None
        app.terminal_diagnostics_provider = previous_terminal_diagnostics_provider
        app.terminal_capabilities = previous_terminal_capabilities
        app.render_requester = previous_render_requester


async def _finish_active_task(
    *,
    app: NativeCodingTuiApp,
    active_task: asyncio.Task[int | None],
    started_at: float | None,
) -> int | None:
    try:
        result = await active_task
    except asyncio.CancelledError:
        app.state.abort(message="Operation aborted", elapsed_seconds=app.elapsed_seconds())
        return None
    except Exception as error:  # noqa: BLE001
        app.add_error(str(error) or error.__class__.__name__)
        app.complete_run(elapsed_seconds=_elapsed_since(app, started_at))
        return 1
    app.complete_run(elapsed_seconds=_elapsed_since(app, started_at))
    return result if isinstance(result, int) else None


def _request_runtime_render(runtime: TuiRuntime, kind: RenderRequestKind) -> None:
    decision = runtime.request_render(kind)
    if decision.render_now:
        runtime.render_now()


def _write_startup_welcome(*, app: NativeCodingTuiApp, runtime: TuiRuntime, stdout: TextIO) -> None:
    if app.state.records or app.state.running or app.state.assistant_draft_buffer is not None:
        return
    size = runtime.terminal.size()
    result = app.startup_welcome_panel().render(
        RenderConstraints(width=size.columns, max_height=size.rows, visible_height=size.rows)
    )
    if not result.lines:
        return
    stdout.write("\n".join(line.text for line in result.lines))
    stdout.write("\n\n")
    stdout.flush()


def _input_events_for_chunk(reader: InputReader, data: str, *, terminal_context: object | None = None) -> tuple[Any, ...]:
    data = _normalize_terminal_input(data, terminal_context=terminal_context)
    batch = reader.feed_batch(data)
    _consume_terminal_control_events(batch.control_events, terminal_context=terminal_context)
    return batch.app_events


def _flush_pending_input(reader: InputReader, *, terminal_context: object | None = None) -> tuple[Any, ...]:
    pending = reader.flush_pending_batch()
    _consume_terminal_control_events(pending.control_events, terminal_context=terminal_context)
    return pending.app_events


def _consume_terminal_control_events(events: tuple[Any, ...], *, terminal_context: object | None = None) -> None:
    consumer = getattr(terminal_context, "consume_control_events", None)
    if callable(consumer):
        consumer(events)


def _terminal_runtime_wakeup_ms(terminal_context: object | None) -> int | None:
    wakeup = getattr(terminal_context, "next_wakeup_delay_ms", None)
    if not callable(wakeup):
        return None
    delay = wakeup()
    return delay if isinstance(delay, int) else None


def _poll_terminal_runtime(terminal_context: object | None) -> bool:
    poll = getattr(terminal_context, "flush_keyboard_protocol_fallback_if_due", None)
    if not callable(poll):
        return False
    return bool(poll())


def _normalize_terminal_input(data: str, *, terminal_context: object | None = None) -> str:
    normalizer = getattr(terminal_context, "normalize_input_chunk", None)
    if not callable(normalizer):
        return data
    normalized = normalizer(data)
    return normalized if isinstance(normalized, str) else data


def _configure_runtime_for_terminal_context(runtime: TuiRuntime, app: NativeCodingTuiApp, terminal_context: object) -> None:
    capabilities = getattr(terminal_context, "capabilities", None)
    if capabilities is not None:
        app.terminal_capabilities = capabilities
    runtime.render_loop.termux_session = bool(getattr(capabilities, "termux_session", False))


def _finish_tui_exit(*, runtime: TuiRuntime, stdout: TextIO, exit_code: int) -> int:
    if _clear_runtime_bottom_frame_for_exit(runtime):
        return exit_code
    stdout.write("\r\x1b[2K\n")
    stdout.flush()
    return exit_code


def _clear_runtime_bottom_frame_for_exit(runtime: TuiRuntime) -> bool:
    render_loop = runtime.render_loop
    current_lines = render_loop.previous_rendered_lines
    if not current_lines:
        return False

    cursor_row = render_loop.previous_cursor_row
    viewport_top = render_loop.previous_viewport_top
    if cursor_row < viewport_top or cursor_row >= len(current_lines):
        return False

    screen_row = cursor_row - viewport_top
    terminal_rows = runtime.terminal.size().rows
    clear_count = min(len(current_lines) - cursor_row, terminal_rows - screen_row)
    if clear_count <= 0:
        return False

    runtime.terminal.flush(_exit_bottom_frame_cleanup_operations(clear_count))
    return True


def _exit_bottom_frame_cleanup_operations(line_count: int) -> tuple[TerminalOperation, ...]:
    line_count = max(1, line_count)
    operations: list[TerminalOperation] = [
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.carriage_return(),
    ]
    for index in range(line_count):
        operations.append(TerminalOperation.clear_line())
        if index < line_count - 1:
            operations.append(TerminalOperation.newline())
    if line_count > 1:
        operations.append(TerminalOperation.move_relative(lines=-(line_count - 1)))
    operations.extend(
        (
            TerminalOperation.carriage_return(),
            TerminalOperation.end_synchronized_update(),
            TerminalOperation.show_cursor(),
        )
    )
    return tuple(operations)


def _format_terminal_diagnostics(terminal_context: object) -> str:
    sections: list[str] = []
    environment = getattr(terminal_context, "environment", None)
    capabilities = getattr(terminal_context, "capabilities", None)
    if environment is not None or capabilities is not None:
        sections.append(format_terminal_capability_diagnostics(environment, capabilities))
    diagnostics_getter = getattr(terminal_context, "diagnostics", None)
    if callable(diagnostics_getter):
        diagnostics = diagnostics_getter()
        sections.append(
            "\n".join(
                (
                    f"keyboard_protocol_state: {_diagnostic_value(diagnostics, 'keyboard_protocol_state')}",
                    f"mouse_mode_active: {_format_bool(_diagnostic_value(diagnostics, 'mouse_mode_active'))}",
                    f"cell_size: {_format_cell_size(_diagnostic_value(diagnostics, 'cell_size'))}",
                    f"runtime_image_protocol: {_diagnostic_value(diagnostics, 'image_protocol')}",
                    f"alternate_screen_active: {_format_bool(_diagnostic_value(diagnostics, 'alternate_screen'))}",
                    f"tmux_passthrough_active: {_format_bool(_diagnostic_value(diagnostics, 'tmux_passthrough'))}",
                    f"windows_vt_input_active: {_format_bool(_diagnostic_value(diagnostics, 'windows_vt_input'))}",
                    f"termux_session_active: {_format_bool(_diagnostic_value(diagnostics, 'termux_session'))}",
                    f"multiplexer_active: {_format_bool(_diagnostic_value(diagnostics, 'is_multiplexer'))}",
                    f"ssh_active: {_format_bool(_diagnostic_value(diagnostics, 'inside_ssh'))}",
                )
            )
        )
    return "\n\n".join(section for section in sections if section) or "Terminal diagnostics are unavailable."


def _diagnostic_value(diagnostics: object, name: str) -> object:
    return getattr(diagnostics, name, "<unknown>")


def _format_bool(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_cell_size(value: object) -> str:
    width = getattr(value, "width_px", None)
    height = getattr(value, "height_px", None)
    if isinstance(width, int) and isinstance(height, int):
        return f"{width}x{height}"
    return "<unknown>"


async def _abort_active(
    *,
    app: NativeCodingTuiApp,
    active_task: asyncio.Task[int | None] | None,
    on_abort: AbortHandler,
) -> None:
    await _maybe_await(on_abort())
    if active_task is not None and not active_task.done():
        active_task.cancel()
        try:
            await active_task
        except asyncio.CancelledError:
            pass
    elif active_task is not None:
        await active_task
    app.state.abort(message="Conversation interrupted - tell the model what to do differently.", elapsed_seconds=app.elapsed_seconds())


def _elapsed_since(app: NativeCodingTuiApp, started_at: float | None) -> float:
    if started_at is None:
        return app.elapsed_seconds()
    return max(0.0, app.now() - started_at)


async def _run_prompt_handler(
    handler: PromptHandler,
    text: str,
    *,
    images: tuple[ImagePart, ...] | None = None,
) -> int | None:
    result = await _call_text_handler(handler, text, images=images)
    return result if isinstance(result, int) else None


async def _run_text_handler(
    handler: TextHandler,
    text: str,
    *,
    images: tuple[ImagePart, ...] | None = None,
) -> int | None:
    result = await _call_text_handler(handler, text, images=images)
    return result if isinstance(result, int) else None


def _pop_interrupt_pending_steer(app: NativeCodingTuiApp) -> str | None:
    if not app.state.pending_steers:
        return None
    pending_steer = app.state.pending_steers.pop(0)
    return pending_steer


async def _call_text_handler(
    handler: Callable[..., object],
    text: str,
    *,
    images: tuple[ImagePart, ...] | None = None,
) -> object:
    if images is not None and _supports_keyword(handler, "images"):
        return await _maybe_await(handler(text, images=images))
    return await _maybe_await(handler(text))


async def _run_surface_intent_handler(handler: SurfaceIntentHandler, intent: InputIntent) -> int | None:
    result = await _maybe_await(handler(intent))
    return result if isinstance(result, int) else None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _supports_keyword(method: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == keyword
        for parameter in signature.parameters.values()
    )


def _terminal_size() -> TerminalSize:
    size = shutil.get_terminal_size((80, 24))
    return TerminalSize(columns=size.columns, rows=size.lines)


__all__ = ["run_native_coding_tui"]
