"""Private source-complete initial Resource Catalog adapter for Coding."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionKind,
)
from loushang.harness.capabilities.model_input_contracts import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.resource_catalog._loader_inputs import (
    bind_product_catalog_receipt,
)
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.plugins.selection import (
    PluginSelection,
)
from loushang.harness.session.product_composition_assembly import (
    CatalogContributionOwnerPolicy,
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    ProductPluginPlanSeed,
    ProductPluginSelectionSeed,
    _complete_catalog_plugin_selection_seed,
    _finalize_catalog_plugin_plan_seed,
    _prepare_catalog_plugin_plan_seed,
    assemble_product_composition,
)

if TYPE_CHECKING:
    from pathlib import Path

    from loushang.harness.resource_catalog.bootstrap_projection import (
        ResourceCatalogBootstrapResult,
    )

_CATALOG_PRODUCT_ID = "coding"
_CATALOG_PRODUCT_LABEL = "Coding"
_PACKAGE_CATALOG_REQUIRED_ROOTS = (MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,)
_PACKAGE_CATALOG_DEFINITIONS = (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
_CODING_RESOURCE_CATALOG_POLICY_REVISION = "coding-resource-catalog-v3"
_CODING_PACKAGE_TRUST_CLASS = "coding-configured-published"
_CODING_PACKAGE_TRUST_POLICY_REVISION = "coding-resource-package-trust-v1"
_CATALOG_OWNER_POLICY = CatalogContributionOwnerPolicy(
    product_id=_CATALOG_PRODUCT_ID,
    configured_trust_class=_CODING_PACKAGE_TRUST_CLASS,
    policy_revision=lambda owner_id, kind: f"{owner_id}-{kind}-coding-ingress-v1",
)


@dataclass(frozen=True, slots=True)
class CodingResourceCatalogSourcePolicy:
    """Product-authored admission policy for Catalog source classes."""

    policy_id: str
    product_policy_revision: str
    include_native_resources: bool
    include_package_resources: bool
    include_embedded_resources: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id.strip()
            or not isinstance(self.product_policy_revision, str)
            or not self.product_policy_revision.strip()
        ):
            raise ValueError("Coding Resource Catalog source policy is invalid")
        for value in (
            self.include_native_resources,
            self.include_package_resources,
            self.include_embedded_resources,
        ):
            if not isinstance(value, bool):
                raise TypeError(
                    "Coding Resource Catalog source policy flags must be bools"
                )


CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY = CodingResourceCatalogSourcePolicy(
    policy_id="coding.standard",
    product_policy_revision=_CODING_RESOURCE_CATALOG_POLICY_REVISION,
    include_native_resources=True,
    include_package_resources=True,
    include_embedded_resources=True,
)
CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY = (
    CodingResourceCatalogSourcePolicy(
        policy_id="coding.product.base-disabled",
        product_policy_revision=_CODING_RESOURCE_CATALOG_POLICY_REVISION,
        include_native_resources=True,
        include_package_resources=False,
        include_embedded_resources=True,
    )
)
CODING_READ_ONLY_AGENT_RESOURCE_CATALOG_SOURCE_POLICY = (
    CodingResourceCatalogSourcePolicy(
        policy_id="coding.agent.read-only-v1",
        product_policy_revision="coding-resource-catalog-agent-read-only-v1",
        include_native_resources=False,
        include_package_resources=False,
        include_embedded_resources=False,
    )
)
_CODING_RESOURCE_CATALOG_SOURCE_POLICIES = {
    item.policy_id: item
    for item in (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
        CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
        CODING_READ_ONLY_AGENT_RESOURCE_CATALOG_SOURCE_POLICY,
    )
}


def canonical_coding_resource_catalog_source_policy(
    policy: CodingResourceCatalogSourcePolicy,
) -> CodingResourceCatalogSourcePolicy:
    """Reject forged Product policies while retaining immutable shared values."""

    if not isinstance(policy, CodingResourceCatalogSourcePolicy):
        raise TypeError("Coding Resource Catalog source policy is invalid")
    canonical = _CODING_RESOURCE_CATALOG_SOURCE_POLICIES.get(policy.policy_id)
    if canonical is None or policy != canonical:
        raise ValueError("Coding Resource Catalog source policy must be canonical")
    return canonical


class _ResourceCatalogReceiptSource(Protocol):
    def _take_initial_resource_catalog_input_receipt(
        self,
    ) -> ResourceCatalogInputReceipt: ...


class CodingResourceCatalogAdmissionError(RuntimeError):
    """Coding cannot faithfully admit an input to its Resource Catalog."""

    code = "coding_resource_catalog_unsupported"

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(sorted(set(reasons)))
        if not self.reasons:
            raise ValueError("Coding Resource Catalog rejection needs a reason")
        super().__init__(f"{self.code}: {', '.join(self.reasons)}")


def prepare_coding_initial_resource_catalog_adapter(
    resource_loader: _ResourceCatalogReceiptSource,
    *,
    product_scope_id: str | None = None,
    disabled_skills: Sequence[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    product_selection: PluginSelection | None = None,
    admission_now: int | None = None,
    clock: Callable[[], int] | None = None,
    source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
) -> InitialResourceCatalogProductAdapter:
    """Consume exactly one owner-issued receipt for a Catalog-owned Session."""

    try:
        receipt = resource_loader._take_initial_resource_catalog_input_receipt()
    except (AttributeError, RuntimeError) as exc:
        raise CodingResourceCatalogAdmissionError(("catalog_receipt_unavailable",)) from exc
    return build_coding_initial_resource_catalog_adapter(
        receipt,
        disabled_skills=disabled_skills,
        product_composition=product_composition,
        product_selection=product_selection,
        product_scope_id=product_scope_id,
        package_admission_now=(
            int(time.time()) if admission_now is None else admission_now
        ),
        clock=clock,
        source_policy=source_policy,
    )


def build_coding_initial_resource_catalog_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None = None,
    disabled_skills: Sequence[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] | None = None,
    product_selection: PluginSelection | None = None,
    package_admission_now: int | None = None,
    clock: Callable[[], int] | None = None,
    source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
) -> InitialResourceCatalogProductAdapter:
    """Map one exact loader receipt without reparsing its selected Bundle."""

    product_label = _CATALOG_PRODUCT_LABEL
    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise TypeError(f"{product_label} Resource Catalog requires an input receipt")
    source_policy = canonical_coding_resource_catalog_source_policy(
        source_policy
    )
    return bind_product_catalog_receipt(
        receipt,
        product_id=_CATALOG_PRODUCT_ID,
        product_label=product_label,
        product_scope_id=product_scope_id,
        default_policy_revision=source_policy.product_policy_revision,
        product_composition=product_composition,
        product_snapshot_resources=product_snapshot_resources,
        product_selection=product_selection,
        package_admission_now=package_admission_now,
        clock=clock,
        include_native_resources=source_policy.include_native_resources,
        include_package_resources=source_policy.include_package_resources,
        include_embedded_resources=source_policy.include_embedded_resources,
        disabled_skills=disabled_skills,
        reject=CodingResourceCatalogAdmissionError,
        compile_package=_compile_package_composition,
    )


def prepare_coding_catalog_projection(
    receipt: ResourceCatalogInputReceipt,
    *,
    cwd: Path,
    session_id: str,
    admission_now: int | None,
    product_id: str = _CATALOG_PRODUCT_ID,
    disabled_skills: Sequence[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] | None = None,
    clock: Callable[[], int] | None = None,
    source_policy: CodingResourceCatalogSourcePolicy = CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
) -> tuple[InitialResourceCatalogProductAdapter, ResourceCatalogBootstrapResult]:
    """Bind one loader receipt to the Catalog projection used by the caller."""
    adapter = build_coding_initial_resource_catalog_adapter(
        receipt,
        product_scope_id=session_id,
        disabled_skills=disabled_skills,
        product_composition=product_composition,
        product_snapshot_resources=product_snapshot_resources,
        package_admission_now=int(time.time()) if admission_now is None else admission_now,
        clock=clock,
        source_policy=source_policy,
    )
    return adapter, adapter.prepare_bootstrap_projection_with_receipt(
        product_id=product_id, session_id=session_id, cwd=cwd
    )


def _compile_package_composition(
    receipt: ResourceCatalogInputReceipt,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None,
) -> ProductCompositionCompilation | None:
    plan_seed = prepare_coding_package_plugin_plan_seed(
        receipt,
        product_scope_id=product_scope_id,
        evaluated_at=evaluated_at,
        product_selection=product_selection,
    )
    if plan_seed is None:
        return None
    seed = finalize_coding_package_plugin_plan_seed(plan_seed)
    return assemble_product_composition(
        ProductCompositionAssemblyRequest(
            selection=seed.selection,
            owner_bindings=seed.owner_bindings,
            mandatory_roots=_PACKAGE_CATALOG_REQUIRED_ROOTS,
            definitions=_PACKAGE_CATALOG_DEFINITIONS,
        ),
        evaluated_at=evaluated_at,
    )


def prepare_coding_package_plugin_plan_seed(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None = None,
    plan_seed: ProductPluginPlanSeed | None = None,
    include_configured_resource_plugins: bool = True,
) -> ProductPluginPlanSeed | None:
    """Merge package facts into an inert plan without finalizing selection."""
    return _prepare_catalog_plugin_plan_seed(
        receipt,
        product_scope_id=product_scope_id,
        evaluated_at=evaluated_at,
        product_selection=product_selection,
        plan_seed=plan_seed,
        include_configured_resource_plugins=include_configured_resource_plugins,
        product_id=_CATALOG_PRODUCT_ID,
        product_policy_revision=_CODING_RESOURCE_CATALOG_POLICY_REVISION,
        configured_trust_class=_CODING_PACKAGE_TRUST_CLASS,
        configured_trust_policy_revision=_CODING_PACKAGE_TRUST_POLICY_REVISION,
        reject=CodingResourceCatalogAdmissionError,
        product_label=_CATALOG_PRODUCT_LABEL,
    )


def finalize_coding_package_plugin_plan_seed(
    seed: ProductPluginPlanSeed,
    *,
    resolve: Callable[[ProductPluginPlanSeed], PluginSelection] | None = None,
) -> ProductPluginSelectionSeed:
    """Finalize a complete package plan exactly once, then bind its owners."""
    return _finalize_catalog_plugin_plan_seed(
        seed,
        resolve=resolve,
        owner_policy=_CATALOG_OWNER_POLICY,
        reject=CodingResourceCatalogAdmissionError,
        product_label=_CATALOG_PRODUCT_LABEL,
    )


def complete_coding_package_plugin_selection_seed(
    seed: ProductPluginPlanSeed, *, selection: PluginSelection
) -> ProductPluginSelectionSeed:
    """Attach exact contribution owners to one already-finalized selection."""
    return _complete_catalog_plugin_selection_seed(
        seed,
        selection=selection,
        owner_policy=_CATALOG_OWNER_POLICY,
        reject=CodingResourceCatalogAdmissionError,
        product_label=_CATALOG_PRODUCT_LABEL,
    )


def _owner_binding_covers(
    binding: ProductContributionOwnerBinding,
    *,
    owner_id: str,
    contribution_kind: OwnerContributionKind,
    trust_classes: set[str],
    collection_ids: set[str],
) -> bool:
    return binding.authority.policy.covers_direct_session(
        owner_id=owner_id,
        contribution_kind=contribution_kind,
        product_id=_CATALOG_PRODUCT_ID,
        trust_classes=trust_classes,
        collection_ids=collection_ids,
    )


__all__ = [
    "CODING_READ_ONLY_AGENT_RESOURCE_CATALOG_SOURCE_POLICY",
    "CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY",
    "CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY",
    "CodingResourceCatalogSourcePolicy",
    "CodingResourceCatalogAdmissionError",
    "InitialResourceCatalogProductAdapter",
    "ResourceCatalogInputReceipt",
    "prepare_coding_initial_resource_catalog_adapter",
]
