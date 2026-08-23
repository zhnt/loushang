from __future__ import annotations

import asyncio
import inspect
import shutil
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol, TextIO, TypeAlias, assert_never

from loushang.harnesstui.conversation.input import (
    ConversationAbortResult,
    ConversationClipboardResult,
    ConversationExitResult,
    ConversationFollowupResult,
    ConversationInputHandled,
    ConversationInputIgnored,
    ConversationInputResult,
    ConversationInputRouter,
    ConversationInputRouterFactoryPort,
    ConversationInputRouterPort,
    ConversationLocalResult,
    ConversationPromptResult,
    ConversationScreenInputPort,
    ConversationSteerResult,
    ConversationSurfaceResult,
)
from loushang.harnesstui.surface.controller import promote_pending_page_surface
from loushang.tui import _runner_utils
from loushang.tui.core import RenderConstraints, RenderResult
from loushang.tui.framework import SurfaceHost
from loushang.tui.input import InputIntent, InputReader
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.render_loop import RenderLoop
from loushang.tui.runtime import TuiRuntime
from loushang.tui.scheduler import RenderRequestKind
from loushang.tui.terminal import ProcessTerminalPort, TerminalSize
from loushang.tui.terminal_capabilities import TerminalRuntimeCapabilities
from loushang.tui.terminal_diagnostics import format_terminal_diagnostics
from loushang.tui.terminal_input import (
    InputChunkReader,
    read_input_chunk_or_render_tick,
)
from loushang.tui.terminal_session import TerminalSession

HandlerResult = Awaitable[int | None] | int | None
PromptHandler = Callable[..., HandlerResult]
TextHandler = Callable[..., HandlerResult]
SurfaceIntentHandler = Callable[[InputIntent[str]], HandlerResult]
AbortHandler = Callable[[], Awaitable[object] | object]
ShouldExit = Callable[[str], bool]
LocalCommandPredicate = Callable[[str], bool]
TerminalModeFactory = Callable[[TextIO, TextIO], AbstractContextManager[object]]
TerminalSizeProvider = Callable[[], TerminalSize]


class ConversationRenderablePort(Protocol):
    """Renderable content returned by a conversation screen."""

    def render(self, constraints: RenderConstraints) -> RenderResult: ...


class ConversationScreenPort(ConversationScreenInputPort, Protocol):
    """Screen application capabilities required by the shared runner."""

    render_requester: Callable[[RenderRequestKind], object] | None
    terminal_diagnostics_provider: Callable[[], str] | None
    terminal_capabilities: TerminalRuntimeCapabilities | None
    surface_host: SurfaceHost | None

    @property
    def now(self) -> Callable[[], float]: ...

    def render(self, constraints: RenderConstraints) -> RenderResult: ...

    def startup_welcome_panel(self) -> ConversationRenderablePort: ...

    def start_pending_prompt(self, text: str) -> None: ...

    def add_error(self, summary: str, diagnostics: str = "") -> None: ...

    def complete_run(self, *, elapsed_seconds: float | None = None) -> None: ...

    def elapsed_seconds(self) -> float: ...


ConversationInputResultPort: TypeAlias = ConversationInputResult


_finish_tui_exit = _runner_utils.finish_tui_exit
_flush_pending_input = _runner_utils.flush_pending_input
_input_events_for_chunk = _runner_utils.input_events_for_chunk
_poll_terminal_runtime = _runner_utils.poll_terminal_runtime
_request_runtime_render = _runner_utils.request_runtime_render
_terminal_runtime_wakeup_ms = _runner_utils.terminal_runtime_wakeup_ms


