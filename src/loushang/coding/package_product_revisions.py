"""First-party Plugin revisions captured from the selected Product Store.

This module supplies verified bytes to the existing Plugin approval and
declaration machinery. It does not approve or execute a Definition itself.
"""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._selected_plugin_revisions import (
    ProductSelectedRevisionHandle,
    ProductSelectedRevisionPolicy,
    open_selected_resolution,
)
from loushang.harness.package_product._selected_plugin_revisions import (
    _host_distribution_lock as _core_host_distribution_lock,
)
from loushang.harness.package_product._selected_plugin_revisions import (
    _validate_builtin_selection as _core_validate_builtin_selection,
)
from loushang.harness.package_product._selected_plugin_revisions import (
    _validate_external_data_selection as _core_validate_external_data_selection,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resources.packages.plugin_lifecycle._exact_product_source import (
    InstalledProductWheelSpec,
)
from loushang.harness.resources.plugins.authority import PluginRuntimeResolution
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)

from ._capability_plugin_specs import (
    CODING_CAPABILITY_PLUGIN_SPEC_BY_ID,
    ordered_coding_capability_plugin_specs,
)
from .package_legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES,
    permits_external_data_owner,
)
from .plugin_dependency_grants import coding_plugin_distribution_evidence_resolver

_MAX_FILES = 64
_MAX_BYTES = 1024 * 1024
_DEFINITION_ENTRYPOINT = "definition.py:declare"


class _ProductSelectedRevisionHandle(ProductSelectedRevisionHandle):
    """Read one immutable capture only while its live Product selection agrees.

    The root is a diagnostic name, never a filesystem source. Every read
    rechecks the Product selection; bytes come from the pinned, verified
    capture, so neither a legacy root nor a stale Desired selection can
    supply executable bytes.
    """

    def acquire(self) -> _ProductSelectedRevisionHandle:
        return cast(_ProductSelectedRevisionHandle, super().acquire())


_ProductSelectedRevisionHandle._handle_type = _ProductSelectedRevisionHandle


def open_coding_product_capability_resolution(
    runtime: PackageProductRuntimeBindingV1,
    *,
    plugin_ids: tuple[str, ...],
) -> PluginRuntimeResolution:
    """Supply exact selected first-party revisions without a legacy materializer.

    This is a revision input to the existing approved Definition/Provider
    composer, not an execution grant. The host distribution grant is restricted
    to a Wheel identical to the installed first-party package.
    """

    if (
        not isinstance(plugin_ids, tuple)
        or not plugin_ids
        or len(plugin_ids) != len(set(plugin_ids))
    ):
        raise ValueError("Coding Product Capability selection is invalid")
    specs = ordered_coding_capability_plugin_specs(plugin_ids)
    if len(specs) != len(plugin_ids):
        raise ValueError("Coding Product Capability selection is invalid")
    return _open_selected_resolution(runtime, tuple(spec.plugin_id for spec in specs))


def open_coding_product_builtin_resolution(
    runtime: PackageProductRuntimeBindingV1,
    *,
    capability_plugin_ids: tuple[str, ...] = (
        "coding.arch.default",
        "coding.lsp.default",
    ),
    external_data_plugin_ids: tuple[str, ...] = (),
) -> PluginRuntimeResolution:
    """Reopen first-party and admitted data-only roots from one Product binding."""

    if (
        not isinstance(capability_plugin_ids, tuple)
        or not capability_plugin_ids
        or len(capability_plugin_ids) != len(set(capability_plugin_ids))
    ):
        raise ValueError("Coding Product Capability selection is invalid")
    specs = ordered_coding_capability_plugin_specs(capability_plugin_ids)
    if len(specs) != len(capability_plugin_ids):
        raise ValueError("Coding Product Capability selection is invalid")

    if (
        not isinstance(external_data_plugin_ids, tuple)
        or tuple(sorted(set(external_data_plugin_ids))) != external_data_plugin_ids
        or set(external_data_plugin_ids)
        & {"coding.base", *(spec.plugin_id for spec in specs)}
        or external_data_plugin_ids != runtime.selected_external_data_plugin_ids()
    ):
        raise ValueError("Coding external data selection changed")
    return _open_selected_resolution(
        runtime,
        tuple(
            sorted(
                (
                    "coding.base",
                    *(spec.plugin_id for spec in specs),
                    *external_data_plugin_ids,
                )
            )
        ),
        external_data_plugin_ids=frozenset(external_data_plugin_ids),
    )


def _open_selected_resolution(
    runtime: PackageProductRuntimeBindingV1,
    plugin_ids: tuple[str, ...],
    *,
    external_data_plugin_ids: frozenset[str] = frozenset(),
) -> PluginRuntimeResolution:
    return open_selected_resolution(
        _revision_policy(),
        runtime,
        plugin_ids,
        external_data_plugin_ids=external_data_plugin_ids,
    )


def _validate_builtin_selection(
    selected: PackageProductSelectedPluginManifestV1, plugin_id: str
) -> None:
    return _core_validate_builtin_selection(_revision_policy(), selected, plugin_id)


def _validate_external_data_selection(
    selected: PackageProductSelectedPluginManifestV1, plugin_id: str
) -> None:
    return _core_validate_external_data_selection(
        _revision_policy(), selected, plugin_id
    )


def _host_distribution_lock(
    plugin_id: str, content_digest: str
) -> PluginDependencyClosureLock:
    return _core_host_distribution_lock(_revision_policy(), plugin_id, content_digest)


__all__ = [
    "open_coding_product_builtin_resolution",
    "open_coding_product_capability_resolution",
]


def _revision_policy() -> ProductSelectedRevisionPolicy:
    """Declare closed Product values and original owner constructors, with no IO."""
    from . import package_builtin_wheel as wheel
    from . import plugin_dependency_grants as grants

    def wheel_spec(plugin_id: str) -> InstalledProductWheelSpec:
        if plugin_id == "coding.base":
            return wheel._BASE_SPEC
        try:
            return wheel._CAPABILITY_SPECS[plugin_id]
        except (KeyError, TypeError) as exc:
            raise ValueError("Unknown Coding Capability Product Plugin") from exc

    def location(plugin_id: str) -> tuple[str, tuple[str, ...]]:
        return grants.__file__, grants._CODING_PRODUCT_SOURCE_LOCATIONS[plugin_id]

    return ProductSelectedRevisionPolicy(
        product_id="coding",
        product_label="Coding",
        base_plugin_id="coding.base",
        base_root_relative="coding_base",
        plugin_version="1",
        source_trust_class="host-equivalent-local",
        definition_entrypoint=lambda: _DEFINITION_ENTRYPOINT,
        capability_spec=lambda plugin_id: CODING_CAPABILITY_PLUGIN_SPEC_BY_ID[
            plugin_id
        ],
        capability_location=location,
        source_files=lambda: wheel._product_source_files,
        wheel_recipe=lambda: wheel._PRODUCT_WHEEL_RECIPE,
        wheel_spec=wheel_spec,
        distribution_resolver=lambda: coding_plugin_distribution_evidence_resolver(),
        distribution_name="loushang",
        maximum_files=lambda: _MAX_FILES,
        maximum_bytes=lambda: _MAX_BYTES,
        handle_type=_ProductSelectedRevisionHandle,
        external_trust_classes=EXTERNAL_DATA_TRUST_CLASSES,
        permits_external_owner=permits_external_data_owner,
        external_resource_owners=frozenset(
            {"resources.skill", "resources.prompt", "resources.theme"}
        ),
    )
