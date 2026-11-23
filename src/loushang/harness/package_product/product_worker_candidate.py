"""Product Worker candidate facts and existing lifecycle coordination."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from pathlib import Path
from re import Pattern
from typing import Literal, Protocol

from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.updates import PluginUpdateOperationEventV2
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductEntrypoint,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_handoff import (
    package_product_command_identity,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
    WorkerNativeExecutablePlatform,
    verify_worker_native_executable_format,
)
from loushang.harness.worker.package_candidate import (
    WorkerPackageCandidateError,
    WorkerPackageCandidateV1,
    verify_worker_package_candidate,
)

from ._plugin_bootstrap import route_project_package
from .product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
    _LocalWheelSelectedManifestReader,
)
from .product_runtime import hold_local_wheel_product_runtime


class ProductWorkerOptInFacts:
    __slots__ = ()
    owner_id: str
    plugin_id: str
    contribution_id: str
    artifact_digest: str
    native_platform: str
    require_worker: bool
    owner_selection_generation: int
    kill_switch_generation: int

    def to_dict(self) -> dict[str, object]:
        raise NotImplementedError

    def _validate_opt_in(
        self,
        *,
        max_text: int,
        identifier: Pattern[str],
        digest: Pattern[str],
        native_profiles: Mapping[str, str],
        label: str,
    ) -> None:
        for value in (self.plugin_id, self.contribution_id, self.owner_id):
            if (
                not isinstance(value, str)
                or len(value) > max_text
                or identifier.fullmatch(value) is None
            ):
                raise ValueError(f"{label} opt-in identity is invalid")
        if (
            not isinstance(self.artifact_digest, str)
            or digest.fullmatch(self.artifact_digest) is None
        ):
            raise ValueError(f"{label} opt-in digest is invalid")
        if (
            not isinstance(self.native_platform, str)
            or self.native_platform not in native_profiles
        ):
            raise ValueError(f"{label} opt-in platform is unsupported")
        if (
            type(self.owner_selection_generation) is not int
            or self.owner_selection_generation < 1
            or type(self.kill_switch_generation) is not int
            or self.kill_switch_generation < 0
            or type(self.require_worker) is not bool
        ):
            raise ValueError(f"{label} opt-in generation or requiredness is invalid")


class ProductWorkerNativeClosureFacts:
    __slots__ = ()
    native_platform: str
    native_profile_catalog_revision: str
    containment_launcher_digest: str
    containment_profile_digest: str

    def to_dict(self) -> dict[str, object]:
        raise NotImplementedError

    def _validate_native_closure(
        self,
        *,
        max_text: int,
        opaque: Pattern[str],
        digest: Pattern[str],
        native_profiles: Mapping[str, str],
        label: str,
    ) -> None:
        if (
            not isinstance(self.native_platform, str)
            or self.native_platform not in native_profiles
            or not isinstance(self.native_profile_catalog_revision, str)
            or len(self.native_profile_catalog_revision) > max_text
            or opaque.fullmatch(self.native_profile_catalog_revision) is None
        ):
            raise ValueError(f"{label} native closure identity is invalid")
        for value in (
            self.containment_launcher_digest,
            self.containment_profile_digest,
        ):
            if not isinstance(value, str) or digest.fullmatch(value) is None:
                raise ValueError(f"{label} native closure digest is invalid")


class ProductWorkerNativeLaunchMaterialFacts:
    __slots__ = ()
    launcher_path: Path
    closure: ProductWorkerNativeClosureFacts


class ProductWorkerSelectedPayloadFacts:
    __slots__ = ()
    configuration: PluginLocalWorkerConfiguration
    body: bytes
    digest: str


def verify_product_selected_worker_candidate(
    selected: PackageProductSelectedPluginManifestV1,
    *,
    contribution_id: str,
    native_platform: WorkerNativeExecutablePlatform,
) -> WorkerPackageCandidateV1:
    """Rejoin one selected root to inert Worker bytes without granting execution.

    Product selection and Store verification belong to the owner that captured
    ``selected``. It must recheck the selected root before issuing a receipt.
    """

    if not isinstance(selected, PackageProductSelectedPluginManifestV1):
        raise WorkerPackageCandidateError("worker_candidate_selection_invalid")
    try:
        manifest = selected.verified_manifest()
        root = manifest.root_relative_path.as_posix()
        manifest_path = "plugin.json" if root == "." else f"{root}/plugin.json"
        members = dict(selected.snapshot.files)
        candidate = verify_worker_package_candidate(
            members,
            manifest_logical_path=manifest_path,
            contribution_id=contribution_id,
        )
        configuration = manifest.contribution_index.items[0].worker_configuration
        assert configuration is not None
        prefix = "" if root == "." else f"{root}/"
        verify_worker_native_executable_format(
            members[f"{prefix}{configuration.entrypoint}"],
            platform=native_platform,
        )
    except WorkerNativeExecutableFormatError as exc:
        raise WorkerPackageCandidateError(
            "worker_candidate_executable_format_invalid"
        ) from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise WorkerPackageCandidateError("worker_candidate_selection_invalid") from exc
    if (
        candidate.plugin_id != selected.snapshot.installation_key.plugin_id
        or candidate.plugin_version != selected.snapshot.root_ref.version
        or candidate.manifest_digest != selected.manifest.manifest_digest
    ):
        raise WorkerPackageCandidateError("worker_candidate_selection_mismatch")
    return candidate


def read_selected_worker_candidate(
    runtime: PackageProductPosixFencedRuntimeOwner,
    selected_manifests: _LocalWheelSelectedManifestReader,
    policy: PackageProductLocalWheelPolicy,
    plugin_id: str,
) -> tuple[WorkerPackageCandidateV1, str, WorkerNativeExecutablePlatform]:
    """Read exact Worker candidate evidence through the caller's fenced owner."""

    runtime.assert_current()
    selected = selected_manifests.capture_selected_manifest_for_plugin(
        plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
    )
    matches = tuple(
        binding
        for binding in policy.bindings
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
    runtime.assert_current()
    return (
        candidate,
        selected.snapshot.root_ref.artifact_digest,
        admission.native_platform,
    )


def _read_product_selected_worker_payload_facts(
    selected: PackageProductSelectedPluginManifestV1,
    *,
    contribution_id: str,
    native_platform: WorkerNativeExecutablePlatform,
) -> tuple[WorkerPackageCandidateV1, PluginLocalWorkerConfiguration, bytes | None]:
    """Return inert payload facts; the caller retains receipt/GC authority."""
    candidate = verify_product_selected_worker_candidate(
        selected, contribution_id=contribution_id, native_platform=native_platform
    )
    manifest = selected.verified_manifest()
    configuration = manifest.contribution_index.items[0].worker_configuration
    assert configuration is not None
    root = manifest.root_relative_path.as_posix()
    prefix = "" if root == "." else f"{root}/"
    body = dict(selected.snapshot.files).get(f"{prefix}{configuration.entrypoint}")
    return candidate, configuration, body


__all__ = ["WorkerPackageCandidateV1", "verify_product_selected_worker_candidate"]


def _capture_worker_opt_in_selection(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    plugin_id: str,
    *,
    product_id: str,
    error_type: Callable[[str], Exception],
    error_prefix: str,
) -> tuple[PackageProductLocalWheelBindingV1, PackageProductLocalWorkerAdmissionV1]:
    """Join original selection/committed facts under the caller's Product GC guard.

    This read establishes no native approval, operator decision or launch right.
    The platform owner still selects its native release and appends its decision.
    """
    product.assert_root_gc_authority_current()
    candidates = tuple(
        binding
        for binding in product.policy.bindings
        if binding.plugin_id == plugin_id
        and binding.source_trust_class == "local-worker-candidate"
        and binding.worker_admission is not None
    )
    if not candidates:
        raise error_type(f"{error_prefix}_opt_in_candidate_unavailable")
    key = PluginInstallationKeyV1(
        product_id=product_id,
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )
    snapshot = product.desired_state.snapshot()
    selected = snapshot.installation(key).selection
    revision = selected.package_revision
    if selected.desired_state != "installed_enabled" or revision is None:
        raise error_type(f"{error_prefix}_opt_in_selection_unavailable")
    bindings = tuple(
        binding
        for binding in candidates
        if binding.source_identity == revision.package_source_identity
        and binding.artifact_digest == revision.package_content_digest
    )
    if len(bindings) != 1:
        raise error_type(f"{error_prefix}_opt_in_candidate_unavailable")
    binding = bindings[0]
    admission = binding.worker_admission
    assert admission is not None
    crosswalks = (
        tuple(
            item
            for item in product.gc_bindings.for_revision(revision)
            if item.request.product_id == product_id
            and item.request.scope_id == key.scope_id
            and item.request.plugin_id == plugin_id
            and item.desired_transition_revision <= snapshot.inventory_revision
        )
        if revision is not None
        else ()
    )
    if (
        selected.desired_state != "installed_enabled"
        or revision is None
        or revision.package_source_identity != binding.source_identity
        or revision.package_content_digest != binding.artifact_digest
        or not crosswalks
    ):
        raise error_type(f"{error_prefix}_opt_in_selection_unavailable")
    committed_ids = {item.request.committed_set_id for item in crosswalks}
    committed = tuple(
        record
        for record in PackageCommittedSetJournal(
            product.state_root / "committed-sets.jsonl"
        ).records()
        if record.committed_set.set_id in committed_ids
        and record.committed_set.product_id == product_id
        and record.committed_set.scope_id == key.scope_id
        and record.committed_set.plugin_id == plugin_id
        and record.committed_set.root_ref.artifact_digest
        == revision.package_content_digest
        and record.closure_lock.lock_digest == revision.dependency_lock_digest
    )
    if len(committed) != 1:
        raise error_type(f"{error_prefix}_opt_in_selection_unavailable")
    if committed[0].closure_lock.node_count != 1:
        raise error_type(f"{error_prefix}_dependency_activation_unsupported")
    return binding, admission


def _observe_installed_worker_candidate(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    plugin_id: str,
    *,
    product_id: str,
    native_platform: WorkerNativeExecutablePlatform,
    label: str,
) -> tuple[WorkerPackageCandidateV1, str]:
    """Verify selected bytes through the existing Product runtime custody."""
    installed = tuple(
        item
        for item in product.desired_state.snapshot().installations
        if item.installation_key.product_id == product_id
        and item.installation_key.installation_scope == "workspace"
        and item.installation_key.plugin_id == plugin_id
        and item.selection.desired_state == "installed_enabled"
        and item.selection.package_revision is not None
    )
    if len(installed) != 1:
        raise ValueError(f"{label} candidate selection is unavailable")
    revision = installed[0].selection.package_revision
    assert revision is not None
    bindings = tuple(
        binding
        for binding in product.policy.bindings
        if binding.plugin_id == plugin_id
        and binding.source_trust_class == "local-worker-candidate"
        and binding.worker_admission is not None
        and binding.source_identity == revision.package_source_identity
        and binding.artifact_digest == revision.package_content_digest
    )
    if len(bindings) != 1:
        raise ValueError(f"{label} candidate selection is unavailable")
    binding = bindings[0]
    admission = binding.worker_admission
    assert admission is not None
    session_id = f"worker-candidate-selection-{secrets.token_hex(16)}"
    with hold_local_wheel_product_runtime(
        product, product_id=product_id, session_id=session_id
    ) as runtime:
        selected = runtime.capture_selected_plugin_manifest_for(
            plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
        )
        revision = selected.snapshot.package_revision
        if (
            revision.package_source_identity != binding.source_identity
            or revision.package_content_digest != binding.artifact_digest
            or selected.snapshot.root_ref.artifact_digest != binding.artifact_digest
        ):
            raise ValueError(f"{label} candidate selection changed")
        candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=admission.contribution_id,
            native_platform=native_platform,
        )
        if candidate.owner_id != admission.owner_id:
            raise ValueError(f"{label} candidate owner changed")
        return candidate, binding.artifact_digest


