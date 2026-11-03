from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductAcquiredCleanupObservationV1,
    PackageProductRebindCleanupObservationV1,
)
from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseObservationV1,
)
from loushang.harness.package_product.product_rebind_preflight import (
    PackageProductAcquiredRebindPreflightV1,
    PackageProductRebindPreflightError,
    PackageProductRebindPreflightV1,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceObservationV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
    activate_package_product_runtime,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductExactHandoffRecoveryV1,
)


class _Lifecycle:
    def __init__(
        self,
        binding_id: str = "owner:one",
        *,
        fail: BaseException | None = None,
        publish_active: bool = True,
    ) -> None:
        self.binding_id = binding_id
        self.active = False
        self.fail = fail
        self.publish_active = publish_active
        self.activations = 0

    def activate(self) -> object:
        self.activations += 1
        if self.fail is not None:
            raise self.fail
        self.active = self.publish_active
        return object()


class _Inventory:
    def __init__(self, binding_id: str = "owner:one") -> None:
        self.binding_id = binding_id


class _Factory:
    def __init__(
        self,
        binding: object,
        *,
        fail: BaseException | None = None,
    ) -> None:
        self.binding = binding
        self.fail = fail
        self.requests: list[PackageProductRuntimeRequestV1] = []

    def create(
        self,
        request: PackageProductRuntimeRequestV1,
    ) -> PackageProductRuntimeBindingV1:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        return cast(PackageProductRuntimeBindingV1, self.binding)


def _binding(
    lifecycle: _Lifecycle | None = None,
    inventory: _Inventory | None = None,
    *,
    product_id: str = "product:test",
    on_dispose: Callable[[], None] | None = None,
) -> PackageProductRuntimeBindingV1:
    return PackageProductRuntimeBindingV1(
        product_id=product_id,
        lifecycle=cast(Any, lifecycle or _Lifecycle()),
        inventory=cast(Any, inventory or _Inventory()),
        mode="enforced",
        on_dispose=on_dispose,
    )


def test_exact_handoff_runtime_binds_one_operation_before_activation() -> None:
    class ExactLifecycle(_Lifecycle):
        def __init__(self) -> None:
            super().__init__()
            self.recovered: list[str] = []

        def recover_handoff_exact(
            self, operation_id: str
        ) -> PackageProductExactHandoffRecoveryV1:
            self.recovered.append(operation_id)
            return PackageProductExactHandoffRecoveryV1(
                operation_id=operation_id,
                retained_handoff_ids=(),
                committed_operation_ids=(operation_id,),
                terminal_state="settled",
            )

    lifecycle = ExactLifecycle()
    runtime = _binding(lifecycle)
    result = runtime.recover_committed_handoff_exact("operation:target")
    assert result.changed
    assert result.operation_id == "operation:target"
    assert lifecycle.recovered == ["operation:target"]
    assert lifecycle.activations == 0
    assert not lifecycle.active
    runtime.dispose_runtime()
    with pytest.raises(PackageProductRuntimeActivationError) as disposed:
        runtime.recover_committed_handoff_exact("operation:other")
    assert disposed.value.code == "package_product_exact_recovery_runtime_unavailable"


def test_package_product_runtime_activates_one_aggregate_before_use(
    tmp_path: Path,
) -> None:
    lifecycle = _Lifecycle()
    binding = _binding(lifecycle)
    factory = _Factory(binding)
    request = PackageProductRuntimeRequestV1(
        product_id="product:test",
        session_id="session:test",
        cwd=str(tmp_path),
    )

    result = activate_package_product_runtime(cast(Any, factory), request)

    assert result is binding
    assert factory.requests == [request]
    assert lifecycle.activations == 1
    assert lifecycle.active
    assert result.binding_id == "owner:one"


def test_package_product_runtime_releases_owner_once_after_use(tmp_path: Path) -> None:
    releases: list[str] = []
    binding = _binding(on_dispose=lambda: releases.append("released"))
    request = PackageProductRuntimeRequestV1(
        product_id="product:test", session_id="session:test", cwd=str(tmp_path)
    )

    assert activate_package_product_runtime(_Factory(binding), request) is binding
    assert releases == []
    binding.dispose_runtime()
    binding.dispose_runtime()
    assert releases == ["released"]


