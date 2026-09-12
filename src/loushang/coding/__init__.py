"""Public Coding entrypoints without eager runtime imports."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING
from typing import Any as _Any

# Preserve the public import order and resolve each symbol from its original owner.
_EXPORTS = {
    "AgentSessionServices": "loushang.coding.bootstrap",
    "AgentSessionRuntime": "loushang.coding.runtime",
    "BootstrapServices": "loushang.coding.bootstrap",
    "CODING_BUILTIN_TOOL_NAMES": "loushang.coding.tool_pack",
    "CODING_BUILTIN_TOOL_PACK": "loushang.coding.tool_pack",
    "CODING_ARCH_CAPABILITY": "loushang.coding.capabilities",
    "CODING_ARCH_TOOL_PACK": "loushang.coding.arch",
    "CODING_LSP_CAPABILITY": "loushang.coding.capabilities",
    "CODING_TOOL_NAMES": "loushang.coding.tool_pack",
    "CapabilityMountMode": "loushang.harness.config.agent",
    "CodingCompositionSetId": "loushang.coding.composition_sets",
    "CodingCompositionSetPlan": "loushang.coding.composition_sets",
    "CompactionDecision": "loushang.coding.session",
    "ContextUsage": "loushang.coding.session",
    "ContextUsageSnapshot": "loushang.coding.session",
    "ControlConfig": "loushang.harness.config.agent",
    "CreateAgentSessionResult": "loushang.coding.bootstrap",
    "CwdBoundServicesAudit": "loushang.coding.bootstrap",
    "CwdBoundServicesAuditIssue": "loushang.coding.bootstrap",
    "DefaultResourceLoader": "loushang.coding.resource_runtime",
    "ExtensionFlagValues": "loushang.coding.bootstrap",
    "HeadlessApprovalMode": "loushang.harness.config.agent",
    "INSPECT_IMPORT_GRAPH_TOOL_NAME": "loushang.coding.arch",
    "ImportGraphToolRuntime": "loushang.coding.arch",
    "ModelSelection": "loushang.ai.model",
    "ToolSettings": "loushang.harness.config.agent",
    "TreeNavigationResult": "loushang.coding.session",
    "SessionManager": "loushang.coding.session_manager",
    "SdkSurfaceCompatibilityReport": "loushang.coding.sdk_surface",
    "SdkSurfaceSnapshot": "loushang.coding.sdk_surface",
    "SettingsManager": "loushang.harness.config.agent",
    "SessionStats": "loushang.coding.session",
    "TokenUsageTotals": "loushang.coding.session",
    "assemble_system_prompt": "loushang.coding.prompt",
    "create_agent_session": "loushang.coding.bootstrap",
    "create_agent_session_from_services": "loushang.coding.bootstrap",
    "create_agent_session_result": "loushang.coding.bootstrap",
    "create_agent_session_services": "loushang.coding.bootstrap",
    "create_coding_tool_definition": "loushang.coding.tool_pack",
    "create_coding_tool_definitions": "loushang.coding.tool_pack",
    "create_coding_tools": "loushang.coding.tool_pack",
    "create_inspect_import_graph_tool_definition": "loushang.coding.arch",
    "create_agent_session_runtime": "loushang.coding.bootstrap",
    "create_services": "loushang.coding.bootstrap",
    "check_sdk_surface_compatibility": "loushang.coding.sdk_surface",
    "get_sdk_surface_snapshot": "loushang.coding.sdk_surface",
    "register_coding_arch_tools": "loushang.coding.arch",
    "resolve_coding_composition_set": "loushang.coding.composition_sets",
}
_ALIASES = {"DefaultResourceLoader": "CodingResourceLoader"}

if TYPE_CHECKING:
    from loushang.ai.model import ModelSelection
    from loushang.coding.arch import (
        CODING_ARCH_TOOL_PACK,
        INSPECT_IMPORT_GRAPH_TOOL_NAME,
        ImportGraphToolRuntime,
        create_inspect_import_graph_tool_definition,
        register_coding_arch_tools,
    )
    from loushang.coding.bootstrap import (
        AgentSessionServices,
        BootstrapServices,
        CreateAgentSessionResult,
        CwdBoundServicesAudit,
        CwdBoundServicesAuditIssue,
        ExtensionFlagValues,
        create_agent_session,
        create_agent_session_from_services,
        create_agent_session_result,
        create_agent_session_runtime,
        create_agent_session_services,
        create_services,
    )
    from loushang.coding.capabilities import (
        CODING_ARCH_CAPABILITY,
        CODING_LSP_CAPABILITY,
    )
    from loushang.coding.composition_sets import (
        CodingCompositionSetId,
        CodingCompositionSetPlan,
        resolve_coding_composition_set,
    )
    from loushang.coding.prompt import assemble_system_prompt
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.sdk_surface import (
        SdkSurfaceCompatibilityReport,
        SdkSurfaceSnapshot,
        check_sdk_surface_compatibility,
        get_sdk_surface_snapshot,
    )
    from loushang.coding.session import (
        CompactionDecision,
        ContextUsage,
        ContextUsageSnapshot,
        SessionStats,
        TokenUsageTotals,
        TreeNavigationResult,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.coding.tool_pack import (
        CODING_BUILTIN_TOOL_NAMES,
        CODING_BUILTIN_TOOL_PACK,
        CODING_TOOL_NAMES,
        create_coding_tool_definition,
        create_coding_tool_definitions,
        create_coding_tools,
    )
    from loushang.harness.config.agent import (
        CapabilityMountMode,
        ControlConfig,
        HeadlessApprovalMode,
        SettingsManager,
        ToolSettings,
    )
else:
    del TYPE_CHECKING

    def __getattr__(name: str) -> _Any:
        """Resolve an original owner object and cache only successful lookups."""
        try:
            module_name = _EXPORTS[name]
        except KeyError as exc:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            ) from exc
        value = getattr(_import_module(module_name), _ALIASES.get(name, name))
        globals()[name] = value
        return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


__all__ = [
    "AgentSessionServices",
    "AgentSessionRuntime",
    "BootstrapServices",
    "CODING_BUILTIN_TOOL_NAMES",
    "CODING_BUILTIN_TOOL_PACK",
    "CODING_ARCH_CAPABILITY",
    "CODING_ARCH_TOOL_PACK",
    "CODING_LSP_CAPABILITY",
    "CODING_TOOL_NAMES",
    "CapabilityMountMode",
    "CodingCompositionSetId",
    "CodingCompositionSetPlan",
    "CompactionDecision",
    "ContextUsage",
    "ContextUsageSnapshot",
    "ControlConfig",
    "CreateAgentSessionResult",
    "CwdBoundServicesAudit",
    "CwdBoundServicesAuditIssue",
    "DefaultResourceLoader",
    "ExtensionFlagValues",
    "HeadlessApprovalMode",
    "INSPECT_IMPORT_GRAPH_TOOL_NAME",
    "ImportGraphToolRuntime",
    "ModelSelection",
    "ToolSettings",
    "TreeNavigationResult",
    "SessionManager",
    "SdkSurfaceCompatibilityReport",
    "SdkSurfaceSnapshot",
    "SettingsManager",
    "SessionStats",
    "TokenUsageTotals",
    "assemble_system_prompt",
    "create_agent_session",
    "create_agent_session_from_services",
    "create_agent_session_result",
    "create_agent_session_services",
    "create_coding_tool_definition",
    "create_coding_tool_definitions",
    "create_coding_tools",
    "create_inspect_import_graph_tool_definition",
    "create_agent_session_runtime",
    "create_services",
    "check_sdk_surface_compatibility",
    "get_sdk_surface_snapshot",
    "register_coding_arch_tools",
    "resolve_coding_composition_set",
]
