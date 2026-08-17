"""Standard session command execution over Product-bound ports.

This module deliberately does not own a command catalog or a session runtime.
Products register their existing command source with ``SessionCommandRuntime``
and delegate the admitted command subset here.  The bound callbacks execute
the already-composed session, lifecycle, and transcript-navigation runtimes.
"""

from __future__ import annotations

import inspect
import shlex
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from loushang.harness.session.commands.catalog import (
    STANDARD_SESSION_COMMAND_PROFILE,
    StandardSessionCommandId,
    StandardSessionCommandProfile,
    resolve_standard_session_command_id,
)

StandardSessionCommandDisposition = Literal[
    "completed", "unavailable", "invalid_arguments"
]
CommandPort = Callable[..., object | Awaitable[object]]
SessionNamePort = Callable[[str | None], object | Awaitable[object]]
SessionExportPort = Callable[[str | None], object | Awaitable[object]]
SessionImportPort = Callable[[str, str | None], object | Awaitable[object]]


@dataclass(frozen=True)
class StandardSessionCommandResult:
    """Typed outcome before a Product projects it to UI or transport values."""

    command_id: StandardSessionCommandId
    disposition: StandardSessionCommandDisposition
    value: object | None = None
    error_code: str | None = None

    @classmethod
    def completed(
        cls,
        command_id: StandardSessionCommandId,
        value: object | None = None,
    ) -> "StandardSessionCommandResult":
        return cls(command_id=command_id, disposition="completed", value=value)

    @classmethod
    def unavailable(
        cls, command_id: StandardSessionCommandId
    ) -> "StandardSessionCommandResult":
        return cls(command_id=command_id, disposition="unavailable")

    @classmethod
    def invalid_arguments(
        cls,
        command_id: StandardSessionCommandId,
        error_code: str,
        value: object | None = None,
    ) -> "StandardSessionCommandResult":
        return cls(
            command_id=command_id,
            disposition="invalid_arguments",
            value=value,
            error_code=error_code,
        )


@dataclass(frozen=True)
class StandardSessionExport:
    """Product-neutral result of a completed transcript export."""

    format: Literal["html", "jsonl"]
    path: object


@dataclass
class StandardSessionCommandPorts:
    """Already-bound session operation callbacks supplied by a Product.

    Each callback delegates to an existing Product composition of Harness
    session, lifecycle, or transcript-navigation runtimes.  This command pack
    only validates arguments and chooses which admitted callback to invoke.
    """

    get_session_info: Callable[[], object] | None = None
    set_session_name: SessionNamePort | None = None
    export_html: SessionExportPort | None = None
    export_jsonl: SessionExportPort | None = None
    import_session: SessionImportPort | None = None
    compact: CommandPort | None = None
    reload: CommandPort | None = None
    new_session: CommandPort | None = None
    resume_session: CommandPort | None = None
    fork_session: CommandPort | None = None
    clone_session: CommandPort | None = None
    navigate_tree: CommandPort | None = None
    get_active_tool_names: Callable[[], list[str]] | None = None
    get_all_tools: Callable[[], Sequence[object]] | None = None
    set_active_tools: Callable[[list[str]], object | Awaitable[object]] | None = None
    get_default_active_tool_names: Callable[[], list[str]] | None = None
    get_extensions: Callable[[], Sequence[object]] | None = None
    get_recent_assistant_texts: Callable[[], tuple[str, ...]] | None = None
    get_last_assistant_text: Callable[[], str | None] | None = None
    copy_text: Callable[[str], object] | None = None
    get_changelog: CommandPort | None = None


