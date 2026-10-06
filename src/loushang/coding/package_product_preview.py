"""Inert Coding Product evidence for an already fenced Package namespace."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import TracebackType

from loushang.harness.capabilities.consumer_requirements import ProductCompositionError
from loushang.harness.capabilities.contribution_admission import (
    ResourceContributionSpec,
)
from loushang.harness.environment.probe import LocalHostEnvironmentProbe
from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs,
    _LocalWheelSelectedManifestReader,
)
from loushang.harness.package_product.product_worker_candidate import (
    WorkerPackageCandidateV1,
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentResourceAdmissionV1,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
    PluginDesiredStateSnapshotV1,
)
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductSelectedRootReader,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PosixPackagePluginRootReadOnlyStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)

from ._base_plugin import CodingBasePluginAssemblyError
from ._base_product_composition import (
    CodingBaseProductCompilation,
    compile_coding_base_product_selection,
    extend_coding_base_product_data_resources,
)
from ._external_data_product_composition import (
    CodingExternalDataProductCompilation,
    compile_coding_external_data_product_selection,
)
from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from ._resource_catalog_shadow import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
    CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
    build_coding_initial_resource_catalog_adapter,
)
from .composition_sets import resolve_coding_composition_set
from .package_builtin_wheel import (
    coding_builtin_product_local_wheel_policy,
    inspect_posix_coding_base_product_wheel,
    inspect_posix_coding_capability_product_wheels,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_external_data_wheel import CodingExternalDataWheelCatalog
from .package_external_dependency_wheel import CodingExternalDependencyWheelCatalog
from .package_external_worker_wheel import CodingExternalWorkerWheelCatalog
from .package_legacy_binding_catalog import CodingLegacyLocalBindingCatalog
from .package_legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournal,
)
from .resource_runtime import CodingResourceLoader

CodingDataResourceAdmissionPreviewV1 = PluginCurrentResourceAdmissionV1
CodingCurrentDataResourcePreviewV1 = PluginCurrentCompositionPreviewV1


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
        self.epoch_runtime.assert_current()
        selected = self.selected_manifests.capture_selected_manifest_for_plugin(
            plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
        )
        matches = tuple(
            binding
            for binding in self.policy.bindings
            if binding.plugin_id == plugin_id
            and binding.source_trust_class == "local-worker-candidate"
            and binding.source_identity
            == selected.snapshot.package_revision.package_source_identity
            and binding.artifact_digest == selected.snapshot.root_ref.artifact_digest
            and binding.worker_admission is not None
        )
        if len(matches) != 1:
            raise ValueError("Selected Worker Product binding is unavailable")
        admission = matches[0].worker_admission
        assert admission is not None
        candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=admission.contribution_id,
            native_platform=admission.native_platform,
        )
        if candidate.owner_id != admission.owner_id:
            raise ValueError("Selected Worker Product owner changed")
        self.epoch_runtime.assert_current()
        return CodingWorkerCandidateReadEvidenceV1(
            candidate=candidate,
            artifact_digest=selected.snapshot.root_ref.artifact_digest,
            native_platform=admission.native_platform,
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
                                plugin_id, max_files=64, max_total_bytes=1024 * 1024
                            )
                            for plugin_id in external_ids
                        ),
                        composition_set=composition_set,
                        session_id="plugin-preview-current",
                        evaluated_at=evaluated_at,
                    )
            else:
                base = self.selected_manifests.capture_selected_manifest_for_plugin(
                    "coding.base", max_files=64, max_total_bytes=1024 * 1024
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
                                plugin_id, max_files=64, max_total_bytes=1024 * 1024
                            )
                            for plugin_id in external_ids
                        ),
                        evaluated_at=evaluated_at,
                    )
                    compiled_plugin_ids = base_compiled.plan.selected_plugin_ids
                compiled = base_compiled
        except (CodingBasePluginAssemblyError, ProductCompositionError) as exc:
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
        adapter = build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id="plugin-preview-current",
            product_composition=(
                compiled.product_composition if compiled is not None else None
            ),
            product_snapshot_resources=(
                compiled.product_resource_inputs() if compiled is not None else None
            ),
            package_admission_now=evaluated_at,
            disabled_skills=disabled_skills or (),
            source_policy=(
                CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
                if compiled is None
                else CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
            ),
        )
        bundle = adapter.prepare_bootstrap_projection(
            product_id=self.policy.product_id,
            session_id="plugin-preview-current",
            cwd=workspace,
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
        admissions = tuple(
            sorted(
                (
                    CodingDataResourceAdmissionPreviewV1(
                        plugin_id=item.plugin_id,
                        contribution_id=item.contribution_id,
                        resource_kind=item.candidate.contribution.resource_kind,
                        owner_id=item.owner_id,
                        admission_fingerprint=item.fingerprint,
                    )
                    for item in (
                        compiled.product_composition.resource_admissions
                        if compiled is not None
                        else ()
                    )
                    if isinstance(item.candidate.contribution, ResourceContributionSpec)
                ),
                key=lambda item: (item.plugin_id, item.contribution_id),
            )
        )
        catalog_resources = tuple(
            sorted(
                (
                    *(
                        ("skill", item.name, item.source_kind)
                        for item in bundle.skills
                        if item.enabled
                    ),
                    *(
                        ("prompt", item.name, item.source_kind)
                        for item in bundle.prompts
                        if item.enabled
                    ),
                    *(
                        ("theme", item.name, item.source_kind)
                        for item in bundle.themes
                        if item.enabled
                    ),
                )
            )
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
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
            read_only=True,
        )
        try:
            if workspace_guard is not None:
                workspace_guard()
            switch = runtime.cutover_result.switch_receipt
            if switch is None:
                raise ValueError("Coding Package Product root is not fenced")
            state_root = runtime.control_root / "product-state"
            source_root = runtime.control_root / "product-sources"
            _require_existing_private_directory(state_root)
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
                policy_revision="coding-product-package-policy:1",
                quota_profile_revision="coding-product-package-quota:1",
                authority_id="coding-product-local-source",
            )
            policy = CodingLegacyLocalBindingCatalog(
                state_root / "legacy-local-bindings.jsonl",
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=layout.scope_id,
                policy_revision=policy.policy_revision,
                acceptance_reader=lambda plugin_id: (
                    reopen_coding_legacy_installed_local_acceptance(
                        layout,
                        runtime,
                        plugin_id=plugin_id,
                        policy_revision=policy.policy_revision,
                    )
                ),
            ).read_extend_policy(policy)
            policy = CodingExternalDataWheelCatalog(
                state_root / "external-data-wheel-bindings.jsonl",
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=layout.scope_id,
                read_only=True,
            ).extend_policy(policy)
            policy = CodingExternalDependencyWheelCatalog(
                state_root / "external-dependency-wheel-bindings.jsonl",
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=layout.scope_id,
                read_only=True,
            ).extend_policy(policy)
            if worker_candidates:
                policy = CodingExternalWorkerWheelCatalog(
                    state_root / "external-worker-wheel-bindings.jsonl",
                    source_root=source_root,
                    store_id=epoch.store_id,
                    namespace_id=switch.namespace_id,
                    scope_id=layout.scope_id,
                    read_only=True,
                ).extend_policy(policy)
            strict = JournalLoadPolicy(partial_tail="raise", create_lock=False)
            gate = PluginPackageGcReservationJournal(
                state_root / "gc-reservations.jsonl", load_policy=strict
            )
            desired = PluginDesiredStateLedger(
                state_root / "desired-state.jsonl", gc_gate=gate, load_policy=strict
            )
            settlements = PackageStoreSettlementJournal(
                state_root / "root-settlements.jsonl"
            )
            root_reader = PackageProductSelectedRootReader(
                product_id=policy.product_id,
                scope_id=policy.project_scope_id,
                installation_scope="workspace",
                desired_state=desired,
                bindings=PluginPackageGcBindingJournal(
                    state_root / "gc-bindings.jsonl"
                ),
                committed_sets=PackageCommittedSetJournal(
                    state_root / "committed-sets.jsonl"
                ),
                root_settlements=settlements,
                root_store=PosixPackagePluginRootReadOnlyStore(
                    epoch.epoch_root(switch.namespace_id),
                    store_identity=f"coding-product-root-store:{epoch.store_id}",
                    settlement_journal=settlements,
                ),
                gc_gate=gate,
            )
            runtime.assert_current()
            if workspace_guard is not None:
                workspace_guard()
            return cls(
                epoch_runtime=runtime,
                policy=policy,
                selected_manifests=_LocalWheelSelectedManifestReader(
                    policy=policy, root_reader=root_reader, read_only=True
                ),
                gc_gate=gate,
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


def _require_existing_private_directory(path: Path) -> None:
    descriptor = os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        opened = os.fstat(descriptor)
        visible = path.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) & 0o077
            or opened.st_uid != os.geteuid()
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise ValueError("Fenced Product state root is unsafe")
    finally:
        os.close(descriptor)


def _workspace_scope_id(workspace: Path) -> str:
    return (
        "workspace:"
        + sha256(
            b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
        ).hexdigest()
    )


def _selection_evidence(
    policy: PackageProductLocalWheelPolicy,
    desired_snapshot: PluginDesiredStateSnapshotV1,
    requested_plugin_ids: tuple[str, ...],
) -> tuple[set[str], set[str]]:
    if not isinstance(desired_snapshot, PluginDesiredStateSnapshotV1):
        raise TypeError("Product preview Desired State snapshot is required")
    desired_selected_ids = {
        item.installation_key.plugin_id
        for item in desired_snapshot.installations
        if item.installation_key.product_id == policy.product_id
        and item.installation_key.scope_id == policy.project_scope_id
        and item.selection.desired_state == "installed_enabled"
    }
    selected_ids = desired_selected_ids & set(requested_plugin_ids)
    binding_ids = {item.plugin_id for item in policy.bindings}
    executable = {
        item.plugin_id
        for item in policy.bindings
        if item.plugin_id in selected_ids
        and item.source_trust_class
        in {"host-equivalent-local", "legacy-local-reacquired"}
        and item.plugin_id != "coding.base"
    }
    gaps = {
        "disabled_skill_settings",
        "session_invocation_options",
        "exact_catalog_generation",
    }
    if desired_selected_ids - binding_ids:
        gaps.add("product_binding_for_selected_plugin")
    if executable:
        gaps.add("capability_authorized_preflight")
    return executable, gaps


__all__ = [
    "CodingCurrentDataResourcePreviewV1",
    "CodingDataResourceAdmissionPreviewV1",
    "CodingFencedProductReadOnlyPreviewOwner",
    "CodingWorkerCandidateReadEvidenceV1",
]
