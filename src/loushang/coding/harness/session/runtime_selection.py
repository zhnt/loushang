"""Recheck pinned Session authorities and observe current composition evidence."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources._catalog_records import (
    ResourceCatalogSnapshot,
    fingerprint_catalog_value,
)

if TYPE_CHECKING:
    from loushang.coding.session.agent_session import AgentSession

SelectionPhase = Literal[
    "worker", "desired", "base", "capability", "selected", "deferred"
]
SelectionError = PackageProductRuntimeActivationError | PackageProductRuntimeReadError
SelectionFailure = Callable[
    [SelectionPhase, SelectionError, PackageProductSelectedPluginManifestV1 | None],
    BaseException,
]


def require_current_selection(session: AgentSession, failure: SelectionFailure) -> None:
    @contextmanager
    def check(
        phase: SelectionPhase,
        selected: PackageProductSelectedPluginManifestV1 | None = None,
    ) -> Iterator[None]:
        try:
            yield
        except (
            PackageProductRuntimeActivationError,
            PackageProductRuntimeReadError,
        ) as exc:
            raise failure(phase, exc, selected) from exc

    # Construction-time admission cannot authorize work after root replacement.
    witness = session.coding_product_workspace_witness
    if witness is not None:
        witness.assert_current()
    product_runtime = session._coding_base_product_runtime_binding
    product_compilation = session._coding_base_product_compilation
    worker_binding = session._coding_product_worker_ordinary_binding
    if product_runtime is not None:
        if (
            worker_binding is not None
            and worker_binding.selected_worker_manifest is not None
        ):
            with check("worker"):
                product_runtime.assert_selected_plugin_manifest_current(
                    worker_binding.selected_worker_manifest
                )
        if not session._coding_product_desired_preflight_completed:
            for selection in session._coding_product_desired_selections:
                with check("desired"):
                    product_runtime.assert_plugin_desired_selection_current(selection)
        if product_compilation is not None:
            with check("base"):
                product_runtime.assert_selected_plugin_manifest_current(
                    product_compilation.selected_manifest
                )
            for selected in product_compilation.selected_capability_manifests:
                with check("capability", selected):
                    product_runtime.assert_selected_plugin_manifest_current(selected)
        else:
            external = session._coding_external_data_product_compilation
            for selected in (
                *session._coding_selected_capability_manifests,
                *(external.selected_manifests if external is not None else ()),
            ):
                with check("selected"):
                    product_runtime.assert_selected_plugin_manifest_current(selected)
    deferred_lsp = session._deferred_lsp_slot
    active_lsp = deferred_lsp.active if deferred_lsp is not None else None
    if active_lsp is not None:
        with check("deferred"):
            active_lsp.assert_current()


def observe_composition_selection(
    session: AgentSession,
    *,
    prepared_catalog_snapshot: object | None,
    catalog_schema: str,
) -> dict[str, object]:
    """Return detached facts without opening or mutating the historical log."""
    compilation = session._coding_base_product_compilation
    external_compilation = session._coding_external_data_product_compilation
    capability_assembly = session._coding_capability_plugin_assembly
    selected = (
        (
            compilation.selected_manifest,
            *compilation.selected_capability_manifests,
            *compilation.selected_external_data_manifests,
        )
        if compilation is not None
        else (
            *session._coding_selected_capability_manifests,
            *(
                external_compilation.selected_manifests
                if external_compilation is not None
                else ()
            ),
        )
    )
    worker_binding = session._coding_product_worker_ordinary_binding
    if (
        worker_binding is not None
        and worker_binding.selected_worker_manifest is not None
    ):
        selected = (*selected, worker_binding.selected_worker_manifest)
    revisions = [
        {
            "pluginId": item.manifest.name,
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                item.snapshot.package_revision
            ),
            "instanceRevisionRef": item.snapshot.instance_revision_ref.to_dict(),
        }
        for item in selected
    ]
    if (
        compilation is None
        and not session._coding_selected_capability_manifests
        and capability_assembly is not None
    ):
        revisions.extend(
            {
                "pluginId": plugin_id,
                "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                    lease.package_revision
                ),
                "instanceRevisionRef": lease.instance_revision_ref.to_dict(),
            }
            for plugin_id, lease in capability_assembly.management_leases.items()
        )
    revisions = sorted(
        revisions,
        key=lambda item: str(item["pluginId"]),
    )
    policy_revision = (
        compilation.plan.context.policy_revision
        if compilation is not None
        else external_compilation.product_composition.authority_context.product_policy_revision
        if external_compilation is not None
        else capability_assembly.selection.plan.context.policy_revision
        if capability_assembly is not None
        else None
    )
    receipts = (
        *(
            session._coding_base_owner_publication.receipts
            if session._coding_base_owner_publication is not None
            else ()
        ),
        *(
            receipt
            for group in (
                session._coding_capability_owner_publication.receipts
                if session._coding_capability_owner_publication is not None
                else {}
            ).values()
            for receipt in group
        ),
    )
    generations = sorted(
        (
            {
                "ownerReference": receipt.owner_reference,
                "ownerGenerationReference": receipt.owner_generation_reference,
                "contributionIds": list(receipt.contribution_ids),
            }
            for receipt in receipts
        ),
        key=lambda item: (
            str(item["ownerReference"]),
            str(item["ownerGenerationReference"]),
        ),
    )
    catalog_snapshot = (
        prepared_catalog_snapshot
        if prepared_catalog_snapshot is not None
        else session._resource_catalog_snapshot
    )
    catalog_fingerprint = (
        fingerprint_catalog_value(
            catalog_schema,
            {
                "activationPolicyFingerprint": (
                    catalog_snapshot.activation_policy_fingerprint
                ),
                "mergePolicyRevision": catalog_snapshot.merge_policy_revision,
                "effectiveEntries": [
                    {
                        "identity": item.identity.to_payload(),
                        "modelInvocable": item.model_invocable,
                        "candidates": [
                            {
                                "canonicalName": candidate.canonical_name,
                                "description": candidate.description,
                                "mediaType": candidate.media_type,
                                "sourceClass": candidate.source_class,
                                "sourceRootOrder": candidate.source_root_order,
                                "expectedContentDigest": candidate.expected_content_digest,
                                "expectedContentLength": candidate.expected_content_length,
                                "invocationPolicy": candidate.invocation_policy.to_payload(),
                            }
                            for candidate in sorted(
                                (
                                    catalog_snapshot.candidate_by_fingerprint(
                                        fingerprint
                                    )
                                    for fingerprint in item.candidate_fingerprints
                                ),
                                key=lambda candidate: (
                                    candidate.canonical_name,
                                    candidate.source_class,
                                    candidate.expected_content_digest or "",
                                ),
                            )
                        ],
                    }
                    for item in catalog_snapshot.effective_entries
                ],
            },
        )
        if isinstance(catalog_snapshot, ResourceCatalogSnapshot)
        else None
    )
    worker_receipt = (
        worker_binding.activation_receipt if worker_binding is not None else None
    )
    worker_selection: dict[str, object] | None = (
        {
            "pluginId": worker_receipt.policy.plugin_id,
            "receiptFingerprint": worker_receipt.fingerprint,
            "productPolicyRevision": worker_receipt.policy.product_policy_revision,
            "nativeProfileId": worker_receipt.policy.native_profile_id,
            "selectedLocatorRevision": worker_receipt.policy.selected_locator_revision,
            "selectedLocatorFingerprint": (
                worker_receipt.policy.selected_locator_fingerprint
            ),
            "workerConfigurationFingerprint": (
                worker_receipt.policy.worker_configuration_fingerprint
            ),
        }
        if worker_receipt is not None
        else None
    )
    evidence: dict[str, object] = {
        "productPolicyRevision": policy_revision,
        "catalogSelectionFingerprint": catalog_fingerprint,
        "selectedRevisions": revisions,
        "ownerGenerations": generations,
    }
    if worker_selection is not None:
        evidence["workerSelection"] = worker_selection
    return evidence
