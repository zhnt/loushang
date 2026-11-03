"""Product-neutral tool authoring and hosted-execution contracts."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING
from typing import Any as _Any

AGENT_DELEGATE_TOOL_NAME = "delegate_agent"

_EXPORTS = {
    "AGENT_DELEGATE_TOOL_PACK": ".agent_delegate",
    "AgentDelegateToolPack": ".agent_delegate",
    "AgentInvocationAdapter": ".agent_delegate",
    "AgentInvocationRequest": ".agent_delegate",
    "AgentInvocationResult": ".agent_delegate",
    "PreparedAgentInvocation": ".agent_delegate",
    "FilesystemActionAdapter": ".authoring",
    "NetworkActionAdapter": ".authoring",
    "ProcessActionAdapter": ".authoring",
    "PublicationActionAdapter": ".authoring",
    "ToolContext": ".authoring",
    "ToolContextProvider": ".authoring",
    "ToolEventSink": ".authoring",
    "authorized_tool": ".authoring",
    "direct_tool": ".authoring",
    "tool": ".authoring",
    "ToolDefinition": ".core",
    "ToolRegistry": ".core",
    "ToolExecutionHost": ".execution",
    "ManagedSkillActionBinding": ".skill_actions",
    "ManagedSkillActionError": ".skill_actions",
    "ManagedSkillActionResult": ".skill_actions",
    "SkillRuntimeBinding": ".skill_actions",
    "execute_managed_skill_action": ".skill_actions",
}

if TYPE_CHECKING:
    from .agent_delegate import (
        AGENT_DELEGATE_TOOL_PACK,
        AgentDelegateToolPack,
        AgentInvocationAdapter,
        AgentInvocationRequest,
        AgentInvocationResult,
        PreparedAgentInvocation,
    )
    from .authoring import (
        FilesystemActionAdapter,
        NetworkActionAdapter,
        ProcessActionAdapter,
        PublicationActionAdapter,
        ToolContext,
        ToolContextProvider,
        ToolEventSink,
        authorized_tool,
        direct_tool,
        tool,
    )
    from .core import ToolDefinition, ToolRegistry
    from .execution import ToolExecutionHost
    from .skill_actions import (
        ManagedSkillActionBinding,
        ManagedSkillActionError,
        ManagedSkillActionResult,
        SkillRuntimeBinding,
        execute_managed_skill_action,
    )

__all__ = [
    "AGENT_DELEGATE_TOOL_NAME",
    "AGENT_DELEGATE_TOOL_PACK",
    "AgentDelegateToolPack",
    "AgentInvocationAdapter",
    "AgentInvocationRequest",
    "AgentInvocationResult",
    "FilesystemActionAdapter",
    "ManagedSkillActionBinding",
    "ManagedSkillActionError",
    "ManagedSkillActionResult",
    "NetworkActionAdapter",
    "ProcessActionAdapter",
    "PublicationActionAdapter",
    "PreparedAgentInvocation",
    "ToolContext",
    "ToolContextProvider",
    "ToolDefinition",
    "ToolEventSink",
    "ToolExecutionHost",
    "ToolRegistry",
    "SkillRuntimeBinding",
    "authorized_tool",
    "direct_tool",
    "execute_managed_skill_action",
    "tool",
]


def __getattr__(name: str) -> _Any:
    owner = _EXPORTS.get(name)
    if owner is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(owner, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
