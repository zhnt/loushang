"""Explicit Hosted Mux interaction owner over a borrowed AppClient."""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable, Coroutine
from secrets import token_hex
from typing import TypeVar

from loushang.appserver.client import AppClientV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxMemberCloseV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.tui.input import InputEvent, InputRouter

from ._shell_screen import HostedMuxScreenV1, safe_text
from ._shell_tasks import ShellActions, join, owned_task
from .controller import HostedMuxControllerV1
from .model import HarnessWindowState, HostedMuxState
from .reducer import select_next, select_previous, select_window, set_active_draft

MAX_DRAFT_BYTES = 64 * 1024
MAX_SHELL_DRAFT_BYTES = 1024 * 1024
T = TypeVar("T")


class HostedMuxShellV1:
    """Own local editing, bounded request waiters and one logical attachment.

    No connection/process close capability is accepted. Cancellation of local
    waiters or detach cannot be converted into interrupt or application stop.
    """

    def __init__(
        self,
        client: AppClientV1,
        *,
        selector: MuxSelectorV1,
        product_id: str,
        scopes: tuple[tuple[SessionScopeV1, str], ...],
        close_timeout: float = 5.0,
    ) -> None:
        if (
            type(close_timeout) not in (float, int)
            or not 0 < close_timeout <= 20
            or not 1 <= len(scopes) <= 2
        ):
            raise ValueError("invalid hosted shell configuration")
        for scope, fingerprint in scopes:
            SessionOpenSpecV1(product_id, "validate", scope, fingerprint, "validate")
        if len({scope for scope, _ in scopes}) != len(scopes):
            raise ValueError("ambiguous hosted scope")
        self._client, self._selector = client, selector
        self._product_id, self._scopes = product_id, dict(scopes)
        self._controller = HostedMuxControllerV1(client, selector=selector)
        self._actions = ShellActions(self._failed)
        self._start_task: asyncio.Task[HostedMuxState] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._detach_task: asyncio.Task[None] | None = None
        self._terminal_waiters: set[asyncio.Task[object]] = set()
        self._deadline: float | None = None
        self._timeout = close_timeout
        self._closing = self._settled = self._membership_pending = False
        self._prefix = False
        self.notice = "cwd / user_home: /new <scope>; /help"
        self.exit_requested = False
        self.exit_code = 0
        self.screen = HostedMuxScreenV1(self)
        self._router = InputRouter(composer=self.screen.composer)

    @property
    def state(self) -> HostedMuxState:
        state = self._controller.state
        if state is None:
            raise RuntimeError("hosted shell is not attached")
        return state

    @property
    def pending_actions(self) -> int:
        return self._actions.pending

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def start(self) -> None:
        if self._start_task is not None or self._closing:
            raise ValueError("hosted shell already started or closed")
        self._start_task = owned_task(self._controller.start)
        try:
            await asyncio.shield(self._start_task)
            if self._closing:
                raise ValueError("hosted shell closed")
            self._sync_editor()
            if any(window.running for window in self.state.windows):
                self.notice = (
                    "running; earlier partial output is not in the v1 snapshot"
                )
        except BaseException:
            await self.close()
            raise

    def handle(self, event: InputEvent) -> None:
        if self._closing or self.exit_requested or event.event_type == "release":
            return
        try:
            self._handle(event)
        except AppServiceError as error:
            self.notice = error.code.value
        except (ValueError, KeyError) as error:
            self.notice = (
                str(error)
                if str(error) in {"draft_limit", "action_queue_full"}
                else "invalid_or_unavailable_action"
            )

    def resize(self, width: int, height: int) -> None:
        self._router.width, self._router.height = width, height

    def start_terminal_waiter(
        self, operation: Callable[[], Coroutine[object, object, T]]
    ) -> asyncio.Task[T]:
        """Retain at most one input reader and one event poll under UI cleanup."""
        if (
            self._closing
            or sum(not task.done() for task in self._terminal_waiters) >= 2
        ):
            raise ValueError("terminal waiter capacity unavailable")
        task = owned_task(operation)
        self._terminal_waiters.add(task)
        task.add_done_callback(self._terminal_waiters.discard)
        return task

    def _handle(self, event: InputEvent) -> None:
        key = event.key if event.kind == "key" else ""
        if key == "ctrl+b":
            self._prefix = True
            return
        if self._prefix:
            self._prefix = False
            choice = event.text if event.kind == "text" else key
            if choice == "d":
                self.exit_requested = True
            elif choice in {"n", "p"}:
                self._select(choice == "n")
            elif choice.isdecimal() and 1 <= int(choice) <= len(self.state.windows):
                select_window(self.state, int(choice) - 1)
                self._sync_editor()
            return
        if key == "ctrl+d" and not self.screen.composer.value:
            self.exit_requested = True
            return
        if key == "ctrl+v":
            self.notice = "image_paste_unavailable"
            return
        if key in {"tab", "shift+tab"} and not self.screen.composer.has_completions:
            self._select(key == "tab")
            return
        if key == "f1":
            self.screen.show_help()
            return
        if key == "f2":
            self._target()
            self.screen.show_approval()
            return
        if key == "ctrl+c":
            self._command("/interrupt")
            return
        if self.screen.handle_details(event):
            return
        if key in {"pageUp", "pageDown"}:
            window = self.state.active_window
            if window is not None:
                end = (
                    len(window.records)
                    if window.scroll_anchor is None
                    else window.scroll_anchor
                )
                end = max(
                    1, min(len(window.records), end + (-8 if key == "pageUp" else 8))
                )
                window.scroll_anchor = None if end == len(window.records) else end
            return
        if key == "enter":
            text = self.screen.composer.value
            if not text:
                return
            if text.startswith("/") and not text.startswith("//"):
                self._command(text)
            else:
                self._turn(text[1:] if text.startswith("//") else text)
            self._set_draft("")
            self.screen.composer.clear()
            return
        if self._membership_pending and self.state.active_window is None:
            self.notice = "member_pending: wait for the first Session"
            return
        before = self.screen.composer.value
        if event.kind in {"text", "paste"}:
            text = safe_text(event.text)
            self._check_draft(before + text)
            event = InputEvent(kind=event.kind, text=text)
        self._router.route(event)
        try:
            self._set_draft(self.screen.composer.value)
        except ValueError:
            self.screen.composer.set_text(before)
            raise

    def _check_draft(self, text: str) -> None:
        size = len(text.encode("utf-8"))
        other = sum(
            len(item.draft.encode("utf-8"))
            for item in self.state.windows
            if item is not self.state.active_window
        )
        if size > MAX_DRAFT_BYTES or size + other > MAX_SHELL_DRAFT_BYTES:
            raise ValueError("draft_limit")

    def _set_draft(self, text: str) -> None:
        self._check_draft(text)
        if self.state.active_window is not None:
            set_active_draft(self.state, text)

    def _select(self, forward: bool) -> None:
        (select_next if forward else select_previous)(self.state)
        self._sync_editor()

    def _sync_editor(self) -> None:
        self.screen.dismiss_details()
        self.screen.composer.clear()
        window = self.state.active_window
        self.screen.composer.set_text(window.draft if window else "")

    def _target(self) -> tuple[HostedMuxState, HarnessWindowState]:
        state = self.state
        if state.snapshot_required or self._membership_pending:
            raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        window = state.active_window
        if window is None:
            raise ValueError("no active member")
        return state, window

    def _turn(self, text: str, *, mode: str = "start") -> None:
        state, window = self._target()
        request = TurnTextV1(
            state.attachment_id, state.controller_generation, window.member_id, text
        )
        operation = {
            "start": self._client.start_turn,
            "steer": self._client.steer_turn,
            "followup": self._client.follow_up_turn,
        }[mode]
        self._actions.submit(lambda: operation(request))
        self.notice = "request_pending; lost replies are not retried"

    def _command(self, text: str) -> None:
        parts = shlex.split(text)
        command, args = parts[0], parts[1:]
        if command in {"/detach", "/exit"} and not args:
            self.exit_requested = True
        elif command == "/help" and not args:
            self.screen.show_help()
        elif command == "/question" and not args:
            self._target()
            self.screen.show_approval()
        elif command == "/refresh" and not args:
            self._membership(self._controller.refresh_snapshot)
        elif command in {"/new", "/resume"} and args:
            scope = SessionScopeV1(args[0])
            fingerprint = self._scopes[scope]
            if command == "/resume" and len(args) != 3:
                raise ValueError("resume requires explicit identity")
            spec = SessionOpenSpecV1(
                self._product_id,
                args[1] if command == "/resume" else token_hex(16),
                scope,
                fingerprint,
                "Resumed" if command == "/resume" else " ".join(args[1:]) or "Session",
                args[2] if command == "/resume" else None,
            )
            self._membership(lambda: self._controller.open_member(spec))
        elif command == "/close" and args == ["--yes"]:
            _, window = self._target()
            request = MuxMemberCloseV1(
                self._selector, window.member_id, close_session=True
            )

            async def close_member() -> HostedMuxState:
                await self._client.close_member(request)
                return await self._controller.refresh_snapshot()

            self._membership(close_member)
        elif command in {"/steer", "/followup"} and args:
            self._turn(" ".join(args), mode=command[1:])
        elif command in {"/approve", "/deny", "/interrupt"} and not args:
            state, window = self._target()
            if command == "/interrupt":
                interrupt = TurnInterruptV1(
                    state.attachment_id, state.controller_generation, window.member_id
                )
                self._actions.submit(
                    lambda: self._client.interrupt_turn(interrupt), control=True
                )
            else:
                if window.pending_interaction_id is None:
                    raise ValueError("no active interaction")
                if command == "/approve" and not self.screen.approval_presented():
                    self.screen.show_approval()
                    self.notice = "Present all approval details, Esc, then /approve"
                    return
                response = InteractionRespondV1(
                    state.attachment_id,
                    state.controller_generation,
                    window.member_id,
                    window.pending_interaction_id,
                    InteractionOutcomeV1.APPROVE
                    if command == "/approve"
                    else InteractionOutcomeV1.DENY,
                )
                self._actions.submit(
                    lambda: self._client.respond_interaction(response), control=True
                )
        else:
            raise ValueError("unsupported action")

    def _membership(
        self, operation: Callable[[], Coroutine[object, object, HostedMuxState]]
    ) -> None:
        if self._membership_pending:
            raise ValueError("membership change pending")

        async def apply() -> HostedMuxState:
            try:
                result = await operation()
                self._sync_editor()
                self.notice = "cwd / user_home; /help"
                return result
            finally:
                self._membership_pending = False

        self._actions.submit(apply)
        self._membership_pending = True

    async def poll(self) -> None:
        if self._closing or self._membership_pending:
            return
        try:
            await self._controller.poll()
            if self.state.snapshot_required:
                self.notice = "snapshot_required: /refresh"
            # Presentation retention does not delete canonical history.
            for window in self.state.windows:
                total = sum(
                    len(record.text.encode("utf-8")) for record in window.records
                )
                while len(window.records) > 256 or total > 512 * 1024:
                    total -= len(window.records.pop(0).text.encode("utf-8"))
                    window.scroll_anchor = None
                    self.notice = (
                        "local_history_window_limited; canonical history retained"
                    )
                if len(window.assistant_draft.encode("utf-8")) > 512 * 1024:
                    window.assistant_draft = window.assistant_draft[-128 * 1024 :]
                    self.notice = (
                        "local_stream_window_limited; canonical history retained"
                    )
        except AppServiceError as error:
            self._failed(error)

    def _failed(self, error: BaseException) -> None:
        self.notice = (
            error.code.value if isinstance(error, AppServiceError) else "action_failed"
        ) + "; outcome unknown, no retry"
        if (
            isinstance(error, AppServiceError)
            and error.code is AppErrorCodeV1.SERVICE_CLOSED
        ):
            self.exit_code, self.exit_requested = 1, True

    async def close(self) -> None:
        if self._settled:
            return
        self._closing = True
        if self._deadline is None:
            self._deadline = asyncio.get_running_loop().time() + self._timeout
        if self._close_task is None or (
            self._close_task.done()
            and (
                self._close_task.cancelled() or self._close_task.exception() is not None
            )
        ):
            self._close_task = owned_task(self._close_once)
        await asyncio.shield(self._close_task)

    async def _close_once(self) -> None:
        assert self._deadline is not None
        waiters = tuple(self._terminal_waiters)
        for task in waiters:
            task.cancel()
        for task in waiters:
            await join(task, self._deadline, ignore_error=True)
        if self._start_task is not None:
            await join(self._start_task, self._deadline, ignore_error=True)
        await self._actions.close(self._deadline)
        if self._detach_task is None:
            self._detach_task = owned_task(self._controller.close)
        await join(self._detach_task, self._deadline)
        self._settled = True


__all__ = ["HostedMuxShellV1"]
