"""Product-neutral tool authoring and hosted-execution contracts."""

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
    "FilesystemActionAdapter",
    "NetworkActionAdapter",
    "ProcessActionAdapter",
    "PublicationActionAdapter",
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
