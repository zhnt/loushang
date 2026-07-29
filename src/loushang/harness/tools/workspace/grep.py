import fnmatch
import json
import os
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from loushang.agent.types import AgentToolResult, TextPart
from loushang.harness.approval import ApprovalResolver
from loushang.harness.workspace.operations import GrepOperations, resolve_operation

from .authoring import tool
from .authorization import AuthorizedWorkspaceAction, execute_workspace_tool_action
from .builtin_renderers import render_grep_call, render_grep_result
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
    normalize_grep_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .policy import ToolPolicyEvaluator
from .process import run_external_process_lines
from .runtime import coerce_int_parameter, pi_truncation_details, prepare_tool_arguments
from .truncate import (
    GREP_MAX_LINE_LENGTH,
    truncate_head,
    truncate_line,
    truncation_details,
)
from .types import PiTruncationDetails, ToolDefinition

DEFAULT_GREP_LIMIT = 100


class GrepToolInput(TypedDict):
    pattern: str
    path: NotRequired[str]
    file_path: NotRequired[str]
    glob: NotRequired[str]
    ignoreCase: NotRequired[bool]
    ignore_case: NotRequired[bool]
    literal: NotRequired[bool]
    context: NotRequired[int]
    limit: NotRequired[int]


class GrepToolMatch(TypedDict):
    path: str
    line_number: int
    line: str


class GrepToolDetails(TypedDict, total=False):
    path: str
    matches: list[GrepToolMatch]
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
    match_limit_reached: bool
    match_limit: int | None
    lines_truncated: bool
    truncation: PiTruncationDetails | None


@dataclass(frozen=True)
class GrepToolOptions:
    operations: GrepOperations | None = None
    external_tool_resolver: ExternalToolResolver | None = None
    external_tool_downloader: ExternalToolDownloader | None = None
    external_tool_policy: ExternalToolPolicy | None = None
    allow_external_tool_downloads: bool = False
    require_external_tool: bool = False
    policy_engine: ToolPolicyEvaluator | None = None
    approval_resolver: ApprovalResolver | None = None


