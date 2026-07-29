import json
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
from loushang.harness.workspace.operations import EditOperations, resolve_operation

from .builtin_renderers import render_edit_call, render_edit_result
from .edit_diff import (
    EditEntry,
    apply_text_edits,
    build_unified_diff,
    first_changed_line,
)
from .operations import (
    normalize_edit_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .runtime import prepare_tool_arguments
from .types import ToolDefinition


class EditToolInput(TypedDict):
    path: str
    file_path: NotRequired[str]
    edits: list[EditEntry]
    oldText: NotRequired[str]
    newText: NotRequired[str]


class EditToolDetails(TypedDict, total=False):
    path: str
    applied_edit_count: int
    diff: str
    first_changed_line: int | None


@dataclass(frozen=True)
class EditToolOptions:
    operations: EditOperations | None = None


def create_edit_tool_definition(
    *,
    operations: EditOperations | None = None,
    options: EditToolOptions | None = None,
) -> ToolDefinition:
    ops = normalize_edit_operations(
        operations or (options.operations if options is not None else None)
    )

    @tool(
        name="edit",
        label="Edit",
        description="Apply exact text replacements to a file in the workspace.",
        prompt_snippet="- edit: Apply exact text replacements to a file in the workspace.",
    )
    async def edit(
        path: str,
        edits: list[EditEntry],
        *,
        ctx: ToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        resolved = resolve_tool_path(path, cwd=ctx.cwd)
        validated_edits = _validate_edits(edits)

        async def execute_edit(_action: object) -> tuple[str, str]:
            raise_if_operation_aborted(ctx.signal)
            async with with_file_mutation_queue(str(resolved)):
                original = await _read_existing_text(resolved, operations=ops)
                raise_if_operation_aborted(ctx.signal)
                updated = apply_text_edits(
                    original,
                    validated_edits,
                    path=str(resolved),
                )
                await _write_exact_text(resolved, updated, operations=ops)
                raise_if_operation_aborted(ctx.signal)
            return original, updated

        original, updated = await execute_edit(None)
        diff = build_unified_diff(str(resolved), original, updated)
        return AgentToolResult(
            content=[
                TextPart(
                    type="text", text=f"Applied {len(validated_edits)} edits to {path}"
                )
            ],
            details={
                "path": str(resolved),
                "applied_edit_count": len(validated_edits),
                "diff": diff,
                "first_changed_line": first_changed_line(original, updated),
            },
        )

    return replace(
        authorized_tool(
            edit,
            action=FilesystemActionAdapter(
                "write",
                authorization_fields=("edits",),
            ),
        ),
        prepare_arguments=_prepare_edit_arguments,
        render_call=render_edit_call,
        render_result=render_edit_result,
    )


async def _read_existing_text(path: Path, *, operations: EditOperations) -> str:
    if not await resolve_operation(operations.exists(path)):
        raise FileNotFoundError(str(path))
    if not await resolve_operation(operations.is_file(path)):
        raise IsADirectoryError(str(path))
    return await resolve_operation(operations.read_text(path, newline=""))


async def _write_exact_text(
    path: Path, content: str, *, operations: EditOperations
) -> None:
    await resolve_operation(operations.write_text(path, content, newline=""))


def _prepare_edit_arguments(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return value  # type: ignore[return-value]

    prepared = prepare_tool_arguments(value, aliases=(("file_path", "path"),))
    edits = prepared.get("edits")
    if isinstance(edits, str):
        try:
            parsed = json.loads(edits)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            prepared["edits"] = parsed

    old_text = prepared.get("oldText")
    new_text = prepared.get("newText")
    if isinstance(old_text, str) and isinstance(new_text, str):
        normalized_edits = prepared.get("edits")
        prepared["edits"] = [
            *(normalized_edits if isinstance(normalized_edits, list) else []),
            {"oldText": old_text, "newText": new_text},
        ]
        prepared.pop("oldText", None)
        prepared.pop("newText", None)

    return prepared


def _validate_edits(edits: object) -> list[EditEntry]:
    if isinstance(edits, str):
        try:
            parsed = json.loads(edits)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            edits = parsed

    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must contain at least one replacement")
    normalized: list[EditEntry] = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise TypeError("each edit must be a mapping")
        old_text = edit.get("oldText")
        new_text = edit.get("newText")
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("oldText must be a non-empty string")
        if not isinstance(new_text, str):
            raise TypeError("newText must be a string")
        normalized.append({"oldText": old_text, "newText": new_text})
    return normalized
