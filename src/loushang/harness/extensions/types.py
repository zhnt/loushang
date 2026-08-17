from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loushang.harness.contributions import ExtensionSurfaceDescriptor
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.routing_types import (
    ExtensionHandler,
    RegisteredExtensionHandler,
)
from loushang.harness.resources.source import SourceInfo
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
    ThemeDescriptor,
)
from loushang.harness.tools.core import ToolDefinition

InputSource = Literal["interactive", "rpc", "extension"]


@dataclass
class InputEvent:
    text: str
    images: list[object] | None = None
    source: InputSource = "interactive"
    type: Literal["input"] = "input"


@dataclass
class InputEventResult:
    action: Literal["continue", "transform", "handled"]
    text: str | None = None
    images: list[object] | None = None


@dataclass(frozen=True)
class BeforeAgentStartResult:
    system_prompt_append: str = ""
    system_prompt: str | None = None
    extra_messages: list[object] = field(default_factory=list)
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)
    block: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class ContextResult:
    messages: list[object] | None = None
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCallDecision:
    block: bool = False
    reason: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResultDecision:
    result: object | None = None
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)


@dataclass(frozen=True)
class ExtensionPolicyDecision:
    enabled: bool = True
    permission_level: Literal["safe", "standard", "powerful"] = "safe"
    capabilities: tuple[str, ...] = ()
    allow_managed_hooks_only: bool = False

    @property
    def active(self) -> bool:
        return self.enabled


@dataclass(frozen=True)
class RegisteredControlContribution:
    descriptor: ExtensionSurfaceDescriptor
    value: object

    def __post_init__(self) -> None:
        if self.descriptor.type not in {"policy", "approval"}:
            raise ValueError(
                "control contributions must use policy or approval surfaces"
            )


@dataclass(frozen=True)
class RegisteredRuntimeCapabilityReplacement:
    """One Extension-declared candidate for an explicit runtime slot."""

    slot: str
    name: str
    create: Callable[[], object]
    dispose: Callable[[object], None] | None = None
    implementation_version: int = 1
    priority: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.slot, str) or not self.slot.strip():
            raise ValueError("runtime capability replacement slot must not be empty")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("runtime capability replacement name must not be empty")
        if not callable(self.create):
            raise TypeError("runtime capability replacement create must be callable")
        if self.dispose is not None and not callable(self.dispose):
            raise TypeError("runtime capability replacement dispose must be callable")
        if (
            isinstance(self.implementation_version, bool)
            or not isinstance(self.implementation_version, int)
            or self.implementation_version < 1
        ):
            raise ValueError(
                "runtime capability replacement implementation_version must be "
                "a positive integer"
            )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError(
                "runtime capability replacement priority must be an integer"
            )


@dataclass(frozen=True, kw_only=True)
class RegisteredCommand:
    name: str
    handler: Callable[[str, object], Awaitable[None]]
    description: str | None = None
    get_argument_completions: (
        Callable[[str], list[object] | Awaitable[list[object] | None] | None] | None
    ) = None

    def __post_init__(self) -> None:
        if not _is_async_callable(self.handler):
            raise TypeError("RegisteredCommand.handler must be an async callable.")


@dataclass(frozen=True, kw_only=True)
class ResolvedCommand(RegisteredCommand):
    invocation_name: str
    source_info: SourceInfo[Path]
    extension_name: str


@dataclass(frozen=True)
class RegisteredFlag:
    name: str
    type: Literal["boolean", "string"]
    description: str | None = None
    default: bool | str | None = None


@dataclass(frozen=True, kw_only=True)
class ResolvedFlag(RegisteredFlag):
    source_info: SourceInfo[Path]
    extension_name: str


@dataclass(frozen=True)
class RegisteredShortcut:
    shortcut: str
    handler: Callable[[object], object | None]
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class ResolvedShortcut(RegisteredShortcut):
    source_info: SourceInfo[Path]
    extension_name: str


@dataclass(frozen=True)
class LoadedExtension:
    name: str
    source_path: Path
    entry_path: Path | None = None
    source: str = "filesystem"
    source_kind: ResourceSourceKind = "project_local"
    source_scope: ResourceSourceScope = "project"
    source_root: Path | None = None
    hooks: dict[str, list[ExtensionHandler]] = field(default_factory=dict)
    tool_definitions: list[ToolDefinition] = field(default_factory=list)
    commands: dict[str, RegisteredCommand] = field(default_factory=dict)
    flags: dict[str, RegisteredFlag] = field(default_factory=dict)
    shortcuts: dict[str, RegisteredShortcut] = field(default_factory=dict)
    message_renderers: dict[str, Callable[[object, object, object], object | None]] = (
        field(default_factory=dict)
    )
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    api: object | None = None
    manifest: object | None = None
    policy: ExtensionPolicyDecision | None = None
    contributions: list[ExtensionSurfaceDescriptor] = field(default_factory=list)
    handler_registrations: list[RegisteredExtensionHandler] = field(
        default_factory=list
    )
    control_contributions: list[RegisteredControlContribution] = field(
        default_factory=list
    )
    runtime_capability_replacements: list[RegisteredRuntimeCapabilityReplacement] = (
        field(default_factory=list)
    )

    def __post_init__(self) -> None:
        if self.handler_registrations and not self.hooks:
            projected: dict[str, list[ExtensionHandler]] = {}
            for registration in self.handler_registrations:
                projected.setdefault(registration.event_name, []).append(
                    registration.handler
                )
            object.__setattr__(self, "hooks", projected)

    @property
    def surfaces(self) -> list[ExtensionSurfaceDescriptor]:
        return list(self.contributions)


def extension_is_active(extension: LoadedExtension) -> bool:
    """Return whether an extension may contribute executable capabilities."""

    return extension.policy is None or extension.policy.active


@dataclass(frozen=True)
class ExtensionResourceContribution:
    prompt_descriptors: list[PromptFragmentDescriptor] = field(default_factory=list)
    skills: list[SkillDescriptor] = field(default_factory=list)
    extensions: list[ExtensionDescriptor] = field(default_factory=list)
    prompts: list[PromptFragmentDescriptor] = field(default_factory=list)
    themes: list[ThemeDescriptor] = field(default_factory=list)
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)


def _is_async_callable(value: object) -> bool:
    if inspect.iscoroutinefunction(value):
        return True
    call = getattr(value, "__call__", None)
    return inspect.iscoroutinefunction(call)


__all__ = [
    "BeforeAgentStartResult",
    "ContextResult",
    "ExtensionHandler",
    "ExtensionPolicyDecision",
    "ExtensionResourceContribution",
    "extension_is_active",
    "InputEvent",
    "InputEventResult",
    "InputSource",
    "LoadedExtension",
    "RegisteredCommand",
    "RegisteredControlContribution",
    "RegisteredRuntimeCapabilityReplacement",
    "RegisteredExtensionHandler",
    "RegisteredFlag",
    "RegisteredShortcut",
    "ResolvedCommand",
    "ResolvedFlag",
    "ResolvedShortcut",
    "ToolCallDecision",
    "ToolResultDecision",
]
