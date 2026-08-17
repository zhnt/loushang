"""Coding transcript loader bound to the shared Agent history projector."""

from __future__ import annotations

from pathlib import Path

from loushang.coding.session_manager import SessionManager
from loushang.harness.presentation import ToolDefinitionResolver
from loushang.harnesstui.conversation.agent_binding import (
    load_agent_session_history_records,
)
from loushang.tui.transcript import DisplayRecord


async def load_persisted_session_history_records(
    session_file: str | Path,
    *,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
) -> tuple[DisplayRecord, ...]:
    return await load_agent_session_history_records(
        session_file,
        load_session=SessionManager.load,
        tool_definition_resolver=tool_definition_resolver,
    )


__all__ = ["load_persisted_session_history_records"]