async def run_conversation_screen(
    *,
    app: ConversationScreenPort,
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
    interruption_message: str,
    cancellation_message: str,
    input_router_factory: ConversationInputRouterFactoryPort | None = None,
    input_chunk_reader: InputChunkReader | None = None,
) -> int:
    """Run one product-neutral interactive conversation screen.

    The application and handlers supply presentation and product policy. This
    runner owns terminal polling, routed interaction, task coordination, and
    render scheduling. It does not own a Harness Session or conversation
    storage.
    """

    reader = InputReader()
    size_provider = terminal_size_provider or terminal_size
    initial_size = size_provider()
    local_predicate = is_local_command or (lambda _text: False)
    if input_router_factory is None:
        router: ConversationInputRouterPort = ConversationInputRouter(
            app=app,
            should_exit=should_exit,
            is_local_command=local_predicate,
            keybindings=keybindings,
            width=initial_size.columns,
            height=initial_size.rows,
        )
    else:
        router = input_router_factory(
            app=app,
            should_exit=should_exit,
            is_local_command=local_predicate,
            keybindings=keybindings,
            width=initial_size.columns,
            height=initial_size.rows,
        )
    runtime = TuiRuntime(
        render_loop=RenderLoop(app),
        terminal=ProcessTerminalPort(
            output=stdout,
            size_provider=size_provider,
            track_screen=False,
        ),
    )
    app.surface_host = runtime.overlay_host()
    promote_pending_page_surface(app)
    mode_factory = terminal_mode_factory or (
        lambda input_stream, output_stream: TerminalSession(
            stdin=input_stream,
            stdout=output_stream,
        )
    )
    active_task: asyncio.Task[int | None] | None = None
    active_prompt_started_at: float | None = None
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
        with mode_factory(stdin, stdout) as terminal_context:
            app.terminal_diagnostics_provider = lambda context=terminal_context: (
                format_terminal_diagnostics(context)
            )
            configure_runtime_for_terminal_context(runtime, app, terminal_context)
            write_startup_welcome(app=app, runtime=runtime, stdout=stdout)
            runtime.render_now()
            while True:
                if active_task is not None and active_task.done():
                    exit_code = await finish_active_task(
                        app=app,
                        active_task=active_task,
                        started_at=active_prompt_started_at,
                        cancellation_message=cancellation_message,
                    )
                    active_task = None
                    active_prompt_started_at = None
                    runtime.render_now()
                    if exit_code is not None:
                        return _finish_tui_exit(
                            runtime=runtime,
                            stdout=stdout,
                            exit_code=exit_code,
                        )

                data = await read_input_chunk_or_render_tick(
                    stdin,
                    runtime=runtime,
                    active_task=active_task,
                    input_chunk_reader=input_chunk_reader,
                    render_wakeup=render_wakeup,
                    pending_input_idle_ms=10 if reader.has_pending else None,
                    idle_wakeup_ms=_terminal_runtime_wakeup_ms(terminal_context),
                )
                input_events: tuple[Any, ...]
                if data is None:
                    _poll_terminal_runtime(terminal_context)
                    if not reader.has_pending:
                        continue
                    input_events = _flush_pending_input(
                        reader,
                        terminal_context=terminal_context,
                    )
                elif data == "" and reader.has_pending:
                    input_events = _flush_pending_input(
                        reader,
                        terminal_context=terminal_context,
                    )
                elif data == "":
                    if active_task is not None:
                        exit_code = await finish_active_task(
                            app=app,
                            active_task=active_task,
                            started_at=active_prompt_started_at,
                            cancellation_message=cancellation_message,
                        )
                        runtime.render_now()
                        return _finish_tui_exit(
                            runtime=runtime,
                            stdout=stdout,
                            exit_code=exit_code if exit_code is not None else 0,
                        )
                    runtime.render_now()
                    return _finish_tui_exit(
                        runtime=runtime,
                        stdout=stdout,
                        exit_code=0,
                    )
                else:
                    input_events = _input_events_for_chunk(
                        reader,
                        data,
                        terminal_context=terminal_context,
                    )

                for event in input_events:
                    result = router.handle(event)
                    if isinstance(result, ConversationExitResult):
                        runtime.render_now()
                        return _finish_tui_exit(
                            runtime=runtime,
                            stdout=stdout,
                            exit_code=result.exit_code,
                        )
                    if isinstance(result, ConversationAbortResult):
                        interrupt_pending_steer = pop_interrupt_pending_steer(app)
                        await abort_active(
                            app=app,
                            active_task=active_task,
                            on_abort=on_abort,
                            interruption_message=interruption_message,
                        )
                        active_task = None
                        active_prompt_started_at = None
                        runtime.render_now()
                        if interrupt_pending_steer is not None:
                            app.start_pending_prompt(interrupt_pending_steer)
                            active_task = asyncio.create_task(
                                run_prompt_handler(
                                    handle_prompt,
                                    interrupt_pending_steer,
                                )
                            )
                            active_prompt_started_at = app.state.active_started_at
                            runtime.render_now()
                        continue
                    if isinstance(result, ConversationPromptResult):
                        active_prompt_started_at = app.state.active_started_at
                        active_task = asyncio.create_task(
                            run_prompt_handler(
                                handle_prompt,
                                result.text,
                                attachments=result.attachments,
                            )
                        )
                    elif isinstance(result, ConversationLocalResult):
                        if handle_local is not None:
                            exit_code = await run_text_handler(
                                handle_local,
                                result.text,
                            )
                            if exit_code is not None:
                                runtime.render_now()
                                return _finish_tui_exit(
                                    runtime=runtime,
                                    stdout=stdout,
                                    exit_code=exit_code,
                                )
                    elif isinstance(result, ConversationSteerResult):
                        if handle_steer is not None:
                            exit_code = await run_text_handler(
                                handle_steer,
                                result.text,
                                attachments=result.attachments,
                            )
                            if exit_code is not None:
                                runtime.render_now()
                                return _finish_tui_exit(
                                    runtime=runtime,
                                    stdout=stdout,
                                    exit_code=exit_code,
                                )
                    elif isinstance(result, ConversationFollowupResult):
                        if handle_followup is not None:
                            exit_code = await run_text_handler(
                                handle_followup,
                                result.text,
                                attachments=result.attachments,
                            )
                            if exit_code is not None:
                                runtime.render_now()
                                return _finish_tui_exit(
                                    runtime=runtime,
                                    stdout=stdout,
                                    exit_code=exit_code,
                                )
                    elif isinstance(result, ConversationSurfaceResult):
                        if handle_surface_intent is not None:
                            exit_code = await run_surface_intent_handler(
                                handle_surface_intent,
                                result.intent,
                            )
                            if exit_code is not None:
                                runtime.render_now()
                                return _finish_tui_exit(
                                    runtime=runtime,
                                    stdout=stdout,
                                    exit_code=exit_code,
                                )
                    elif isinstance(result, ConversationClipboardResult):
                        pass
                    elif isinstance(result, ConversationInputHandled):
                        pass
                    elif isinstance(result, ConversationInputIgnored):
                        pass
                    else:
                        assert_never(result)
                    if result.render_requested:
                        _request_runtime_render(runtime, "input")
    finally:
        app.surface_host = None
        app.terminal_diagnostics_provider = previous_terminal_diagnostics_provider
        app.terminal_capabilities = previous_terminal_capabilities
        app.render_requester = previous_render_requester


