"""Product-neutral projection for standard session command results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass

from loushang.harness.session.commands.catalog import StandardSessionCommandId
from loushang.harness.session.commands.execution import (
    StandardSessionCommandResult,
    StandardSessionExport,
)


def project_standard_session_command_result(
    result: StandardSessionCommandResult,
) -> dict[str, object]:
    """Project a standard result into the neutral command result mapping."""

    command = result.command_id.value
    if result.disposition == "unavailable":
        return _unsupported_command_result(command)
    if result.disposition == "invalid_arguments":
        return _error_command_result(command, _standard_argument_error(result))

    match result.command_id:
        case StandardSessionCommandId.SESSION:
            session = result.value
            if isinstance(session, Mapping):
                session = dict(session)
            return _ok_command_result(
                command,
                session=session,
                message=_session_message(session),
            )
        case StandardSessionCommandId.RENAME:
            name = result.value
            return _ok_command_result(
                command,
                name=name,
                message=(
                    f"Session renamed to {name}"
                    if isinstance(name, str)
                    else "Session name cleared"
                ),
            )
        case StandardSessionCommandId.EXPORT:
            export = result.value
            if not isinstance(export, StandardSessionExport):
                raise TypeError("standard export command returned an invalid result")
            return _ok_command_result(command, format=export.format, path=export.path)
        case StandardSessionCommandId.IMPORT | StandardSessionCommandId.COMPACT:
            return _ok_command_result(command, result=_to_plain_data(result.value))
        case StandardSessionCommandId.RELOAD:
            return _ok_command_result(command, reloaded=True)
        case StandardSessionCommandId.NEW:
            value = _to_plain_data(result.value)
            cancelled = isinstance(value, Mapping) and value.get("cancelled") is True
            return _ok_command_result(
                command,
                result=value,
                message=(
                    "New session creation cancelled."
                    if cancelled
                    else "Started a new session."
                ),
            )
        case (
            StandardSessionCommandId.RESUME
            | StandardSessionCommandId.FORK
            | StandardSessionCommandId.CLONE
            | StandardSessionCommandId.TREE
        ):
            return _ok_command_result(command, result=_to_plain_data(result.value))
        case StandardSessionCommandId.TOOLS:
            value = result.value
            if not isinstance(value, Mapping):
                raise TypeError("standard tools command returned an invalid result")
            active_tools = value.get("active_tools", [])
            available_tools = value.get("available_tools", [])
            if not isinstance(active_tools, list) or not isinstance(
                available_tools, list
            ):
                raise TypeError("standard tools command returned invalid tool data")
            fields: dict[str, object] = {
                "active_tools": [
                    name for name in active_tools if isinstance(name, str)
                ],
                "available_tools": [
                    entry for entry in available_tools if isinstance(entry, dict)
                ],
                "message": (
                    "Active tools: "
                    + ", ".join(name for name in active_tools if isinstance(name, str))
                    if active_tools
                    else "Active tools: (none)"
                ),
            }
            action = value.get("action")
            if isinstance(action, str):
                fields["action"] = action
            return _ok_command_result(command, **fields)
        case StandardSessionCommandId.EXTENSIONS:
            value = result.value
            if not isinstance(value, Mapping):
                raise TypeError(
                    "standard extensions command returned an invalid result"
                )
            extensions = value.get("extensions", [])
            query = value.get("query")
            selected = value.get("selected")
            if not isinstance(extensions, list):
                raise TypeError("standard extensions command returned invalid data")
            extensions = [entry for entry in extensions if isinstance(entry, dict)]
            if not isinstance(query, str) or not query:
                return _extensions_command_result(extensions)
            if not isinstance(selected, Mapping):
                available = (
                    ", ".join(_extension_id(extension) for extension in extensions)
                    or "(none)"
                )
                return _error_command_result(
                    command,
                    f"Unknown extension: {query}. Loaded extensions: {available}",
                )
            return _ok_command_result(
                command,
                extension=dict(selected),
                message=f"Extension {_extension_id(selected)}: "
                f"{_extension_name(selected)}",
                display=_extension_detail_display(selected),
            )
        case StandardSessionCommandId.COPY:
            value = result.value
            if not isinstance(value, Mapping):
                raise TypeError("standard copy command returned an invalid result")
            index = value.get("index", 1)
            if not isinstance(index, int):
                index = 1
            if not value.get("available", False):
                return _unsupported_command_result(command)
            if not value.get("copied", False):
                return _ok_command_result(
                    command,
                    copied=False,
                    characters=0,
                    message=f"No assistant text is available for /copy {index}.",
                    index=index,
                )
            return _ok_command_result(
                command,
                copied=True,
                characters=value.get("characters", 0),
                command_backend=value.get("command"),
                message=value.get("message"),
                index=index,
            )
        case StandardSessionCommandId.CHANGELOG:
            return _ok_command_result(command, changelog=_to_plain_data(result.value))
    raise ValueError(f"Unsupported standard session command: {result.command_id}")


def _to_plain_data(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_data(item) for item in value]
    return value


def _standard_argument_error(result: StandardSessionCommandResult) -> str:
    match result.command_id, result.error_code:
        case StandardSessionCommandId.COPY, "invalid_copy_index":
            return "Usage: /copy [N], where N is a positive integer."
        case StandardSessionCommandId.TOOLS, "unknown_tool":
            value = result.value
            if isinstance(value, Mapping):
                unknown = value.get("unknown", [])
                available = value.get("available", [])
                if isinstance(unknown, list) and isinstance(available, list):
                    return (
                        f"Unknown tool: {', '.join(str(item) for item in unknown)}. "
                        f"Available tools: {', '.join(str(item) for item in available)}"
                    )
            return "Unknown tool"
        case StandardSessionCommandId.RESUME, "missing_reference":
            return "Usage: /resume <session-id-or-path>"
        case StandardSessionCommandId.NEW, "unexpected_arguments":
            return "Usage: /new"
        case StandardSessionCommandId.DELETE, "unexpected_arguments":
            return "Usage: /delete"
        case StandardSessionCommandId.FORK, "missing_record_id":
            return "Usage: /fork <entry-id> [before|at]"
        case StandardSessionCommandId.FORK, "invalid_fork_position":
            return f"Unsupported fork position: {result.value}"
        case StandardSessionCommandId.IMPORT, "missing_import_path":
            return "Usage: /import <jsonl-path> [cwd]"
        case StandardSessionCommandId.TREE, "missing_record_id":
            return "Usage: /tree <entry-id> [--summarize] [--label <label>]"
        case _:
            return f"Invalid arguments for /{result.command_id.value}"


def _session_message(session: object) -> str:
    if not isinstance(session, Mapping):
        return "Session information available."

    fields = (
        ("Session", session.get("session_id")),
        ("Name", session.get("session_name")),
        ("CWD", session.get("cwd")),
    )
    parts = [
        f"{label}: {value}"
        for label, value in fields
        if isinstance(value, str) and value
    ]
    compaction = session.get("compaction")
    compact_status = _compact_status_message(compaction)
    if compact_status is not None:
        parts.append(compact_status)
    context = session.get("context")
    context_status = _context_status_message(context)
    if context_status is not None:
        parts.append(context_status)
    return " | ".join(parts) or "Session information available."


def _compact_status_message(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("is_compacting") is True:
        return "Compact: running"
    reason = value.get("last_reason")
    stage = value.get("last_stage")
    if not isinstance(reason, str) or not reason:
        return None
    label = reason
    if isinstance(stage, str) and stage:
        label += f"/{stage}"
    mode = value.get("last_summary_mode")
    if isinstance(mode, str) and mode:
        label += f", {mode}"
    before = value.get("last_tokens_before")
    after = value.get("last_tokens_after")
    if isinstance(before, int) and not isinstance(before, bool):
        label += f", {before}"
        if isinstance(after, int) and not isinstance(after, bool):
            label += f"→{after} tokens"
        else:
            label += " tokens before"
    return f"Compact: {label}"


def _context_status_message(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    tokens = value.get("tokens")
    window = value.get("context_window")
    reserve = value.get("reserve_tokens")
    parts: list[str] = []
    if isinstance(tokens, int) and not isinstance(tokens, bool):
        if isinstance(window, int) and not isinstance(window, bool):
            parts.append(f"{tokens}/{window} tokens")
        else:
            parts.append(f"{tokens} tokens")
    elif isinstance(window, int) and not isinstance(window, bool):
        parts.append(f"window {window}")
    if isinstance(reserve, int) and not isinstance(reserve, bool):
        parts.append(f"reserve {reserve}")
    return f"Context: {', '.join(parts)}" if parts else None


def _ok_command_result(command: str, **fields: object) -> dict[str, object]:
    return {"source": "builtin", "command": command, "status": "ok", **fields}


def _error_command_result(command: str, message: str) -> dict[str, object]:
    return {
        "source": "builtin",
        "command": command,
        "status": "error",
        "message": message,
    }


def _unsupported_command_result(command: str) -> dict[str, object]:
    return {
        "source": "builtin",
        "command": command,
        "status": "unsupported",
        "message": f'Builtin command "/{command}" is handled by the interactive shell.',
    }


def _extensions_command_result(
    extensions: list[dict[str, object]],
) -> dict[str, object]:
    if not extensions:
        return _ok_command_result(
            "extensions",
            extensions=[],
            message="Extensions: (none)",
            display="Extensions:\n(none)",
        )
    summary = "; ".join(_extension_summary(extension) for extension in extensions)
    lines = ["Extensions:"]
    for extension in extensions:
        lines.append(
            f"- {_extension_id(extension)} - {_extension_name(extension)} "
            f"[{_string_mapping_field(extension, 'permissionLevel', default='safe')}]"
        )
        source_path = _string_mapping_field(extension, "sourcePath")
        if source_path:
            lines.append(f"  Source: {source_path}")
        surfaces = _surface_records(extension)
        if surfaces:
            lines.append(f"  Surfaces: {_surfaces_summary(surfaces)}")
        diagnostics = _list_field(extension, "diagnostics")
        if diagnostics:
            lines.append(f"  Diagnostics: {len(diagnostics)}")
    return _ok_command_result(
        "extensions",
        extensions=extensions,
        message=f"Extensions: {summary}",
        display="\n".join(lines),
    )


def _extension_summary(extension: Mapping[str, object]) -> str:
    surfaces = len(_surface_records(extension))
    diagnostics = len(_list_field(extension, "diagnostics"))
    details = [_string_mapping_field(extension, "permissionLevel", default="safe")]
    details.append(f"{surfaces} {'surface' if surfaces == 1 else 'surfaces'}")
    if diagnostics:
        details.append(
            f"{diagnostics} {'diagnostic' if diagnostics == 1 else 'diagnostics'}"
        )
    return f"{_extension_id(extension)} ({', '.join(details)})"


def _extension_detail_display(extension: Mapping[str, object]) -> str:
    lines = [
        f"Extension {_extension_id(extension)}",
        f"Name: {_extension_name(extension)}",
    ]
    for label, field in (("Version", "version"), ("Description", "description")):
        value = _string_mapping_field(extension, field)
        if value:
            lines.append(f"{label}: {value}")
    lines.append(
        f"Permission: {_string_mapping_field(extension, 'permissionLevel', default='safe')}"
    )
    capabilities = [
        item
        for item in _list_field(extension, "capabilities")
        if isinstance(item, str) and item
    ]
    lines.append(
        f"Capabilities: {', '.join(capabilities) if capabilities else '(none)'}"
    )
    source_path = _string_mapping_field(extension, "sourcePath")
    if source_path:
        lines.append(f"Source: {source_path}")
    manifest_path = _string_mapping_field(extension, "manifestPath")
    if manifest_path:
        lines.append(f"Manifest: {manifest_path}")
    surfaces = _surface_records(extension)
    lines.append("Surfaces:")
    if surfaces:
        for surface in surfaces:
            if isinstance(surface, Mapping):
                surface_type = _string_mapping_field(surface, "type", default="surface")
                name = _string_mapping_field(surface, "name", default="(unnamed)")
                source = _string_mapping_field(surface, "source")
                lines.append(
                    f"- {surface_type} {name}{f' ({source})' if source else ''}"
                )
    else:
        lines.append("- (none)")
    diagnostics = _list_field(extension, "diagnostics")
    lines.append("Diagnostics:")
    if diagnostics:
        for diagnostic in diagnostics:
            if isinstance(diagnostic, Mapping):
                code = _string_mapping_field(diagnostic, "code", default="diagnostic")
                message = _string_mapping_field(diagnostic, "message")
                lines.append(f"- {code}: {message}" if message else f"- {code}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _surface_records(extension: Mapping[str, object]) -> list[object]:
    surfaces = _list_field(extension, "surfaces")
    return surfaces if surfaces else _list_field(extension, "contributions")


def _surfaces_summary(surfaces: list[object]) -> str:
    parts = []
    for surface in surfaces:
        if isinstance(surface, Mapping):
            name = _string_mapping_field(surface, "name")
            if name:
                parts.append(
                    f"{_string_mapping_field(surface, 'type', default='surface')} {name}"
                )
    return ", ".join(parts) if parts else "(none)"


def _extension_id(extension: Mapping[str, object]) -> str:
    return _string_mapping_field(extension, "id", default=_extension_name(extension))


def _extension_name(extension: Mapping[str, object]) -> str:
    return _string_mapping_field(extension, "name", default="")


def _string_mapping_field(
    value: Mapping[str, object],
    field: str,
    *,
    default: str = "",
) -> str:
    raw = value.get(field)
    return raw if isinstance(raw, str) and raw else default


def _list_field(value: Mapping[str, object], field: str) -> list[object]:
    raw = value.get(field)
    return list(raw) if isinstance(raw, (list, tuple)) else []


__all__ = ["project_standard_session_command_result"]