async def execute_standard_session_command_async(
    invocation_name: str,
    args: str,
    ports: StandardSessionCommandPorts,
    *,
    profile: StandardSessionCommandProfile = STANDARD_SESSION_COMMAND_PROFILE,
) -> StandardSessionCommandResult | None:
    """Execute one selected standard command or return ``None`` when unhandled.

    Product-local commands stay unhandled.  Exceptions from a bound operation
    deliberately propagate: lifecycle, compaction, and navigation runtimes
    retain their established rollback and failure behavior.
    """

    command_id = resolve_standard_session_command_id(invocation_name)
    if command_id is None or not profile.includes(command_id):
        return None

    match command_id:
        case StandardSessionCommandId.SESSION:
            if ports.get_session_info is None:
                return StandardSessionCommandResult.unavailable(command_id)
            return StandardSessionCommandResult.completed(
                command_id, ports.get_session_info()
            )
        case StandardSessionCommandId.RENAME:
            if ports.set_session_name is None:
                return StandardSessionCommandResult.unavailable(command_id)
            name = args.strip() or None
            await _resolve(ports.set_session_name(name))
            return StandardSessionCommandResult.completed(command_id, name)
        case StandardSessionCommandId.EXPORT:
            raw_path = args.strip() or None
            export_format: Literal["html", "jsonl"] = (
                "jsonl"
                if raw_path is not None and raw_path.lower().endswith(".jsonl")
                else "html"
            )
            export_port = (
                ports.export_jsonl if export_format == "jsonl" else ports.export_html
            )
            if export_port is None:
                return StandardSessionCommandResult.unavailable(command_id)
            path = await _resolve(export_port(raw_path))
            return StandardSessionCommandResult.completed(
                command_id,
                StandardSessionExport(format=export_format, path=path),
            )
        case StandardSessionCommandId.IMPORT:
            if ports.import_session is None:
                return StandardSessionCommandResult.unavailable(command_id)
            tokens = _split_args(args)
            if not tokens:
                return StandardSessionCommandResult.invalid_arguments(
                    command_id, "missing_import_path"
                )
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(
                    ports.import_session(
                        tokens[0], tokens[1] if len(tokens) > 1 else None
                    )
                ),
            )
        case StandardSessionCommandId.COMPACT:
            if ports.compact is None:
                return StandardSessionCommandResult.unavailable(command_id)
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(ports.compact(args.strip() or None)),
            )
        case StandardSessionCommandId.RELOAD:
            if ports.reload is None:
                return StandardSessionCommandResult.unavailable(command_id)
            await _resolve(ports.reload())
            return StandardSessionCommandResult.completed(command_id)
        case StandardSessionCommandId.NEW:
            if ports.new_session is None:
                return StandardSessionCommandResult.unavailable(command_id)
            if args.strip():
                return StandardSessionCommandResult.invalid_arguments(
                    command_id, "unexpected_arguments"
                )
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(ports.new_session()),
            )
        case StandardSessionCommandId.RESUME:
            if ports.resume_session is None:
                return StandardSessionCommandResult.unavailable(command_id)
            tokens = _split_args(args)
            if not tokens:
                return StandardSessionCommandResult.invalid_arguments(
                    command_id, "missing_reference"
                )
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(ports.resume_session(tokens[0], None)),
            )
        case StandardSessionCommandId.DELETE:
            if args.strip():
                return StandardSessionCommandResult.invalid_arguments(
                    command_id, "unexpected_arguments"
                )
            return StandardSessionCommandResult.unavailable(command_id)
        case StandardSessionCommandId.FORK:
            if ports.fork_session is None:
                return StandardSessionCommandResult.unavailable(command_id)
            tokens = _split_args(args)
            if not tokens:
                return StandardSessionCommandResult.invalid_arguments(
                    command_id, "missing_record_id"
                )
            options: dict[str, object] = {}
            if len(tokens) > 1:
                if tokens[1] not in {"before", "at"}:
                    return StandardSessionCommandResult.invalid_arguments(
                        command_id, "invalid_fork_position", tokens[1]
                    )
                options["position"] = tokens[1]
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(ports.fork_session(tokens[0], options or None)),
            )
        case StandardSessionCommandId.CLONE:
            if ports.clone_session is None:
                return StandardSessionCommandResult.unavailable(command_id)
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(ports.clone_session()),
            )
        case StandardSessionCommandId.TREE:
            if ports.navigate_tree is None:
                return StandardSessionCommandResult.unavailable(command_id)
            tokens = _split_args(args)
            if not tokens:
                return StandardSessionCommandResult.invalid_arguments(
                    command_id, "missing_record_id"
                )
            options = _parse_tree_options(tokens[1:])
            return StandardSessionCommandResult.completed(
                command_id,
                await _resolve(ports.navigate_tree(tokens[0], options or None)),
            )
        case StandardSessionCommandId.TOOLS:
            return await _execute_tools_command(args, ports)
        case StandardSessionCommandId.EXTENSIONS:
            return await _execute_extensions_command(args, ports)
        case StandardSessionCommandId.COPY:
            return _execute_copy_command(args, ports)
        case StandardSessionCommandId.CHANGELOG:
            if ports.get_changelog is None:
                return StandardSessionCommandResult.unavailable(command_id)
            return StandardSessionCommandResult.completed(
                command_id, await _resolve(ports.get_changelog(args))
            )


