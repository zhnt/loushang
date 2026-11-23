"""Agent access to files explicitly submitted to the current Session."""

from __future__ import annotations

import json
from collections.abc import Callable

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart, ToolCall
from loushang.appserver.protocol import AppServiceError
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import DirectExecution, DirectToolContext

from .resources import HostedResourceAccess

SESSION_FILES = "session_files"


def session_files_tool(get_access: Callable[[], HostedResourceAccess]) -> ToolDefinition:
    async def handle(call: ToolCall, context: DirectToolContext) -> AgentToolResult[None]:
        arguments = call.arguments
        action = arguments.get("action")
        access = get_access()
        try:
            if action == "list":
                text = json.dumps([
                    {"id": item.id, "name": item.name, "sizeBytes": item.size_bytes}
                    for item in access.associated(kind="file")
                ], ensure_ascii=False)
            elif action == "read" and isinstance(arguments.get("id"), str):
                text = json.dumps(
                    access.read_text(arguments["id"], offset=arguments.get("offset", 0)),
                    ensure_ascii=False,
                )
            else:
                text = "Select list or read. Reading requires a Session file ID."
        except (AppServiceError, OSError, ValueError):
            text = "The selected Session file is unavailable."
        return AgentToolResult([TextPart(type="text", text=text)], None)

    return ToolDefinition(
        name=SESSION_FILES,
        label="Session files",
        description="List files attached by the user to this session and read UTF-8 text or source code by file ID.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "read"]},
                "id": {"type": "string", "description": "File ID returned by list."},
                "offset": {"type": "integer", "minimum": 0, "description": "Use nextOffset to read the next page."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        execution=DirectExecution(handle),
    )
