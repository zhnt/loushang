from __future__ import annotations

from typing import Literal

from loushang.harness.extensions.manifest import ExtensionManifest, PermissionLevel
from loushang.harness.extensions.types import ExtensionPolicyDecision

ExtensionCapability = Literal[
    "exec",
    "filesystem",
    "network",
    "model",
    "session_mutation",
    "ui_mutation",
    "tool_mutation",
    "interaction.side_question",
]

_DEFAULT_CAPABILITIES: dict[PermissionLevel, tuple[str, ...]] = {
    "safe": (),
    "standard": ("filesystem", "model"),
    "powerful": (
        "exec",
        "filesystem",
        "network",
        "model",
        "session_mutation",
        "ui_mutation",
        "tool_mutation",
    ),
}


def policy_from_manifest(
    manifest: ExtensionManifest | None,
    *,
    enabled: bool = True,
    allow_managed_hooks_only: bool = False,
) -> ExtensionPolicyDecision:
    if manifest is None:
        return ExtensionPolicyDecision(
            enabled=enabled,
            allow_managed_hooks_only=allow_managed_hooks_only,
        )
    capabilities = (
        manifest.permissions.capabilities
        if manifest.permissions.capabilities
        else _DEFAULT_CAPABILITIES[manifest.permissions.level]
    )
    return ExtensionPolicyDecision(
        enabled=enabled,
        permission_level=manifest.permissions.level,
        capabilities=tuple(capabilities),
        allow_managed_hooks_only=allow_managed_hooks_only,
    )
