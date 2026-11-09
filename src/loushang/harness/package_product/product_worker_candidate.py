"""Product Worker candidate facts and existing lifecycle coordination."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Literal, Protocol

from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
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
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_handoff import (
    package_product_command_identity,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWorkerAdmissionV1,
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

from .product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from .product_runtime import PackageProductRuntimeRequestV1


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
    factory = product.factory_for_session(
        session_id=session_id, cwd=product.workspace, runtime_id=session_id
    )
    try:
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id=product_id, session_id=session_id, cwd=str(product.workspace)
            )
        )
    except BaseException:
        factory.dispose_unbound_runtime()
        raise
    try:
        runtime.activate()
        routed = runtime.lifecycle.route(
            PackageProductLifecycleIntentV1(
                operation_id=operation_id,
                action=action,
                source=binding.source_identity,
                scope="project",
            ),
            entrypoint=entrypoint,
        )
        if (
            not routed.handled
            or routed.record is None
            or routed.record.lifecycle != "installed"
        ):
            raise ValueError(f"{label} candidate {action} did not settle")
        snapshot = product.desired_state.snapshot()
        selected = tuple(
            item
            for item in snapshot.installations
            if (
                item.installation_key == selected_key
                if action == "update"
                else item.installation_key.plugin_id == plugin_id
                and item.installation_key.product_id == product_id
                and item.installation_key.installation_scope == "workspace"
            )
        )
        if (
            len(selected) != 1
            or selected[0].selection.package_revision is None
            or selected[0].selection.package_revision.package_source_identity
            != binding.source_identity
            or selected[0].selection.package_revision.package_content_digest
            != binding.artifact_digest
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
    finally:
        runtime.dispose_runtime()


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
