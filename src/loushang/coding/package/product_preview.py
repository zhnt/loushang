"""Inert Coding Product evidence for an already fenced Package namespace."""

from __future__ import annotations

import time as time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssemblyError as CodingBasePluginAssemblyError,
)
from loushang.coding.composition.base_product import (
    CodingBaseProductCompilation as CodingBaseProductCompilation,
)
from loushang.coding.composition.base_product import (
    compile_coding_base_product_selection as compile_coding_base_product_selection,
)
from loushang.coding.composition.base_product import (
    extend_coding_base_product_data_resources as extend_coding_base_product_data_resources,
)
from loushang.coding.composition.external_data import (
    CodingExternalDataProductCompilation as CodingExternalDataProductCompilation,
)
from loushang.coding.composition.external_data import (
    compile_coding_external_data_product_selection as compile_coding_external_data_product_selection,
)
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.plugin_manager.lifecycle import (
    _workspace_scope_id as _workspace_scope_id,
)
from loushang.coding.resources.catalog import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY as CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
)
from loushang.coding.resources.catalog import (
    CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY as CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
)
from loushang.coding.resources.catalog import (
    build_coding_initial_resource_catalog_adapter as build_coding_initial_resource_catalog_adapter,
)
from loushang.coding.resources.runtime import (
    CodingResourceLoader as CodingResourceLoader,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionError as ProductCompositionError,
)
from loushang.harness.environment.probe import (
    LocalHostEnvironmentProbe as LocalHostEnvironmentProbe,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs as PosixLocalWheelProductHostInputs,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    _LocalWheelSelectedManifestReader,
    bind_read_only_local_wheel_manifests,
)
from loushang.harness.package_product.product_worker_candidate import (
    WorkerPackageCandidateV1,
    read_selected_worker_candidate,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentResourceAdmissionV1,
    project_current_selection_evidence,
)
from loushang.harness.plugin_management.current_preview import (
    project_current_product_resource_facts as project_current_product_resource_facts,
)
from loushang.harness.plugin_management.current_preview import (
    project_current_product_resource_selections as project_current_product_resource_selections,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)

from .builtin_wheel import (
    coding_builtin_product_local_wheel_policy as coding_builtin_product_local_wheel_policy,
)
from .builtin_wheel import (
    inspect_posix_coding_base_product_wheel as inspect_posix_coding_base_product_wheel,
)
from .builtin_wheel import (
    inspect_posix_coding_capability_product_wheels as inspect_posix_coding_capability_product_wheels,
)
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    _extend_coding_product_source_policy,
)
from .product_worker_opt_in import CodingWorkerOptInDecisionV1, CodingWorkerOptInJournal

CodingDataResourceAdmissionPreviewV1 = PluginCurrentResourceAdmissionV1
CodingCurrentDataResourcePreviewV1 = PluginCurrentCompositionPreviewV1


_RESOURCE_PREVIEW_MAX_FILES = 64
_RESOURCE_PREVIEW_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerCandidateReadEvidenceV1:
    """Selected candidate identity observed without a Worker-use decision."""

    candidate: WorkerPackageCandidateV1
    artifact_digest: str
    native_platform: str


