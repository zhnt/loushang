"""Private value objects and precedence constants for resource loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

import loushang.harness.resources._discovery_conventions as _conventions
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
    ThemeDescriptor,
)

DEFAULT_CONTEXT_FILE_NAMES = _conventions.DEFAULT_CONTEXT_FILE_NAMES
_IGNORE_FILE_NAMES = _conventions.IGNORE_FILE_NAMES
_SOURCE_LABEL = _conventions.SOURCE_LABEL
_SOURCE_SCOPE = _conventions.SOURCE_SCOPE

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


__all__ = [
    "DEFAULT_CONTEXT_FILE_NAMES",
    "DescriptorT",
    "_IGNORE_FILE_NAMES",
    "_SOURCE_LABEL",
    "_SOURCE_SCOPE",
    "_SourceDiscovery",
]
