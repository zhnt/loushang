"""Typed in-process Agent integration for Harness extension runtimes.

The profile is optional: neutral ``harness.extensions`` modules do not import
it.  It composes extension input, Agent hooks, and lifecycle callbacks through
public Agent/AI values and injected ports; it is neither an event bus nor a
session runtime.
"""

from loushang.harness.extensions.agent.api import ExtensionAPI
from loushang.harness.extensions.agent.hooks import (
    BeforeAgentStartState,
    ContextHookEvent,
    ExtensionAgentHookPort,
    ExtensionAgentHookRuntime,
    ExtensionPromptHookDispatcher,
    ExtensionSessionHookDispatcher,
    ExtensionToolHookDispatcher,
    compose_after_tool_call_hooks,
    compose_before_tool_call_hooks,
)
from loushang.harness.extensions.agent.input import (
    ApplicationInputDeliveryPort,
    ExtensionApplicationInput,
    ExtensionInputRuntime,
    ExtensionUserInput,
    PreparedUserInputQueuePort,
)
from loushang.harness.extensions.agent.input_adapter import ExtensionInputAdapter
from loushang.harness.extensions.agent.lifecycle import (
    ExtensionAgentEventRuntime,
    ExtensionEventPort,
)
from loushang.harness.extensions.agent.loader import ExtensionLoader
from loushang.harness.extensions.agent.policy import (
    ExtensionPolicyDecision,
    policy_from_manifest,
)
from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.extensions.agent.runner import ExtensionRunner
from loushang.harness.extensions.context import (
    ExtensionCommandContext,
    ExtensionContext,
    ExtensionRuntimeBindings,
    ReplacedSessionContext,
    SessionActionDecision,
    SessionBeforeCompactEvent,
    SessionBeforeCompactResult,
    SessionBeforeForkEvent,
    SessionBeforeForkResult,
    SessionBeforeSwitchEvent,
    SessionBeforeTreeEvent,
    SessionBeforeTreeResult,
    SessionRefreshEvent,
    SessionShutdownEvent,
    SessionStartEvent,
)
from loushang.harness.extensions.contributions import (
    ContributionDescriptor,
    ContributionRegistry,
    DuplicateContributionKeyError,
    DuplicateExtensionSurfaceKeyError,
    ExtensionInventory,
    ExtensionSurfaceDescriptor,
    ExtensionSurfaceType,
    surfaces_from_loaded_extension,
)
from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS
from loushang.harness.extensions.manifest import (
    ExtensionDependencyDeclaration,
    ExtensionHookDeclaration,
    ExtensionManifest,
    ExtensionManifestParseResult,
    ExtensionPermissionDeclaration,
    parse_extension_manifest,
)
from loushang.harness.extensions.types import (
    BeforeAgentStartResult,
    ContextResult,
    ExtensionResourceContribution,
    InputEvent,
    InputEventResult,
    InputSource,
    LoadedExtension,
    RegisteredCommand,
    RegisteredFlag,
    RegisteredShortcut,
    ResolvedCommand,
    ResolvedFlag,
    ResolvedShortcut,
    ToolCallDecision,
    ToolResultDecision,
)
from loushang.harness.resources.source import SourceInfo

__all__ = [
    "ApplicationInputDeliveryPort",
    "BeforeAgentStartResult",
    "BeforeAgentStartState",
    "ContextResult",
    "ContextHookEvent",
    "ContributionDescriptor",
    "ContributionRegistry",
    "DuplicateContributionKeyError",
    "DuplicateExtensionSurfaceKeyError",
    "ExtensionAPI",
    "ExtensionAgentEventRuntime",
    "ExtensionAgentHookPort",
    "ExtensionAgentHookRuntime",
    "ExtensionApplicationInput",
    "ExtensionCommandContext",
    "ExtensionContext",
    "ExtensionDependencyDeclaration",
    "ExtensionEventPort",
    "ExtensionHookDeclaration",
    "ExtensionInputRuntime",
    "ExtensionInputAdapter",
    "ExtensionInventory",
    "ExtensionLoader",
    "ExtensionManifest",
    "ExtensionManifestParseResult",
    "ExtensionPermissionDeclaration",
    "ExtensionPolicyDecision",
    "ExtensionPromptHookDispatcher",
    "ExtensionResourceContribution",
    "ExtensionRunner",
    "ExtensionRuntimeBindings",
    "ExtensionSessionHookDispatcher",
    "ExtensionSurfaceDescriptor",
    "ExtensionSurfaceType",
    "ExtensionToolHookDispatcher",
    "ExtensionReplacementRuntime",
    "ExtensionUserInput",
    "InputEvent",
    "InputEventResult",
    "InputSource",
    "LoadedExtension",
    "PreparedUserInputQueuePort",
    "RegisteredCommand",
    "RegisteredFlag",
    "RegisteredShortcut",
    "ReplacedSessionContext",
    "ResolvedCommand",
    "ResolvedFlag",
    "ResolvedShortcut",
    "SessionActionDecision",
    "SessionBeforeCompactEvent",
    "SessionBeforeCompactResult",
    "SessionBeforeForkEvent",
    "SessionBeforeForkResult",
    "SessionBeforeSwitchEvent",
    "SessionBeforeTreeEvent",
    "SessionBeforeTreeResult",
    "SessionRefreshEvent",
    "SessionShutdownEvent",
    "SessionStartEvent",
    "SourceInfo",
    "ToolCallDecision",
    "ToolResultDecision",
    "VALID_EXTENSION_EVENTS",
    "compose_after_tool_call_hooks",
    "compose_before_tool_call_hooks",
    "parse_extension_manifest",
    "policy_from_manifest",
    "surfaces_from_loaded_extension",
]
