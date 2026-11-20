"""Bind observed input to one Resource Catalog adapter."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from loushang.coding.resources import catalog as _binding
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.resource_catalog._loader_inputs import (
    _select_loader_catalog_inputs,
)
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.plugins.selection import PluginSelection
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    assemble_product_composition,
)

if TYPE_CHECKING:
    from loushang.harness.resource_catalog.product_snapshot_source import (
        ProductSelectedResourceInput,
    )


def take_initial_receipt(
    resource_loader: _binding._ResourceCatalogReceiptSource,
) -> ResourceCatalogInputReceipt:
    """Take the one-shot receipt through the original loader transfer."""
    try:
        return resource_loader._take_initial_resource_catalog_input_receipt()
    except (AttributeError, RuntimeError) as exc:
        raise _binding.CodingResourceCatalogAdmissionError(
            ("catalog_receipt_unavailable",)
        ) from exc


def build_catalog_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    disabled_skills: Sequence[str],
    product_composition: ProductCompositionCompilation | None,
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] | None,
    product_selection: PluginSelection | None,
    package_admission_now: int | None,
    clock: Callable[[], int] | None,
    source_policy: _binding.CodingResourceCatalogSourcePolicy,
) -> InitialResourceCatalogProductAdapter:
    """Bind one exact receipt to the existing Catalog input owner."""

    product_id = _binding._CATALOG_PRODUCT_ID
    product_label = _binding._CATALOG_PRODUCT_LABEL
    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise TypeError(f"{product_label} Resource Catalog requires an input receipt")
    source_policy = _binding.canonical_coding_resource_catalog_source_policy(
        source_policy
    )
    if product_scope_id is not None and (
        not isinstance(product_scope_id, str) or not product_scope_id.strip()
    ):
        raise ValueError(f"{product_label} Resource Catalog Product scope is invalid")
    resolved_clock = clock or (lambda: int(time.time()))
    if not callable(resolved_clock):
        raise TypeError(f"{product_label} Resource Catalog clock is invalid")
    resolved_admission_now = (
        resolved_clock() if package_admission_now is None else package_admission_now
    )
    if product_composition is not None and not isinstance(
        product_composition,
        ProductCompositionCompilation,
    ):
        raise TypeError(
            f"{product_label} Resource Catalog Product composition is invalid"
        )
    if product_selection is not None and not isinstance(
        product_selection,
        PluginSelection,
    ):
        raise TypeError(
            f"{product_label} Resource Catalog Product selection is invalid"
        )
    if product_composition is not None and product_selection is not None:
        raise ValueError(
            f"{product_label} Resource Catalog cannot receive both a composition and selection"
        )
    if product_snapshot_resources is not None and product_selection is not None:
        raise ValueError(
            f"{product_label} Resource Catalog cannot mix Product snapshot and legacy selection"
        )
    if product_snapshot_resources is not None and product_composition is None:
        raise ValueError(
            f"{product_label} Resource Catalog Product snapshot requires a composition"
        )
    if product_selection is not None and not source_policy.include_package_resources:
        raise ValueError(
            f"{product_label} Resource Catalog source policy excludes Product package selection"
        )
    if product_composition is None and source_policy.include_package_resources:
        product_composition = _compile_package_composition(
            receipt, product_scope_id, resolved_admission_now, product_selection
        )
    admissions = (
        tuple(product_composition.resource_admissions)
        if product_composition is not None
        else ()
    )
    if any(
        not isinstance(item, OwnerContributionAdmissionRecord) for item in admissions
    ):
        raise TypeError(
            f"{product_label} Product composition Resource admissions are invalid"
        )
    product_policy_revision = (
        product_composition.authority_context.product_policy_revision
        if product_composition is not None
        else source_policy.product_policy_revision
    )
    if admissions and (
        isinstance(resolved_admission_now, bool)
        or not isinstance(resolved_admission_now, int)
    ):
        raise TypeError(
            f"{product_label} package Resource admissions require an integer time"
        )
    return InitialResourceCatalogProductAdapter(
        _select_loader_catalog_inputs(
            receipt,
            product_id=product_id,
            product_policy_revision=product_policy_revision,
            product_composition=product_composition,
            product_snapshot_resources=product_snapshot_resources,
            admissions=admissions,
            resolved_admission_now=resolved_admission_now,
            include_native_resources=source_policy.include_native_resources,
            include_package_resources=source_policy.include_package_resources,
            include_embedded_resources=source_policy.include_embedded_resources,
            disabled_skills=disabled_skills,
            reject=_binding.CodingResourceCatalogAdmissionError,
        ),
        clock=resolved_clock,
    )


def _compile_package_composition(
    receipt: ResourceCatalogInputReceipt,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None,
) -> ProductCompositionCompilation | None:
    plan_seed = _binding.prepare_coding_package_plugin_plan_seed(
        receipt,
        product_scope_id=product_scope_id,
        evaluated_at=evaluated_at,
        product_selection=product_selection,
    )
    if plan_seed is None:
        return None
    seed = _binding.finalize_coding_package_plugin_plan_seed(plan_seed)
    return assemble_product_composition(
        ProductCompositionAssemblyRequest(
            selection=seed.selection,
            owner_bindings=seed.owner_bindings,
            mandatory_roots=_binding._PACKAGE_CATALOG_REQUIRED_ROOTS,
            definitions=_binding._PACKAGE_CATALOG_DEFINITIONS,
        ),
        evaluated_at=evaluated_at,
    )
