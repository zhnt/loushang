"""Projection of extension command contributions into shared descriptors."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from loushang.harness.commands import SessionCommandDescriptor
from loushang.harness.extensions.types import ResolvedCommand
from loushang.harness.resources.source import SourceInfo, create_source_info


def list_extension_command_descriptors(
    commands: Iterable[ResolvedCommand],
) -> list[SessionCommandDescriptor]:
    """Project resolved extension commands without Product-specific metadata."""

    return [
        SessionCommandDescriptor(
            name=command.invocation_name,
            description=command.description,
            source="extension",
            source_info=command_source_info_from_extension(command.source_info),
            invocation_name=command.invocation_name,
            conflict_group=(
                command.name if command.invocation_name != command.name else None
            ),
        )
        for command in commands
    ]


def command_source_info_from_extension(
    source_info: SourceInfo[Path],
) -> SourceInfo[str]:
    """Convert extension provenance to the string-path command contract."""

    return create_source_info(
        source_info.path,
        source=source_info.source,
        scope=source_info.scope,
        origin=source_info.origin,
        base_dir=source_info.base_dir
        if source_info.base_dir is not None
        else source_info.path.parent,
    )


__all__ = [
    "command_source_info_from_extension",
    "list_extension_command_descriptors",
]
