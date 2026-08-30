"""Product-neutral tool authoring and hosted-execution contracts."""

from .agent_delegate import (
    AGENT_DELEGATE_TOOL_NAME,
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
