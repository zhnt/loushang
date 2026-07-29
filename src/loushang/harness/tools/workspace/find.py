import fnmatch
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from loushang.agent.types import AgentToolResult, TextPart
from loushang.harness.approval import ApprovalResolver
from loushang.harness.workspace.operations import FindOperations, resolve_operation

from .authoring import tool
from .authorization import AuthorizedWorkspaceAction, execute_workspace_tool_action
from .builtin_renderers import render_find_call, render_find_or_ls_result
from .context import ToolContext, context_approval_resolver
from .external_tools import (
    ExternalToolDownloader,
    ExternalToolPolicy,
    ExternalToolResolver,
    external_tool_required_for_policy,
    external_tool_resolver_for_policy,
    external_tools_enabled_for_policy,
    get_managed_external_tool_install,
    normalize_external_tool_policy,
    resolve_external_tool,
)
from .ignore import load_ignore_matcher
from .normalize import tool_to_definition
from .operations import (
    normalize_find_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .policy import ToolPolicyEvaluator
from .process import run_external_process
from .runtime import coerce_int_parameter, pi_truncation_details, prepare_tool_arguments
from .truncate import truncate_head, truncation_details
from .types import PiTruncationDetails, ToolDefinition

DEFAULT_FIND_LIMIT = 1000


class FindToolInput(TypedDict):
    pattern: str
    path: NotRequired[str]
    file_path: NotRequired[str]
    limit: NotRequired[int]


class FindToolMatch(TypedDict):
    path: str


class FindToolDetails(TypedDict, total=False):
    path: str
    matches: list[FindToolMatch]
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
    result_limit_reached: bool
    result_limit: int | None
    truncation: PiTruncationDetails | None


@dataclass(frozen=True)
class FindToolOptions:
    operations: FindOperations | None = None
    external_tool_resolver: ExternalToolResolver | None = None
    external_tool_downloader: ExternalToolDownloader | None = None
    external_tool_policy: ExternalToolPolicy | None = None
    allow_external_tool_downloads: bool = False
    require_external_tool: bool = False
    policy_engine: ToolPolicyEvaluator | None = None
    approval_resolver: ApprovalResolver | None = None


def create_find_tool_definition(
    *,
    operations: FindOperations | None = None,
    policy_engine: ToolPolicyEvaluator | None = None,
    approval_resolver: ApprovalResolver | None = None,
    options: FindToolOptions | None = None,
) -> ToolDefinition:
    selected_operations = operations or (
        options.operations if options is not None else None
    )
    external_tool_policy = normalize_external_tool_policy(
        options.external_tool_policy if options is not None else None,
        allow_download=bool(options.allow_external_tool_downloads)
        if options is not None
        else False,
    )
    external_tool_resolver = external_tool_resolver_for_policy(
        resolver=options.external_tool_resolver if options is not None else None,
        downloader=options.external_tool_downloader if options is not None else None,
        policy=external_tool_policy,
        allow_download=bool(options.allow_external_tool_downloads)
        if options is not None
        else False,
    )
    require_external_tool = external_tool_required_for_policy(
        external_tool_policy,
        require=bool(options.require_external_tool) if options is not None else False,
    )
    ops = normalize_find_operations(selected_operations)
    use_external_tools = (
        selected_operations is None
        and external_tools_enabled_for_policy(external_tool_policy)
    )
    resolved_policy_engine = policy_engine or (
        options.policy_engine if options is not None else None
    )
    resolved_approval_resolver = approval_resolver or (
        options.approval_resolver if options is not None else None
    )

    @tool(
        name="find",
        label="Find",
        description="Find file paths in the workspace.",
        prompt_snippet="- find: Find file paths by glob pattern in the workspace.",
        prompt_guidelines=(
            "Use find to locate files by path pattern instead of shelling out to find/fd.",
            "Patterns with glob metacharacters are matched as globs; plain patterns match path substrings.",
        ),
    )
    async def find(
        pattern: str,
        path: str | None = None,
        limit: int | None = None,
        *,
        ctx: ToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        raise_if_operation_aborted(ctx.signal)
        resolved_root = resolve_tool_path(path or ".", cwd=ctx.cwd)

        async def execute(
            _action: AuthorizedWorkspaceAction,
        ) -> AgentToolResult[dict[str, Any]]:
            root = await _require_directory(resolved_root, operations=ops)
            effective_limit = _effective_limit(limit)
            matches, result_limit_reached = await _walk_matching_paths(
                root,
                pattern=pattern,
                limit=effective_limit,
                operations=ops,
                use_external_tools=use_external_tools,
                external_tool_resolver=external_tool_resolver,
                require_external_tool=require_external_tool,
                signal=ctx.signal,
            )
            raise_if_operation_aborted(ctx.signal)
            raw_output = "\n".join(match["path"] for match in matches)
            truncation = truncate_head(raw_output)
            visible_matches = _visible_find_matches(matches, truncation.content)
            rendered = (
                truncation.content
                if matches
                else "No files found matching pattern"
            )
            if matches:
                rendered = _append_find_notices(
                    rendered,
                    result_limit=effective_limit,
                    result_limit_reached=result_limit_reached,
                    byte_truncated=truncation.truncated_by == "bytes",
                )
            return AgentToolResult(
                content=[TextPart(type="text", text=rendered)],
                details={
                    "path": str(root),
                    "matches": visible_matches,
                    **truncation_details(truncation),
                    "truncated": result_limit_reached or truncation.truncated,
                    "result_limit_reached": result_limit_reached,
                    "result_limit": (
                        effective_limit if result_limit_reached else None
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
            tool_name="find",
            arguments={"path": str(resolved_root), "pattern": pattern},
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
        tool_to_definition(find),
        prepare_arguments=lambda value: prepare_tool_arguments(
            value, aliases=(("file_path", "path"),)
        ),
        render_call=render_find_call,
        render_result=render_find_or_ls_result,
    )


async def _require_directory(path: Path, *, operations: FindOperations) -> Path:
    resolved = path
    if not await resolve_operation(operations.exists(resolved)):
        raise FileNotFoundError(str(resolved))
    if not await resolve_operation(operations.is_dir(resolved)):
        raise NotADirectoryError(str(resolved))
    return resolved


async def _walk_matching_paths(
    root: Path,
    *,
    pattern: str,
    limit: int,
    operations: FindOperations,
    use_external_tools: bool,
    external_tool_resolver: ExternalToolResolver | None,
    require_external_tool: bool,
    signal: object | None,
) -> tuple[list[dict[str, str]], bool]:
    if not isinstance(pattern, str) or not pattern:
        raise TypeError("pattern must be a non-empty string")

    external_matches = (
        await _walk_matching_paths_with_fd(
            root,
            pattern=pattern,
            limit=limit,
            external_tool_resolver=external_tool_resolver,
            require_external_tool=require_external_tool,
            signal=signal,
        )
        if use_external_tools
        else None
    )
    used_external = external_matches is not None
    used_custom_glob = False
    if external_matches is not None:
        all_matches = external_matches
    elif callable(getattr(operations, "glob_paths", None)):
        used_custom_glob = True
        all_matches = await _walk_matching_paths_with_glob_operations(
            root,
            pattern=pattern,
            limit=limit,
            operations=operations,
        )
    else:
        all_matches = await _walk_matching_paths_with_operations(
            root,
            pattern=pattern,
            operations=operations,
            respect_ignore=use_external_tools,
        )

    if len(all_matches) < limit:
        return all_matches, False
    if len(all_matches) == limit:
        return all_matches, used_external or used_custom_glob
    return all_matches[:limit], True


def _effective_limit(limit: int | None) -> int:
    return (
        coerce_int_parameter(limit, field_name="limit", minimum=1) or DEFAULT_FIND_LIMIT
    )


async def _walk_matching_paths_with_fd(
    root: Path,
    *,
    pattern: str,
    limit: int,
    external_tool_resolver: ExternalToolResolver | None = None,
    require_external_tool: bool = False,
    signal: object | None = None,
) -> list[dict[str, str]] | None:
    fd_path = await _resolve_fd_path(external_tool_resolver)
    if fd_path is None:
        if require_external_tool:
            raise RuntimeError(
                "fd is not available and could not be downloaded (fd external tool is required but unavailable)"
            )
        return None
    effective_pattern = (
        pattern if any(char in pattern for char in "*?[]") else f"*{pattern}*"
    )
    command = [
        fd_path,
        "--glob",
        "--color=never",
        "--hidden",
        "--no-require-git",
        "--max-results",
        str(limit),
        "--exclude",
        ".git",
        "--exclude",
        "node_modules",
    ]
    if "/" in effective_pattern:
        command.append("--full-path")
        if (
            not effective_pattern.startswith("/")
            and not effective_pattern.startswith("**/")
            and effective_pattern != "**"
        ):
            effective_pattern = f"**/{effective_pattern}"
    command.extend([effective_pattern, "."])
    completed = await run_external_process(
        command,
        cwd=root,
        signal=signal,
    )
    if completed.returncode not in {0, 1} and not completed.stdout:
        raise RuntimeError(
            completed.stderr.strip() or f"fd exited with code {completed.returncode}"
        )
    matches: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        normalized = _normalize_fd_output_path(line, root)
        if normalized:
            matches.append({"path": normalized})
    return matches


async def _resolve_fd_path(
    external_tool_resolver: ExternalToolResolver | None,
) -> str | None:
    if external_tool_resolver is not None:
        return await resolve_external_tool("fd", resolver=external_tool_resolver)
    system_path = shutil.which("fd") or shutil.which("fdfind")
    if system_path is not None:
        return system_path
    managed = get_managed_external_tool_install("fd")
    if managed is not None:
        return managed.binary_path
    return None


def _normalize_fd_output_path(line: str, root: Path) -> str:
    cleaned = line.rstrip("\r").strip()
    if not cleaned:
        return ""
    had_trailing_slash = cleaned.endswith(("/", "\\"))
    relative = cleaned.removeprefix("./")
    candidate = Path(relative)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            relative = os.path.relpath(candidate, root).replace(os.sep, "/")
    else:
        relative = relative.replace("\\", "/")
    if relative == ".":
        relative = ""
    if had_trailing_slash and relative and not relative.endswith("/"):
        relative += "/"
    return relative


async def _walk_matching_paths_with_operations(
    root: Path,
    *,
    pattern: str,
    operations: FindOperations,
    respect_ignore: bool,
) -> list[dict[str, str]]:
    all_matches: list[dict[str, str]] = []
    ignore_matcher = load_ignore_matcher(root) if respect_ignore else None
    candidates = sorted(
        await resolve_operation(operations.walk_files(root)), key=lambda item: str(item)
    )
    for candidate in candidates:
        if ignore_matcher is not None and ignore_matcher.is_ignored(candidate):
            continue
        relative = _relative_path(candidate, root)
        if not _path_matches_pattern(relative, pattern):
            continue
        all_matches.append({"path": relative})
    return all_matches


async def _walk_matching_paths_with_glob_operations(
    root: Path,
    *,
    pattern: str,
    limit: int,
    operations: FindOperations,
) -> list[dict[str, str]]:
    glob_paths = getattr(operations, "glob_paths")
    candidates = await resolve_operation(glob_paths(root, pattern=pattern, limit=limit))
    return [{"path": _relative_path(candidate, root)} for candidate in candidates]


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _path_matches_pattern(relative_path: str, pattern: str) -> bool:
    if any(char in pattern for char in "*?[]"):
        zero_depth_pattern = pattern[3:] if pattern.startswith("**/") else None
        return (
            fnmatch.fnmatch(relative_path, pattern)
            or (
                zero_depth_pattern is not None
                and fnmatch.fnmatch(relative_path, zero_depth_pattern)
            )
            or fnmatch.fnmatch(relative_path.rsplit("/", 1)[-1], pattern)
        )
    return pattern in relative_path


def _visible_find_matches(
    matches: list[dict[str, str]], content: str
) -> list[dict[str, str]]:
    visible_matches: list[dict[str, str]] = []
    cursor = 0
    for index, match in enumerate(matches):
        segment = match["path"] if index == 0 else f"\n{match['path']}"
        if content[cursor : cursor + len(segment)] != segment:
            break
        visible_matches.append(match)
        cursor += len(segment)
        if cursor >= len(content):
            break
    return visible_matches


def _append_find_notices(
    content: str,
    *,
    result_limit: int,
    result_limit_reached: bool,
    byte_truncated: bool,
) -> str:
    notices: list[str] = []
    if result_limit_reached:
        notices.append(
            f"{result_limit} results limit reached. Use limit={result_limit * 2} for more, or refine pattern"
        )
    if byte_truncated:
        notices.append("50.0KB limit reached")
    if not notices:
        return content
    return f"{content}\n\n[{'. '.join(notices)}]"
