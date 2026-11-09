"""Product-owned, default-dark opt-in for one selected local Worker candidate."""

from __future__ import annotations

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_worker_candidate import (
    _capture_worker_opt_in_selection,
)

from .package_product_worker_installed_native import (
    open_coding_product_installed_worker_release_reader,
)
from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournal,
)
from .package_product_worker_policy import CodingWorkerOptInV1


class CodingWorkerProductOptInError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingWorkerProductOptInOwner:
    """Derive an operator decision from current Product facts, without launching."""

    def __init__(self, product_owner: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or product_owner.policy.product_id != "coding"
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product_owner.policy.bindings
            )
        ):
            raise ValueError("Coding Worker candidate Product owner is required")
        self._product = product_owner
        self._journal = CodingWorkerOptInJournal(
            product_owner.state_root / "worker-opt-in.jsonl",
            scope_id=product_owner.policy.project_scope_id,
            gc_gate=product_owner.gc_gate,
            store_id=product_owner.epoch_runtime.registry.store_id,
        )

    def current(self, plugin_id: str) -> CodingWorkerOptInDecisionV1 | None:
        return self._journal.current(plugin_id)

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> CodingWorkerOptInDecisionV1:
        """Pin the currently enabled candidate and approved native release."""

        if type(require_worker) is not bool:
            raise TypeError("Coding Worker requiredness must be boolean")
        with self._product.gc_gate.guard(require_write=True):
            binding, admission = _capture_worker_opt_in_selection(
                self._product,
                plugin_id,
                product_id="coding",
                error_type=CodingWorkerProductOptInError,
                error_prefix="coding_worker",
            )
            closure = open_coding_product_installed_worker_release_reader(
                self._product
            ).current_closure()
            if closure.native_platform != admission.native_platform:
                raise CodingWorkerProductOptInError(
                    "coding_worker_opt_in_native_platform_changed"
                )
            previous = self._journal.current(plugin_id)
            generation = 0 if previous is None else previous.generation
            kill_generation = 0 if previous is None else previous.kill_switch_generation
            if (
                previous is not None
                and previous.operation_id == operation_id
                and previous.action == "allow"
                and previous.generation == expected_generation + 1
            ):
                prior_opt_in = previous.opt_in
                if (
                    prior_opt_in is None
                    or prior_opt_in.plugin_id != plugin_id
                    or prior_opt_in.contribution_id != admission.contribution_id
                    or prior_opt_in.owner_id != admission.owner_id
                    or prior_opt_in.artifact_digest != binding.artifact_digest
                    or prior_opt_in.native_platform != admission.native_platform
                    or prior_opt_in.require_worker != require_worker
                ):
                    raise CodingWorkerProductOptInError(
                        "coding_worker_opt_in_operation_conflict"
                    )
                return self._journal.change(
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="allow",
                    opt_in=prior_opt_in,
                )
            if generation != expected_generation:
                raise CodingWorkerProductOptInError("coding_worker_opt_in_stale")
            return self._journal.change(
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
        """Revoke even when the selected candidate or native bytes disappeared."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            return self._journal.change(
                plugin_id=plugin_id,
                operation_id=operation_id,
                expected_generation=expected_generation,
                action="revoke",
                opt_in=None,
            )


__all__ = ["CodingWorkerProductOptInError", "CodingWorkerProductOptInOwner"]