def _capture_worker_candidate_installations(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    plugin_id: str,
    artifact_digest: str,
    *,
    product_id: str,
    label: str,
) -> tuple[
    PackageProductLocalWheelBindingV1,
    PluginDesiredStateSnapshotV1,
    tuple[PluginInstallationStateV1, ...],
]:
    """Read the admitted candidate and its existing workspace installations."""
    matches = tuple(
        binding
        for binding in product.policy.bindings
        if binding.source_trust_class == "local-worker-candidate"
        and binding.plugin_id == plugin_id
        and binding.artifact_digest == artifact_digest
    )
    if len(matches) != 1:
        raise ValueError(f"{label} candidate is unavailable or ambiguous")
    snapshot = product.desired_state.snapshot()
    return (
        matches[0],
        snapshot,
        _worker_candidate_installations(
            snapshot, product_id=product_id, plugin_id=plugin_id
        ),
    )


def _worker_candidate_installations(
    snapshot: PluginDesiredStateSnapshotV1, *, product_id: str, plugin_id: str
) -> tuple[PluginInstallationStateV1, ...]:
    return tuple(
        item
        for item in snapshot.installations
        if item.installation_key.plugin_id == plugin_id
        and item.installation_key.product_id == product_id
        and item.installation_key.installation_scope == "workspace"
    )


