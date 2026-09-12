"""Linux loading-screen coordination; Product execution stays on the main loop.

Selected by Coding's screen-first adapter only for real Linux terminal input.
"""

from __future__ import annotations

import asyncio
from typing import TextIO

from loushang.harnesstui.conversation.loading_surface import (
    LoadingScreenTransfer,
    LoadingSurfaceJoinTimeout,
    LoadingSurfaceWorker,
)
from loushang.harnesstui.conversation.screen_runner import (
    ConversationScreenContinuation,
    TerminalModeFactory,
    TerminalSizeProvider,
    terminal_size,
)
from loushang.harnesstui.conversation.startup_host import (
    ScreenConversationStartup,
    join_screen_settlement,
)
from loushang.tui.terminal_backends.posix import PosixTerminalInputReader
from loushang.tui.terminal_session import TerminalSession


class ThreadedScreenStartup:
    """Own one terminal lease around a joined loading-to-main handoff."""

    def __init__(self, startup: ScreenConversationStartup) -> None:
        self.startup = startup
        self._wake = asyncio.Event()
        self._handoff_requested = False
        self._worker: LoadingSurfaceWorker | None = None
        self._transfer: LoadingScreenTransfer | None = None
        self._joined = False
        self._ran = False

    async def before_product_ui(self) -> None:
        """Call before any Product UI import/binding that touches the shared app."""
        self._handoff_requested = True
        self._wake.set()
        await self.startup.wait_for_input_owner()
        if not self._joined:
            raise RuntimeError("input owner exposed before loading thread joined")

    async def _join_loading(self) -> None:
        if self._joined or self._worker is None:
            return
        worker = self._worker
        worker.request_transfer()

        async def collect() -> None:
            while True:
                try:
                    # Nonblocking Thread.join on main needs no executor whose
                    # submission failure could be mistaken for worker completion.
                    self._transfer = worker.join(0)
                except LoadingSurfaceJoinTimeout:
                    # A timeout does not transfer ownership or release the lease.
                    await asyncio.sleep(0.01)
                    continue
                except BaseException:
                    self._joined = True
                    raise
                self._joined = True
                return

        await join_screen_settlement(asyncio.create_task(collect()))

    async def run(
        self,
        *,
        stdin: TextIO,
        stdout: TextIO,
        terminal_mode_factory: TerminalModeFactory | None = None,
        terminal_size_provider: TerminalSizeProvider | None = None,
    ) -> int:
        if self._ran:
            raise RuntimeError("threaded startup may only run once")
        self._ran = True
        loop = asyncio.get_running_loop()

        def notify_closing() -> None:
            loop.call_soon_threadsafe(self._wake.set)

        size_provider = terminal_size_provider or terminal_size
        mode = (
            terminal_mode_factory(stdin, stdout)
            if terminal_mode_factory is not None
            else TerminalSession(stdin=stdin, stdout=stdout)
        )
        with mode as context:
            reader = PosixTerminalInputReader(stdin.fileno())
            self.startup.defer_submission_until_input_boundary(reader.at_input_boundary)
            worker = LoadingSurfaceWorker(
                app=self.startup.app,
                byte_reader=reader,
                stdout=stdout,
                terminal_context=context,
                size_provider=size_provider,
                on_closing=notify_closing,
            )
            worker.start()
            self._worker = worker
            primary_error: BaseException | None = None
            try:
                # No Product work exists yet. Wait releases the GIL to the owner.
                worker.wait_first_frame(10)
                if worker.closing_code is None:
                    self.startup.start(self._wake.set)
                while (
                    not self._handoff_requested
                    and self.startup.task is not None
                    and not self.startup.task.done()
                    and worker.closing_code is None
                ):
                    await self._wake.wait()
                    self._wake.clear()
                await self._join_loading()
                if worker.closing_code is not None:
                    await self.startup.settle(worker.closing_code, None, lambda: None)
                    return self.startup.exit_code or worker.closing_code
                assert self._transfer is not None
                state = self._transfer

                async def read(_stdin: TextIO) -> str:
                    return await state.byte_reader.read_chunk()

                continuation = ConversationScreenContinuation(
                    app=state.app,
                    parser=state.parser,
                    runtime=state.runtime,
                    terminal_context=state.terminal_context,
                    input_chunk_reader=read,
                    pending_idle_deadline=state.pending_idle_deadline,
                    before_input_read=self.startup.before_input_read,
                    resume_preparation=True,
                )
                return await self.startup.run(
                    stdin=stdin,
                    stdout=stdout,
                    continuation=continuation,
                    terminal_size_provider=size_provider,
                )
            except BaseException as error:
                primary_error = error
                raise
            finally:
                cleanup_errors: list[BaseException] = []
                deferred_cancel: asyncio.CancelledError | None = None
                try:
                    await self._join_loading()
                except asyncio.CancelledError as error:
                    deferred_cancel = error
                except BaseException as error:
                    if error is not primary_error:
                        cleanup_errors.append(error)
                try:
                    if not self.startup.closing:
                        await self.startup.settle(1, None, lambda: None)
                except asyncio.CancelledError as error:
                    deferred_cancel = error
                except BaseException as error:
                    cleanup_errors.append(error)
                if cleanup_errors:
                    if primary_error is not None:
                        cleanup_errors.insert(0, primary_error)
                    raise BaseExceptionGroup(
                        "loading startup and settlement failed", cleanup_errors
                    )
                if deferred_cancel is not None and primary_error is None:
                    raise deferred_cancel
