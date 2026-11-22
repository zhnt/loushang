"""Recheck pinned Session authorities and observe current composition evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loushang.harness.package_product._selected_plugin_revisions import (
    ProductSessionSelection,
    SelectionFailure,
    translate_selection_failure,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductPluginDesiredSelectionV1,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.session.composition_evidence import (
    observe_session_composition_evidence,
    publish_composition_startup,
)

if TYPE_CHECKING:
    from loushang.coding.composition.base_product import (
        CodingBaseProductSessionAssembly,
    )
    from loushang.coding.composition.capability_plugins import (
        CodingCapabilityPluginCompositionAssembly,
    )
    from loushang.coding.composition.external_data import (
        CodingExternalDataProductCompilation,
    )
    from loushang.coding.package.product_worker_session_composition import (
        CodingProductWorkerOrdinarySessionBinding,
    )
    from loushang.coding.session.agent_session import AgentSession
    from loushang.coding.session.manager import SessionManager
    from loushang.harness.capabilities.provider_binding import (
        CapabilityBundleProviderBinding,
    )


def require_prepared_selection(
    *,
    base: CodingBaseProductSessionAssembly | None,
    capabilities: CodingCapabilityPluginCompositionAssembly | None,
    runtime: PackageProductRuntimeBindingV1 | None,
    selected_capabilities: tuple[PackageProductSelectedPluginManifestV1, ...],
    external: CodingExternalDataProductCompilation | None,
    desired_selections: tuple[PackageProductPluginDesiredSelectionV1, ...],
    worker: CodingProductWorkerOrdinarySessionBinding | None,
    needs_worker_receipt: bool,
    workspace_binding: CapabilityBundleProviderBinding | None,
    has_peer_materializer: bool,
    has_catalog_bootstrap: bool,
    session_manager: SessionManager,
    product_id: str,
    product_label: str,
) -> ProductSessionSelection:
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
    if (
        base is not None
        and capabilities is not None
        and (
            capabilities.session_inputs is not base.session_inputs
            or capabilities.selection.plan != base.compilation.plan
            or capabilities.plugin_assembly.product_composition
            is not base.compilation.product_composition
        )
    ):
        raise ValueError(f"{product_label} Product Session composition changed")
    compilation = base.compilation if base is not None else None
    pinned = ProductSessionSelection(
        runtime=runtime,
        desired=desired_selections,
        base=compilation.selected_manifest if compilation is not None else None,
        capabilities=(
            compilation.selected_capability_manifests
            if compilation is not None
            else selected_capabilities
        ),
        external=(
            compilation.selected_external_data_manifests
            if compilation is not None
            else external.selected_manifests
            if external is not None
            else ()
        ),
        worker=worker.selected_worker_manifest if worker is not None else None,
    )
    if capabilities is not None and (
        base is not None or runtime is not None or selected_capabilities
    ):
        # Managed plugins have no Product Package pins.
        pinned.require_prepared_inventory(
            capabilities.runtime.packages, product_label=product_label
        )
    if base is not None:
        if has_peer_materializer:
            raise ValueError(
                f"{product_label} base Product cannot use a peer materializer"
            )
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
    return pinned


def require_current_selection(session: AgentSession, failure: SelectionFailure) -> None:
    # Construction-time admission cannot authorize work after root replacement.
    witness = session.coding_product_workspace_witness
    if witness is not None:
        witness.assert_current()
    session._product_session_selection.require_current(
        failure,
        check_desired=not session._coding_product_desired_preflight_completed,
    )
    deferred_lsp = session._deferred_lsp_slot
    active_lsp = deferred_lsp.active if deferred_lsp is not None else None
    if active_lsp is not None:
        with translate_selection_failure(failure, "deferred"):
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
    selected = session._product_session_selection
    worker_binding = session._coding_product_worker_ordinary_binding
    managed_revisions = (
        (
            (plugin_id, lease.package_revision, lease.instance_revision_ref)
            for plugin_id, lease in capability_assembly.management_leases.items()
        )
        if compilation is None
        and not selected.capabilities
        and capability_assembly is not None
        else ()
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
    base_publication = session._coding_base_owner_publication
    capability_publication = session._coding_capability_owner_publication
    return observe_session_composition_evidence(
        selected.manifests(),
        managed_revisions=managed_revisions,
        policy_revision=policy_revision,
        base_receipts=base_publication.receipts if base_publication is not None else (),
        capability_receipts=(
            capability_publication.receipts.values()
            if capability_publication is not None
            else ()
        ),
        catalog_snapshot=(
            prepared_catalog_snapshot
            if prepared_catalog_snapshot is not None
            else session._resource_catalog_snapshot
        ),
        catalog_schema=catalog_schema,
        worker_receipt=worker_binding.activation_receipt
        if worker_binding is not None
        else None,
    )


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
        had_entries_at_construction=lambda: (
            session._coding_composition_had_entries_at_construction
        ),
        build_current_receipt=lambda: session._build_current_coding_composition_receipt(
            prepared_catalog_snapshot=prepared_catalog_snapshot
        ),
        mark_prepared=session._coding_session_manager.mark_composition_startup_prepared,
        header_key=header_key,
        extension_type=extension_type,
        label=label,
    )
