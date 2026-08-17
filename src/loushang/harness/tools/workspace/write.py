from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from loushang.agent.types import AgentToolResult, TextPart
from loushang.harness.tools.authoring import (
    FilesystemActionAdapter,
    ToolContext,
    authorized_tool,
    tool,
)
from loushang.harness.workspace.mutation_queue import with_file_mutation_queue
from loushang.harness.workspace.operations import WriteOperations, resolve_operation

from .builtin_renderers import render_write_call, render_write_result
from .operations import (
    normalize_write_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .runtime import prepare_tool_arguments
from .types import ToolDefinition


class WriteToolInput(TypedDict):
    path: str
    file_path: NotRequired[str]
    content: str


class WriteToolDetails(TypedDict, total=False):
    path: str
    bytes_written: int
    operation: str


@dataclass(frozen=True)
class WriteToolOptions:
    operations: WriteOperations | None = None


def create_write_tool_definition(
    *,
    operations: WriteOperations | None = None,
    options: WriteToolOptions | None = None,
) -> ToolDefinition:
    ops = normalize_write_operations(
        operations or (options.operations if options is not None else None)
    )

    @tool(
        name="write",
        label="Write",
        description="Write a text file in the workspace.",
        prompt_snippet="- write: Write a text file in the workspace.",
    )
    async def write(
        path: str,
        content: str,
        *,
        ctx: ToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        resolved = resolve_tool_path(path, cwd=ctx.cwd)
        _validate_content(content)

        async def execute_write(_action: object) -> tuple[str, int]:
            raise_if_operation_aborted(ctx.signal)
            async with with_file_mutation_queue(str(resolved)):
                operation = await _write_text_payload(
                    resolved,
                    content,
                    operations=ops,
                )
                raise_if_operation_aborted(ctx.signal)
                bytes_written = len(content.encode("utf-8"))
            return operation, bytes_written

        operation, bytes_written = await execute_write(None)
        return AgentToolResult(
            content=[
                TextPart(
                    type="text",
                    text=f"Successfully wrote {bytes_written} bytes to {path}",
                )
            ],
            details={
                "path": str(resolved),
                "bytes_written": bytes_written,
                "operation": operation,
            },
        )

    return replace(
        authorized_tool(
            write,
            action=FilesystemActionAdapter(
                "write",
                authorization_fields=("content",),
            ),
        ),
        prepare_arguments=lambda value: prepare_tool_arguments(
            value, aliases=(("file_path", "path"),)
        ),
        render_call=render_write_call,
        render_result=render_write_result,
    )


async def _write_text_payload(
    path: Path, content: str, *, operations: WriteOperations
) -> str:
    existed = await resolve_operation(operations.exists(path))
    if existed and not await resolve_operation(operations.is_file(path)):
        raise IsADirectoryError(str(path))

    await resolve_operation(operations.mkdir(path.parent, parents=True, exist_ok=True))
    await resolve_operation(operations.write_text(path, content))
    return "overwrite" if existed else "create"


def _validate_content(content: str) -> None:
    if not isinstance(content, str):
        raise TypeError("content must be a string")
