"""Bind observed input to one Resource Catalog adapter."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

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
from loushang.harness.resources.plugins.selection import PluginSelection

if TYPE_CHECKING:
    from loushang.coding.resources.catalog import CodingResourceCatalogSourcePolicy
    from loushang.harness.resource_catalog.product_snapshot_source import (
        ProductSelectedResourceInput,
    )
    from loushang.harness.resources._catalog_input_receipt import (
        ResourceCatalogInputReceipt,
    )


def build_catalog_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_id: str,
    product_label: str,
    product_scope_id: str | None,
    disabled_skills: Sequence[str],
    product_composition: ProductCompositionCompilation | None,
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] | None,
    product_selection: PluginSelection | None,
    package_admission_now: int | None,
    clock: Callable[[], int] | None,
    source_policy: CodingResourceCatalogSourcePolicy,
    compile_composition: Callable[
        [ResourceCatalogInputReceipt, str | None, int, PluginSelection | None],
        ProductCompositionCompilation | None,
    ],
    reject: Callable[[Sequence[str]], Exception],
) -> InitialResourceCatalogProductAdapter:
    """Bind one exact receipt to the existing Catalog input owner."""

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
        product_composition = compile_composition(
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
            reject=reject,
        ),
        clock=resolved_clock,
    )