async def _resolve(value: object | Awaitable[object]) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _split_args(args: str) -> list[str]:
    try:
        return shlex.split(args)
    except ValueError:
        return args.split()


def _parse_tree_options(tokens: list[str]) -> dict[str, object]:
    options: dict[str, object] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--summarize":
            options["summarize"] = True
        elif token in {"--label", "-l"} and index + 1 < len(tokens):
            index += 1
            options["label"] = tokens[index]
        elif token == "--replace-instructions":
            options["replace_instructions"] = True
        elif token in {"--instructions", "--custom-instructions"} and index + 1 < len(
            tokens
        ):
            index += 1
            options["custom_instructions"] = tokens[index]
        index += 1
    return options


async def _execute_tools_command(
    args: str, ports: StandardSessionCommandPorts
) -> StandardSessionCommandResult:
    command_id = StandardSessionCommandId.TOOLS
    if ports.get_active_tool_names is None or ports.get_all_tools is None:
        return StandardSessionCommandResult.unavailable(command_id)
    active_tools = list(ports.get_active_tool_names())
    available_tools = _available_tool_entries(ports.get_all_tools(), active_tools)
    available_names = [
        name for entry in available_tools if isinstance(name := entry.get("name"), str)
    ]
    tokens = _split_args(args.strip()) if args.strip() else []
    if not tokens:
        return StandardSessionCommandResult.completed(
            command_id, _tools_result(active_tools, available_tools)
        )
    action = tokens[0]
    if action == "reset":
        if len(tokens) != 1 or ports.set_active_tools is None:
            return StandardSessionCommandResult.invalid_arguments(
                command_id, "invalid_tools_arguments"
            )
        if ports.get_default_active_tool_names is None:
            return StandardSessionCommandResult.unavailable(command_id)
        next_tools = _filter_available_tools(
            ports.get_default_active_tool_names(), available_names
        )
    else:
        if action not in {"on", "off", "only"} or ports.set_active_tools is None:
            return StandardSessionCommandResult.invalid_arguments(
                command_id, "invalid_tools_arguments"
            )
        requested = _parse_tool_names(tokens[1:])
        if not requested:
            return StandardSessionCommandResult.invalid_arguments(
                command_id, "missing_tool_names"
            )
        unknown = [name for name in requested if name not in available_names]
        if unknown:
            return StandardSessionCommandResult.invalid_arguments(
                command_id,
                "unknown_tool",
                {"unknown": unknown, "available": available_names},
            )
        if action == "on":
            next_tools = [
                *active_tools,
                *(name for name in requested if name not in active_tools),
            ]
        elif action == "off":
            next_tools = [name for name in active_tools if name not in set(requested)]
        else:
            next_tools = requested
        next_tools = _filter_available_tools(next_tools, available_names)
    await _resolve(ports.set_active_tools(next_tools))
    return StandardSessionCommandResult.completed(
        command_id,
        _tools_result(
            next_tools,
            _available_tool_entries(ports.get_all_tools(), next_tools),
            action=None if action == "reset" else action,
        ),
    )


def _tools_result(
    active_tools: list[str],
    available_tools: list[dict[str, object]],
    *,
    action: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "active_tools": active_tools,
        "available_tools": available_tools,
    }
    if action is not None:
        result["action"] = action
    return result


async def _execute_extensions_command(
    args: str, ports: StandardSessionCommandPorts
) -> StandardSessionCommandResult:
    command_id = StandardSessionCommandId.EXTENSIONS
    if ports.get_extensions is None:
        return StandardSessionCommandResult.unavailable(command_id)
    extensions = [_extension_entry(extension) for extension in ports.get_extensions()]
    query = args.strip()
    if not query:
        return StandardSessionCommandResult.completed(
            command_id, {"extensions": extensions, "query": None, "selected": None}
        )
    selected = next(
        (
            extension
            for extension in extensions
            if query
            in {
                _extension_field(extension, "id"),
                _extension_field(extension, "name"),
                _extension_field(extension, "runtimeName"),
            }
        ),
        None,
    )
    return StandardSessionCommandResult.completed(
        command_id,
        {"extensions": extensions, "query": query, "selected": selected},
    )


