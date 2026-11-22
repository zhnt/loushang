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
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.session.composition_evidence import (
    catalog_composition_selection_fingerprint,
    composition_generation_evidence,
    composition_manifest_revision_evidence,
    publish_composition_startup,
    worker_composition_selection_evidence,
)

if TYPE_CHECKING:
    from loushang.coding.composition.base_product import (
        CodingBaseProductCompilation,
        CodingBaseProductSessionAssembly,
    )
    from loushang.coding.composition.capability_plugins import (
        CodingCapabilityPluginCompositionAssembly,
    )
    from loushang.coding.package.product_worker_session_composition import (
        CodingProductWorkerOrdinarySessionBinding,
    )
    from loushang.coding.session.agent_session import AgentSession
    from loushang.coding.session.manager import SessionManager
    from loushang.harness.capabilities.provider_binding import (
        CapabilityBundleProviderBinding,
    )

SelectionPhase = Literal[
    "worker", "desired", "base", "capability", "selected", "deferred"
]
SelectionError = PackageProductRuntimeActivationError | PackageProductRuntimeReadError
SelectionFailure = Callable[
    [SelectionPhase, SelectionError, PackageProductSelectedPluginManifestV1 | None],
    BaseException,
]


def _selected_base_manifests(
    compilation: CodingBaseProductCompilation,
) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
    return (
        compilation.selected_manifest,
        *compilation.selected_capability_manifests,
        *compilation.selected_external_data_manifests,
    )


def require_prepared_selection(
    *,
    base: CodingBaseProductSessionAssembly | None,
    capabilities: CodingCapabilityPluginCompositionAssembly | None,
    runtime: PackageProductRuntimeBindingV1 | None,
    selected_capabilities: tuple[PackageProductSelectedPluginManifestV1, ...],
    worker: CodingProductWorkerOrdinarySessionBinding | None,
    needs_worker_receipt: bool,
    workspace_binding: CapabilityBundleProviderBinding | None,
    has_peer_materializer: bool,
    has_catalog_bootstrap: bool,
    session_manager: SessionManager,
    product_id: str,
    product_label: str,
) -> None:
    """Admit the original prepared graph and package evidence as one Session."""
    if worker is not None:
        from loushang.coding.package.product_worker_session_composition import (
            CodingProductWorkerOrdinarySessionBinding,
            validate_coding_product_worker_ordinary_session_inputs,
        )

        if (
            not isinstance(worker, CodingProductWorkerOrdinarySessionBinding)
            or base is None
            or worker.ordinary is not base.session_inputs
            or workspace_binding is not base.workspace_binding
            or worker.workspace_binding is not workspace_binding
        ):
            raise ValueError(f"{product_label} Product Worker ordinary Session changed")
        validate_coding_product_worker_ordinary_session_inputs(
            ordinary=worker.ordinary,
            combined=worker.combined,
            workspace_binding=workspace_binding,
        )
    if needs_worker_receipt and (worker is None or worker.activation_receipt is None):
        raise ValueError(
            f"{product_label} Worker turn Tool requires a selected Worker receipt"
        )
    if base is not None and capabilities is not None and (
        capabilities.session_inputs is not base.session_inputs
        or capabilities.selection.plan != base.compilation.plan
        or capabilities.plugin_assembly.product_composition
        is not base.compilation.product_composition
    ):
        raise ValueError(f"{product_label} Product Session composition changed")
    if capabilities is not None and (
        base is not None or runtime is not None or selected_capabilities
    ):
        # The managed path has no Product package evidence. The capability-only
        # Product path compares a set, including an empty selection.
        selected = (
            _selected_base_manifests(base.compilation)
            if base is not None
            else selected_capabilities
        )
        packages = capabilities.runtime.packages
        inventory_changed = (
            tuple(package.manifest.name for package in packages)
            != tuple(sorted(item.manifest.name for item in selected))
            if base is not None
            else len(packages) != len(selected)
        )
        if inventory_changed or {
            package.manifest.name: package.content_digest for package in packages
        } != {
            item.manifest.name: item.snapshot.root_ref.artifact_digest
            for item in selected
        }:
            raise ValueError(f"{product_label} Product Session packages changed")
    if base is not None:
        if has_peer_materializer:
            raise ValueError(f"{product_label} base Product cannot use a peer materializer")
        if not has_catalog_bootstrap:
            raise ValueError(f"{product_label} base Product requires Catalog bootstrap")
        if workspace_binding is not base.workspace_binding:
            raise ValueError(f"{product_label} base Product workspace binding changed")
        if runtime is None:
            raise ValueError(f"{product_label} base Product requires runtime binding")
        if (
            base.compilation.plan.context.scope_id
            != f"session:{session_manager.get_header().conversation_id}"
        ):
            raise ValueError(f"{product_label} base Product Session identity changed")
    if runtime is not None and (
        not isinstance(runtime, PackageProductRuntimeBindingV1)
        or runtime.product_id != product_id
    ):
        raise ValueError(f"{product_label} Product runtime binding is invalid")


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
        _selected_base_manifests(compilation)
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
    revisions = composition_manifest_revision_evidence(selected)
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
    generations = composition_generation_evidence(receipts)
    catalog_snapshot = (
        prepared_catalog_snapshot
        if prepared_catalog_snapshot is not None
        else session._resource_catalog_snapshot
    )
    catalog_fingerprint = catalog_composition_selection_fingerprint(
        catalog_snapshot, catalog_schema=catalog_schema
    )
    worker_receipt = (
        worker_binding.activation_receipt if worker_binding is not None else None
    )
    worker_selection = worker_composition_selection_evidence(worker_receipt)
    evidence: dict[str, object] = {
        "productPolicyRevision": policy_revision,
        "catalogSelectionFingerprint": catalog_fingerprint,
        "selectedRevisions": revisions,
        "ownerGenerations": generations,
    }
    if worker_selection is not None:
        evidence["workerSelection"] = worker_selection
    return evidence


async def record_composition_startup(
    session: AgentSession,
    *,
    existing_only: bool,
    prepared_catalog_snapshot: object | None,
    header_key: str,
    extension_type: str,
    label: str,
) -> None:
    """Correlate sealed history before appending the first startup receipt."""
    plan = session._coding_composition_plan
    if plan is None or not session.session_manager.persist:
        return
    await publish_composition_startup(
        session.session_manager,
        set_id=plan.set_id,
        existing_only=existing_only,
        had_entries_at_construction=lambda: session._coding_composition_had_entries_at_construction,
        build_current_receipt=lambda: session._build_current_coding_composition_receipt(
            prepared_catalog_snapshot=prepared_catalog_snapshot
        ),
        mark_prepared=session._coding_session_manager.mark_composition_startup_prepared,
        header_key=header_key,
        extension_type=extension_type,
        label=label,
    )
