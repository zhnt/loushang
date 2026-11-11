"""Receipt-to-Catalog binding over the existing loader and source owners."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    ResourceContributionSpec,
)
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductSelection,
    ProductAdmittedPackageResourceSpec,
    ProductEmbeddedResourceCollectionSpec,
    ProductNativeResourceRootSpec,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources._catalog_embedded_source import (
    capture_built_in_resource_package_files,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.builtin import BuiltInResourcePackage
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle


def _select_loader_catalog_inputs(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_id: str,
    product_policy_revision: str,
    product_composition: ProductCompositionCompilation | None,
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] | None,
    admissions: tuple[OwnerContributionAdmissionRecord, ...],
    resolved_admission_now: int | None,
    include_native_resources: bool,
    include_package_resources: bool,
    include_embedded_resources: bool,
    disabled_skills: Sequence[str],
    reject: Callable[[Sequence[str]], Exception],
) -> InitialResourceCatalogProductSelection:
    """Bind exact observed sources; Product retains selection and error policy."""

    rejection_reasons: list[str] = []
    if (
        product_composition is not None
        and product_composition.authority_context.product_id != product_id
    ):
        rejection_reasons.append("foreign_product_composition")
    if receipt.has_temporary_inputs and any(
        (
            include_native_resources,
            include_package_resources,
            include_embedded_resources,
        )
    ):
        rejection_reasons.append("temporary_sources")
    if receipt.has_resource_kind_switches:
        rejection_reasons.append("resource_kind_switches")
    if admissions and not include_package_resources:
        rejection_reasons.append("source_policy_package_admission_mismatch")
    if product_snapshot_resources is not None and any(
        (
            receipt.package_mounts,
            receipt.package_resource_candidates,
            receipt.package_diagnostic_codes,
            receipt.catalog_plugin_package_inputs,
        )
    ):
        rejection_reasons.append("legacy_package_inputs_with_product_snapshot")
    package_resources = (
        _prepare_package_resources(
            receipt,
            admissions=admissions,
            product_id=product_id,
            product_selection_present=product_composition is not None,
            product_policy_revision=product_policy_revision,
            admission_now=resolved_admission_now,
            rejection_reasons=rejection_reasons,
        )
        if (include_package_resources and product_snapshot_resources is None)
        else ()
    )

    native_roots: list[ProductNativeResourceRootSpec] = []
    for index, root in enumerate(
        receipt.user_resource_roots if include_native_resources else ()
    ):
        if not root.exists() or not root.is_dir():
            if root in receipt.explicit_user_resource_roots:
                rejection_reasons.append("explicit_user_root_unavailable")
            continue
        if root.is_symlink():
            rejection_reasons.append("symlinked_user_root")
            continue
        native_roots.append(
            ProductNativeResourceRootSpec(
                handle_id=f"{product_id}-user-{index}",
                root=root,
                source_class="user_global",
                root_kind=("standard" if receipt.no_context_files else "combined"),
                source_root_order=index,
            )
        )

    for index, root in enumerate(
        receipt.project_context_roots if include_native_resources else ()
    ):
        if not _is_admissible_native_root(root):
            rejection_reasons.append("project_context_root_unavailable")
            continue
        native_roots.append(
            ProductNativeResourceRootSpec(
                handle_id=f"{product_id}-project-context-{index}",
                root=root,
                source_class="project_local",
                root_kind="context",
                source_root_order=index,
            )
        )

    if include_native_resources:
        project_root = receipt.project_resource_root
        if not _is_admissible_native_root(project_root):
            rejection_reasons.append("project_resource_root_unavailable")
        else:
            native_roots.append(
                ProductNativeResourceRootSpec(
                    handle_id=f"{product_id}-project-standard",
                    root=project_root,
                    source_class="project_local",
                    root_kind="standard",
                )
            )

    if rejection_reasons:
        raise reject(rejection_reasons)

    embedded = (
        tuple(
            _capture_built_in_collection(
                package, source_root_order=index, product_id=product_id
            )
            for index, package in enumerate(receipt.built_in_resource_packages)
        )
        if include_embedded_resources
        else ()
    )
    return InitialResourceCatalogProductSelection(
        product_policy_revision=product_policy_revision,
        product_composition=product_composition,
        native_roots=tuple(native_roots),
        package_resources=package_resources,
        product_snapshot_resources=tuple(product_snapshot_resources or ()),
        embedded_collections=embedded,
        source_disposition=(
            "intentionally_empty"
            if not any(
                (
                    include_native_resources,
                    include_package_resources,
                    include_embedded_resources,
                )
            )
            else "selected"
        ),
        context_file_names=receipt.context_file_names,
        disabled_skill_selectors=tuple(item for item in disabled_skills if item),
    )


def _prepare_package_resources(
    receipt: ResourceCatalogInputReceipt,
    *,
    admissions: tuple[OwnerContributionAdmissionRecord, ...],
    product_id: str,
    product_selection_present: bool,
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
    if receipt.package_diagnostic_codes and not _only_empty_code_plugin_diagnostics(
        receipt,
        enabled_mounts=enabled_mounts,
    ):
        rejection_reasons.append("package_discovery_diagnostics")
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

    all_facts = tuple(receipt.package_resource_candidates)
    facts = tuple(
        fact for fact in all_facts if fact.resource_kind in {"prompt", "skill", "theme"}
    )
    matched_facts: set[int] = set()
    specs: list[ProductAdmittedPackageResourceSpec] = []
    for admission in admissions:
        contribution = admission.candidate.contribution
        if admission.product_id != product_id:
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
    # A selected Plugin may leave an exactly reserved optional Resource
    # unselected, but it may not silently acquire legacy filesystem content
    # that has no contribution reservation. Count reservations per verified
    # package/kind; selected declarations are already path-matched above.
    declared_counts: dict[tuple[int, str], int] = {}
    for plugin_input in receipt.catalog_plugin_package_inputs:
        for reservation in plugin_input.package.contribution_index.items:
            if reservation.kind != "resource_item" or not reservation.owner.startswith(
                "resources."
            ):
                continue
            key = (
                plugin_input.source_root_order,
                reservation.owner.removeprefix("resources."),
            )
            declared_counts[key] = declared_counts.get(key, 0) + 1
    selected_counts: dict[tuple[int, str], int] = {}
    for fact_index in matched_facts:
        fact = facts[fact_index]
        key = (fact.source_root_order, fact.resource_kind)
        selected_counts[key] = selected_counts.get(key, 0) + 1
    for key, count in selected_counts.items():
        declared_counts[key] = max(declared_counts.get(key, 0), count)
    observed_counts: dict[tuple[int, str], int] = {}
    for fact in all_facts:
        key = (fact.source_root_order, fact.resource_kind)
        observed_counts[key] = observed_counts.get(key, 0) + 1
    has_undeclared_fact = any(
        count > declared_counts.get(key, 0) for key, count in observed_counts.items()
    )
    if not product_selection_present and len(matched_facts) != len(facts):
        rejection_reasons.append("package_candidate_without_admission")
    elif has_undeclared_fact:
        rejection_reasons.append("undeclared_plugin_resources")
    if len(specs) != len(admissions):
        return ()
    return tuple(specs)


def _only_empty_code_plugin_diagnostics(
    receipt: ResourceCatalogInputReceipt,
    *,
    enabled_mounts: Mapping[int, PackageResourceMount],
) -> bool:
    """Ignore legacy empty-root noise for verified Plugins with no Resources."""

    diagnostic_codes = receipt.package_diagnostic_codes
    if not diagnostic_codes or any(
        code != "empty_package_root" for code in diagnostic_codes
    ):
        return False
    resource_orders = {
        fact.source_root_order for fact in receipt.package_resource_candidates
    }
    empty_mount_orders = set(enabled_mounts).difference(resource_orders)
    plugin_orders = {
        item.source_root_order for item in receipt.catalog_plugin_package_inputs
    }
    return len(diagnostic_codes) == len(
        empty_mount_orders
    ) and empty_mount_orders.issubset(plugin_orders)


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
    product_id: str,
) -> ProductEmbeddedResourceCollectionSpec:
    collection_id = f"{product_id}-built-in-{source_root_order}"
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
