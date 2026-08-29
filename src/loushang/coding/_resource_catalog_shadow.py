"""Private source-complete initial Resource Catalog adapter for Coding."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionKind,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.capabilities.model_input_contracts import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
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
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    ProductPluginSelectionSeed,
    assemble_product_composition,
)

_CODING_RESOURCE_CATALOG_POLICY_REVISION = "coding-resource-catalog-v3"
_CODING_PACKAGE_TRUST_CLASS = "coding-configured-published"
_CODING_PACKAGE_TRUST_POLICY_REVISION = "coding-resource-package-trust-v1"


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
) -> InitialResourceCatalogProductAdapter:
    """Consume exactly one owner-issued receipt for a Catalog-owned Session."""

    try:
        receipt = resource_loader._take_initial_resource_catalog_input_receipt()
    except (AttributeError, RuntimeError) as exc:
        raise CodingResourceCatalogAdmissionError(
            ("catalog_receipt_unavailable",)
        ) from exc
    return build_coding_initial_resource_catalog_adapter(
        receipt,
        disabled_skills=disabled_skills,
        product_composition=product_composition,
        product_selection=product_selection,
        product_scope_id=product_scope_id,
        package_admission_now=(
            int(time.time()) if admission_now is None else admission_now
        ),
    )


def build_coding_initial_resource_catalog_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None = None,
    disabled_skills: Sequence[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    product_selection: PluginSelection | None = None,
    package_admission_now: int | None = None,
) -> InitialResourceCatalogProductAdapter:
    """Map one exact loader receipt without reparsing its selected Bundle."""

    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise TypeError("Coding Resource Catalog requires an input receipt")
    if product_scope_id is not None and (
        not isinstance(product_scope_id, str) or not product_scope_id.strip()
    ):
        raise ValueError("Coding Resource Catalog Product scope is invalid")
    resolved_admission_now = (
        int(time.time()) if package_admission_now is None else package_admission_now
    )
    if product_composition is not None and not isinstance(
        product_composition,
        ProductCompositionCompilation,
    ):
        raise TypeError("Coding Resource Catalog Product composition is invalid")
    if product_selection is not None and not isinstance(
        product_selection,
        PluginSelection,
    ):
        raise TypeError("Coding Resource Catalog Product selection is invalid")
    if product_composition is not None and product_selection is not None:
        raise ValueError(
            "Coding Resource Catalog cannot receive both a composition and selection"
        )
    if product_composition is None:
        product_composition = _compile_coding_package_product_composition(
            receipt,
            product_scope_id=product_scope_id,
            evaluated_at=resolved_admission_now,
            product_selection=product_selection,
        )
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
        else _CODING_RESOURCE_CATALOG_POLICY_REVISION
    )
    if admissions and (
        isinstance(resolved_admission_now, bool)
        or not isinstance(resolved_admission_now, int)
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
    package_resources = _prepare_package_resources(
        receipt,
        admissions=admissions,
        product_policy_revision=product_policy_revision,
        admission_now=resolved_admission_now,
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
        raise CodingResourceCatalogAdmissionError(rejection_reasons)

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
            disabled_skill_selectors=tuple(item for item in disabled_skills if item),
        ),
        clock=lambda: resolved_admission_now,
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

    facts = tuple(
        fact
        for fact in receipt.package_resource_candidates
        if fact.resource_kind in {"prompt", "skill", "theme"}
    )
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


def prepare_coding_package_plugin_selection_seed(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None = None,
    selection_seed: ProductPluginSelectionSeed | None = None,
) -> ProductPluginSelectionSeed | None:
    """Combine configured Resource Plugins with one exact Product seed."""

    if selection_seed is not None:
        if not isinstance(selection_seed, ProductPluginSelectionSeed):
            raise TypeError("Coding package Product selection seed is invalid")
        if product_selection is not None:
            raise ValueError("Coding package selection received two Product seeds")
        product_selection = selection_seed.selection
    package_inputs = receipt.catalog_plugin_package_inputs
    if not package_inputs:
        return None
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError("Coding package Resource admission time must be an integer")

    seed_plugin_ids = (
        tuple(product_selection.plan.selected_plugin_ids)
        if product_selection is not None
        else ()
    )
    selected_inputs = tuple(
        sorted(
            (
                item
                for item in package_inputs
                if item.package.manifest.name in seed_plugin_ids
                or any(
                    reservation.kind == "resource_item"
                    for reservation in item.package.contribution_index.items
                )
            ),
            key=lambda item: item.package.manifest.name,
        )
    )
    if not selected_inputs:
        return None
    selected_input_by_id = {
        item.package.manifest.name: item for item in selected_inputs
    }
    seed_selected_contributions = (
        {
            (item.plugin_id, item.contribution_id)
            for item in product_selection.plan.selected_contributions
        }
        if product_selection is not None
        else set()
    )

    def selected_reservation(plugin_id: str, contribution_id: str, kind: str) -> bool:
        if plugin_id in seed_plugin_ids:
            return (plugin_id, contribution_id) in seed_selected_contributions
        return kind == "resource_item"

    missing_seed_plugins = sorted(set(seed_plugin_ids) - set(selected_input_by_id))
    if missing_seed_plugins:
        raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
    if product_selection is not None:
        selected_seed_digests = {
            candidate.package.manifest.name: candidate.package.content_digest
            for candidate in product_selection.candidates
        }
        if any(
            selected_input_by_id[plugin_id].package.content_digest
            != selected_seed_digests.get(plugin_id)
            for plugin_id in seed_plugin_ids
        ):
            raise CodingResourceCatalogAdmissionError(
                ("product_selected_package_revision_mismatch",)
            )
    scope_id = (
        product_selection.plan.context.scope_id
        if product_selection is not None
        else (
            product_scope_id.strip() if product_scope_id else f"session:{receipt.cwd}"
        )
    )
    seed_instance_refs = (
        {
            item.plugin_id: item
            for item in product_selection.plan.context.instance_revision_refs
        }
        if product_selection is not None
        else {}
    )
    seed_trust = (
        {item.plugin_id: item for item in product_selection.plan.source_trust_snapshots}
        if product_selection is not None
        else {}
    )
    context = (
        product_selection.plan.context
        if product_selection is not None
        else PluginPreflightContextV1(
            product_id="coding",
            scope_id=scope_id,
            policy_revision=_CODING_RESOURCE_CATALOG_POLICY_REVISION,
            instance_revision_refs=tuple(
                PluginInstanceRevisionRef(
                    instance_id=f"{item.package.manifest.name}@{scope_id}",
                    plugin_id=item.package.manifest.name,
                    revision=1,
                )
                for item in selected_inputs
            ),
        )
    )
    plan = PluginSelectionPlanV2(
        context=replace(
            context,
            instance_revision_refs=tuple(
                seed_instance_refs.get(item.package.manifest.name)
                or PluginInstanceRevisionRef(
                    instance_id=f"{item.package.manifest.name}@{scope_id}",
                    plugin_id=item.package.manifest.name,
                    revision=1,
                )
                for item in selected_inputs
            ),
        ),
        selected_plugin_ids=tuple(
            item.package.manifest.name for item in selected_inputs
        ),
        selected_contributions=tuple(
            PluginContributionRef(
                item.package.manifest.name,
                reservation.contribution_id,
            )
            for item in selected_inputs
            for reservation in item.package.contribution_index.items
            if selected_reservation(
                item.package.manifest.name,
                reservation.contribution_id,
                reservation.kind,
            )
        ),
        source_trust_snapshots=tuple(
            seed_trust.get(item.package.manifest.name)
            or PluginSourceTrustSnapshotV1(
                plugin_id=item.package.manifest.name,
                package_source_identity=item.binding.source_identity,
                source_trust_class=_CODING_PACKAGE_TRUST_CLASS,
                source_trust_policy_revision=_CODING_PACKAGE_TRUST_POLICY_REVISION,
                trusted=True,
            )
            for item in selected_inputs
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=item.package.manifest.name,
                    contribution_id=reservation.contribution_id,
                    configuration=reservation.configuration,
                )
                for item in selected_inputs
                for reservation in item.package.contribution_index.items
                if selected_reservation(
                    item.package.manifest.name,
                    reservation.contribution_id,
                    reservation.kind,
                )
            )
        ),
        allowed_authority_ceiling=(
            product_selection.plan.allowed_authority_ceiling
            if product_selection is not None
            else ()
        ),
    )
    selection = PluginDeclarationHost().resolve(
        tuple(item.package for item in selected_inputs),
        bindings=tuple(item.binding for item in selected_inputs),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    if not isinstance(selection, PluginSelection):
        raise CodingResourceCatalogAdmissionError(
            ("package_declaration_selection_incomplete",)
        )

    candidates = tuple(
        prepare_owner_contribution_candidate(selection, item)
        for item in selection.candidates
    )
    owner_collections: dict[tuple[str, OwnerContributionKind], set[str]] = {}
    owner_trust_classes: dict[tuple[str, OwnerContributionKind], set[str]] = {}
    for candidate in candidates:
        contribution = candidate.contribution
        if not isinstance(
            contribution,
            ResourceContributionSpec | CatalogConsumerContributionSpec,
        ):
            raise CodingResourceCatalogAdmissionError(
                ("invalid_package_resource_declaration",)
            )
        owner_key = (candidate.owner_id, candidate.contribution_kind)
        owner_collections.setdefault(owner_key, set()).add(contribution.collection_id)
        owner_trust_classes.setdefault(owner_key, set()).add(
            candidate.source_trust_class
        )
    owner_bindings = tuple(
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                OwnerContributionPolicy(
                    owner_id=owner_key[0],
                    contribution_kind=owner_key[1],
                    product_id="coding",
                    policy_revision=(
                        f"{owner_key[0]}-{owner_key[1]}-coding-ingress-v1"
                    ),
                    revocation_epoch=0,
                    allowed_source_trust_classes=tuple(
                        sorted(owner_trust_classes[owner_key])
                    ),
                    allowed_collection_ids=tuple(sorted(collection_ids)),
                    allowed_requirement_bindings=("direct",),
                    consumer_scope="session",
                    consumer_refresh_boundary="sealed",
                )
            )
        )
        for owner_key, collection_ids in sorted(owner_collections.items())
    )
    return ProductPluginSelectionSeed(
        selection=selection,
        packages=tuple(item.package for item in selected_inputs),
        bindings=tuple(item.binding for item in selected_inputs),
        owner_bindings=owner_bindings,
    )


def _compile_coding_package_product_composition(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None = None,
) -> ProductCompositionCompilation | None:
    seed = prepare_coding_package_plugin_selection_seed(
        receipt,
        product_scope_id=product_scope_id,
        evaluated_at=evaluated_at,
        product_selection=product_selection,
    )
    if seed is None:
        return None
    request = ProductCompositionAssemblyRequest(
        selection=seed.selection,
        owner_bindings=seed.owner_bindings,
        mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        definitions=(
            MODEL_INPUT_CAPABILITY_DEFINITION,
            WORKSPACE_CAPABILITY_DEFINITION,
        ),
    )
    return assemble_product_composition(request, evaluated_at=evaluated_at)


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
    "CodingResourceCatalogAdmissionError",
    "prepare_coding_initial_resource_catalog_adapter",
]