def test_rebind_source_read_uses_product_guard_and_refuses_inactive_runtime() -> None:
    class GuardedLifecycle(_Lifecycle):
        inside_guard = False

        async def execute_guarded_query(self, query: Any) -> Any:
            assert self.active
            self.inside_guard = True
            try:
                return await query()
            finally:
                self.inside_guard = False

    lifecycle = GuardedLifecycle()
    observation = PackageProductRebindSourceObservationV1(
        operation_id="operation:read",
        request_fingerprint="1" * 64,
        attempt_epoch=1,
        attempt_revision=3,
        artifact_digests=("2" * 64,),
        resolution_evidence_refs=(),
        source_proof_ref="3" * 64,
    )
    lease_observation = PackageProductRebindLeaseObservationV1(
        operation_id="operation:read",
        request_fingerprint="1" * 64,
        attempt_epoch=1,
        attempt_revision=3,
        original_binding_id="4" * 64,
        original_admission_request_id="8" * 64,
        new_admission_request_id="9" * 64,
        store_id="package-store:test",
        old_lease_id="5" * 64,
        new_lease_id="6" * 64,
        lease_snapshot_id="7" * 64,
        lease_owner_revision=2,
    )
    cleanup_observation = PackageProductRebindCleanupObservationV1(
        operation_id="operation:read",
        request_fingerprint="1" * 64,
        attempt_epoch=1,
        attempt_revision=3,
        known_attempts=(),
        store_identity=(1, 2),
        committed_attempts=(),
        artifact_evidence_refs=(),
        resolution_evidence_refs=(),
        cleanup_ids=(),
        known_cleanup_ref="a" * 64,
    )
    acquired_cleanup_observation = PackageProductAcquiredCleanupObservationV1(
        status=cast(
            Any,
            SimpleNamespace(
                operation_id="operation:read",
                request_fingerprint="1" * 64,
                attempt_epoch=1,
                attempt_revision=3,
            ),
        ),
        root_attempt=cast(Any, object()),
        acquisition_receipt=cast(Any, object()),
        artifact_evidence_refs=(),
        resolution_evidence_refs=(),
        store_identity=(1, 2),
        committed_attempts=(),
    )
    calls: list[tuple[str, int]] = []

    class Reader:
        def observe(
            self, operation_id: str, *, max_bytes: int
        ) -> PackageProductRebindSourceObservationV1:
            assert lifecycle.inside_guard
            calls.append((operation_id, max_bytes))
            return observation

        def observe_acquired_claim(
            self, operation_id: str, *, max_bytes: int
        ) -> PackageProductRebindSourceObservationV1:
            return self.observe(operation_id, max_bytes=max_bytes)

    class LeaseReader:
        def observe(self, operation_id: str) -> PackageProductRebindLeaseObservationV1:
            assert lifecycle.inside_guard
            assert operation_id == "operation:read"
            return lease_observation

        def observe_acquired_claim(
            self, operation_id: str
        ) -> PackageProductRebindLeaseObservationV1:
            return self.observe(operation_id)

    class CleanupReader:
        def observe(
            self, operation_id: str
        ) -> PackageProductRebindCleanupObservationV1:
            assert lifecycle.inside_guard
            assert operation_id == "operation:read"
            return cleanup_observation

        def observe_acquired_claim(
            self, operation_id: str
        ) -> PackageProductAcquiredCleanupObservationV1:
            assert lifecycle.inside_guard
            assert operation_id == "operation:read"
            return acquired_cleanup_observation

    binding = PackageProductRuntimeBindingV1(
        product_id="product:test",
        lifecycle=cast(Any, lifecycle),
        inventory=cast(Any, _Inventory()),
        mode="enforced",
        _rebind_source_reader=Reader(),
        _rebind_lease_reader=LeaseReader(),
        _rebind_cleanup_reader=CleanupReader(),
    )
    with pytest.raises(PackageProductRuntimeActivationError) as inactive:
        asyncio.run(binding.inspect_rebind_source("operation:read", max_bytes=1024))
    assert inactive.value.code == "package_product_runtime_inactive"
    assert calls == []

    binding.activate()
    assert (
        asyncio.run(binding.inspect_rebind_source("operation:read", max_bytes=1024))
        == observation
    )
    assert calls == [("operation:read", 1024)]
    assert (
        asyncio.run(binding.inspect_rebind_lease("operation:read")) == lease_observation
    )
    assert (
        asyncio.run(binding.inspect_rebind_cleanup("operation:read"))
        == cleanup_observation
    )
    assert asyncio.run(
        binding.inspect_rebind_preflight("operation:read", max_bytes=1024)
    ) == PackageProductRebindPreflightV1(
        source=observation,
        lease=lease_observation,
        cleanup=cleanup_observation,
    )
    assert asyncio.run(
        binding.inspect_acquired_rebind_claim("operation:read", max_bytes=1024)
    ) == PackageProductAcquiredRebindPreflightV1(
        source=observation,
        lease=lease_observation,
        cleanup=acquired_cleanup_observation,
    )
    binding.dispose_runtime()
    with pytest.raises(PackageProductRuntimeActivationError) as disposed:
        asyncio.run(binding.inspect_rebind_source("operation:read", max_bytes=1024))
    assert disposed.value.code == "package_product_runtime_inactive"
    assert calls == [("operation:read", 1024)] * 3


