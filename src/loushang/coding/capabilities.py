"""Coding-owned Product capability identities and mount policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loushang.harness.config.agent import CapabilityMountMode

CODING_ARCH_CAPABILITY = "coding.arch"
CODING_LSP_CAPABILITY = "coding.lsp"

_CODING_CAPABILITY_DEFAULTS: Mapping[str, CapabilityMountMode] = {
    CODING_ARCH_CAPABILITY: "on_demand",
    CODING_LSP_CAPABILITY: "on_demand",
}


def coding_capability_mount_mode(
    settings_manager: object | None,
    capability: str,
) -> CapabilityMountMode:
    """Resolve one Coding capability without leaking Product ids into Harness."""

    default = _CODING_CAPABILITY_DEFAULTS.get(capability, "disabled")
    if settings_manager is None:
        return default
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        return default
    configured = getattr(get_settings(), "capabilities", {})
    if not isinstance(configured, Mapping):
        return default
    mode = configured.get(capability, default)
    return mode if mode in {"disabled", "on_demand", "always"} else default


def parse_capability_mount(value: str) -> tuple[str, CapabilityMountMode]:
    """Parse the generic ``CAPABILITY=MODE`` Coding CLI form."""

    capability, separator, mode = value.partition("=")
    capability = capability.strip()
    mode = mode.strip()
    if not separator or not capability:
        raise ValueError("expected CAPABILITY=disabled|on_demand|always")
    if mode not in {"disabled", "on_demand", "always"}:
        raise ValueError("mount mode must be disabled, on_demand, or always")
    return capability, cast(CapabilityMountMode, mode)


def coding_lsp_should_defer(
    *,
    enabled: bool,
    mode: CapabilityMountMode,
    has_history: bool,
    startup: Mapping[str, object] | None,
    legacy_disabled: bool = False,
) -> bool:
    """Share the initial LSP owner decision between Resume and bootstrap.

    ``startup`` is the original validated composition receipt. A dormant
    receipt permits a fresh on-demand generation; it does not require eager
    Plugin parents merely because LSP is allowed. Historical eager sessions
    and older history without a receipt retain their existing eager route.
    This decides initial assembly only, not settlement of pending effects.
    """

    if not enabled or mode != "on_demand" or legacy_disabled:
        return False
    if not has_history:
        return True
    if startup is None:
        return False
    return not any(
        item["pluginId"] == "coding.lsp.default"
        for item in cast(list[dict[str, object]], startup["selectedRevisions"])
    )


__all__ = [
    "CODING_ARCH_CAPABILITY",
    "CODING_LSP_CAPABILITY",
    "coding_capability_mount_mode",
    "parse_capability_mount",
]
