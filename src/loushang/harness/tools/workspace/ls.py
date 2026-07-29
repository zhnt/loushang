from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from loushang.agent.types import AgentToolResult, TextPart
from loushang.harness.approval import ApprovalResolver
from loushang.harness.workspace.operations import LsOperations, resolve_operation

from .authoring import tool
from .authorization import AuthorizedWorkspaceAction, execute_workspace_tool_action
from .builtin_renderers import render_find_or_ls_result, render_ls_call
from .context import ToolContext, context_approval_resolver
from .normalize import tool_to_definition
from .operations import (
    normalize_ls_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .policy import ToolPolicyEvaluator
from .runtime import coerce_int_parameter, pi_truncation_details, prepare_tool_arguments
from .truncate import truncate_head, truncation_details
from .types import PiTruncationDetails, ToolDefinition

DEFAULT_LS_LIMIT = 500


class LsToolInput(TypedDict, total=False):
    path: str
    file_path: NotRequired[str]
    limit: int


class LsToolDetails(TypedDict, total=False):
    path: str
    total_lines: int
    output_lines: int
    total_bytes: int
    output_bytes: int
    max_lines: int
    max_bytes: int
    truncated: bool
    truncated_by: str | None
    first_line_exceeds_limit: bool
    last_line_partial: bool
    entry_limit_reached: bool
    entry_limit: int | None
    truncation: PiTruncationDetails | None


@dataclass(frozen=True)
class LsToolOptions:
    operations: LsOperations | None = None
    policy_engine: ToolPolicyEvaluator | None = None
    approval_resolver: ApprovalResolver | None = None


def create_ls_tool_definition(
    *,
    operations: LsOperations | None = None,
    policy_engine: ToolPolicyEvaluator | None = None,
    approval_resolver: ApprovalResolver | None = None,
    options: LsToolOptions | None = None,
) -> ToolDefinition:
    ops = normalize_ls_operations(
        operations or (options.operations if options is not None else None)
    )
    resolved_policy_engine = policy_engine or (
        options.policy_engine if options is not None else None
    )
    resolved_approval_resolver = approval_resolver or (
        options.approval_resolver if options is not None else None
    )

    @tool(
        name="ls",
        label="Ls",
        description="List directory entries in the workspace.",
        prompt_snippet="- ls: List directory entries in the workspace.",
    )
    async def ls(
        path: str | None = None,
        limit: int | None = None,
        *,
        ctx: ToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        raise_if_operation_aborted(ctx.signal)
        resolved = resolve_tool_path(path or ".", cwd=ctx.cwd)

        async def execute(
            _action: AuthorizedWorkspaceAction,
        ) -> AgentToolResult[dict[str, Any]]:
            directory = await _require_directory(resolved, operations=ops)
            effective_limit = _effective_limit(limit)
            lines, entry_limit_reached = await _list_entries(
                directory, limit=effective_limit, operations=ops
            )
            raise_if_operation_aborted(ctx.signal)
            raw_content = "\n".join(lines)
            truncation = truncate_head(raw_content)
            content = truncation.content if lines else "(empty directory)"
            if lines:
                content = _append_ls_notices(
                    content,
                    entry_limit=effective_limit,
                    entry_limit_reached=entry_limit_reached,
                    byte_truncated=truncation.truncated_by == "bytes",
                )
            return AgentToolResult(
                content=[TextPart(type="text", text=content)],
                details={
                    "path": str(directory),
                    **truncation_details(truncation),
                    "truncated": entry_limit_reached or truncation.truncated,
                    "entry_limit_reached": entry_limit_reached,
                    "entry_limit": (
                        effective_limit if entry_limit_reached else None
                    ),
                    "truncation": (
                        pi_truncation_details(truncation)
                        if truncation.truncated
                        else None
                    ),
                },
            )

        return await execute_workspace_tool_action(
            resolved_policy_engine,
            tool_name="ls",
            arguments={"path": str(resolved)},
            executor=execute,
            cwd=ctx.cwd,
            approval_resolver=context_approval_resolver(
                ctx,
                resolved_approval_resolver,
            ),
            tool_call_id=ctx.tool_call_id,
            audit_sink=ctx.event_sink,
            execution_profile_ceiling=getattr(
                ctx.exec_service,
                "execution_profile",
                None,
            ),
        )

    return replace(
        tool_to_definition(ls),
        prepare_arguments=lambda value: prepare_tool_arguments(
            value, aliases=(("file_path", "path"),)
        ),
        render_call=render_ls_call,
        render_result=render_find_or_ls_result,
    )


async def _require_directory(path: Path, *, operations: LsOperations) -> Path:
    resolved = path
    if not await resolve_operation(operations.exists(resolved)):
        raise FileNotFoundError(str(resolved))
    if not await resolve_operation(operations.is_dir(resolved)):
        raise NotADirectoryError(str(resolved))
    return resolved


def _effective_limit(limit: int | None) -> int:
    return (
        coerce_int_parameter(limit, field_name="limit", minimum=1) or DEFAULT_LS_LIMIT
    )


async def _list_entries(
    path: Path, *, limit: int, operations: LsOperations
) -> tuple[list[str], bool]:
    entries = sorted(
        await resolve_operation(operations.iterdir(path)),
        key=lambda entry: (entry.name.casefold(), entry.name),
    )
    truncated = False
    if len(entries) > limit:
        entries = entries[:limit]
        truncated = True

    lines: list[str] = []
    for entry in entries:
        suffix = "/" if await resolve_operation(operations.is_dir(entry)) else ""
        lines.append(f"{entry.name}{suffix}")
    return lines, truncated


def _append_ls_notices(
    content: str,
    *,
    entry_limit: int,
    entry_limit_reached: bool,
    byte_truncated: bool,
) -> str:
    notices: list[str] = []
    if entry_limit_reached:
        notices.append(
            f"{entry_limit} entries limit reached. Use limit={entry_limit * 2} for more"
        )
    if byte_truncated:
        notices.append("50.0KB limit reached")
    if not notices:
        return content
    return f"{content}\n\n[{'. '.join(notices)}]"
