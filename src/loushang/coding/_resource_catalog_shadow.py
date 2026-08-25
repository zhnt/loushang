"""Private source-complete initial Resource Catalog adapter for Coding."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    ResourceContributionSpec,
)
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
    InitialResourceCatalogProductSelection,
    ProductAdmittedPackageResourceSpec,
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
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle

_CODING_SHADOW_POLICY_REVISION = "coding-resource-catalog-shadow-v2"


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
    product_composition: ProductCompositionCompilation | None = None,
) -> InitialResourceCatalogProductAdapter:
    """Consume exactly one owner-issued receipt for a private shadow Session."""

    return build_coding_initial_resource_catalog_shadow_adapter(
        resource_loader._take_initial_resource_catalog_input_receipt(),
        disabled_skills=disabled_skills,
        product_composition=product_composition,
        package_admission_now=int(time.time()),
    )


def build_coding_initial_resource_catalog_shadow_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    disabled_skills: Sequence[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    package_admission_now: int | None = None,
) -> InitialResourceCatalogProductAdapter:
    """Map one exact loader receipt without reparsing its selected Bundle."""

    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise TypeError("Coding Resource Catalog shadow requires an input receipt")
    if product_composition is not None and not isinstance(
        product_composition,
        ProductCompositionCompilation,
    ):
        raise TypeError("Coding Resource Catalog Product composition is invalid")
    admissions = (
        tuple(product_composition.resource_admissions)
        if product_composition is not None
        else ()
    )
    if any(
        not isinstance(item, OwnerContributionAdmissionRecord) for item in admissions
    ):
        raise TypeError("Coding Product composition Resource admissions are invalid")
    product_policy_revision = (
        product_composition.authority_context.product_policy_revision
        if product_composition is not None
        else _CODING_SHADOW_POLICY_REVISION
    )
    if admissions and (
        isinstance(package_admission_now, bool)
        or not isinstance(package_admission_now, int)
    ):
        raise TypeError("Coding package Resource admissions require an integer time")
    rejection_reasons: list[str] = []
    if (
        product_composition is not None
        and product_composition.authority_context.product_id != "coding"
    ):
        rejection_reasons.append("foreign_product_composition")
    if receipt.has_temporary_inputs:
        rejection_reasons.append("temporary_sources")
    if receipt.has_resource_kind_switches:
        rejection_reasons.append("resource_kind_switches")
    if any(item for item in disabled_skills):
        rejection_reasons.append("disabled_skills")
    package_resources = _prepare_package_resources(
        receipt,
        admissions=admissions,
        product_policy_revision=product_policy_revision,
        admission_now=package_admission_now,
        rejection_reasons=rejection_reasons,
    )

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
            product_policy_revision=product_policy_revision,
            product_composition=product_composition,
            native_roots=tuple(native_roots),
            package_resources=package_resources,
            embedded_collections=embedded,
            context_file_names=receipt.context_file_names,
        )
    )


def _prepare_package_resources(
    receipt: ResourceCatalogInputReceipt,
    *,
    admissions: tuple[OwnerContributionAdmissionRecord, ...],
    product_policy_revision: str,
    admission_now: int | None,
    rejection_reasons: list[str],
) -> tuple[ProductAdmittedPackageResourceSpec, ...]:
    enabled_mounts = {
        index: mount
        for index, mount in enumerate(receipt.package_mounts)
        if mount.enabled
    }
    if not enabled_mounts:
        if admissions:
            rejection_reasons.append("package_admissions_without_source")
        return ()
    if receipt.package_diagnostic_codes:
        rejection_reasons.append("package_discovery_diagnostics")
    if any(
        fact.resource_kind == "extension"
        for fact in receipt.package_resource_candidates
    ):
        rejection_reasons.append("package_extensions")
    if len({item.fingerprint for item in admissions}) != len(admissions):
        rejection_reasons.append("duplicate_package_admissions")
        return ()

    invalid_mounts = False
    verified_mounts: dict[
        int,
        tuple[PackageResourceMount, VerifiedRevisionHandle],
    ] = {}
    for index, mount in enabled_mounts.items():
        handle = mount.revision_handle
        if handle is None:
            rejection_reasons.append("unverified_package_sources")
            invalid_mounts = True
            continue
        if handle.closed:
            rejection_reasons.append("package_revision_unavailable")
            invalid_mounts = True
        if mount.root != handle.root:
            rejection_reasons.append("package_subroots")
            invalid_mounts = True
        verified_mounts[index] = (mount, handle)
    if invalid_mounts:
        return ()

    facts = receipt.package_resource_candidates
    matched_facts: set[int] = set()
    specs: list[ProductAdmittedPackageResourceSpec] = []
    for admission in admissions:
        contribution = admission.candidate.contribution
        if admission.product_id != "coding":
            rejection_reasons.append("foreign_package_admission")
            continue
        if admission.candidate.product_policy_revision != product_policy_revision:
            rejection_reasons.append("stale_package_admission_policy")
            continue
        if (
            admission.consumer_scope != "session"
            or admission.consumer_refresh_boundary != "sealed"
        ):
            rejection_reasons.append("unsealed_package_admission")
            continue
        assert admission_now is not None
        if not admission.issued_at <= admission_now < admission.expires_at:
            rejection_reasons.append("inactive_package_admission")
            continue
        if admission.contribution_kind != "resource_item" or not isinstance(
            contribution,
            ResourceContributionSpec,
        ):
            rejection_reasons.append("invalid_package_admission")
            continue
        if admission.owner_id != f"resources.{contribution.resource_kind}":
            rejection_reasons.append("foreign_package_resource_owner")
            continue
        if contribution.resource_kind not in {"prompt", "skill", "theme"}:
            rejection_reasons.append("unsupported_package_resource_kind")
            continue
        try:
            observed_paths = _package_admission_observed_paths(
                verified_mounts,
                contribution=contribution,
            )
        except ValueError:
            rejection_reasons.append("invalid_package_admission")
            continue
        matching = [
            (index, fact)
            for index, fact in enumerate(facts)
            if index not in matched_facts
            and fact.resource_kind == contribution.resource_kind
            and fact.package_content_digest
            == admission.candidate.package_content_digest
            and fact.source_path == observed_paths[fact.source_root_order]
        ]
        if len(matching) != 1:
            rejection_reasons.append("package_admission_candidate_mismatch")
            continue
        fact_index, fact = matching[0]
        _, revision_handle = verified_mounts[fact.source_root_order]
        matched_facts.add(fact_index)
        specs.append(
            ProductAdmittedPackageResourceSpec(
                admission=admission,
                revision_handle=revision_handle,
                source_root_order=fact.source_root_order,
            )
        )
    if len(matched_facts) != len(facts):
        rejection_reasons.append("package_candidate_without_admission")
    if len(specs) != len(admissions):
        return ()
    return tuple(specs)


def _package_admission_observed_paths(
    verified_mounts: Mapping[
        int,
        tuple[PackageResourceMount, VerifiedRevisionHandle],
    ],
    *,
    contribution: ResourceContributionSpec,
) -> dict[int, Path]:
    locator = canonical_plugin_relative_path(contribution.locator)
    observed_paths: dict[int, Path] = {}
    for root_order, (_, revision_handle) in verified_mounts.items():
        path = revision_handle.root.joinpath(*locator.parts)
        if (
            contribution.locator_kind == "directory"
            and contribution.resource_kind == "skill"
        ):
            path /= "SKILL.md"
        observed_paths[root_order] = path
    return observed_paths


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
