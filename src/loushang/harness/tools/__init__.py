"""Product-neutral tool authoring and hosted-execution contracts."""

from loushang.harness.resources.skill_actions import SkillActionCatalogSelection

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
    NativeSkillActionSource,
    PackageSkillActionSource,
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
    "NativeSkillActionSource",
    "NetworkActionAdapter",
    "ProcessActionAdapter",
    "PublicationActionAdapter",
    "PackageSkillActionSource",
    "PreparedAgentInvocation",
    "ToolContext",
    "ToolContextProvider",
    "ToolDefinition",
    "ToolEventSink",
    "ToolExecutionHost",
    "ToolRegistry",
    "SkillActionCatalogSelection",
    "SkillRuntimeBinding",
    "authorized_tool",
    "direct_tool",
    "execute_managed_skill_action",
    "tool",
]
