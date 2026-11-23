"""Public Coding entrypoints without eager runtime imports."""

import sys as _sys
from contextlib import suppress as _suppress
from importlib import import_module as _import_module
from typing import Any as _Any


class _DeferredComponentImports:
    _coding_import_bootstrap = True

    def find_spec(self, fullname: str, path: _Any = None, target: _Any = None) -> _Any:
        if not fullname.startswith("loushang.coding.") or fullname in {
            "loushang.coding._component_imports",
            "loushang.coding._compat",
            "loushang.coding._compat.root_names",
            "loushang.coding.cli",
            "loushang.coding.cli.__main__",
            "loushang.coding.package",
            "loushang.coding.package._legacy_names",
            "loushang.coding.plugin_manager",
            "loushang.coding.plugin_manager._legacy_names",
        }:
            return None
        owner = _import_module("loushang.coding._component_imports").install()
        with _suppress(ValueError):
            _sys.meta_path.remove(self)
        return owner.find_spec(fullname, path, target)


_sys.meta_path.insert(0, _DeferredComponentImports())

# Preserve the public import order and resolve each symbol from its original owner.
_EXPORTS = {
    "AgentSessionServices": 'loushang.coding.composition.bootstrap',
    "AgentSessionRuntime": "loushang.coding.runtime",
    "BootstrapServices": 'loushang.coding.composition.bootstrap',
    "CODING_BUILTIN_TOOL_NAMES": 'loushang.coding.resources.tool_pack',
    "CODING_BUILTIN_TOOL_PACK": 'loushang.coding.resources.tool_pack',
    "CODING_ARCH_CAPABILITY": 'loushang.coding.composition.capabilities',
    "CODING_ARCH_TOOL_PACK": "loushang.coding.arch",
    "CODING_LSP_CAPABILITY": 'loushang.coding.composition.capabilities',
    "CODING_TOOL_NAMES": 'loushang.coding.resources.tool_pack',
    "CapabilityMountMode": "loushang.harness.config.agent",
    "CodingCompositionSetId": 'loushang.coding.composition.sets',
    "CodingCompositionSetPlan": 'loushang.coding.composition.sets',
    "CompactionDecision": "loushang.coding.session",
    "ContextUsage": "loushang.coding.session",
    "ContextUsageSnapshot": "loushang.coding.session",
    "ControlConfig": "loushang.harness.config.agent",
    "CreateAgentSessionResult": 'loushang.coding.composition.bootstrap',
    "CwdBoundServicesAudit": 'loushang.coding.composition.bootstrap',
    "CwdBoundServicesAuditIssue": 'loushang.coding.composition.bootstrap',
    "DefaultResourceLoader": 'loushang.coding.resources.runtime',
    "ExtensionFlagValues": 'loushang.coding.composition.bootstrap',
    "HeadlessApprovalMode": "loushang.harness.config.agent",
    "INSPECT_IMPORT_GRAPH_TOOL_NAME": "loushang.coding.arch",
    "ImportGraphToolRuntime": "loushang.coding.arch",
    "ModelSelection": "loushang.ai.model",
    "ToolSettings": "loushang.harness.config.agent",
    "TreeNavigationResult": "loushang.coding.session",
    "SessionManager": 'loushang.coding.session.manager',
    "SdkSurfaceCompatibilityReport": "loushang.coding.sdk_surface",
    "SdkSurfaceSnapshot": "loushang.coding.sdk_surface",
    "SettingsManager": "loushang.harness.config.agent",
    "SessionStats": "loushang.coding.session",
    "TokenUsageTotals": "loushang.coding.session",
    "assemble_system_prompt": "loushang.coding.prompt",
    "create_agent_session": 'loushang.coding.composition.bootstrap',
    "create_agent_session_from_services": 'loushang.coding.composition.bootstrap',
    "create_agent_session_result": 'loushang.coding.composition.bootstrap',
    "create_agent_session_services": 'loushang.coding.composition.bootstrap',
    "create_coding_tool_definition": 'loushang.coding.resources.tool_pack',
    "create_coding_tool_definitions": 'loushang.coding.resources.tool_pack',
    "create_coding_tools": 'loushang.coding.resources.tool_pack',
    "create_inspect_import_graph_tool_definition": "loushang.coding.arch",
    "create_agent_session_runtime": 'loushang.coding.composition.bootstrap',
    "create_services": 'loushang.coding.composition.bootstrap',
    "check_sdk_surface_compatibility": "loushang.coding.sdk_surface",
    "get_sdk_surface_snapshot": "loushang.coding.sdk_surface",
    "register_coding_arch_tools": "loushang.coding.arch",
    "resolve_coding_composition_set": 'loushang.coding.composition.sets',
}
_ALIASES = {"DefaultResourceLoader": "CodingResourceLoader"}

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
