"""Private value objects and precedence constants for resource loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
    ThemeDescriptor,
)

_IGNORE_FILE_NAMES = (".gitignore", ".ignore", ".fdignore")

DEFAULT_CONTEXT_FILE_NAMES = ("AGENTS.md", "AGENTS.MD")

_SOURCE_SCOPE: dict[ResourceSourceKind, ResourceSourceScope] = {
    "built_in": "builtin",
    "external_package": "package",
    "project_local": "project",
    "user_global": "user",
    "temporary": "temporary",
}

_SOURCE_LABEL = {
    "built_in": "package_resource",
    "external_package": "package_resource",
    "project_local": "filesystem",
    "user_global": "filesystem",
    "temporary": "filesystem",
}

DescriptorT = TypeVar(
    "DescriptorT",
    PromptFragmentDescriptor,
    SkillDescriptor,
    ExtensionDescriptor,
    ThemeDescriptor,
)


@dataclass(frozen=True)
class _SourceDiscovery:
    prompts: list[PromptFragmentDescriptor] = field(default_factory=list)
    skills: list[SkillDescriptor] = field(default_factory=list)
    extensions: list[ExtensionDescriptor] = field(default_factory=list)
    themes: list[ThemeDescriptor] = field(default_factory=list)
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)