def _worker_candidate_revision_matches(
    revision: PluginPackageRevisionRefV1 | None,
    binding: PackageProductLocalWheelBindingV1,
) -> bool:
    return (
        revision is not None
        and revision.package_source_identity == binding.source_identity
        and revision.package_content_digest == binding.artifact_digest
    )


def _install_worker_candidate(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    binding: PackageProductLocalWheelBindingV1,
    snapshot: PluginDesiredStateSnapshotV1,
    selected: PluginInstallationStateV1 | None,
    *,
    product_id: str,
    plugin_id: str,
    operation_id: str,
    label: str,
    reinstall_removed: bool,
    refresh_inventory: bool = False,
) -> tuple[str, int, bool]:
    """Prove an install replay or install through the existing lifecycle owner."""
    if selected is not None:
        revision = selected.selection.package_revision
        if _worker_candidate_revision_matches(revision, binding):
            return "installed", snapshot.inventory_revision, True
        if revision is not None or not reinstall_removed:
            raise ValueError(f"{label} candidate installation changed")
    lifecycle, inventory_revision = _run_worker_candidate_lifecycle(
        product,
        binding,
        product_id=product_id,
        plugin_id=plugin_id,
        operation_id=operation_id,
        session_id=f"worker-candidate-install-{secrets.token_hex(16)}",
        action="install",
        label=label,
        entrypoint="cli",
        refresh_install_inventory=refresh_inventory,
    )
    return lifecycle, inventory_revision, False