def test_generic_product_binding_does_not_select_rebind_source_reader() -> None:
    binding = _binding()
    binding.activate()
    with pytest.raises(PackageProductRuntimeActivationError) as absent:
        asyncio.run(binding.inspect_rebind_source("operation:read", max_bytes=1024))
    assert absent.value.code == "package_product_rebind_source_reader_unavailable"
    with pytest.raises(PackageProductRuntimeActivationError) as missing_lease:
        asyncio.run(binding.inspect_rebind_lease("operation:read"))
    assert missing_lease.value.code == "package_product_rebind_lease_reader_unavailable"
    with pytest.raises(PackageProductRuntimeActivationError) as missing_cleanup:
        asyncio.run(binding.inspect_rebind_cleanup("operation:read"))
    assert (
        missing_cleanup.value.code
        == "package_product_rebind_cleanup_reader_unavailable"
    )
    with pytest.raises(PackageProductRuntimeActivationError) as missing_preflight:
        asyncio.run(binding.inspect_rebind_preflight("operation:read", max_bytes=1024))
    assert (
        missing_preflight.value.code == "package_product_rebind_preflight_unavailable"
    )
    with pytest.raises(PackageProductRuntimeActivationError) as missing_acquired:
        asyncio.run(
            binding.inspect_acquired_rebind_claim("operation:read", max_bytes=1024)
        )
    assert missing_acquired.value.code == "package_product_rebind_preflight_unavailable"
    with pytest.raises(PackageProductRuntimeActivationError) as missing_recovery:
        binding.recover_acquired_rebind("operation:read", max_bytes=1024)
    assert missing_recovery.value.code == "package_product_rebind_recovery_unavailable"


def test_acquired_rebind_recovery_uses_product_mutation_guard() -> None:
    class GuardedLifecycle(_Lifecycle):
        inside_guard = False

        def execute_guarded_mutation(self, mutation: Any) -> Any:
            assert self.active
            self.inside_guard = True
            try:
                return mutation("admission:current")
            finally:
                self.inside_guard = False

    lifecycle = GuardedLifecycle()
    result = object()

    class DecisionOwner:
        prepare = resume = route = authorize = revoke = object.__str__
        recover_unstarted_claim = object.__str__

        def recover_acquired_claim(
            self, operation_id: str, *, max_bytes: int, admission: object
        ) -> object:
            assert lifecycle.inside_guard
            assert operation_id == "operation:read"
            assert max_bytes == 1024
            assert admission == "admission:current"
            return result

    binding = PackageProductRuntimeBindingV1(
        product_id="product:test",
        lifecycle=cast(Any, lifecycle),
        inventory=cast(Any, _Inventory()),
        mode="enforced",
        _rebind_decision_owner=cast(Any, DecisionOwner()),
    )
    with pytest.raises(PackageProductRuntimeActivationError) as inactive:
        binding.recover_acquired_rebind("operation:read", max_bytes=1024)
    assert inactive.value.code == "package_product_runtime_inactive"
    binding.activate()
    assert binding.recover_acquired_rebind("operation:read", max_bytes=1024) is result
    assert not lifecycle.inside_guard


def test_rebind_preflight_refuses_split_attempt_observations() -> None:
    source = PackageProductRebindSourceObservationV1(
        operation_id="operation:read",
        request_fingerprint="1" * 64,
        attempt_epoch=1,
        attempt_revision=3,
        artifact_digests=(),
        resolution_evidence_refs=(),
        source_proof_ref="2" * 64,
    )
    lease = PackageProductRebindLeaseObservationV1(
        operation_id="operation:read",
        request_fingerprint="1" * 64,
        attempt_epoch=1,
        attempt_revision=4,
        original_binding_id="3" * 64,
        original_admission_request_id="4" * 64,
        new_admission_request_id="5" * 64,
        store_id="package-store:test",
        old_lease_id="6" * 64,
        new_lease_id="7" * 64,
        lease_snapshot_id="8" * 64,
        lease_owner_revision=2,
    )
    cleanup = PackageProductRebindCleanupObservationV1(
        operation_id="operation:read",
        request_fingerprint="1" * 64,
        attempt_epoch=1,
        attempt_revision=3,
        known_attempts=(),
        store_identity=(1, 2),
        committed_attempts=(),
        artifact_evidence_refs=(),
        resolution_evidence_refs=(),
        cleanup_ids=(),
        known_cleanup_ref="9" * 64,
    )
    with pytest.raises(PackageProductRebindPreflightError) as changed:
        PackageProductRebindPreflightV1(source=source, lease=lease, cleanup=cleanup)
    assert changed.value.code == "package_rebind_preflight_attempt_changed"

    with pytest.raises(PackageProductRebindPreflightError) as late_resolution:
        PackageProductRebindPreflightV1(
            source=source,
            lease=replace(lease, attempt_revision=3),
            cleanup=replace(cleanup, resolution_evidence_refs=("a" * 64,)),
        )
    assert late_resolution.value.code == "package_rebind_preflight_resolution_changed"


