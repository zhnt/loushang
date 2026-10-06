"""Product-bound Windows Worker decisions from current selection and release."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)

from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_opt_in_owner import CodingWorkerProductOptInError
from .package_product_worker_policy import CodingWorkerOptInV1
from .package_product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)


class CodingWindowsWorkerProductOptInOwner:
    """Derive, read, and revoke under current Product GC and state-root owners."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product.policy.bindings
            )
        ):
            raise ValueError("Windows Worker candidate Product owner is required")
        product.assert_root_gc_authority_current()
        self._product = product
        self._journal = CodingWindowsWorkerOptInJournal(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
        )

    def current(self, plugin_id: str) -> CodingWorkerOptInDecisionV1 | None:
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                decision = self._journal.current(plugin_id, directory_fd=root)
            self._product.assert_root_gc_authority_current()
            return decision

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> CodingWorkerOptInDecisionV1:
        """Record only the selected candidate with an approved installed backend."""

        if type(require_worker) is not bool:
            raise TypeError("Coding Worker requiredness must be boolean")
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            bindings = tuple(
                binding
                for binding in self._product.policy.bindings
                if binding.plugin_id == plugin_id
                and binding.source_trust_class == "local-worker-candidate"
                and binding.worker_admission is not None
            )
            if len(bindings) != 1:
                raise CodingWorkerProductOptInError(
                    "coding_worker_opt_in_candidate_unavailable"
                )
            binding = bindings[0]
            admission = binding.worker_admission
            assert admission is not None
            key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=self._product.policy.project_scope_id,
                plugin_id=plugin_id,
            )
            snapshot = self._product.desired_state.snapshot()
            selected = snapshot.installation(key).selection
            revision = selected.package_revision
            crosswalks = (
                tuple(
                    item
                    for item in self._product.gc_bindings.for_revision(revision)
                    if item.request.product_id == "coding"
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
                raise CodingWorkerProductOptInError(
                    "coding_worker_opt_in_selection_unavailable"
                )
            committed_ids = {item.request.committed_set_id for item in crosswalks}
            committed = tuple(
                record
                for record in PackageCommittedSetJournal(
                    self._product.state_root / "committed-sets.jsonl"
                ).records()
                if record.committed_set.set_id in committed_ids
                and record.committed_set.product_id == "coding"
                and record.committed_set.scope_id == key.scope_id
                and record.committed_set.plugin_id == plugin_id
                and record.committed_set.root_ref.artifact_digest
                == revision.package_content_digest
                and record.closure_lock.lock_digest == revision.dependency_lock_digest
            )
            if len(committed) != 1:
                raise CodingWorkerProductOptInError(
                    "coding_worker_opt_in_selection_unavailable"
                )
            if committed[0].closure_lock.node_count != 1:
                raise CodingWorkerProductOptInError(
                    "coding_worker_dependency_activation_unsupported"
                )
            closure = read_coding_windows_worker_installed_backend_release(
                self._product
            ).native_closure()
            if closure.native_platform != admission.native_platform:
                raise CodingWorkerProductOptInError(
                    "coding_worker_opt_in_native_platform_changed"
                )
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                previous = self._journal.current(plugin_id, directory_fd=root)
                generation = 0 if previous is None else previous.generation
                kill_generation = (
                    0 if previous is None else previous.kill_switch_generation
                )
                if (
                    previous is not None
                    and previous.operation_id == operation_id
                    and previous.action == "allow"
                    and previous.generation == expected_generation + 1
                ):
                    prior = previous.opt_in
                    if (
                        prior is None
                        or prior.plugin_id != plugin_id
                        or prior.contribution_id != admission.contribution_id
                        or prior.owner_id != admission.owner_id
                        or prior.artifact_digest != binding.artifact_digest
                        or prior.native_platform != admission.native_platform
                        or prior.require_worker != require_worker
                    ):
                        raise CodingWorkerProductOptInError(
                            "coding_worker_opt_in_operation_conflict"
                        )
                    return self._journal.change(
                        directory_fd=root,
                        plugin_id=plugin_id,
                        operation_id=operation_id,
                        expected_generation=expected_generation,
                        action="allow",
                        opt_in=prior,
                    )
                if generation != expected_generation:
                    raise CodingWorkerProductOptInError("coding_worker_opt_in_stale")
                return self._journal.change(
                    directory_fd=root,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="allow",
                    opt_in=CodingWorkerOptInV1(
                        plugin_id=plugin_id,
                        contribution_id=admission.contribution_id,
                        owner_id=admission.owner_id,
                        artifact_digest=binding.artifact_digest,
                        native_platform=admission.native_platform,
                        owner_selection_generation=generation + 1,
                        kill_switch_generation=kill_generation,
                        require_worker=require_worker,
                    ),
                )

    def revoke(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
    ) -> CodingWorkerOptInDecisionV1:
        """Persist a kill generation even if the release has disappeared."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                decision = self._journal.change(
                    directory_fd=root,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="revoke",
                    opt_in=None,
                )
            self._product.assert_root_gc_authority_current()
            return decision


__all__ = ["CodingWindowsWorkerProductOptInOwner"]