def _run_worker_candidate_lifecycle(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    binding: PackageProductLocalWheelBindingV1,
    *,
    product_id: str,
    plugin_id: str,
    operation_id: str,
    session_id: str,
    action: Literal["install", "update"],
    label: str,
    entrypoint: PackageProductEntrypoint,
    selected_key: PluginInstallationKeyV1 | None = None,
    refresh_install_inventory: bool = False,
    update_error_type: Callable[[str, str], Exception] | None = None,
    update_error_code: str = "",
) -> tuple[str, int]:
    """Use the original factory/lifecycle owner and prove the resulting revision.

    Callers retain selection/CAS/opt-in preconditions and response formatting.
    Fixed internal inputs come from the already parsed operator command.
    """
    with hold_local_wheel_product_runtime(
        product, product_id=product_id, session_id=session_id
    ) as runtime:
        routed = route_project_package(
            runtime,
            operation_id=operation_id,
            action=action,
            source=binding.source_identity,
            entrypoint=entrypoint,
        )
        if (
            not routed.handled
            or routed.record is None
            or routed.record.lifecycle != "installed"
        ):
            raise ValueError(f"{label} candidate {action} did not settle")
        snapshot = product.desired_state.snapshot()
        if action == "update":
            selected = tuple(
                item
                for item in snapshot.installations
                if item.installation_key == selected_key
            )
        else:
            selected = _worker_candidate_installations(
                snapshot, product_id=product_id, plugin_id=plugin_id
            )
        if len(selected) != 1 or not _worker_candidate_revision_matches(
            selected[0].selection.package_revision, binding
        ):
            message = f"{label} candidate {action} selection changed"
            if action == "update" and update_error_type is not None:
                raise update_error_type(update_error_code, message)
            raise ValueError(message)
        inventory_revision = (
            product.desired_state.snapshot().inventory_revision
            if action == "install" and refresh_install_inventory
            else snapshot.inventory_revision
        )
        return routed.record.lifecycle, inventory_revision


def _change_worker_candidate_lifecycle(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    binding: PackageProductLocalWheelBindingV1,
    snapshot: PluginDesiredStateSnapshotV1,
    selected: PluginInstallationStateV1,
    *,
    action: Literal["enable", "disable", "remove"],
    operation_id: str,
    expected_inventory_revision: int,
    label: str,
    unsettled_message: str,
) -> tuple[dict[str, object], int]:
    """Submit a validated candidate change or prove the exact removal replay.

    The operator route checks candidate selection and opt-in policy before
    calling this function. Its original validation order stays at that edge.
    """
    if selected.selection.package_revision is None:
        prior = product.management.operation(operation_id)
        if (
            action != "remove"
            or selected.selection.desired_state != "absent"
            or not isinstance(prior, PluginManagementOperationEventV1)
            or prior.command.action != "remove"
            or prior.command.mutation.installation_key != selected.installation_key
            or prior.command.mutation.expected_inventory_revision
            != expected_inventory_revision
            or prior.status != "terminal"
            or prior.result is None
            or prior.result.disposition != "succeeded"
            or prior.result.transition is None
            or (
                previous
                := prior.result.transition.previous_state.selection.package_revision
            )
            is None
            or previous.package_source_identity != binding.source_identity
            or previous.package_content_digest != binding.artifact_digest
        ):
            raise ValueError(f"{label} candidate removal changed")
        return prior.to_dict(), snapshot.inventory_revision

    desired_state: Literal["installed_enabled", "installed_disabled", "absent"]
    if action == "enable":
        desired_state = "installed_enabled"
    elif action == "disable":
        desired_state = "installed_disabled"
    else:
        desired_state = "absent"
    operation = product.management.submit(
        PluginManagementCommandV1(
            action=action,
            mutation=PluginDesiredStateMutationV1(
                operation_id=operation_id,
                idempotency_key=operation_id,
                expected_inventory_revision=expected_inventory_revision,
                installation_key=selected.installation_key,
                desired_state=desired_state,
                package_revision=None,
                actor_id=product.actor_id,
                policy_revision=product.desired_policy_revision,
            ),
        )
    )
    if (
        operation.status != "terminal"
        or operation.result is None
        or operation.result.disposition != "succeeded"
    ):
        raise ValueError(unsettled_message)
    return operation.to_dict(), product.desired_state.snapshot().inventory_revision


