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

__all__ = [
    "AGENT_DELEGATE_TOOL_NAME",
    "AGENT_DELEGATE_TOOL_PACK",
    "AgentDelegateToolPack",
    "AgentInvocationAdapter",
    "AgentInvocationRequest",
    "AgentInvocationResult",
    "FilesystemActionAdapter",
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
    "authorized_tool",
    "direct_tool",
    "tool",
]
