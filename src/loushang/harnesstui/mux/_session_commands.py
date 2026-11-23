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
    SessionModelSelectV1,
    SessionModelsV1,
    SessionSnapshotRequestV1,
)
from loushang.harness.commands import DEFAULT_LOCAL_COMMANDS_PROFILE
from loushang.tui import CompletionItem, CompletionProvider
from loushang.tui.completion import SlashCommand

from ..selection.catalog import (
    ModelChoice,
    current_model_choice_first,
    format_model_choices,
    model_choice_select_items,
    model_completion_provider,
)
from ..selection.interaction import ModelInteractionSnapshot, resolve_model_interaction
from ..selection.model import ModelSelectorSurface

if TYPE_CHECKING:
    from .model import HarnessWindowState
    from .shell import HostedMuxShellV1


MODEL_COMMANDS = ("model", "models")


def _model_choices(models: SessionModelsV1) -> tuple[ModelChoice, ...]:
    return tuple(
        ModelChoice(item.label, item.id, item, endpoint_id=item.endpoint_id)
        for item in models.models
    )


def _thinking_hint(models: SessionModelsV1) -> str:
    if models.thinking is None:
        return ""
    levels = ", ".join(models.thinking.available_levels)
    return f"Reasoning {models.thinking.current_level or 'default'} · {levels} · /model --thinking <level>"


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
        self._model_arguments: CompletionProvider | None = None
        self._model_request = 0
        self._catalog_pending = False
        self._checked_at = 0.0
        self._submissions: dict[
            tuple[SessionIdentityV1, SessionCommandInvocationV1], SubmissionRecoveryV1
        ] = {}

    @property
    def client(self) -> SessionCommandClientV1 | None:
        client = self._shell._execution_client
        return client if isinstance(client, SessionCommandClientV1) else None

    @property
    def models_available(self) -> bool:
        return all(
            callable(getattr(self._shell._client, operation, None))
            for operation in ("list_session_models", "select_session_model")
        )

    def invalidate(self) -> None:
        self._catalog = None
        self._model_arguments = None
        self._prefix = ""
        self._checked_at = 0.0

    def completions(self) -> list[SlashCommand]:
        model_commands = (
            [
                SlashCommand(
                    name,
                    description=DEFAULT_LOCAL_COMMANDS_PROFILE.local_commands_by_name[
                        name
                    ].description
                    or "",
                    argument_provider=self._model_arguments
                    if name == "model"
                    else None,
                )
                for name in MODEL_COMMANDS
            ]
            if self.models_available and self._shell.state.active_window is not None
            else []
        )
        if self._catalog is None:
            return model_commands
        name, separator, _ = self._prefix.lstrip("/").partition(" ")
        arguments = CompletionProvider(
            tuple(CompletionItem(value) for value in self._catalog.completions)
        )
        return model_commands + [
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
        client = self.client
        if client is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return client, *self._view_target()

    def _view_target(
        self,
    ) -> tuple[SessionSnapshotRequestV1, HarnessWindowState, Callable[[], bool]]:
        shell = self._shell
        state, window = shell._target()
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

        return control, window, current

    def refresh(self) -> None:
        shell = self._shell
        prefix = shell.screen.composer.value
        if (
            self._catalog_pending
            or shell.state.snapshot_required
            or shell.state.active_window is None
            or not prefix.startswith("/")
            or prefix.startswith("//")
            or len(prefix.encode("utf-8")) > 512
            or "\n" in prefix
        ):
            return
        model_prefix = self.models_available and prefix.startswith("/model ")
        if not model_prefix and (
            self.client is None or command_name(prefix) in self._local_names
        ):
            return
        now = asyncio.get_running_loop().time()
        if self._prefix == prefix and now - self._checked_at < 2:
            return
        control, _, current = self._view_target()
        client = self.client

        async def refresh() -> None:
            catalog = None
            arguments = None
            try:
                if model_prefix:
                    models = await shell._client.list_session_models(control)
                    arguments = model_completion_provider(
                        _model_choices(models), current_value=models.current_id
                    )
                elif client is not None:
                    catalog = await client.session_command_catalog(
                        control, client.service_instance_id, prefix
                    )
            except (AppServiceError, ExecutionServiceErrorV1):
                catalog = None
            finally:
                self._catalog_pending = False
            if current() and shell.screen.composer.value == prefix:
                changed = (
                    catalog != self._catalog
                    or prefix != self._prefix
                    or arguments != self._model_arguments
                )
                self._catalog, self._prefix, self._checked_at = catalog, prefix, now
                self._model_arguments = arguments
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
            name in MODEL_COMMANDS
            or (self.client is not None and name and name not in self._local_names)
        ) and not text.startswith("//"):
            # Discovery is asynchronous. Enter must not replace a typed
            # command with a similar local one (e.g. /session and /sessions).
            # Tab still applies the selected suggestion.
            composer.clear_completion_items()

    def submit_model(self, name: str, query: str) -> None:
        shell = self._shell
        control, window, view_current = self._view_target()
        self._model_request += 1
        request = self._model_request

        def current() -> bool:
            return self._model_request == request and view_current()

        def update_model_label(models: SessionModelsV1) -> None:
            selected = next(
                (item.label for item in models.models if item.id == models.current_id),
                None,
            )
            window.model_label = selected

        async def select(model_id: str, level: str | None = None) -> None:
            if not current():
                return
            models = await shell._client.select_session_model(
                SessionModelSelectV1(
                    control.attachment_id,
                    control.controller_generation,
                    control.member_id,
                    model_id,
                    level,
                )
            )
            if current():
                update_model_label(models)
                shell.notice = f"Model {window.model_label or 'unavailable'}"
                if hint := _thinking_hint(models):
                    shell.screen.show_command_details(
                        "Current model", f"{window.model_label}\n{hint}"
                    )

        async def run() -> None:
            models = await shell._client.list_session_models(control)
            if not current():
                return
            update_model_label(models)
            choices = _model_choices(models)
            if name == "models":
                summary = format_model_choices(
                    choices, query=query, current_value=models.current_id
                )
                shell.screen.show_command_details(
                    "Models", "\n".join(filter(None, (summary, _thinking_hint(models))))
                )
                return
            if query == "--thinking" or query.startswith("--thinking "):
                level = query.removeprefix("--thinking").strip()
                if (
                    models.current_id
                    and models.thinking
                    and level in models.thinking.available_levels
                ):
                    await select(models.current_id, level)
                else:
                    shell.screen.show_command_details(
                        "Reasoning levels",
                        _thinking_hint(models)
                        or "The current model has no reasoning settings",
                    )
                return
            resolution = resolve_model_interaction(
                ModelInteractionSnapshot(choices, models.current_id), query=query
            )
            if resolution.choice is not None:
                await select(resolution.choice.value)
            elif resolution.matches:
                items = model_choice_select_items(
                    current_model_choice_first(
                        resolution.matches, current_value=models.current_id
                    ),
                    current_value=models.current_id,
                )
                shell.screen.show_model_picker(
                    ModelSelectorSurface(
                        tuple(items), selected_value=models.current_id
                    ),
                    lambda value: self._run_read(lambda: select(value), current),
                )
            else:
                shell.screen.show_command_details(
                    "Models",
                    format_model_choices(
                        choices, query=query, current_value=models.current_id
                    ),
                )

        self._run_read(run, current)

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
                catalog = await client.session_command_catalog(
                    control, instance, f"/{name} {args}"
                )
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
                if entry.name == "rename" and not args:
                    self._shell.screen.composer.set_text("/rename ")
                    self._shell._set_draft("/rename ")
                    self._shell.notice = "Enter the new Session name"
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
        lines = [
            f"/{name}  {DEFAULT_LOCAL_COMMANDS_PROFILE.local_commands_by_name[name].description}"
            for name in MODEL_COMMANDS
            if self.models_available
        ]
        for entry in catalog.commands:
            if entry.name in MODEL_COMMANDS:
                continue
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