class _WorkerCandidateUpdateInput(Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def operation_id(self) -> str: ...

    @property
    def artifact_digest(self) -> str: ...

    @property
    def from_artifact_digest(self) -> str: ...

    @property
    def expected_inventory_revision(self) -> int: ...


def _update_worker_candidate(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    binding: PackageProductLocalWheelBindingV1,
    snapshot: PluginDesiredStateSnapshotV1,
    selected: PluginInstallationStateV1 | None,
    request: _WorkerCandidateUpdateInput,
    *,
    product_id: str,
    label: str,
    require_revoked: Callable[[], None],
    error_type: Callable[[str, str], Exception],
    error_code: str,
    post_selection_error_type: Callable[[str, str], Exception] | None = None,
) -> tuple[str, int, bool]:
    """Prove an exact retry or update through the original lifecycle authorities.

    Selection-count policy remains at the caller. The deferred guard supplies
    one Product opt-in decision and never drives a lifecycle phase.
    """
    selected_revision = (
        None if selected is None else selected.selection.package_revision
    )
    lifecycle_request = PackageLifecycleJournal(
        product.state_root / "lifecycle.jsonl"
    ).request(request.operation_id)
    prior_update = None
    if (
        isinstance(lifecycle_request, PackageLifecycleRequestV2)
        and lifecycle_request.action == "update"
        and lifecycle_request.requested_plugin_id == request.plugin_id
        and lifecycle_request.canonical_source_identity == binding.source_identity
    ):
        command_id, _ = package_product_command_identity(
            request.operation_id, lifecycle_request.request_fingerprint
        )
        prior_update = product.management.operation(command_id)
    if (
        isinstance(prior_update, PluginUpdateOperationEventV2)
        and selected is not None
        and selected_revision is not None
        and prior_update.status == "terminal"
        and prior_update.result is not None
        and prior_update.result.disposition in {"succeeded", "restart_required"}
        and prior_update.result.transition is not None
        and prior_update.command.installation_key == selected.installation_key
        and prior_update.command.expected_inventory_revision
        == request.expected_inventory_revision
        and prior_update.command.expected_package_revision.package_content_digest
        == request.from_artifact_digest
        and prior_update.command.staged_package_revision.package_source_identity
        == binding.source_identity
        and prior_update.command.staged_package_revision.package_content_digest
        == request.artifact_digest
        and prior_update.result.transition.committed_state == selected
        and prior_update.result.transition.inventory_revision
        == snapshot.inventory_revision
    ):
        require_revoked()
        return ("installed", snapshot.inventory_revision, True)
    if (
        snapshot.inventory_revision != request.expected_inventory_revision
        or selected is None
        or selected_revision is None
        or selected_revision.package_content_digest != request.from_artifact_digest
        or request.from_artifact_digest == request.artifact_digest
        or selected.selection.desired_state
        not in {"installed_enabled", "installed_disabled"}
    ):
        raise error_type(error_code, f"{label} candidate update selection changed")
    require_revoked()
    session_id = f"worker-candidate-update-{secrets.token_hex(16)}"
    lifecycle, inventory_revision = _run_worker_candidate_lifecycle(
        product,
        binding,
        product_id=product_id,
        plugin_id=request.plugin_id,
        operation_id=request.operation_id,
        session_id=session_id,
        action="update",
        label=label,
        entrypoint="cli",
        selected_key=selected.installation_key,
        update_error_type=post_selection_error_type,
        update_error_code=error_code,
    )
    return (lifecycle, inventory_revision, False)