async def finish_active_task(
    *,
    app: ConversationScreenPort,
    active_task: asyncio.Task[int | None],
    started_at: float | None,
    cancellation_message: str,
) -> int | None:
    try:
        result = await active_task
    except asyncio.CancelledError:
        app.state.abort(
            message=cancellation_message,
            elapsed_seconds=app.elapsed_seconds(),
        )
        return None
    except Exception as error:
        app.add_error(str(error) or error.__class__.__name__)
        app.complete_run(elapsed_seconds=elapsed_since(app, started_at))
        return 1
    app.complete_run(elapsed_seconds=elapsed_since(app, started_at))
    return result if isinstance(result, int) else None


def write_startup_welcome(
    *,
    app: ConversationScreenPort,
    runtime: TuiRuntime,
    stdout: TextIO,
) -> None:
    if (
        app.state.records
        or app.state.running
        or app.state.assistant_draft_buffer is not None
    ):
        return
    size = runtime.terminal.size()
    result = app.startup_welcome_panel().render(
        RenderConstraints(
            width=size.columns,
            max_height=size.rows,
            visible_height=size.rows,
        )
    )
    if not result.lines:
        return
    stdout.write("\n".join(line.text for line in result.lines))
    stdout.write("\n\n")
    stdout.flush()


def configure_runtime_for_terminal_context(
    runtime: TuiRuntime,
    app: ConversationScreenPort,
    terminal_context: object,
) -> None:
    capabilities = getattr(terminal_context, "capabilities", None)
    if capabilities is not None:
        app.terminal_capabilities = capabilities
    _runner_utils.configure_runtime_for_terminal_context(runtime, terminal_context)


async def abort_active(
    *,
    app: ConversationScreenPort,
    active_task: asyncio.Task[int | None] | None,
    on_abort: AbortHandler,
    interruption_message: str,
) -> None:
    await maybe_await(on_abort())
    if active_task is not None:
        try:
            await active_task
        except asyncio.CancelledError:
            pass
        except Exception as error:
            app.add_error(str(error) or error.__class__.__name__)
    app.state.abort(
        message=interruption_message,
        elapsed_seconds=app.elapsed_seconds(),
    )


def elapsed_since(app: ConversationScreenPort, started_at: float | None) -> float:
    if started_at is None:
        return app.elapsed_seconds()
    return max(0.0, app.now() - started_at)


async def run_prompt_handler(
    handler: PromptHandler,
    text: str,
    *,
    attachments: tuple[object, ...] | None = None,
) -> int | None:
    result = await call_text_handler(handler, text, attachments=attachments)
    return result if isinstance(result, int) else None


async def run_text_handler(
    handler: TextHandler,
    text: str,
    *,
    attachments: tuple[object, ...] | None = None,
) -> int | None:
    result = await call_text_handler(handler, text, attachments=attachments)
    return result if isinstance(result, int) else None


def pop_interrupt_pending_steer(app: ConversationScreenPort) -> str | None:
    if not app.state.pending_steers:
        return None
    return app.state.pending_steers.pop(0)


async def call_text_handler(
    handler: Callable[..., object],
    text: str,
    *,
    attachments: tuple[object, ...] | None = None,
) -> object:
    if attachments is not None and supports_keyword(handler, "attachments"):
        return await maybe_await(handler(text, attachments=attachments))
    return await maybe_await(handler(text))


async def run_surface_intent_handler(
    handler: SurfaceIntentHandler,
    intent: InputIntent[str],
) -> int | None:
    result = await maybe_await(handler(intent))
    return result if isinstance(result, int) else None


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def supports_keyword(method: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == keyword
        for parameter in signature.parameters.values()
    )


def terminal_size() -> TerminalSize:
    size = shutil.get_terminal_size((80, 24))
    return TerminalSize(columns=size.columns, rows=size.lines)


__all__ = [
    "ConversationInputResultPort",
    "ConversationInputRouterFactoryPort",
    "ConversationInputRouterPort",
    "ConversationRenderablePort",
    "ConversationScreenPort",
    "run_conversation_screen",
]
