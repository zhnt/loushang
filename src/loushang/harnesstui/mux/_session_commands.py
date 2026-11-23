"""Hosted Session command presentation on the shell's existing action tasks."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from secrets import token_hex
from typing import TYPE_CHECKING

from loushang.appserver.execution.client import SessionCommandClientV1
from loushang.appserver.execution.model import (
    ExecutionRecordV1,
    ExecutionServiceErrorV1,
)
from loushang.appserver.execution.recovery import (
    PendingSubmissionV1,
    SubmissionDeliveryV1,
    SubmissionRecoveryV1,
)
from loushang.appserver.execution.session_commands import (
    SessionCommandCatalogV1,
    SessionCommandInvocationV1,
    SessionCommandResultV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
)
from loushang.tui import CompletionItem, CompletionProvider
from loushang.tui.completion import SlashCommand

if TYPE_CHECKING:
    from .model import HarnessWindowState
    from .shell import HostedMuxShellV1


def command_name(text: str) -> str:
    if not text.startswith("/"):
        return ""
    name, *_ = (*text[1:].split(maxsplit=1), "")
    return name


class HostedSessionCommandUI:
    def __init__(self, shell: HostedMuxShellV1, local_names: tuple[str, ...]) -> None:
        self._shell, self._local_names = shell, frozenset(local_names)
        self._catalog: SessionCommandCatalogV1 | None = None
        self._prefix = ""
        self._catalog_pending = False
        self._checked_at = 0.0
        self._submissions: dict[
            tuple[SessionIdentityV1, SessionCommandInvocationV1], SubmissionRecoveryV1
        ] = {}

    @property
    def client(self) -> SessionCommandClientV1 | None:
        client = self._shell._execution_client
        return client if isinstance(client, SessionCommandClientV1) else None

    def invalidate(self) -> None:
        self._catalog = None
        self._prefix = ""
        self._checked_at = 0.0

    def completions(self) -> list[SlashCommand]:
        if self._catalog is None:
            return []
        name, separator, _ = self._prefix.lstrip("/").partition(" ")
        arguments = CompletionProvider(
            tuple(CompletionItem(value) for value in self._catalog.completions)
        )
        return [
            SlashCommand(
                candidate,
                description=entry.description,
                argument_provider=arguments
                if separator and candidate == name
                else None,
            )
            for entry in self._catalog.commands
            if entry.unavailable_reason is None
            for candidate in (entry.name, *entry.aliases)
            if candidate not in self._local_names
        ]

    def _target(
        self,
    ) -> tuple[
        SessionCommandClientV1,
        SessionSnapshotRequestV1,
        HarnessWindowState,
        Callable[[], bool],
    ]:
        shell = self._shell
        state, window = shell._target()
        client = self.client
        if client is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        control = SessionSnapshotRequestV1(
            state.attachment_id, state.controller_generation, window.member_id
        )
        serial = shell._request_serial

        def current() -> bool:
            return (
                not shell._closing
                and not shell._membership_pending
                and not shell.state.snapshot_required
                and shell.state is state
                and shell.state.active_window is window
                and shell._request_serial == serial
            )

        return client, control, window, current

    def refresh(self) -> None:
        shell = self._shell
        prefix = shell.screen.composer.value
        if (
            self.client is None
            or self._catalog_pending
            or shell.state.snapshot_required
            or shell.state.active_window is None
            or not prefix.startswith("/")
            or prefix.startswith("//")
            or len(prefix.encode("utf-8")) > 512
            or "\n" in prefix
        ):
            return
        if command_name(prefix) in self._local_names:
            return
        now = asyncio.get_running_loop().time()
        if self._prefix == prefix and now - self._checked_at < 2:
            return
        client, control, _, current = self._target()

        async def refresh() -> None:
            try:
                catalog = await client.session_command_catalog(
                    control, client.service_instance_id, prefix
                )
            except (AppServiceError, ExecutionServiceErrorV1):
                catalog = None
            finally:
                self._catalog_pending = False
            if current() and shell.screen.composer.value == prefix:
                changed = catalog != self._catalog or prefix != self._prefix
                self._catalog, self._prefix, self._checked_at = catalog, prefix, now
                if changed:
                    shell.refresh_capability_completions(force=True)
                    shell.screen.composer.refresh_completions(force=True)

        shell._actions.submit(refresh, control=True)
        self._catalog_pending = True

    def preserve_typed_command(self) -> None:
        composer = self._shell.screen.composer
        text = composer.value.lstrip()
        name = command_name(text)
        if (
            self.client is not None
            and name
            and name not in self._local_names
            and not text.startswith("//")
        ):
            # Discovery is asynchronous. Enter must not replace a typed
            # command with a similar local one (e.g. /session and /sessions).
            # Tab still applies the selected suggestion.
            composer.clear_completion_items()

    def submit(self, text: str) -> None:
        client, control, window, current = self._target()
        instance = client.service_instance_id
        parts = text[1:].split(maxsplit=1)
        if not parts:
            raise ValueError("command name required")
        name, args = parts[0], parts[1] if len(parts) > 1 else ""
        if args.startswith("(MCP)") and (len(args) == 5 or args[5:6].isspace()):
            name, args = name + " (MCP)", args[5:].lstrip()

        async def wait_for_result(record: ExecutionRecordV1) -> None:
            while current() and not record.state.status.terminal:
                await asyncio.sleep(0.2)
                record = await client.get_execution(
                    control, instance, record.state.execution_id
                )
            if not current():
                return
            result = await client.session_command_result(
                control, instance, record.state.execution_id
            )
            if current():
                self._present_result(record, result)

        if name == "commands" and not args:

            async def show_catalog() -> None:
                catalog = await client.session_command_catalog(control, instance)
                if current():
                    self._show_catalog(catalog)

            self._run_read(show_catalog, current)
            return

        if name == "command-result":

            async def find_result() -> None:
                record = await client.find_execution_by_submission(
                    control, instance, args
                )
                if record is not None:
                    await wait_for_result(record)
                    if current():
                        for key, recovery in tuple(self._submissions.items()):
                            if recovery.pending.submission_id == args:
                                self._submissions.pop(key)
                elif current():
                    self._shell.notice = (
                        "Command result unavailable for this Session and Host instance"
                    )

            if not args:
                raise ValueError("submission ID required")
            self._run_read(find_result, current)
            return

        invocation = SessionCommandInvocationV1(name, args)
        key = window.identity, invocation
        prior = self._submissions.get(key)
        if prior is not None:
            self._shell.notice = f"Command already submitted; /command-result {prior.pending.submission_id}"
            return
        if len(self._submissions) >= 64:
            raise ValueError("action_queue_full")
        submission_id = token_hex(16)
        recovery = SubmissionRecoveryV1(
            PendingSubmissionV1(
                instance, window.identity, submission_id, "", invocation
            )
        )

        async def run() -> None:
            finished = False
            try:
                catalog = await client.session_command_catalog(control, instance)
                entry = next(
                    (
                        entry
                        for entry in catalog.commands
                        if name in (entry.name, *entry.aliases)
                    ),
                    None,
                )
                if not current():
                    return
                if entry is None or entry.unavailable_reason:
                    reason = (
                        entry.unavailable_reason if entry else "command unavailable"
                    )
                    self._shell.notice = f"/{name}: {reason}"
                    return
                if entry.read_only:
                    result = await client.read_session_command(
                        control, instance, invocation
                    )
                    if current():
                        self._show_result(f"/{name}", result)
                    return
                self._shell.notice = (
                    f"/{name} submitted; /command-result {submission_id}"
                )
                await recovery.submit(client, control)
                if recovery.record is not None:
                    await wait_for_result(recovery.record)
                    finished = current()
            except (AppServiceError, ExecutionServiceErrorV1) as error:
                if current():
                    suffix = (
                        f"; /command-result {submission_id}"
                        if recovery.delivery
                        in {
                            SubmissionDeliveryV1.UNKNOWN,
                            SubmissionDeliveryV1.KNOWN,
                        }
                        else ""
                    )
                    self._shell.notice = f"/{name}: {error.code.value}{suffix}"
            finally:
                if finished or recovery.delivery in {
                    SubmissionDeliveryV1.READY,
                    SubmissionDeliveryV1.REJECTED,
                    SubmissionDeliveryV1.INSTANCE_CHANGED,
                }:
                    self._submissions.pop(key, None)

        self._shell._actions.submit(run)
        self._submissions[key] = recovery

    def _run_read(
        self, operation: Callable[[], Awaitable[None]], current: Callable[[], bool]
    ) -> None:
        async def run() -> None:
            try:
                await operation()
            except (AppServiceError, ExecutionServiceErrorV1) as error:
                if current():
                    self._shell.notice = error.code.value

        self._shell._actions.submit(run)

    def _show_catalog(self, catalog: SessionCommandCatalogV1) -> None:
        lines = []
        for entry in catalog.commands:
            reason = (
                "reserved by Hosted TUI"
                if entry.name in self._local_names
                else entry.unavailable_reason
            )
            suffix = f" ({reason})" if reason else ""
            lines.append(
                f"/{entry.name} {entry.argument_hint}  {entry.description}{suffix}"
            )
        if catalog.truncated:
            lines.append("Additional commands omitted.")
        self._shell.screen.show_command_details(
            "Session commands", "\n".join(lines) or "No Session commands"
        )

    def _show_result(self, title: str, result: SessionCommandResultV1) -> None:
        self._shell.screen.show_command_details(
            title, json.dumps(result.data, indent=2, ensure_ascii=False)
        )

    def _present_result(
        self, record: ExecutionRecordV1, result: SessionCommandResultV1 | None
    ) -> None:
        status = record.state.status.value
        outcome = record.state.outcome
        reason = (
            f" ({outcome.error_code})"
            if outcome is not None and outcome.error_code
            else ""
        )
        self._shell.notice = f"Session command {status}{reason}"
        if result is not None:
            self._show_result("Session command", result)

    def interrupt(self, window: HarnessWindowState) -> bool:
        client = self.client
        if client is None:
            return False
        record = next(
            (
                recovery.record
                for (identity, _), recovery in self._submissions.items()
                if identity == window.identity
                and recovery.record is not None
                and not recovery.record.state.status.terminal
            ),
            None,
        )
        if record is None:
            return False
        _, control, _, current = self._target()

        async def interrupt() -> None:
            try:
                await client.interrupt_execution(
                    control, client.service_instance_id, record.state.execution_id
                )
            except (AppServiceError, ExecutionServiceErrorV1) as error:
                if current():
                    self._shell.notice = error.code.value

        self._shell._actions.submit(interrupt, control=True)
        return True
