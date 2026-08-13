from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from loushang.agent import ThinkingLevel
from loushang.ai.model import ModelSelection
from loushang.harness.permissions import PermissionProfileId, permission_profile
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.sandbox import SandboxSettings

QueueMode = Literal["all", "one-at-a-time"]
DoubleEscapeAction = Literal["fork", "tree", "none"]
TreeFilterMode = Literal["default", "no-tools", "user-only", "labeled-only", "all"]
ExternalToolPolicy = Literal["never", "auto", "required"]
CapabilityMountMode = Literal["disabled", "on_demand", "always"]
HeadlessApprovalMode = Literal["allow", "deny"]
StatusLineAutoValue = Literal["auto", "true", "false"]
StatusLineSeparator = Literal["pipe", "dot"]
StatusLineStyle = Literal["codex-like", "muted", "plain"]
KeybindingValue = str | tuple[str, ...] | None


class ThinkingBudgetMap(TypedDict, total=False):
    minimal: int
    low: int
    medium: int
    high: int


@dataclass(frozen=True)
class CompactionSettings:
    """Product overrides for the capability-selected compaction policy.

    ``None`` means that the corresponding value is inherited from the active
    runtime capability.  Concrete values remain compatible with existing
    settings files and allow each Product or session to override fields
    independently.
    """

    enabled: bool | None = None
    compact_percent: float | None = None
    reserve_tokens: int | None = None
    keep_recent_tokens: int | None = None


@dataclass(frozen=True)
class BranchSummarySettings:
    enabled: bool = True
    reserve_tokens: int = 8_192
    skip_prompt: bool = False


@dataclass(frozen=True)
class RetrySettings:
    enabled: bool = True
    max_retries: int = 2
    base_delay_ms: int = 250
    provider_timeout_ms: int | None = None
    provider_max_retries: int | None = None
    provider_max_retry_delay_ms: int = 60_000


@dataclass(frozen=True)
class ImageSettings:
    auto_resize: bool = True
    block_images: bool = False


@dataclass(frozen=True)
class TerminalSettings:
    show_images: bool = True
    image_width_cells: int = 60
    clear_on_shrink: bool = False
    show_terminal_progress: bool = False


@dataclass(frozen=True)
class MarkdownSettings:
    code_block_indent: str = "  "


@dataclass(frozen=True)
class WarningSettings:
    anthropic_extra_usage: bool = True


@dataclass(frozen=True)
class MethodSettings:
    mode: str = "explicit"
    selected_method: str | None = None


@dataclass(frozen=True)
class ToolSettings:
    external_tool_policy: ExternalToolPolicy = "auto"
    blocked_tools: tuple[str, ...] = ()
    ask_tools: tuple[str, ...] = ()
    blocked_capabilities: tuple[str, ...] = ()
    ask_capabilities: tuple[str, ...] = ()
    blocked_substrings: tuple[str, ...] = ()
    ask_substrings: tuple[str, ...] = ()
    blocked_path_substrings: tuple[str, ...] = ()
    ask_path_substrings: tuple[str, ...] = ()
    approval_mode: HeadlessApprovalMode | None = None
    approval_reason: str | None = None


@dataclass(frozen=True)
class PermissionSettings:
    profile: PermissionProfileId = "standard"

    def __post_init__(self) -> None:
        permission_profile(self.profile)


@dataclass(frozen=True)
class StatusLineControlSettings:
    enabled: bool = True
    model: bool = True
    workspace: bool = True
    branch: bool = True
    session: bool = True
    permissions: bool = True
    runtime: bool = True
    queue: StatusLineAutoValue = "auto"
    message: StatusLineAutoValue = "auto"
    separator: StatusLineSeparator = "pipe"
    style: StatusLineStyle = "codex-like"


@dataclass(frozen=True)
class ControlConfig:
    default_model: ModelSelection | None = None
    thinking_level: ThinkingLevel = "off"
    steering_mode: QueueMode = "one-at-a-time"
    follow_up_mode: QueueMode = "one-at-a-time"
    theme: str | None = None
    system_prompt: str = ""
    hide_thinking_block: bool = False
    shell_path: str | None = None
    quiet_startup: bool = False
    shell_command_prefix: str | None = None
    npm_command: tuple[str, ...] | None = None
    collapse_changelog: bool = False
    enable_install_telemetry: bool = True
    enable_skill_commands: bool = True
    enabled_models: tuple[str, ...] | None = None
    double_escape_action: DoubleEscapeAction = "tree"
    tree_filter_mode: TreeFilterMode = "default"
    show_hardware_cursor: bool = False
    editor_padding_x: int = 0
    autocomplete_max_visible: int = 5
    keybindings: dict[str, KeybindingValue] = field(default_factory=dict)
    capabilities: dict[str, CapabilityMountMode] = field(default_factory=dict)
    thinking_budgets: ThinkingBudgetMap | None = None
    compaction: CompactionSettings = field(default_factory=CompactionSettings)
    branch_summary: BranchSummarySettings = field(default_factory=BranchSummarySettings)
    retry: RetrySettings = field(default_factory=RetrySettings)
    images: ImageSettings = field(default_factory=ImageSettings)
    terminal: TerminalSettings = field(default_factory=TerminalSettings)
    markdown: MarkdownSettings = field(default_factory=MarkdownSettings)
    warnings: WarningSettings = field(default_factory=WarningSettings)
    method: MethodSettings = field(default_factory=MethodSettings)
    permissions: PermissionSettings = field(default_factory=PermissionSettings)
    tools: ToolSettings = field(default_factory=ToolSettings)
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    statusline: StatusLineControlSettings = field(
        default_factory=StatusLineControlSettings
    )
    session_dir: str | None = None
    resource_roots: tuple[str, ...] = ()
    package_roots: tuple[str, ...] = ()
    package_sources: tuple[PackageSourceConfig, ...] = ()
    plugin_sources: tuple[str, ...] = ()
    disabled_skills: tuple[str, ...] = ()
    disabled_plugins: tuple[str, ...] = ()


__all__ = [
    "BranchSummarySettings",
    "CompactionSettings",
    "CapabilityMountMode",
    "ControlConfig",
    "DoubleEscapeAction",
    "ExternalToolPolicy",
    "HeadlessApprovalMode",
    "ImageSettings",
    "KeybindingValue",
    "MarkdownSettings",
    "MethodSettings",
    "PermissionSettings",
    "QueueMode",
    "RetrySettings",
    "SandboxSettings",
    "StatusLineAutoValue",
    "StatusLineControlSettings",
    "StatusLineSeparator",
    "StatusLineStyle",
    "TerminalSettings",
    "ThinkingBudgetMap",
    "ToolSettings",
    "TreeFilterMode",
    "WarningSettings",
]