@dataclass(slots=True)
class CodingFencedProductReadOnlyPreviewOwner:
    """Hold the existing Product epoch while inspecting exact selected bytes."""

    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    policy: PackageProductLocalWheelPolicy
    selected_manifests: _LocalWheelSelectedManifestReader
    gc_gate: PluginPackageGcReservationJournal
    worker_candidates: bool = False

    def selected_worker_candidate(self, plugin_id: str) -> WorkerPackageCandidateV1:
        """Verify inert bytes of one currently selected Worker; grant no execution."""

        return self.selected_worker_candidate_evidence(plugin_id).candidate

    def selected_worker_candidate_evidence(
        self, plugin_id: str
    ) -> CodingWorkerCandidateReadEvidenceV1:
        """Preserve the Product-selected artifact and native profile identity."""

        if not self.worker_candidates:
            raise PermissionError("Worker candidate read was not selected")
        candidate, artifact_digest, native_platform = read_selected_worker_candidate(
            self.epoch_runtime,
            self.selected_manifests,
            self.policy,
            plugin_id,
        )
        return CodingWorkerCandidateReadEvidenceV1(
            candidate=candidate,
            artifact_digest=artifact_digest,
            native_platform=native_platform,
        )

    def worker_opt_in_decision(
        self, plugin_id: str
    ) -> CodingWorkerOptInDecisionV1 | None:
        """Read one existing Worker decision without conferring selection or use."""

        self.epoch_runtime.assert_current()
        decision = CodingWorkerOptInJournal(
            self.epoch_runtime.control_root / "product-state/worker-opt-in.jsonl",
            scope_id=self.policy.project_scope_id,
            gc_gate=self.gc_gate,
            store_id=self.epoch_runtime.registry.store_id,
        ).current_read_only(plugin_id)
        self.epoch_runtime.assert_current()
        return decision

    def preview_current_data_resources(
        self,
        *,
        workspace: Path,
        composition_set_id: str = "coding-standard",
        disabled_skills: tuple[str, ...] | None = None,
    ) -> CodingCurrentDataResourcePreviewV1:
        """Compile installed data under Product policy without live activation."""

        self.epoch_runtime.assert_current()
        if (
            not isinstance(workspace, Path)
            or not workspace.is_absolute()
            or workspace != workspace.resolve(strict=True)
            or self.policy.project_scope_id != _workspace_scope_id(workspace)
        ):
            raise ValueError("Coding Product preview workspace scope changed")
        composition_set = resolve_coding_composition_set(composition_set_id)
        if disabled_skills is not None and any(
            not isinstance(item, str) or not item for item in disabled_skills
        ):
            raise ValueError("Coding Product preview disabled Skills are invalid")
        desired = self.selected_manifests.root_reader.desired_state
        before, _ = desired.capture_read_only()
        base_key = PluginInstallationKeyV1(
            product_id=self.policy.product_id,
            installation_scope="workspace",
            scope_id=self.policy.project_scope_id,
            plugin_id="coding.base",
        )
        base_state = before.installation(base_key).selection.desired_state
        base_disabled = base_state == "installed_disabled"
        external_ids = self.selected_manifests.selected_external_data_plugin_ids()
        evaluated_at = int(time.time())
        compiled: (
            CodingBaseProductCompilation | CodingExternalDataProductCompilation | None
        ) = None
        compiled_plugin_ids: tuple[str, ...] = ()
        try:
            if base_state == "absent":
                raise CodingBasePluginAssemblyError(
                    "Coding Product base Plugin is not installed",
                    code="product_requested_base_not_installed",
                )
            if base_disabled:
                if external_ids:
                    compiled_plugin_ids = external_ids
                    compiled = compile_coding_external_data_product_selection(
                        tuple(
                            self.selected_manifests.capture_selected_manifest_for_plugin(
                                plugin_id,
                                max_files=_RESOURCE_PREVIEW_MAX_FILES,
                                max_total_bytes=_RESOURCE_PREVIEW_MAX_BYTES,
                            )
                            for plugin_id in external_ids
                        ),
                        composition_set=composition_set,
                        session_id="plugin-preview-current",
                        evaluated_at=evaluated_at,
                    )
            else:
                base = self.selected_manifests.capture_selected_manifest_for_plugin(
                    "coding.base",
                    max_files=_RESOURCE_PREVIEW_MAX_FILES,
                    max_total_bytes=_RESOURCE_PREVIEW_MAX_BYTES,
                )
                base_compiled = compile_coding_base_product_selection(
                    base,
                    composition_set,
                    installation_key=base.snapshot.installation_key,
                    session_id="plugin-preview-current",
                    host_environment=LocalHostEnvironmentProbe().detect(),
                    evaluated_at=evaluated_at,
                )
                compiled_plugin_ids = base_compiled.plan.selected_plugin_ids
                if external_ids:
                    compiled_plugin_ids = tuple(
                        sorted((*compiled_plugin_ids, *external_ids))
                    )
                    base_compiled = extend_coding_base_product_data_resources(
                        base_compiled,
                        tuple(
                            self.selected_manifests.capture_selected_manifest_for_plugin(
                                plugin_id,
                                max_files=_RESOURCE_PREVIEW_MAX_FILES,
                                max_total_bytes=_RESOURCE_PREVIEW_MAX_BYTES,
                            )
                            for plugin_id in external_ids
                        ),
                        evaluated_at=evaluated_at,
                    )
                    compiled_plugin_ids = base_compiled.plan.selected_plugin_ids
                compiled = base_compiled
        except (
            CodingBasePluginAssemblyError,
            ProductCompositionError,
        ) as exc:
            after, _ = desired.capture_read_only()
            self.epoch_runtime.assert_current()
            executable, gaps = _selection_evidence(
                self.policy,
                before,
                tuple(item.plugin_id for item in composition_set.plugin_requests),
            )
            if disabled_skills is not None:
                gaps.discard("disabled_skill_settings")
            gaps.add("resource_catalog_not_reached")
            if before.inventory_revision != after.inventory_revision:
                gaps.add("stale_snapshot")
            return CodingCurrentDataResourcePreviewV1(
                product_id=self.policy.product_id,
                scope_id=self.policy.project_scope_id,
                composition_set_id=composition_set.set_id,
                observed_at_unix_ns=time.time_ns(),
                desired_inventory_revision=before.inventory_revision,
                product_policy_revision=self.policy.policy_revision,
                product_authority_revision=self.policy.authority_revision,
                compiled_plugin_ids=compiled_plugin_ids,
                admitted_resources=(),
                catalog_resources=(),
                catalog_diagnostic_codes=(),
                requires_authorized_preflight=tuple(sorted(executable)),
                evidence_gaps=tuple(sorted(gaps)),
                disposition="blocked",
                blocking_owner="product_composition",
                blocking_code=exc.code,
                blocking_admission_fingerprints=(
                    exc.admission_fingerprints
                    if isinstance(exc, ProductCompositionError)
                    else ()
                ),
            )
        loader = CodingResourceLoader(workspace_root=workspace)
        receipt = loader.prepare_catalog_input_receipt(workspace)
        product_inputs = (
            compiled.product_resource_inputs() if compiled is not None else ()
        )
        adapter = build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id="plugin-preview-current",
            product_composition=(
                compiled.product_composition if compiled is not None else None
            ),
            product_snapshot_resources=(
                product_inputs if compiled is not None else None
            ),
            package_admission_now=evaluated_at,
            disabled_skills=disabled_skills or (),
            source_policy=(
                CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
                if compiled is None
                else CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
            ),
        )
        catalog_result = adapter.prepare_bootstrap_projection_with_receipt(
            product_id=self.policy.product_id,
            session_id="plugin-preview-current",
            cwd=workspace,
        )
        bundle = catalog_result.bundle
        catalog = catalog_result.catalog
        selections = project_current_product_resource_selections(
            catalog, product_inputs
        )
        after, _ = desired.capture_read_only()
        self.epoch_runtime.assert_current()
        executable, gaps = _selection_evidence(
            self.policy,
            before,
            tuple(item.plugin_id for item in composition_set.plugin_requests),
        )
        if disabled_skills is not None:
            gaps.discard("disabled_skill_settings")
        if before.inventory_revision != after.inventory_revision:
            gaps.add("stale_snapshot")
        admissions, catalog_resources = project_current_product_resource_facts(
            (
                compiled.product_composition.resource_admissions
                if compiled is not None
                else ()
            ),
            bundle,
        )
        return CodingCurrentDataResourcePreviewV1(
            product_id=self.policy.product_id,
            scope_id=self.policy.project_scope_id,
            composition_set_id=composition_set.set_id,
            observed_at_unix_ns=time.time_ns(),
            desired_inventory_revision=before.inventory_revision,
            product_policy_revision=self.policy.policy_revision,
            product_authority_revision=self.policy.authority_revision,
            compiled_plugin_ids=compiled_plugin_ids,
            admitted_resources=admissions,
            catalog_resources=catalog_resources,
            catalog_diagnostic_codes=tuple(
                sorted({item.code for item in bundle.diagnostics})
            ),
            catalog_generation=catalog.catalog_generation,
            catalog_snapshot_fingerprint=catalog.snapshot_fingerprint,
            selected_resources=tuple(
                sorted(
                    selections,
                    key=lambda item: (
                        item.installation_key.plugin_id,
                        item.contribution_id,
                    ),
                )
            ),
            requires_authorized_preflight=tuple(sorted(executable)),
            evidence_gaps=tuple(sorted(gaps)),
        )

    @classmethod
    def open(
        cls,
        layout: CodingPluginLifecycleStateLayout,
        *,
        workspace_guard: Callable[[], None] | None = None,
        worker_candidates: bool = False,
    ) -> CodingFencedProductReadOnlyPreviewOwner:
        if workspace_guard is not None:
            workspace_guard()
        if not isinstance(layout, CodingPluginLifecycleStateLayout):
            raise TypeError("Coding Plugin lifecycle layout is required")
        epoch = resolve_coding_package_epoch_layout(layout)
        runtime = PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs(), read_only=True
        )
        try:
            if workspace_guard is not None:
                workspace_guard()
            switch = runtime.cutover_result.switch_receipt
            if switch is None:
                raise ValueError("Coding Package Product root is not fenced")
            state_root = runtime.control_root / "product-state"
            source_root = runtime.control_root / "product-sources"
            runtime.require_existing_product_state_root()
            base = inspect_posix_coding_base_product_wheel(source_root)
            capabilities = inspect_posix_coding_capability_product_wheels(source_root)
            host = PosixLocalWheelProductHostInputs.current_host(
                max_transport_bytes=2 * 1024 * 1024
            )
            policy = coding_builtin_product_local_wheel_policy(
                base,
                capabilities,
                project_scope_id=layout.scope_id,
                resolution_environment_fingerprint=host.environment.fingerprint,
                policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                quota_profile_revision="coding-product-package-quota:1",
                authority_id="coding-product-local-source",
            )
            policy = _extend_coding_product_source_policy(
                policy,
                layout,
                runtime,
                state_root=state_root,
                source_root=source_root,
                namespace_id=switch.namespace_id,
                include_worker_candidates=worker_candidates,
                read_only=True,
            )
            selected_manifests, gc_gate = bind_read_only_local_wheel_manifests(
                runtime,
                policy=policy,
                plugin_store_root=epoch.epoch_root(switch.namespace_id),
                root_store_identity=f"coding-product-root-store:{epoch.store_id}",
            )
            runtime.assert_current()
            if workspace_guard is not None:
                workspace_guard()
            return cls(
                epoch_runtime=runtime,
                policy=policy,
                selected_manifests=selected_manifests,
                gc_gate=gc_gate,
                worker_candidates=worker_candidates,
            )
        except BaseException:
            runtime.close()
            raise

    def close(self) -> None:
        self.epoch_runtime.close()

    def __enter__(self) -> CodingFencedProductReadOnlyPreviewOwner:
        self.epoch_runtime.assert_current()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


def _selection_evidence(
    policy: PackageProductLocalWheelPolicy,
    desired_snapshot: PluginDesiredStateSnapshotV1,
    requested_plugin_ids: tuple[str, ...],
) -> tuple[set[str], set[str]]:
    return project_current_selection_evidence(
        policy,
        desired_snapshot,
        requested_plugin_ids,
        executable_trust_classes=frozenset(
            {"host-equivalent-local", "legacy-local-reacquired"}
        ),
        excluded_plugin_id="coding.base",
    )


__all__ = [
    "CodingCurrentDataResourcePreviewV1",
    "CodingDataResourceAdmissionPreviewV1",
    "CodingFencedProductReadOnlyPreviewOwner",
    "CodingWorkerCandidateReadEvidenceV1",
]
