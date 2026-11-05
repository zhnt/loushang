"""Compatibility names for the production Coding Resource Catalog adapter."""

from ._resource_catalog_adapter import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
    CODING_READ_ONLY_AGENT_RESOURCE_CATALOG_SOURCE_POLICY,
    CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
    CodingResourceCatalogAdmissionError,
    CodingResourceCatalogSourcePolicy,
    InitialResourceCatalogProductAdapter,
    ResourceCatalogInputReceipt,
    prepare_coding_initial_resource_catalog_adapter,
)
from ._resource_catalog_adapter import (
    _owner_binding_covers as _owner_binding_covers,
)
from ._resource_catalog_adapter import (
    build_coding_initial_resource_catalog_adapter as build_coding_initial_resource_catalog_adapter,
)
from ._resource_catalog_adapter import (
    canonical_coding_resource_catalog_source_policy as canonical_coding_resource_catalog_source_policy,
)
from ._resource_catalog_adapter import (
    complete_coding_package_plugin_selection_seed as complete_coding_package_plugin_selection_seed,
)
from ._resource_catalog_adapter import (
    finalize_coding_package_plugin_plan_seed as finalize_coding_package_plugin_plan_seed,
)
from ._resource_catalog_adapter import (
    prepare_coding_package_plugin_plan_seed as prepare_coding_package_plugin_plan_seed,
)

# Private compatibility aliases retain the RCP4/RCP5 rollback seam while the
# default Product uses the production names above.
CodingResourceCatalogShadowAdmissionError = CodingResourceCatalogAdmissionError
build_coding_initial_resource_catalog_shadow_adapter = (
    build_coding_initial_resource_catalog_adapter
)
prepare_coding_initial_resource_catalog_shadow_adapter = (
    prepare_coding_initial_resource_catalog_adapter
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