def create_grep_tool_definition(
    *,
    operations: GrepOperations | None = None,
    policy_engine: ToolPolicyEvaluator | None = None,
    approval_resolver: ApprovalResolver | None = None,
    options: GrepToolOptions | None = None,
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
    ops = normalize_grep_operations(selected_operations)
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
        name="grep",
        label="Grep",
        description="Search file contents in the workspace.",
        prompt_snippet="- grep: Search file contents for patterns in the workspace.",
        prompt_guidelines=(
            "Use grep to search file contents instead of shelling out to grep or rg.",
            "Use literal=true for exact text searches and glob to narrow file types.",
        ),
    )
    async def grep(
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        ignoreCase: bool | None = None,
        literal: bool | None = None,
        context: int | None = None,
        limit: int | None = None,
        *,
        ctx: ToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        context_lines = _validate_context(context)
        raise_if_operation_aborted(ctx.signal)
        resolved_path = resolve_tool_path(path or ".", cwd=ctx.cwd)

        async def execute(
            _action: AuthorizedWorkspaceAction,
        ) -> AgentToolResult[dict[str, Any]]:
            search_path, base_dir = await _require_search_path(
                resolved_path,
                operations=ops,
            )
            effective_limit = _effective_limit(limit)
            matches, match_limit_reached = await _search_contents(
                search_path,
                base_dir=base_dir,
                pattern=pattern,
                glob=glob,
                ignore_case=bool(ignoreCase),
                literal=bool(literal),
                limit=effective_limit,
                operations=ops,
                use_external_tools=use_external_tools,
                external_tool_resolver=external_tool_resolver,
                require_external_tool=require_external_tool,
                signal=ctx.signal,
            )
            rendered_entries = await _render_grep_entries(
                base_dir, matches, context=context_lines, operations=ops
            )
            raise_if_operation_aborted(ctx.signal)
            raw_output = "\n".join(
                entry["rendered"] for entry in rendered_entries
            )
            truncation = truncate_head(raw_output, max_lines=1_000_000)
            visible_matches = _visible_grep_matches(
                rendered_entries,
                truncation.content,
            )
            lines_truncated = any(
                entry["line_truncated"] for entry in rendered_entries
            )
            rendered = truncation.content if matches else "No matches found"
            if matches:
                rendered = _append_grep_notices(
                    rendered,
                    match_limit=effective_limit,
                    match_limit_reached=match_limit_reached,
                    byte_truncated=truncation.truncated_by == "bytes",
                    lines_truncated=lines_truncated,
                )
            return AgentToolResult(
                content=[TextPart(type="text", text=rendered)],
                details={
                    "path": str(search_path),
                    "matches": visible_matches,
                    **truncation_details(truncation),
                    "truncated": match_limit_reached or truncation.truncated,
                    "match_limit_reached": match_limit_reached,
                    "match_limit": (
                        effective_limit if match_limit_reached else None
                    ),
                    "lines_truncated": lines_truncated,
                    "truncation": (
                        pi_truncation_details(truncation)
                        if truncation.truncated
                        else None
                    ),
                },
            )

        return await execute_workspace_tool_action(
            resolved_policy_engine,
            tool_name="grep",
            arguments={"path": str(resolved_path), "pattern": pattern},
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
        tool_to_definition(grep),
        prepare_arguments=lambda value: prepare_tool_arguments(
            value,
            aliases=(("file_path", "path"), ("ignore_case", "ignoreCase")),
        ),
        render_call=render_grep_call,
        render_result=render_grep_result,
    )


async def _require_search_path(
    path: Path, *, operations: GrepOperations
) -> tuple[Path, Path]:
    resolved = path
    if not await resolve_operation(operations.exists(resolved)):
        raise FileNotFoundError(str(resolved))
    if await resolve_operation(operations.is_dir(resolved)):
        return resolved, resolved
    if await resolve_operation(operations.is_file(resolved)):
        return resolved, resolved.parent
    raise NotADirectoryError(str(resolved))


def _validate_context(context: int | None) -> int:
    return coerce_int_parameter(context, field_name="context", minimum=0) or 0


def _effective_limit(limit: int | None) -> int:
    return (
        coerce_int_parameter(limit, field_name="limit", minimum=1) or DEFAULT_GREP_LIMIT
    )


async def _search_contents(
    search_path: Path,
    *,
    base_dir: Path,
    pattern: str,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    limit: int,
    operations: GrepOperations,
    use_external_tools: bool,
    external_tool_resolver: ExternalToolResolver | None,
    require_external_tool: bool,
    signal: object | None,
) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(pattern, str) or not pattern:
        raise TypeError("pattern must be a non-empty string")
    if glob is not None and (not isinstance(glob, str) or not glob):
        raise TypeError("glob must be a non-empty string when provided")
    external_result = (
        await _search_contents_with_rg(
            search_path,
            base_dir=base_dir,
            pattern=pattern,
            glob=glob,
            ignore_case=ignore_case,
            literal=literal,
            limit=limit,
            external_tool_resolver=external_tool_resolver,
            require_external_tool=require_external_tool,
            signal=signal,
        )
        if use_external_tools
        else None
    )
    if external_result is not None:
        return external_result
    regex: re.Pattern[str] | None = None
    if not literal:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
    elif ignore_case:
        pattern = pattern.lower()
    all_matches = await _search_contents_with_operations(
        search_path,
        base_dir=base_dir,
        pattern=pattern,
        glob=glob,
        ignore_case=ignore_case,
        literal=literal,
        regex=regex,
        operations=operations,
        respect_ignore=use_external_tools,
    )

    if len(all_matches) <= limit:
        return all_matches, False
    return all_matches[:limit], True


async def _search_contents_with_rg(
    search_path: Path,
    *,
    base_dir: Path,
    pattern: str,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    limit: int,
    external_tool_resolver: ExternalToolResolver | None = None,
    require_external_tool: bool = False,
    signal: object | None = None,
) -> tuple[list[dict[str, Any]], bool] | None:
    rg_path = await _resolve_rg_path(external_tool_resolver)
    if rg_path is None:
        if require_external_tool:
            raise RuntimeError(
                "ripgrep (rg) is not available and could not be downloaded "
                "(rg external tool is required but unavailable)"
            )
        return None
    command = [
        rg_path,
        "--json",
        "--line-number",
        "--color=never",
        "--hidden",
        "--glob",
        "!.git/**",
        "--glob",
        "!node_modules/**",
    ]
    if ignore_case:
        command.append("--ignore-case")
    if literal:
        command.append("--fixed-strings")
    if glob is not None:
        command.extend(["--glob", glob])
    search_target = search_path.name if search_path.is_file() else "."
    command.extend([pattern, search_target])

    matches: list[dict[str, Any]] = []
    match_limit_reached = False

    def on_stdout_line(line: str) -> bool:
        nonlocal match_limit_reached
        if not line.strip():
            return True
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return True
        if event.get("type") != "match":
            return True
        data = event.get("data", {})
        path_text = data.get("path", {}).get("text")
        line_number = data.get("line_number")
        line_text = data.get("lines", {}).get("text", "").rstrip("\n")
        if not isinstance(path_text, str) or not isinstance(line_number, int):
            return True
        matches.append(
            {
                "path": _normalize_rg_output_path(path_text, search_path),
                "line_number": line_number,
                "line": line_text,
            }
        )
        if len(matches) >= limit:
            match_limit_reached = True
            return False
        return True

    completed = await run_external_process_lines(
        command,
        cwd=base_dir,
        on_stdout_line=on_stdout_line,
        signal=signal,
    )
    if completed.returncode == 1 and not matches:
        return [], False
    if completed.returncode != 0 and not completed.stopped_early:
        raise RuntimeError(
            completed.stderr.strip()
            or f"ripgrep exited with code {completed.returncode}"
        )
    return matches, match_limit_reached


async def _resolve_rg_path(
    external_tool_resolver: ExternalToolResolver | None,
) -> str | None:
    if external_tool_resolver is not None:
        return await resolve_external_tool("rg", resolver=external_tool_resolver)
    system_path = shutil.which("rg")
    if system_path is not None:
        return system_path
    managed = get_managed_external_tool_install("rg")
    if managed is not None:
        return managed.binary_path
    return None


def _normalize_rg_output_path(path_text: str, search_path: Path) -> str:
    cleaned = path_text.rstrip("\r").strip()
    if not cleaned:
        return ""
    if search_path.is_file():
        return Path(cleaned.removeprefix("./")).name
    relative = cleaned.removeprefix("./")
    candidate = Path(relative)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(search_path).as_posix()
        except ValueError:
            relative = os.path.relpath(candidate, search_path).replace(os.sep, "/")
    else:
        relative = relative.replace("\\", "/")
    return relative


async def _search_contents_with_operations(
    search_path: Path,
    *,
    base_dir: Path,
    pattern: str,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    regex: re.Pattern[str] | None,
    operations: GrepOperations,
    respect_ignore: bool,
) -> list[dict[str, Any]]:
    all_matches: list[dict[str, Any]] = []
    search_is_file = base_dir != search_path
    ignore_matcher = (
        load_ignore_matcher(search_path)
        if respect_ignore and not search_is_file
        else None
    )
    candidates = (
        [search_path]
        if search_is_file
        else sorted(
            await resolve_operation(operations.walk_files(search_path)),
            key=lambda item: str(item),
        )
    )
    for candidate in candidates:
        if ignore_matcher is not None and ignore_matcher.is_ignored(candidate):
            continue
        relative = _relative_path(candidate, base_dir)
        if glob is not None and not fnmatch.fnmatch(relative, glob):
            continue
        try:
            contents = await resolve_operation(operations.read_text(candidate))
        except UnicodeDecodeError:
            continue
        except OSError:
            continue
        if "\x00" in contents:
            continue

        for line_no, line in enumerate(contents.splitlines(), start=1):
            haystack = line.lower() if literal and ignore_case else line
            matched = (pattern in haystack) if literal else bool(regex.search(line))
            if not matched:
                continue
            all_matches.append(
                {
                    "path": relative,
                    "line_number": line_no,
                    "line": line,
                }
            )
    return all_matches


async def _render_grep_entries(
    base_dir: Path,
    matches: list[dict[str, Any]],
    *,
    context: int,
    operations: GrepOperations,
) -> list[dict[str, Any]]:
    rendered_entries: list[dict[str, Any]] = []
    for match in matches:
        if context == 0:
            rendered_line, line_truncated = _truncate_grep_line(match["line"])
            rendered_entries.append(
                {
                    "rendered": _render_grep_line(
                        {**match, "line": rendered_line}, is_match=True
                    ),
                    "match": match,
                    "line_truncated": line_truncated,
                }
            )
            continue

        path = base_dir / match["path"]
        try:
            lines = (await resolve_operation(operations.read_text(path))).splitlines()
        except UnicodeDecodeError:
            lines = []
        except OSError:
            lines = []

        if not lines:
            rendered_line, line_truncated = _truncate_grep_line(match["line"])
            rendered_entries.append(
                {
                    "rendered": _render_grep_line(
                        {**match, "line": rendered_line}, is_match=True
                    ),
                    "match": match,
                    "line_truncated": line_truncated,
                }
            )
            continue

        line_number = match["line_number"]
        start = max(1, line_number - context)
        end = min(len(lines), line_number + context)
        for current_line_number in range(start, end + 1):
            line_text = lines[current_line_number - 1].rstrip("\r")
            is_match = current_line_number == line_number
            rendered_line, line_truncated = _truncate_grep_line(line_text)
            rendered_entries.append(
                {
                    "rendered": _render_grep_line(
                        {
                            "path": match["path"],
                            "line_number": current_line_number,
                            "line": rendered_line,
                        },
                        is_match=is_match,
                    ),
                    "match": match if is_match else None,
                    "line_truncated": line_truncated,
                }
            )
    return rendered_entries


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _render_grep_line(match: dict[str, Any], *, is_match: bool) -> str:
    separator = ":" if is_match else "-"
    return f"{match['path']}{separator}{match['line_number']}{separator}{match['line']}"


def _truncate_grep_line(line: str) -> tuple[str, bool]:
    result = truncate_line(line, max_chars=GREP_MAX_LINE_LENGTH)
    return result.text, result.was_truncated


def _visible_grep_matches(
    rendered_entries: list[dict[str, Any]], content: str
) -> list[dict[str, Any]]:
    visible_matches: list[dict[str, Any]] = []
    cursor = 0
    for index, entry in enumerate(rendered_entries):
        rendered = entry["rendered"]
        segment = rendered if index == 0 else f"\n{rendered}"
        if content[cursor : cursor + len(segment)] != segment:
            break
        match = entry.get("match")
        if match is not None:
            visible_matches.append(match)
        cursor += len(segment)
        if cursor >= len(content):
            break
    return visible_matches


def _append_grep_notices(
    content: str,
    *,
    match_limit: int,
    match_limit_reached: bool,
    byte_truncated: bool,
    lines_truncated: bool,
) -> str:
    notices: list[str] = []
    if match_limit_reached:
        notices.append(
            f"{match_limit} matches limit reached. Use limit={match_limit * 2} for more, or refine pattern"
        )
    if byte_truncated:
        notices.append("50.0KB limit reached")
    if lines_truncated:
        notices.append(
            f"Some lines truncated to {GREP_MAX_LINE_LENGTH} chars. Use read tool to see full lines"
        )
    if not notices:
        return content
    return f"{content}\n\n[{'. '.join(notices)}]"
