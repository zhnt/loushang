"""Source-neutral Resource discovery conventions shared during migration."""

from __future__ import annotations

from loushang.harness.resources.types import (
    ResourceSourceKind,
    ResourceSourceScope,
)

IGNORE_FILE_NAMES = (".gitignore", ".ignore", ".fdignore")
DEFAULT_CONTEXT_FILE_NAMES = ("AGENTS.md", "AGENTS.MD")

SOURCE_SCOPE: dict[ResourceSourceKind, ResourceSourceScope] = {
    "built_in": "builtin",
    "external_package": "package",
    "project_local": "project",
    "user_global": "user",
    "temporary": "temporary",
}

SOURCE_LABEL: dict[ResourceSourceKind, str] = {
    "built_in": "package_resource",
    "external_package": "package_resource",
    "project_local": "filesystem",
    "user_global": "filesystem",
    "temporary": "filesystem",
}

__all__ = [
    "DEFAULT_CONTEXT_FILE_NAMES",
    "IGNORE_FILE_NAMES",
    "SOURCE_LABEL",
    "SOURCE_SCOPE",
]
