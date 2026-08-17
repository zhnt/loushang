"""Shared CLI command catalog discovery and projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from loushang.harness.commands import project_command_descriptor


class CommandListingError(RuntimeError):
    """Raised when a session command catalog cannot be listed."""


def list_command_records(session: object) -> list[dict[str, object]]:
    getter = getattr(session, "list_commands", None)
    if not callable(getter):
        raise CommandListingError("command registry is not available.")
    try:
        commands = getter()
    except Exception as error:
        raise CommandListingError(str(error)) from error
    if not isinstance(commands, list):
        raise CommandListingError("command registry returned an invalid response.")
    records: list[dict[str, object]] = []
    for command in commands:
        try:
            projected = project_command_descriptor(command)
        except Exception:
            projected = None
        if projected is not None:
            records.append(projected)
    return records


def format_command_records(
    records: Sequence[Mapping[str, object]],
    output_format: str,
) -> str:
    if output_format == "json":
        return json.dumps(records, ensure_ascii=False) + "\n"
    return "".join(
        f"{command['name']}\t{command['source']}\t"
        f"{_command_source_path(command)}\t{command['description']}\n"
        for command in records
    )


def _command_source_path(command: Mapping[str, object]) -> object:
    source_info = command.get("source_info")
    return source_info.get("path", "") if isinstance(source_info, Mapping) else ""


__all__ = ["CommandListingError", "format_command_records", "list_command_records"]
