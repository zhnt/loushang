"""Immutable contracts for the product-neutral multi-agent control plane."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias

AgentStatus = Literal[
    "idle",
    "running",
    "completed",
    "failed",
    "interrupted",
    "closed",
]
TerminalStatus = Literal["completed", "failed", "interrupted"]
AgentFactKind = Literal[
    "spawned",
    "status_changed",
    "workspace",
    "progress",
    "terminal",
    "closed",
]
AgentMessageKind = Literal["follow_up", "steering"]
AgentInputKind = Literal["follow_up", "steering", "mailbox"]
TransitionReason = Literal[
    "applied",
    "duplicate",
    "stale_ref",
    "stale_round",
    "closed",
    "invalid_state",
]

_AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_AGENT_STATUSES = frozenset(
    {"idle", "running", "completed", "failed", "interrupted", "closed"}
)
_TERMINAL_STATUSES = frozenset({"completed", "failed", "interrupted"})


def require_agent_name(value: str, *, field_name: str = "agent name") -> str:
    """Validate one stable path/type segment."""

    if not isinstance(value, str) or not _AGENT_NAME.fullmatch(value):
        raise ValueError(
            f"{field_name} must contain only lowercase letters, digits, "
            "underscores, or hyphens"
        )
    return value


@dataclass(frozen=True, order=True, slots=True)
class AgentPath:
    """Canonical logical address within one root-owned agent tree."""

    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        parts = tuple(self.parts)
        if not parts or parts[0] != "root":
            raise ValueError("agent path must start at /root")
        for part in parts:
            require_agent_name(part, field_name="agent path segment")
        object.__setattr__(self, "parts", parts)

    @classmethod
    def root(cls) -> AgentPath:
        return cls(("root",))

    @classmethod
    def parse(cls, value: str) -> AgentPath:
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError("canonical agent path must start with '/'")
        if value != "/root" and (value.endswith("/") or "//" in value):
            raise ValueError("canonical agent path must not contain empty segments")
        parts = tuple(value[1:].split("/"))
        return cls(parts)

    @property
    def name(self) -> str:
        return self.parts[-1]

    @property
    def depth(self) -> int:
        return len(self.parts) - 1

    @property
    def parent(self) -> AgentPath | None:
        if self.depth == 0:
            return None
        return AgentPath(self.parts[:-1])

    def child(self, name: str) -> AgentPath:
        return AgentPath((*self.parts, require_agent_name(name)))

    def is_descendant_of(self, other: AgentPath, *, include_self: bool = False) -> bool:
        if len(self.parts) < len(other.parts):
            return False
        if self.parts[: len(other.parts)] != other.parts:
            return False
        return include_self or len(self.parts) > len(other.parts)

    def __str__(self) -> str:
        return "/" + "/".join(self.parts)


@dataclass(frozen=True, order=True, slots=True)
class AgentRef:
    """Incarnation-safe reference to one use of an AgentPath."""

    path: AgentPath
    incarnation: int

    def __post_init__(self) -> None:
        if type(self.incarnation) is not int or self.incarnation < 1:
            raise ValueError("agent incarnation must be a positive integer")

    def __str__(self) -> str:
        return f"{self.path}@{self.incarnation}"


@dataclass(frozen=True, slots=True)
class HostCaller:
    """Product control-plane caller; still audited through authority policy."""


@dataclass(frozen=True, slots=True)
class AgentCaller:
    """Caller identity for a live agent incarnation."""

    ref: AgentRef


ControlCaller: TypeAlias = HostCaller | AgentCaller


@dataclass(frozen=True, slots=True)
class AgentTypeSpec:
    """Product-admitted policy envelope for one technical agent type."""

    name: str
    default_model: str | None = None
    allowed_tools: tuple[str, ...] = ()
    can_spawn: bool = False
    maximum_children: int = 1
    workspace_mode: Literal["inherit", "isolated"] = "inherit"

    def __post_init__(self) -> None:
        require_agent_name(self.name, field_name="agent type")
        if self.default_model is not None and not self.default_model:
            raise ValueError("default_model must be non-empty when provided")
        tools = tuple(self.allowed_tools)
        if any(not isinstance(tool, str) or not tool for tool in tools):
            raise ValueError("allowed_tools must contain non-empty strings")
        if len(set(tools)) != len(tools):
            raise ValueError("allowed_tools must not contain duplicates")
        if type(self.can_spawn) is not bool:
            raise TypeError("can_spawn must be a bool")
        if type(self.maximum_children) is not int or self.maximum_children < 1:
            raise ValueError("maximum_children must be a positive integer")
        if self.workspace_mode not in {"inherit", "isolated"}:
            raise ValueError(f"invalid workspace_mode: {self.workspace_mode}")
        object.__setattr__(self, "allowed_tools", tools)


class AgentTypeRegistry:
    """Immutable Product-provided type catalog."""

    def __init__(self, specs: Iterable[AgentTypeSpec] = ()) -> None:
        values: dict[str, AgentTypeSpec] = {}
        for spec in specs:
            if not isinstance(spec, AgentTypeSpec):
                raise TypeError("agent type registry values must be AgentTypeSpec")
            if spec.name in values:
                raise ValueError(f"duplicate agent type: {spec.name}")
            values[spec.name] = spec
        self._specs: Mapping[str, AgentTypeSpec] = MappingProxyType(values)

    def resolve(self, name: str) -> AgentTypeSpec | None:
        return self._specs.get(name)

    def values(self) -> tuple[AgentTypeSpec, ...]:
        return tuple(self._specs[name] for name in sorted(self._specs))


@dataclass(frozen=True, slots=True)
class AgentUsage:
    """Usage accounting that matches cumulative provider input semantics."""

    latest_input_tokens: int = 0
    cumulative_output_tokens: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.latest_input_tokens) is not int
            or type(self.cumulative_output_tokens) is not int
            or self.latest_input_tokens < 0
            or self.cumulative_output_tokens < 0
        ):
            raise ValueError("agent token usage must be non-negative")


@dataclass(frozen=True, slots=True)
class AgentProgress:
    """Progress fields whose summary and activity update independently."""

    usage: AgentUsage = field(default_factory=AgentUsage)
    tool_uses: int = 0
    recent_activity: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        if type(self.tool_uses) is not int or self.tool_uses < 0:
            raise ValueError("agent tool_uses must be non-negative")
        if self.recent_activity is not None and not isinstance(
            self.recent_activity, str
        ):
            raise TypeError("agent recent_activity must be a string or None")
        if self.summary is not None and not isinstance(self.summary, str):
            raise TypeError("agent summary must be a string or None")


@dataclass(frozen=True, slots=True)
class AgentRecord:
    """Authoritative immutable snapshot of one registry entry."""

    ref: AgentRef
    parent_ref: AgentRef | None
    agent_type: str
    status: AgentStatus
    round_id: int
    created_at: datetime
    updated_at: datetime
    progress: AgentProgress = field(default_factory=AgentProgress)
    workspace_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    change_set_ref: str | None = None

    def __post_init__(self) -> None:
        require_agent_name(self.agent_type, field_name="agent type")
        if self.status not in _AGENT_STATUSES:
            raise ValueError(f"invalid agent status: {self.status}")
        if self.round_id < 0:
            raise ValueError("agent round_id must be non-negative")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("agent timestamps must be timezone-aware")
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))

    @property
    def path(self) -> AgentPath:
        return self.ref.path

    @property
    def is_open(self) -> bool:
        return self.status != "closed"


@dataclass(frozen=True, slots=True)
class TerminalPayload:
    status: TerminalStatus
    final_message: str
    usage: AgentUsage
    duration_ms: int
    tool_uses: int

    def __post_init__(self) -> None:
        if self.status not in _TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {self.status}")
        if type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ValueError("terminal duration_ms must be non-negative")
        if type(self.tool_uses) is not int or self.tool_uses < 0:
            raise ValueError("terminal tool_uses must be non-negative")


@dataclass(frozen=True, slots=True)
class AgentFact:
    """Ordered technical fact; consumers must not mutate control state."""

    sequence: int
    kind: AgentFactKind
    ref: AgentRef
    parent_ref: AgentRef | None
    agent_type: str
    status: AgentStatus
    round_id: int
    at: datetime
    progress: AgentProgress | None = None
    terminal: TerminalPayload | None = None
    workspace_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    change_set_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("agent fact sequence must be positive")
        if self.at.tzinfo is None:
            raise ValueError("agent fact timestamp must be timezone-aware")
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))


@dataclass(frozen=True, slots=True)
class AgentCompletionNotice:
    """Exactly-once terminal payload, separate from ordinary messages."""

    notice_id: str
    sender_ref: AgentRef
    recipient_ref: AgentRef
    round_id: int
    terminal: TerminalPayload
    summary: str | None = None
    workspace_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    change_set_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AgentInputMessage:
    """One authorized message route; a session adapter performs delivery."""

    message_id: str
    sender: ControlCaller
    recipient_ref: AgentRef
    kind: AgentInputKind
    text: str
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("agent message text must be non-empty")
        if self.kind not in {"follow_up", "steering", "mailbox"}:
            raise ValueError(
                "agent input kind must be follow_up, steering, or mailbox"
            )


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    """Pure routing result without queue mutation or runtime wake-up."""

    message: AgentInputMessage
    target_status: AgentStatus
    requires_wake: bool


@dataclass(frozen=True, slots=True)
class ControlLimits:
    max_open_agents: int = 6
    max_spawn_depth: int = 3

    def __post_init__(self) -> None:
        if type(self.max_open_agents) is not int or self.max_open_agents < 1:
            raise ValueError("max_open_agents must be positive")
        if type(self.max_spawn_depth) is not int or self.max_spawn_depth < 0:
            raise ValueError("max_spawn_depth must be non-negative")


@dataclass(frozen=True, slots=True)
class AgentTransition:
    """Race-safe lifecycle result for callbacks owned by a future run handle."""

    applied: bool
    reason: TransitionReason
    record: AgentRecord | None
    notice: AgentCompletionNotice | None = None


class AgentAuthorityPolicy(Protocol):
    def allows_control(self, caller: ControlCaller, target: AgentRecord) -> bool: ...

    def allows_message(self, caller: ControlCaller, target: AgentRecord) -> bool: ...


class MultiAgentError(ValueError):
    """Stable structured error raised inside the pure control plane."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = MappingProxyType(dict(details or {}))
        self.tool_result_details = MappingProxyType(
            {"code": code, **self.details}
        )


__all__ = [
    "AgentAuthorityPolicy",
    "AgentCaller",
    "AgentCompletionNotice",
    "AgentFact",
    "AgentFactKind",
    "AgentInputKind",
    "AgentInputMessage",
    "AgentMessageKind",
    "AgentPath",
    "AgentProgress",
    "AgentRecord",
    "AgentRef",
    "AgentStatus",
    "AgentTransition",
    "AgentTypeRegistry",
    "AgentTypeSpec",
    "AgentUsage",
    "ControlCaller",
    "ControlLimits",
    "DeliveryIntent",
    "HostCaller",
    "MultiAgentError",
    "TerminalPayload",
    "TerminalStatus",
    "TransitionReason",
    "require_agent_name",
]
