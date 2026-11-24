"""Project and invoke Coding Session commands through the existing Execution guard."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from loushang.ai.model import normalize_model_selection
from loushang.ai.model.selection import is_usable_model_selection
from loushang.appserver.execution.session_commands import (
    SessionCommandCatalogV1,
    SessionCommandChoiceV1,
    SessionCommandInvocationV1,
    SessionCommandResultV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.appservice.execution_guard import ExecutionControlV1
from loushang.coding.lsp.commands import LSP_SESSION_COMMAND_NAME, lsp_command_mutates
from loushang.harness.commands import (
    CommandCatalog,
    CommandDescriptor,
    complete_slash_commands,
    normalize_command_name,
)
from loushang.harness.session import CommandExecutionResult
from loushang.harness.session.commands.catalog import STANDARD_SESSION_COMMANDS
from loushang.harness.transcript.maintenance import CompactionAborted

if TYPE_CHECKING:
    from loushang.coding.session.agent_session import AgentSession

# The owning command pack declares which operations can use this execution
# path. Lifecycle and local commands keep their existing entry points.
_HOSTED = {
    definition.name: definition.hosted
    for definition in STANDARD_SESSION_COMMANDS
    if definition.hosted
}


def _text(value: str, size: int) -> str:
    return (
        value.replace("\x00", "")
        .encode("utf-8")[:size]
        .decode("utf-8", errors="ignore")
    )


class CodingHostedSessionCommands:
    def __init__(self, session: AgentSession) -> None:
        self._session = session

    def _catalog(self) -> CommandCatalog:
        return CommandCatalog(
            item
            for item in self._session.list_commands()
            if isinstance(item, CommandDescriptor)
        )

    @staticmethod
    def _mode(name: str, args: str = "") -> str | None:
        if name == LSP_SESSION_COMMAND_NAME:
            return "session" if lsp_command_mutates(args) else "read"
        if name == "tools" and not args.strip():
            return "read"
        return _HOSTED.get(name)

    def _unavailable(self, name: str, source: str) -> str | None:
        mode = self._mode(name) if source == "builtin" else None
        if mode is None:
            return "requires_a_different_command_route"
        if mode == "model" and not is_usable_model_selection(
            normalize_model_selection(self._session.agent.model)
        ):
            return "model_required"
        if not self._session.execution_available:
            return "session_unavailable"
        return None

    async def catalog(self, prefix: str) -> SessionCommandCatalogV1:
        catalog = self._catalog()
        command, separator, args = prefix.lstrip().partition(" ")
        match = catalog.lookup(command)
        commands = []
        for item in catalog.commands():
            name = item.effective_invocation_name
            try:
                commands.append(
                    SessionCommandChoiceV1(
                        name,
                        _text(item.description or "", 512),
                        _text(item.source, 64),
                        tuple(
                            alias
                            for alias in map(normalize_command_name, item.aliases)
                            if catalog.lookup(alias) is item
                            and len(alias.encode("utf-8")) <= 128
                        )[:8],
                        _text(item.argument_hint or "", 256),
                        self._unavailable(name, item.source),
                        read_only=item.source == "builtin"
                        and self._mode(name, args if item is match else "") == "read",
                    )
                )
            except ValueError:
                continue
        if (
            separator
            and match is not None
            and self._unavailable(match.effective_invocation_name, match.source) is None
        ):
            raw = await self._session.get_command_argument_completions(
                match.effective_invocation_name, args
            )
            completions = [
                value
                for item in raw or []
                if isinstance(item, Mapping)
                and isinstance(value := item.get("value"), str)
            ]
        elif separator:
            completions = []
        else:
            completions = [
                str(item["value"])
                for item in complete_slash_commands(command, catalog.commands())
                if (winner := catalog.lookup(str(item["value"]))) is not None
                and self._unavailable(winner.effective_invocation_name, winner.source)
                is None
            ]
        if len(commands) > 128:
            commands.sort(key=lambda entry: entry.unavailable_reason is not None)
        return SessionCommandCatalogV1(
            tuple(commands[:128]),
            tuple(
                dict.fromkeys(
                    value for value in completions if _text(value, 256) == value
                )
            )[:256],
            len(commands) > 128 or len(completions) > 256,
        )

    def require_ready(self, invocation: SessionCommandInvocationV1) -> str:
        descriptor = self._catalog().lookup(invocation.name)
        if descriptor is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        canonical = descriptor.effective_invocation_name
        if self._unavailable(canonical, descriptor.source) is not None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        controller = self._session._composition.command_controller
        if controller.extract_extension_command_invocation(f"/{canonical}") is not None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return canonical

    async def read(
        self, invocation: SessionCommandInvocationV1
    ) -> SessionCommandResultV1:
        name = self.require_ready(invocation)
        if self._mode(name, invocation.args) != "read":
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self._session.runtime.execution_admission.require_current()
        return _project_result(await self._dispatch(name, invocation.args))

    async def _dispatch(self, name: str, args: str) -> dict[str, object]:
        # The caller resolved an admitted builtin. Invoke that bound owner,
        # even if an extension is published while other work is settling.
        invocation = (
            self._session.execute_lsp_command(args)
            if name == LSP_SESSION_COMMAND_NAME
            else self._session._composition.command_controller.execute_builtin_command_async(
                name, args
            )
        )
        outcome: CommandExecutionResult | None
        if name == "rename" or (
            name == LSP_SESSION_COMMAND_NAME and lsp_command_mutates(args)
        ):
            # Join an entered metadata write or process stop before releasing
            # the guard. Its actual outcome survives an interrupt request.
            task = asyncio.create_task(invocation)
            try:
                outcome = await asyncio.shield(task)
            except asyncio.CancelledError:
                outcome = await task
        else:
            outcome = await invocation
        result = outcome.result if outcome is not None else None
        if not isinstance(result, dict) or result.get("source") != "builtin":
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return result

    async def execute(
        self, invocation: SessionCommandInvocationV1
    ) -> ExecutionOutcomeV1:
        session = self._session
        name = self.require_ready(invocation)
        admission = session.runtime.execution_admission
        admission.require_current()
        admission.require_unbound_run()
        ticket = admission.begin_input()
        try:
            if self._mode(name, invocation.args) == "model":
                await session.prepare_execution()
            ticket.check()
            admission.require_current()
            if self.require_ready(invocation) != name:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            # Dispatch through the same Session runtime and bound pack as the
            # Embedded TUI. Catalog changes are checked again after preparation.
            result = await self._dispatch(name, invocation.args)
            if name == "rename" and result.get("status") == "ok":
                result["persisted"] = session.session_manager.is_persisted()
                if not result["persisted"]:
                    result["message"] = (
                        "Session renamed. This Session has no durable transcript yet."
                    )
            data = _project_result(result)
            if result.get("status") != "ok":
                error = (
                    "command_invalid_arguments"
                    if result.get("status") == "error"
                    else "command_unavailable"
                )
                return ExecutionOutcomeV1(
                    ExecutionStatusV1.FAILED, error, command_result=data
                )
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED, command_result=data)
        except CompactionAborted:
            return ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
        finally:
            ticket.close()

    def create_work(
        self,
        invocation: SessionCommandInvocationV1,
        wait_for_title: Callable[[], Awaitable[None]],
    ) -> _CommandWork:
        return _CommandWork(self, invocation, wait_for_title)


def _project_result(result: dict[str, object]) -> SessionCommandResultV1:
    data = dict(result)
    if isinstance(session := data.get("session"), Mapping):
        data.pop("message", None)
        public_session = {
            key: session[key]
            for key in (
                "session_id",
                "session_name",
                "entry_count",
                "message_count",
                "custom_message_count",
                "active_tool_count",
                "is_retrying",
                "is_compacting",
                "context",
            )
            if key in session
        }
        if isinstance(status := session.get("compaction"), Mapping):
            public_session["compaction"] = {
                key: value for key, value in status.items() if key != "last_error"
            }
        data["session"] = public_session
    if isinstance(compaction := data.get("result"), Mapping):
        public = {
            key: value
            for key, value in compaction.items()
            if key in {"first_kept_entry_id", "tokens_before", "summary"}
        }
        if isinstance(summary := compaction.get("summary"), str):
            public["summary"] = _text(summary, 4096)
        data["result"] = public
    if isinstance(tools := data.get("available_tools"), list):
        descriptions_left = 4096
        public_tools: list[dict[str, object]] = []
        for entry in tools:
            if not isinstance(entry, dict):
                continue
            public_tool = {
                key: value
                for key, value in entry.items()
                if key in {"name", "active", "allowed"}
            }
            if isinstance(description := entry.get("description"), str):
                description = _text(description, min(256, descriptions_left))
                if description:
                    public_tool["description"] = description
                    descriptions_left -= len(
                        json.dumps(description, ensure_ascii=False).encode("utf-8")
                    )
            descriptions_left = max(0, descriptions_left)
            public_tools.append(public_tool)
        data["available_tools"] = public_tools
    if data.get("command") == "extensions":
        data.pop("display", None)
        if isinstance(extensions := data.get("extensions"), list):
            data["extensions"] = [
                _public_extension(entry)
                for entry in extensions
                if isinstance(entry, Mapping)
            ]
        if isinstance(extension := data.get("extension"), Mapping):
            data["extension"] = _public_extension(extension)
    if data.get("command") == LSP_SESSION_COMMAND_NAME:
        data.pop("display", None)
        if isinstance(servers := data.get("servers"), list):
            data["servers"] = [
                {key: value for key, value in entry.items() if key != "last_error"}
                for entry in servers
                if isinstance(entry, Mapping)
            ]
        if data.get("enabled") is False:
            data.setdefault("message", "Coding LSP is disabled for this session.")
        elif data.get("servers") == []:
            data.setdefault(
                "message", "No language server has been started in this session."
            )
    try:
        return SessionCommandResultV1.from_data(data)
    except (ValueError, TypeError):
        # The operation has already happened. Report that fact even if its
        # complete payload could not fit in the bounded result ledger.
        return SessionCommandResultV1.from_data(
            {
                "command": data.get("command"),
                "status": data.get("status"),
                "truncated": True,
            }
        )


def _public_extension(entry: Mapping[str, object]) -> dict[str, object]:
    public = {
        key: entry[key]
        for key in (
            "id",
            "name",
            "runtimeName",
            "version",
            "enabled",
            "permissionLevel",
        )
        if key in entry
    }
    diagnostics = entry.get("diagnostics")
    if isinstance(diagnostics, list):
        public["diagnostics"] = [
            {"code": item["code"]}
            for item in diagnostics
            if isinstance(item, Mapping) and isinstance(item.get("code"), str)
        ]
    return public


class _CommandWork:
    def __init__(
        self,
        commands: CodingHostedSessionCommands,
        invocation: SessionCommandInvocationV1,
        wait_for_title: Callable[[], Awaitable[None]],
    ) -> None:
        self._commands, self._invocation = commands, invocation
        self._wait_for_title = wait_for_title
        self._interrupted = False

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        try:
            await self._wait_for_title()
            return await self._commands.execute(self._invocation)
        except asyncio.CancelledError:
            self._interrupted = True
            raise

    async def settle(self) -> None:
        await self._commands._session.settle_execution(interrupted=self._interrupted)