def _execute_copy_command(
    args: str, ports: StandardSessionCommandPorts
) -> StandardSessionCommandResult:
    command_id = StandardSessionCommandId.COPY
    index = _parse_copy_index(args)
    if index is None:
        return StandardSessionCommandResult.invalid_arguments(
            command_id, "invalid_copy_index"
        )
    if (
        ports.get_recent_assistant_texts is None
        and ports.get_last_assistant_text is None
    ):
        return StandardSessionCommandResult.unavailable(command_id)
    texts = (
        tuple(ports.get_recent_assistant_texts())
        if ports.get_recent_assistant_texts is not None
        else (
            (text,)
            if ports.get_last_assistant_text is not None
            and (text := ports.get_last_assistant_text())
            else ()
        )
    )
    if index > len(texts):
        return StandardSessionCommandResult.completed(
            command_id,
            {"copied": False, "characters": 0, "index": index, "available": True},
        )
    if ports.copy_text is None:
        return StandardSessionCommandResult.unavailable(command_id)
    text = texts[index - 1]
    result = ports.copy_text(text)
    return StandardSessionCommandResult.completed(
        command_id,
        {
            "copied": bool(getattr(result, "ok", False)),
            "characters": len(text),
            "index": index,
            "available": True,
            "command": getattr(result, "command", None),
            "message": getattr(result, "message", None),
        },
    )


def _parse_copy_index(args: str) -> int | None:
    stripped = args.strip()
    if not stripped:
        return 1
    tokens = _split_args(stripped)
    if len(tokens) != 1:
        return None
    try:
        value = int(tokens[0])
    except ValueError:
        return None
    return value if value > 0 else None


def _extension_entry(extension: object) -> dict[str, object]:
    if isinstance(extension, Mapping):
        return dict(extension)
    name = _object_field(extension, "name")
    return {
        "id": _object_field(extension, "id") or name,
        "name": name,
        "runtimeName": _object_field(extension, "runtimeName"),
    }


def _extension_field(extension: Mapping[str, object], field: str) -> str:
    value = extension.get(field)
    return value if isinstance(value, str) else ""


def _object_field(value: object, field: str) -> str:
    raw = getattr(value, field, None)
    return raw if isinstance(raw, str) else ""


def _available_tool_entries(
    tools: Sequence[object],
    active_tools: list[str],
) -> list[dict[str, object]]:
    active_set = set(active_tools)
    entries: list[dict[str, object]] = []
    for tool in tools:
        name = _tool_field(tool, "name")
        if not name:
            continue
        entry: dict[str, object] = {
            "name": name,
            "active": name in active_set,
            "description": _tool_field(tool, "description"),
        }
        source_info = _tool_source_info(tool)
        if source_info is not None:
            entry["sourceInfo"] = dict(source_info)
        entries.append(entry)
    return entries


def _tool_field(tool: object, field: str) -> str:
    value = tool.get(field) if isinstance(tool, Mapping) else getattr(tool, field, None)
    return value if isinstance(value, str) else ""


def _tool_source_info(tool: object) -> Mapping[object, object] | None:
    value = (
        tool.get("sourceInfo") or tool.get("source_info")
        if isinstance(tool, Mapping)
        else getattr(tool, "sourceInfo", None) or getattr(tool, "source_info", None)
    )
    return value if isinstance(value, Mapping) else None


def _parse_tool_names(tokens: list[str]) -> list[str]:
    names: list[str] = []
    for token in tokens:
        for name in token.split(","):
            cleaned = name.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)
    return names


def _filter_available_tools(
    tool_names: list[str], available_names: list[str]
) -> list[str]:
    available = set(available_names)
    return [name for name in tool_names if name in available]


__all__ = [
    "StandardSessionCommandDisposition",
    "StandardSessionCommandPorts",
    "StandardSessionCommandResult",
    "StandardSessionExport",
    "execute_standard_session_command_async",
]
