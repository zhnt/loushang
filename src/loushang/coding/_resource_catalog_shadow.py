"""Private source-complete initial Resource Catalog adapter for Coding."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
    InitialResourceCatalogProductSelection,
    ProductEmbeddedResourceCollectionSpec,
    ProductNativeResourceRootSpec,
)
from loushang.harness.resources._catalog_embedded_source import (
    capture_built_in_resource_package_files,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.builtin import BuiltInResourcePackage

_CODING_SHADOW_POLICY_REVISION = "coding-resource-catalog-shadow-v1"


class _ResourceCatalogReceiptSource(Protocol):
    def _take_initial_resource_catalog_input_receipt(
        self,
    ) -> ResourceCatalogInputReceipt: ...


class CodingResourceCatalogShadowAdmissionError(RuntimeError):
    """The current thin shadow slice cannot faithfully represent an input."""

    code = "coding_resource_catalog_shadow_unsupported"

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(sorted(set(reasons)))
        if not self.reasons:
            raise ValueError("Coding Resource Catalog rejection needs a reason")
        super().__init__(f"{self.code}: {', '.join(self.reasons)}")


def prepare_coding_initial_resource_catalog_shadow_adapter(
    resource_loader: _ResourceCatalogReceiptSource,
    *,
    disabled_skills: Sequence[str] = (),
) -> InitialResourceCatalogProductAdapter:
    """Consume exactly one owner-issued receipt for a private shadow Session."""

    return build_coding_initial_resource_catalog_shadow_adapter(
        resource_loader._take_initial_resource_catalog_input_receipt(),
        disabled_skills=disabled_skills,
    )


def build_coding_initial_resource_catalog_shadow_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    disabled_skills: Sequence[str] = (),
) -> InitialResourceCatalogProductAdapter:
    """Map one exact loader receipt without reparsing its selected Bundle."""

    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise TypeError("Coding Resource Catalog shadow requires an input receipt")
    rejection_reasons: list[str] = []
    if receipt.package_roots:
        rejection_reasons.append("package_sources")
    if receipt.has_temporary_inputs:
        rejection_reasons.append("temporary_sources")
    if receipt.has_resource_kind_switches:
        rejection_reasons.append("resource_kind_switches")
    if any(item for item in disabled_skills):
        rejection_reasons.append("disabled_skills")

    native_roots: list[ProductNativeResourceRootSpec] = []
    for index, root in enumerate(receipt.user_resource_roots):
        if not root.exists() or not root.is_dir():
            if root in receipt.explicit_user_resource_roots:
                rejection_reasons.append("explicit_user_root_unavailable")
            continue
        if root.is_symlink():
            rejection_reasons.append("symlinked_user_root")
            continue
        native_roots.append(
            ProductNativeResourceRootSpec(
                handle_id=f"coding-user-{index}",
                root=root,
                source_class="user_global",
                root_kind=("standard" if receipt.no_context_files else "combined"),
                source_root_order=index,
            )
        )

    for index, root in enumerate(receipt.project_context_roots):
        if not _is_admissible_native_root(root):
            rejection_reasons.append("project_context_root_unavailable")
            continue
        native_roots.append(
            ProductNativeResourceRootSpec(
                handle_id=f"coding-project-context-{index}",
                root=root,
                source_class="project_local",
                root_kind="context",
                source_root_order=index,
            )
        )

    project_root = receipt.project_resource_root
    if not _is_admissible_native_root(project_root):
        rejection_reasons.append("project_resource_root_unavailable")
    else:
        native_roots.append(
            ProductNativeResourceRootSpec(
                handle_id="coding-project-standard",
                root=project_root,
                source_class="project_local",
                root_kind="standard",
            )
        )

    if rejection_reasons:
        raise CodingResourceCatalogShadowAdmissionError(rejection_reasons)

    embedded = tuple(
        _capture_built_in_collection(package, source_root_order=index)
        for index, package in enumerate(receipt.built_in_resource_packages)
    )
    return InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision=_CODING_SHADOW_POLICY_REVISION,
            native_roots=tuple(native_roots),
            embedded_collections=embedded,
            context_file_names=receipt.context_file_names,
        )
    )


def _capture_built_in_collection(
    import_path: str,
    *,
    source_root_order: int,
) -> ProductEmbeddedResourceCollectionSpec:
    collection_id = f"coding-built-in-{source_root_order}"
    files = capture_built_in_resource_package_files(
        BuiltInResourcePackage(name=collection_id, package=import_path)
    )
    return ProductEmbeddedResourceCollectionSpec(
        collection_id=collection_id,
        embedded_revision=_embedded_revision(import_path, files),
        files=files,
        source_root_order=source_root_order,
    )


def _embedded_revision(import_path: str, files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(import_path.encode("utf-8"))
    for path, body in sorted(files.items()):
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(body).digest())
    return f"sha256:{digest.hexdigest()}"


def _is_admissible_native_root(root: Path) -> bool:
    return root.is_dir() and not root.is_symlink()


__all__ = [
    "CodingResourceCatalogShadowAdmissionError",
    "prepare_coding_initial_resource_catalog_shadow_adapter",
]
