from __future__ import annotations

from loushang.harness.extensions.agent.api import ExtensionAPI
from loushang.harness.extensions.agent.policy import policy_from_manifest
from loushang.harness.extensions.loader import ExtensionLoader as HarnessExtensionLoader
from loushang.harness.extensions.manifest import ExtensionManifest
from loushang.harness.extensions.types import ExtensionPolicyDecision

_LEGACY_EVENT_NAMES = (
    "session_start",
    "session_refresh",
    "before_agent_start",
    "session_shutdown",
    "resources_discover",
    "context",
    "tool_call",
    "tool_result",
)


def _coding_policy(
    manifest: ExtensionManifest | None,
    enabled: bool,
) -> ExtensionPolicyDecision:
    return policy_from_manifest(manifest, enabled=enabled)


class ExtensionLoader(HarnessExtensionLoader):
    """Agent profile over the product-neutral Harness extension loader."""

    def __init__(self) -> None:
        super().__init__(
            api_factory=ExtensionAPI,
            policy_resolver=_coding_policy,
            legacy_event_names=_LEGACY_EVENT_NAMES,
        )


__all__ = ["ExtensionLoader"]
