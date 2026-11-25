"""Bind Coding LSP to the standard hosted Session command adapter."""

from __future__ import annotations

from collections.abc import Coroutine, Mapping
from typing import Any

from loushang.apphost.integrations._session_commands import HostedSessionCommands
from loushang.coding.lsp.commands import LSP_SESSION_COMMAND_NAME, lsp_command_mutates
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.session import CommandExecutionResult


class CodingHostedSessionCommands(HostedSessionCommands[AgentSession]):
    def _mode(self, name: str, args: str = "") -> str | None:
        if name == LSP_SESSION_COMMAND_NAME:
            return "session" if lsp_command_mutates(args) else "read"
        return super()._mode(name, args)

    def _invoke(
        self, name: str, args: str
    ) -> tuple[Coroutine[Any, Any, CommandExecutionResult | None], bool]:
        if name == LSP_SESSION_COMMAND_NAME:
            return self._session.execute_lsp_command(args), lsp_command_mutates(args)
        return super()._invoke(name, args)

    def _project_product_fields(self, data: dict[str, object]) -> None:
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
