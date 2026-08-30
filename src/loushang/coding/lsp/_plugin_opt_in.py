"""Compatibility facade for the original LSP-only Product composition API."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolOwner
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CodingLspPluginConfigV1,
)
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.approval.plugin_activation import (
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationDecisionRecordV1,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.resources.plugins.selection import (
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
)
from loushang.harness.session.product_composition_assembly import (
    ProductPluginPlanSeed,
)

_LSP_PLUGIN_ID = "coding.lsp.default"

_LEGACY_ERROR_CODES = {
    "coding_capability_plugin_definition_approval_mismatch": (
        "coding_lsp_plugin_definition_approval_mismatch"
    ),
    "coding_capability_plugin_definition_denied": (
        "coding_lsp_plugin_definition_denied"
    ),
    "coding_capability_plugin_activation_approval_mismatch": (
        "coding_lsp_plugin_activation_approval_mismatch"
    ),
    "coding_capability_plugin_activation_denied": (
        "coding_lsp_plugin_activation_denied"
    ),
    "coding_capability_plugin_activation_not_available": (
        "coding_lsp_plugin_activation_not_available"
    ),
    "coding_capability_definition_subject_rejected": (
        "coding_lsp_default_definition_subject_rejected"
    ),
    "coding_capability_activation_subject_rejected": (
        "coding_lsp_default_activation_subject_rejected"
    ),
}

CodingLspPluginApprovalOwner = CodingCapabilityPluginApprovalOwner
CodingLspPluginOptInError = CodingCapabilityPluginCompositionError
CodingLspPluginOptInRequest = CodingCapabilityPluginCompositionRequest


def _translate_lsp_error(
    error: CodingCapabilityPluginCompositionError,
) -> CodingCapabilityPluginCompositionError:
    legacy_code = _LEGACY_ERROR_CODES.get(error.code)
    if legacy_code is None and error.code.startswith(
        "coding_capability_plugin_definition_"
    ):
        legacy_code = error.code.replace(
            "coding_capability_plugin_definition_",
            "coding_lsp_plugin_definition_",
            1,
        )
    if legacy_code is None:
        return error
    translated = CodingCapabilityPluginCompositionError(
        str(error),
        code=legacy_code,
    )
    for note in getattr(error, "__notes__", ()):
        translated.add_note(note)
    return translated


@dataclass(frozen=True, slots=True)
class _CodingLspApprovalOwnerAdapter:
    inner: CodingCapabilityPluginApprovalOwner

    def bind_selected_instances(
        self,
        *,
        selected_plugin_ids: frozenset[str],
        instance_revision_refs: Mapping[str, PluginInstanceRevisionRef],
    ) -> CodingCapabilityPluginApprovalOwner:
        binder = getattr(self.inner, "bind_selected_instances", None)
        if not callable(binder):
            return self
        return _CodingLspApprovalOwnerAdapter(
            binder(
                selected_plugin_ids=selected_plugin_ids,
                instance_revision_refs=instance_revision_refs,
            )
        )

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1:
        try:
            return self.inner.approve_definition(journal=journal, subject=subject)
        except CodingCapabilityPluginCompositionError as error:
            translated = _translate_lsp_error(error)
            if translated is error:
                raise
            raise translated from error

    def approve_activation(
        self,
        *,
        journal: PluginActivationDecisionJournal,
        subject: ContributionActivationApprovalSubject,
    ) -> PluginActivationDecisionRecordV1:
        try:
            return self.inner.approve_activation(journal=journal, subject=subject)
        except CodingCapabilityPluginCompositionError as error:
            translated = _translate_lsp_error(error)
            if translated is error:
                raise
            raise translated from error


@dataclass(slots=True)
class CodingLspPluginOptInAssembly:
    """LSP-shaped compatibility view kept outside the neutral composer."""

    capability_assembly: CodingCapabilityPluginCompositionAssembly

    @property
    def tool_owner(self) -> CodingLspToolOwner:
        owner = self.capability_assembly.tool_owner_for(_LSP_PLUGIN_ID)
        if not isinstance(owner, CodingLspToolOwner):
            raise RuntimeError("Coding LSP Tool owner is not selected")
        return owner

    @property
    def provider_owner_authority(self) -> CapabilityProviderOwnerAuthority:
        return self.capability_assembly.provider_owner_authorities[
            CODING_LSP_CAPABILITY_DEFINITION.capability_id
        ]

    def close(self) -> None:
        self.capability_assembly.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.capability_assembly, name)


@dataclass(slots=True)
class CodingLspPluginOptInPreparation:
    """LSP-only binding adapter around a neutral Capability preparation."""

    capability_preparation: CodingCapabilityPluginCompositionPreparation

    def bind_workspace(
        self,
        workspace_binding: CapabilityBundleProviderBinding,
        *,
        host_boot_id: str,
        tool_mode: CapabilityMountMode,
        clock: Callable[[], int],
    ) -> CodingLspPluginOptInAssembly:
        try:
            return CodingLspPluginOptInAssembly(
                self.capability_preparation.bind_workspace(
                    workspace_binding,
                    host_boot_id=host_boot_id,
                    tool_modes={
                        CODING_LSP_CAPABILITY_DEFINITION.capability_id: tool_mode
                    },
                    clock=clock,
                )
            )
        except CodingCapabilityPluginCompositionError as error:
            translated = _translate_lsp_error(error)
            if translated is error:
                raise
            raise translated from error

    def close(self) -> None:
        self.capability_preparation.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.capability_preparation, name)


def create_coding_lsp_default_plugin_opt_in_request(
    *,
    clock: Callable[[], int],
    product_policy_revision: str = "coding-capability-plugins-2",
) -> CodingLspPluginOptInRequest:
    """Create the legacy LSP-only view of the shared Product request."""

    request = create_coding_capability_plugin_composition_request(
        clock=clock,
        plugin_ids=frozenset({_LSP_PLUGIN_ID}),
        approval_source="coding-lsp-default-product-policy",
        product_policy_revision=product_policy_revision,
    )
    return CodingLspPluginOptInRequest(
        approval_owner=_CodingLspApprovalOwnerAdapter(request.approval_owner)
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

    try:
        return CodingLspPluginOptInPreparation(
            prepare_coding_capability_plugin_composition(
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
        )
    except CodingCapabilityPluginCompositionError as error:
        translated = _translate_lsp_error(error)
        if translated is error:
            raise
        raise translated from error


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
