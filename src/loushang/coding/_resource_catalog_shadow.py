"""Private source-complete initial Resource Catalog adapter for Coding."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

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
    ProductPluginPlanSeed,
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
    clock: Callable[[], int] | None = None,
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
        clock=clock,
    )


def build_coding_initial_resource_catalog_adapter(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None = None,
    disabled_skills: Sequence[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    product_selection: PluginSelection | None = None,
    package_admission_now: int | None = None,
    clock: Callable[[], int] | None = None,
) -> InitialResourceCatalogProductAdapter:
    """Map one exact loader receipt without reparsing its selected Bundle."""

    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise TypeError("Coding Resource Catalog requires an input receipt")
    if product_scope_id is not None and (
        not isinstance(product_scope_id, str) or not product_scope_id.strip()
    ):
        raise ValueError("Coding Resource Catalog Product scope is invalid")
    resolved_clock = clock or (lambda: int(time.time()))
    if not callable(resolved_clock):
        raise TypeError("Coding Resource Catalog clock is invalid")
    resolved_admission_now = (
        resolved_clock() if package_admission_now is None else package_admission_now
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
        product_selection_present=product_composition is not None,
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
        clock=resolved_clock,
    )


def _prepare_package_resources(
    receipt: ResourceCatalogInputReceipt,
    *,
    admissions: tuple[OwnerContributionAdmissionRecord, ...],
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
        fact
        for fact in all_facts
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
        count > declared_counts.get(key, 0)
        for key, count in observed_counts.items()
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
    return (
        len(diagnostic_codes) == len(empty_mount_orders)
        and empty_mount_orders.issubset(plugin_orders)
    )


def prepare_coding_package_plugin_plan_seed(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None = None,
    plan_seed: ProductPluginPlanSeed | None = None,
) -> ProductPluginPlanSeed | None:
    """Merge package facts into an inert plan without finalizing selection."""

    seed_plan: PluginSelectionPlanV2 | None
    if plan_seed is not None:
        if not isinstance(plan_seed, ProductPluginPlanSeed):
            raise TypeError("Coding package Product plan seed is invalid")
        if product_selection is not None:
            raise ValueError("Coding package selection received two Product seeds")
        seed_plan = plan_seed.plan
    else:
        seed_plan = product_selection.plan if product_selection is not None else None
    package_inputs = receipt.catalog_plugin_package_inputs
    if not package_inputs:
        return None
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError("Coding package Resource admission time must be an integer")

    seed_plugin_ids = (
        tuple(seed_plan.selected_plugin_ids)
        if seed_plan is not None
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
            for item in seed_plan.selected_contributions
        }
        if seed_plan is not None
        else set()
    )
    seed_configuration_by_ref = (
        {
            (item.plugin_id, item.contribution_id): item.configuration
            for item in seed_plan.effective_configuration_set.entries
        }
        if seed_plan is not None
        else {}
    )

    def selected_reservation(plugin_id: str, contribution_id: str, kind: str) -> bool:
        if plugin_id in seed_plugin_ids:
            return (plugin_id, contribution_id) in seed_selected_contributions
        return kind == "resource_item"

    selected_source_fingerprints = {
        item.package.manifest.name: {
            reservation.source_descriptor_fingerprint
            for reservation in item.package.contribution_index.items
            if selected_reservation(
                item.package.manifest.name,
                reservation.contribution_id,
                reservation.kind,
            )
        }
        for item in selected_inputs
    }

    missing_seed_plugins = sorted(set(seed_plugin_ids) - set(selected_input_by_id))
    if missing_seed_plugins:
        raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
    if seed_plan is not None:
        if plan_seed is not None:
            selected_seed_digests = {
                package.manifest.name: package.content_digest
                for package in plan_seed.packages
            }
        else:
            assert product_selection is not None
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
        seed_plan.context.scope_id
        if seed_plan is not None
        else (
            product_scope_id.strip() if product_scope_id else f"session:{receipt.cwd}"
        )
    )
    seed_instance_refs = (
        {
            item.plugin_id: item
            for item in seed_plan.context.instance_revision_refs
        }
        if seed_plan is not None
        else {}
    )
    seed_trust = (
        {item.plugin_id: item for item in seed_plan.source_trust_snapshots}
        if seed_plan is not None
        else {}
    )
    context = (
        seed_plan.context
        if seed_plan is not None
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
                    configuration=seed_configuration_by_ref.get(
                        (
                            item.package.manifest.name,
                            reservation.contribution_id,
                        ),
                        reservation.configuration,
                    ),
                )
                for item in selected_inputs
                for reservation in item.package.contribution_index.items
                if reservation.source_descriptor_fingerprint
                in selected_source_fingerprints[item.package.manifest.name]
            )
        ),
        allowed_authority_ceiling=(
            seed_plan.allowed_authority_ceiling
            if seed_plan is not None
            else ()
        ),
    )
    configured_resource_owners = {
        reservation.owner
        for item in selected_inputs
        if item.package.manifest.name not in seed_plugin_ids
        for reservation in item.package.contribution_index.items
        if reservation.kind == "resource_item"
    }
    owner_bindings = tuple(
        _extend_owner_binding_for_configured_resources(item)
        if item.owner_key[0] in configured_resource_owners
        and item.owner_key[1] == "resource_item"
        else item
        for item in (plan_seed.owner_bindings if plan_seed is not None else ())
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple(item.package for item in selected_inputs),
        bindings=tuple(item.binding for item in selected_inputs),
        owner_bindings=owner_bindings,
    )


def _extend_owner_binding_for_configured_resources(
    binding: ProductContributionOwnerBinding,
) -> ProductContributionOwnerBinding:
    """Make configured-package trust explicit while the plan is still inert."""

    policy = binding.authority.policy
    if _CODING_PACKAGE_TRUST_CLASS in policy.allowed_source_trust_classes:
        return binding
    return ProductContributionOwnerBinding(
        authority=OwnerContributionAuthority(
            replace(
                policy,
                policy_revision=f"{policy.policy_revision}+configured-resources",
                allowed_source_trust_classes=tuple(
                    sorted(
                        (
                            *policy.allowed_source_trust_classes,
                            _CODING_PACKAGE_TRUST_CLASS,
                        )
                    )
                ),
            )
        ),
        admission_ttl_seconds=binding.admission_ttl_seconds,
    )


def finalize_coding_package_plugin_plan_seed(
    seed: ProductPluginPlanSeed,
    *,
    resolve: Callable[[ProductPluginPlanSeed], PluginSelection] | None = None,
) -> ProductPluginSelectionSeed:
    """Finalize a complete package plan exactly once, then bind its owners."""

    if not isinstance(seed, ProductPluginPlanSeed):
        raise TypeError("Coding package Product plan seed is invalid")
    if resolve is None:
        outcome = PluginDeclarationHost().resolve(
            seed.packages,
            bindings=seed.bindings,
            plan=seed.plan,
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        if not isinstance(outcome, PluginSelection):
            raise CodingResourceCatalogAdmissionError(
                ("package_declaration_selection_incomplete",)
            )
        selection = outcome
    else:
        if not callable(resolve):
            raise TypeError("Coding package Product selection resolver is invalid")
        selection = resolve(seed)
        if not isinstance(selection, PluginSelection) or selection.plan != seed.plan:
            raise CodingResourceCatalogAdmissionError(
                ("package_declaration_selection_mismatch",)
            )
    return complete_coding_package_plugin_selection_seed(seed, selection=selection)


def complete_coding_package_plugin_selection_seed(
    seed: ProductPluginPlanSeed,
    *,
    selection: PluginSelection,
) -> ProductPluginSelectionSeed:
    """Attach exact contribution owners to one already-finalized selection."""

    if not isinstance(seed, ProductPluginPlanSeed):
        raise TypeError("Coding package Product plan seed is invalid")
    if not isinstance(selection, PluginSelection) or selection.plan != seed.plan:
        raise ValueError("Coding package Product selection does not match its plan")
    candidates = tuple(
        prepare_owner_contribution_candidate(selection, item)
        for item in selection.candidates
        if item.declaration.kind in {"resource_item", "tool_pack", "command_pack"}
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
    supplied: dict[
        tuple[str, OwnerContributionKind], ProductContributionOwnerBinding
    ] = {}
    for binding in seed.owner_bindings:
        owner_id, raw_contribution_kind, _ = binding.owner_key
        if raw_contribution_kind not in {
            "resource_item",
            "tool_pack",
            "command_pack",
        }:
            raise CodingResourceCatalogAdmissionError(
                ("invalid_product_owner_binding_kind",)
            )
        contribution_kind = cast(
            OwnerContributionKind,
            raw_contribution_kind,
        )
        owner_key = (owner_id, contribution_kind)
        if owner_key in supplied:
            raise CodingResourceCatalogAdmissionError(
                ("duplicate_product_owner_binding",)
            )
        supplied[owner_key] = binding

    if set(supplied) - set(owner_collections):
        raise CodingResourceCatalogAdmissionError(
            ("product_owner_binding_extra",)
        )

    owner_bindings_list: list[ProductContributionOwnerBinding] = []
    for owner_key, collection_ids in sorted(owner_collections.items()):
        supplied_binding = supplied.get(owner_key)
        if supplied_binding is not None:
            if not _owner_binding_covers(
                supplied_binding,
                owner_id=owner_key[0],
                contribution_kind=owner_key[1],
                trust_classes=owner_trust_classes[owner_key],
                collection_ids=collection_ids,
            ):
                raise CodingResourceCatalogAdmissionError(
                    ("product_owner_binding_boundary_mismatch",)
                )
            owner_bindings_list.append(supplied_binding)
            continue
        if (
            owner_key[1] != "resource_item"
            or owner_trust_classes[owner_key] != {_CODING_PACKAGE_TRUST_CLASS}
        ):
            raise CodingResourceCatalogAdmissionError(
                ("product_owner_binding_missing",)
            )
        owner_bindings_list.append(
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
        )
    owner_bindings = tuple(owner_bindings_list)
    return ProductPluginSelectionSeed(
        selection=selection,
        packages=seed.packages,
        bindings=seed.bindings,
        owner_bindings=owner_bindings,
    )


def _owner_binding_covers(
    binding: ProductContributionOwnerBinding,
    *,
    owner_id: str,
    contribution_kind: OwnerContributionKind,
    trust_classes: set[str],
    collection_ids: set[str],
) -> bool:
    policy = binding.authority.policy
    return (
        policy.owner_id == owner_id
        and policy.contribution_kind == contribution_kind
        and policy.product_id == "coding"
        and set(policy.allowed_source_trust_classes) == trust_classes
        and set(policy.allowed_collection_ids) == collection_ids
        and policy.allowed_requirement_bindings == ("direct",)
        and policy.consumer_scope == "session"
        and policy.consumer_refresh_boundary == "sealed"
    )


def _compile_coding_package_product_composition(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None = None,
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
    "InitialResourceCatalogProductAdapter",
    "ResourceCatalogInputReceipt",
    "prepare_coding_initial_resource_catalog_adapter",
]