def test_package_product_runtime_rejects_split_owner_binding() -> None:
    with pytest.raises(ValueError, match="changed binding"):
        _binding(_Lifecycle("owner:one"), _Inventory("owner:two"))


def test_package_product_runtime_rejects_product_substitution(tmp_path: Path) -> None:
    factory = _Factory(_binding(product_id="product:other"))

    with pytest.raises(PackageProductRuntimeActivationError) as raised:
        activate_package_product_runtime(
            cast(Any, factory),
            PackageProductRuntimeRequestV1(
                product_id="product:test",
                session_id="session:test",
                cwd=str(tmp_path),
            ),
        )

    assert raised.value.code == "package_product_runtime_product_changed"
    assert factory.requests[0].product_id == "product:test"


def test_package_product_runtime_factory_failure_is_opaque(tmp_path: Path) -> None:
    factory = _Factory(
        _binding(),
        fail=RuntimeError("file:///private?token=secret"),
    )

    with pytest.raises(PackageProductRuntimeActivationError) as raised:
        activate_package_product_runtime(
            cast(Any, factory),
            PackageProductRuntimeRequestV1(
                product_id="product:test",
                session_id="session:test",
                cwd=str(tmp_path),
            ),
        )

    assert raised.value.code == "package_product_runtime_factory_failed"
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("lifecycle", "code"),
    [
        (
            _Lifecycle(fail=RuntimeError("file:///private?token=secret")),
            "package_product_runtime_activation_failed",
        ),
        (
            _Lifecycle(publish_active=False),
            "package_product_runtime_activation_incomplete",
        ),
    ],
)
def test_package_product_runtime_activation_fails_closed_without_detail(
    tmp_path: Path,
    lifecycle: _Lifecycle,
    code: str,
) -> None:
    factory = _Factory(_binding(lifecycle))

    with pytest.raises(PackageProductRuntimeActivationError) as raised:
        activate_package_product_runtime(
            cast(Any, factory),
            PackageProductRuntimeRequestV1(
                product_id="product:test",
                session_id="session:test",
                cwd=str(tmp_path),
            ),
        )

    assert raised.value.code == code
    assert "secret" not in str(raised.value)


def test_package_product_runtime_activation_failure_releases_owner(
    tmp_path: Path,
) -> None:
    releases: list[str] = []
    binding = _binding(
        _Lifecycle(fail=RuntimeError("cannot activate")),
        on_dispose=lambda: releases.append("released"),
    )
    with pytest.raises(PackageProductRuntimeActivationError):
        activate_package_product_runtime(
            _Factory(binding),
            PackageProductRuntimeRequestV1(
                product_id="product:test", session_id="session:test", cwd=str(tmp_path)
            ),
        )
    assert releases == ["released"]


def test_package_product_runtime_factory_failure_releases_unbound_owner(
    tmp_path: Path,
) -> None:
    releases: list[str] = []

    class RejectingFactory:
        def create(self, _request: PackageProductRuntimeRequestV1) -> None:
            raise ValueError("wrong Session")

        def dispose_unbound_runtime(self) -> None:
            releases.append("released")

    with pytest.raises(PackageProductRuntimeActivationError) as rejected:
        activate_package_product_runtime(
            cast(Any, RejectingFactory()),
            PackageProductRuntimeRequestV1(
                product_id="product:test", session_id="session:test", cwd=str(tmp_path)
            ),
        )
    assert rejected.value.code == "package_product_runtime_factory_failed"
    assert releases == ["released"]


def test_package_product_runtime_request_requires_absolute_cwd() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        PackageProductRuntimeRequestV1(
            product_id="product:test",
            session_id="session:test",
            cwd="relative",
        )
