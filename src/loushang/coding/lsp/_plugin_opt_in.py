"""Compatibility facade for the original LSP-only Product composition API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loushang.coding._base_plugin import CodingBasePluginAssembly
from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginApprovalOwner,
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionError,
    CodingCapabilityPluginCompositionPreparation,
    CodingCapabilityPluginCompositionRequest,
    create_coding_capability_plugin_composition_request,
    prepare_coding_capability_plugin_composition,
)
from loushang.coding.lsp._provider_api import CodingLspPluginConfigV1
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.session.product_composition_assembly import (
    ProductPluginPlanSeed,
)

_LSP_PLUGIN_ID = "coding.lsp.default"

CodingLspPluginApprovalOwner = CodingCapabilityPluginApprovalOwner
CodingLspPluginOptInAssembly = CodingCapabilityPluginCompositionAssembly
CodingLspPluginOptInError = CodingCapabilityPluginCompositionError
CodingLspPluginOptInPreparation = CodingCapabilityPluginCompositionPreparation
CodingLspPluginOptInRequest = CodingCapabilityPluginCompositionRequest


def create_coding_lsp_default_plugin_opt_in_request(
    *,
    clock: Callable[[], int],
    product_policy_revision: str = "coding-capability-plugins-2",
) -> CodingLspPluginOptInRequest:
    """Create the legacy LSP-only view of the shared Product request."""

    return create_coding_capability_plugin_composition_request(
        clock=clock,
        plugin_ids=frozenset({_LSP_PLUGIN_ID}),
        approval_source="coding-lsp-default-product-policy",
        product_policy_revision=product_policy_revision,
    )


def prepare_coding_lsp_plugin_opt_in(
    request: CodingLspPluginOptInRequest,
    *,
    session_id: str,
    config: CodingLspPluginConfigV1,
    package_materializer: CodingPackageMaterializer,
    state_root: str | Path,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
    coding_product_plan_seed: ProductPluginPlanSeed | None = None,
    state_cleanup: Callable[[], None] | None = None,
) -> CodingLspPluginOptInPreparation:
    """Prepare one LSP Provider through the shared Capability composition."""

    return prepare_coding_capability_plugin_composition(
        request,
        session_id=session_id,
        configurations={_LSP_PLUGIN_ID: config},
        package_materializer=package_materializer,
        state_root=state_root,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
        state_cleanup=state_cleanup,
    )


def assemble_coding_lsp_plugin_opt_in(
    request: CodingLspPluginOptInRequest,
    *,
    session_id: str,
    config: CodingLspPluginConfigV1,
    package_materializer: CodingPackageMaterializer,
    workspace_binding: CapabilityBundleProviderBinding,
    state_root: str | Path,
    host_boot_id: str,
    tool_mode: CapabilityMountMode,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
    coding_product_plan_seed: ProductPluginPlanSeed | None = None,
    state_cleanup: Callable[[], None] | None = None,
) -> CodingLspPluginOptInAssembly:
    """Assemble the LSP-only compatibility view in one call."""

    preparation = prepare_coding_lsp_plugin_opt_in(
        request,
        session_id=session_id,
        config=config,
        package_materializer=package_materializer,
        state_root=state_root,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
        state_cleanup=state_cleanup,
    )
    return preparation.bind_workspace(
        workspace_binding,
        host_boot_id=host_boot_id,
        tool_mode=tool_mode,
        clock=clock,
    )


__all__ = [
    "CodingLspPluginApprovalOwner",
    "CodingLspPluginOptInAssembly",
    "CodingLspPluginOptInError",
    "CodingLspPluginOptInPreparation",
    "CodingLspPluginOptInRequest",
    "assemble_coding_lsp_plugin_opt_in",
    "create_coding_lsp_default_plugin_opt_in_request",
    "prepare_coding_lsp_plugin_opt_in",
]
