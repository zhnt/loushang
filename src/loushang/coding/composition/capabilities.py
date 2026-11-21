"""Coding-owned Product capability identities and mount policy."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.coding.harness.session.composition_receipt import (
    configured_mount_mode,
    parse_mount,
    should_defer_mount,
)
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

    return configured_mount_mode(
        settings_manager,
        capability,
        _CODING_CAPABILITY_DEFAULTS.get(capability, "disabled"),
    )


def parse_capability_mount(value: str) -> tuple[str, CapabilityMountMode]:
    """Parse the generic ``CAPABILITY=MODE`` Coding CLI form."""

    return parse_mount(value)


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

    return should_defer_mount(
        "coding.lsp.default",
        enabled=enabled,
        mode=mode,
        has_history=has_history,
        startup=startup,
        legacy_disabled=legacy_disabled,
    )


__all__ = [
    "CODING_ARCH_CAPABILITY",
    "CODING_LSP_CAPABILITY",
    "coding_capability_mount_mode",
    "parse_capability_mount",
]
