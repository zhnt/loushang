"""A single-screen startup handshake over opaque Product preparation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextvars import Context, copy_context
from typing import Any, TextIO

from loushang.harnesstui.conversation.control import ConversationActionHost
from loushang.harnesstui.conversation.host import (
    ConversationScreenRunProfile,
    bind_action_host_to_screen_runner,
    open_conversation_screen_runtime,
)
from loushang.harnesstui.conversation.input import (
    ConversationExitResult,
    ConversationInputHandled,
    ConversationInputResult,
    ConversationInputRouter,
    ConversationInputRouterPort,
)
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_runner import (
    ConversationScreenPort,
    LocalCommandPredicate,
    ShouldExit,
    SurfaceIntentHandler,
    TextHandler,
    run_conversation_screen,
)
from loushang.tui.input import InputEvent
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager

LOADING_MESSAGE = "Loading session — you can type; submission is disabled"


def startup_failure_summary(error: BaseException) -> str:
    """Keep bounded leaf diagnostics instead of an opaque exception-group count."""
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(
            startup_failure_summary(item) for item in error.exceptions[:4]
        )[:1000]
    return (str(error) or type(error).__name__)[:1000]


async def join_screen_settlement(task: asyncio.Task[None]) -> None:
    """Defer repeated cancellation until the owned cleanup has settled."""

    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    task.result()
    if interrupted:
        raise asyncio.CancelledError


class _LoadingRouter(ConversationInputRouter):
    def handle(self, event: InputEvent) -> ConversationInputResult:
        if event.kind == "key" and event.event_type != "release":
            if event.key in {"ctrl+c", "ctrl+d"}:
                return ConversationExitResult(
                    exit_code=130 if event.key == "ctrl+c" else 0
                )
            if self._keybindings().matches(
                event.key, "tui.input.submit"
            ) or event.key in {"ctrl+v", "alt+v", "tab"}:
                # Gate BEFORE the normal submit path can clear draft or stage files.
                if not (self.app.state.status_message or "").startswith(
                    "Session unavailable"
                ):
                    self.app.state.status_message = LOADING_MESSAGE
                return ConversationInputHandled()
        return super().handle(event)


class _StartupRouter:
    def __init__(self, startup: ScreenConversationStartup, **kwargs: Any) -> None:
        self.startup = startup
        self.kwargs = kwargs
        self.loading = _LoadingRouter(**kwargs)
        self.ready: ConversationInputRouterPort | None = None
        self.disposed = False

    def handle(self, event: InputEvent) -> ConversationInputResult:
        if event.kind == "resize":
            if event.columns:
                self.kwargs["width"] = event.columns
            if event.rows:
                self.kwargs["height"] = event.rows
        if self.ready is not None and not self.startup.closing:
            assert self.startup.context is not None
            return self.startup.context.copy().run(self.ready.handle, event)
        return self.loading.handle(event)

    def dispose(self) -> None:
        if self.disposed:
            return
        self.disposed = True
        try:
            if self.ready is not None:
                dispose = getattr(self.ready, "dispose", None)
                if callable(dispose):
                    assert self.startup.context is not None
                    self.startup.context.copy().run(dispose)
        finally:
            self.loading.dispose()


class ScreenConversationStartup:
    """Own one bootstrap task, late interaction binding and closing handshake.

    Product preparation calls ``attach`` instead of starting another terminal.
    The preparation task retains its context managers until the screen releases
    that continuation. No Session/runtime crosses this port.
    """

    def __init__(
        self,
        app: ScreenConversationApp,
        prepare: Callable[[], Awaitable[int]],
        failure_summary: Callable[[int], str] | None = None,
    ) -> None:
        self.app = app
        self.prepare = prepare
        self.failure_summary = failure_summary
        self.context: Context | None = None
        self.closing = False
        self.attached = False
        self.preparation_settling = False
        self.exit_code = 0
        self.task: asyncio.Task[int] | None = None
        self.finished: asyncio.Future[int] | None = None
        self.router: _StartupRouter | None = None
        self.handlers: dict[str, Callable[..., object] | None] = {}
        self._wake: Callable[[], None] = lambda: None
        self._observed = False
        self.app.state.permission_profile = None
        self.app.state.startup_pending = True
        self.app.state.status_message = LOADING_MESSAGE

    def start(self, wake: Callable[[], None]) -> None:
        if self.task is not None:
            raise RuntimeError("screen startup may only start once")
        self._wake = wake

        async def prepare() -> int:
            return await self.prepare()

        self.task = asyncio.create_task(prepare(), name="conversation-startup")
        self.task.add_done_callback(lambda _task: wake())

    def begin_cleanup(self) -> None:
        """The preparation owner has stopped acquiring and entered settlement."""
        self.preparation_settling = True

    @property
    def wait_task(self) -> asyncio.Task[int] | None:
        return None if self._observed else self.task

    def poll(self) -> int | None:
        if self.task is None or not self.task.done() or self._observed:
            return None
        self._observed = True
        try:
            result = self.task.result()
        except Exception as error:
            self.exit_code = 1
            self.app.add_error(startup_failure_summary(error))
        else:
            self.exit_code = result
            if result == 0:
                return result
            self.app.add_error(
                self.failure_summary(result)
                if self.failure_summary is not None
                else f"Session preparation failed (exit {result})."
            )
        self.app.state.status_message = "Session unavailable — Ctrl-C or Ctrl-D to exit"
        self.app.request_render()
        return None

    def build_router(self, **kwargs: Any) -> _StartupRouter:
        if self.router is not None:
            raise RuntimeError("screen startup already has an input owner")
        self.router = _StartupRouter(self, **kwargs)
        return self.router

    async def attach(
        self,
        *,
        app: ConversationScreenPort,
        stdin: TextIO,
        stdout: TextIO,
        action_host: ConversationActionHost,
        profile: ConversationScreenRunProfile,
        should_exit: ShouldExit,
        handle_local: TextHandler | None = None,
        handle_surface_intent: SurfaceIntentHandler | None = None,
        is_local_command: LocalCommandPredicate | None = None,
        keybindings: KeybindingManager | KeybindingConfig | None = None,
    ) -> int:
        del stdin, stdout  # Only the original outer runner owns terminal streams.
        if self.closing or self.attached or app is not self.app:
            raise RuntimeError("invalid or late screen attachment")
        if self.router is None or self.router.disposed:
            raise RuntimeError("screen input owner is unavailable")
        with open_conversation_screen_runtime(profile) as factory:
            callbacks = bind_action_host_to_screen_runner(action_host)
            self.handlers = {
                "prompt": callbacks.handle_prompt,
                "local": handle_local,
                "steer": callbacks.handle_steer,
                "followup": callbacks.handle_followup,
                "surface": handle_surface_intent,
                "abort": callbacks.on_abort,
            }
            self.context = copy_context()
            kwargs = dict(self.router.kwargs)
            kwargs.update(
                should_exit=should_exit,
                is_local_command=is_local_command or (lambda _text: False),
                keybindings=keybindings,
            )
            self.router.ready = (factory or ConversationInputRouter)(**kwargs)
            self.finished = asyncio.get_running_loop().create_future()
            self.attached = True
            self.app.state.startup_pending = False
            self.app.state.status_message = None
            self.app.request_render()
            self._wake()
            return await self.finished

    def handler(self, name: str) -> Callable[..., Awaitable[Any]]:
        async def forwarded(*args: Any, **kwargs: Any) -> Any:
            callback = self.handlers.get(name)
            if callback is None or self.closing:
                return None
            assert self.context is not None

            async def invoke() -> Any:
                result = callback(*args, **kwargs)
                return await result if inspect.isawaitable(result) else result

            return await asyncio.create_task(invoke(), context=self.context.copy())

        return forwarded

    async def settle(
        self,
        exit_code: int,
        active_task: asyncio.Task[int | None] | None,
        dispose_router: Callable[[], None],
    ) -> None:
        self.closing = True  # Synchronous fence wins over a late attach.

        async def cleanup() -> None:
            errors: list[BaseException] = []
            if active_task is not None:
                if not active_task.done():
                    active_task.cancel()
                try:
                    await active_task
                except asyncio.CancelledError:
                    pass
                except BaseException as error:
                    errors.append(error)
            try:
                dispose_router()
            except BaseException as error:
                errors.append(error)
            if self.finished is not None and not self.finished.done():
                self.finished.set_result(exit_code)
            if self.task is not None:
                requested_cancel = False
                if (
                    not self.attached
                    and not self.preparation_settling
                    and not self.task.done()
                ):
                    self.task.cancel()
                    requested_cancel = True
                try:
                    result = await self.task
                    self.exit_code = self.exit_code or result or exit_code
                except asyncio.CancelledError:
                    if requested_cancel:
                        self.exit_code = self.exit_code or exit_code
                    else:
                        errors.append(
                            RuntimeError(
                                "Session preparation/cleanup cancelled unexpectedly"
                            )
                        )
                except BaseException as error:
                    # A displayed preparation failure is already observable.
                    if not self._observed:
                        errors.append(error)
            if errors:
                raise BaseExceptionGroup("screen startup settlement failed", errors)

        await join_screen_settlement(asyncio.create_task(cleanup()))

    async def run(self, *, stdin: TextIO, stdout: TextIO, **runner_options: Any) -> int:
        result = await run_conversation_screen(
            app=self.app,
            stdin=stdin,
            stdout=stdout,
            handle_prompt=self.handler("prompt"),
            handle_local=self.handler("local"),
            handle_steer=self.handler("steer"),
            handle_followup=self.handler("followup"),
            handle_surface_intent=self.handler("surface"),
            on_abort=self.handler("abort"),
            should_exit=lambda _text: False,
            interruption_message="Conversation interrupted",
            cancellation_message="Operation aborted",
            input_router_factory=self.build_router,
            lifecycle=self,
            **runner_options,
        )
        return self.exit_code or result


__all__ = [
    "ScreenConversationStartup",
    "join_screen_settlement",
    "startup_failure_summary",
]
