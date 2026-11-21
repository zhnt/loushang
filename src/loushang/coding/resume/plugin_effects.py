"""Shared Coding Resume Plugin admission checks, without UI construction."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.coding.composition.capabilities import (
    CODING_ARCH_CAPABILITY,
    CODING_LSP_CAPABILITY,
    coding_capability_mount_mode,
    coding_lsp_should_defer,
)
from loushang.coding.composition.capability_specs import CODING_CAPABILITY_PLUGIN_IDS
from loushang.coding.harness.session.plugin_resume import require_no_plugin_effects
from loushang.harness.session.bootstrap_utils import NoToolsMode, normalize_no_tools

from .activation_attempt_v2 import CodingActivationAttemptV2
from .history import CodingResumeHistoryPreview


def _resume_capability_plugins_required(
    *,
    plan_set_id: str,
    settings_manager: object | None,
    no_tools: NoToolsMode | bool | None,
    history: CodingResumeHistoryPreview,
) -> bool:
    """Select owners for this activation, not all enabled capabilities."""
    mode = normalize_no_tools(no_tools)
    if mode == "all":
        return False
    if plan_set_id == "coding-minimal":
        return False
    lsp = coding_capability_mount_mode(settings_manager, CODING_LSP_CAPABILITY)
    eager_lsp = lsp != "disabled" and not coding_lsp_should_defer(
        enabled=True,
        mode=lsp,
        # Even an empty historical Session gains an activation intent before
        # bootstrap. Without a startup receipt it follows the legacy route.
        has_history=True,
        startup=history.startup,
    )
    if plan_set_id == "coding-standard":
        return eager_lsp
    if plan_set_id == "coding-architecture":
        arch = coding_capability_mount_mode(
            settings_manager, CODING_ARCH_CAPABILITY
        )
        return eager_lsp or arch != "disabled"
    raise ValueError("Coding Resume composition set is unsupported")

def _require_no_capability_plugin_effects(
    attempt: CodingActivationAttemptV2,
    receipt: Mapping[str, object],
    *,
    expected_set_id: str,
    allowed_owner_ids: frozenset[str] = frozenset(),
) -> None:
    require_no_plugin_effects(
        attempt,
        receipt,
        expected_set_id=expected_set_id,
        allowed_owner_ids=allowed_owner_ids,
        capability_plugin_ids=CODING_CAPABILITY_PLUGIN_IDS,
    )


# Existing private lookup routes retain callable identity at their old module.
_resume_capability_plugins_required.__module__ = "loushang.coding.embedded_resume"
_require_no_capability_plugin_effects.__module__ = "loushang.coding.embedded_resume"
resume_capability_plugins_required = _resume_capability_plugins_required
require_no_capability_plugin_effects = _require_no_capability_plugin_effects

__all__ = ["require_no_capability_plugin_effects", "resume_capability_plugins_required"]
