from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.cli.package_lifecycle import (
    PackageLifecycleRequest,
    run_package_lifecycle,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
)
from loushang.harness.resources.packages.operations import PackageOperationsRuntime
from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceRequestV1,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecyclePhase,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductActivationError,
    PackageProductLifecycleActivation,
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_composition import (
    compose_package_product_lifecycle,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductEntrypoint,
    PackageProductRouteRequestV1,
)
from loushang.harness.resources.packages.session import SessionPackageController
from loushang.harness.resources.packages.settings_mutation import (
    PackageSourceSettingsMutation,
)
from loushang.harness.resources.packages.source_resolver import PackageSourceResolver

_PHASES: tuple[PackageLifecyclePhase, ...] = (
    "acquiring",
    "acquired",
    "inspecting",
    "extracted",
    "resolving_closure",
    "closure_verified",
    "transaction_pinned",
    "staging",
    "set_published",
    "committed",
)
_ENTRYPOINTS: tuple[PackageProductEntrypoint, ...] = (
    "operations",
    "session",
    "cli",
    "rpc",
    "startup",
)


@dataclass
class _Recovery:
    events: list[str]

    def recover(self) -> None:
        self.events.append("recovered")


@dataclass
class _LeaseAuthority:
    snapshot_value: PackageEpochLeaseSnapshotV1
    calls: int = 0

    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
        self.calls += 1
        assert store_id == self.snapshot_value.store_id
        return self.snapshot_value


@dataclass(frozen=True)
class _ClassificationAuthority:
    decision: str

    def classification_facts(
        self,
        _request: PackageLifecycleIngressRequestV1,
    ) -> PackageClassificationFactsV1:
        present = {
            "plugin_bound": "explicit_plugin_intent",
            "non_plugin": "independent_non_plugin_authority",
        }.get(self.decision)
        kinds = (
            "explicit_plugin_intent",
            "existing_plugin_binding",
            "existing_plugin_history",
            "independent_non_plugin_authority",
        )
        return PackageClassificationFactsV1(
            facts=tuple(
                PackageClassificationBasisFactV1(
                    kind=kind,  # type: ignore[arg-type]
                    present=kind == present,
                    authority_id=f"authority:{kind}",
                    owner_revision="revision:1",
                )
                for kind in kinds
            ),
            policy_revision="policy:1",
            classifier_epoch=1,
        )


@dataclass(frozen=True)
class _IngressFactory:
    def create(
        self,
        intent: PackageProductLifecycleIntentV1,
    ) -> PackageLifecycleIngressRequestV1:
        return PackageLifecycleIngressRequestV1(
            operation_id=intent.operation_id,
            action=intent.action,
            product_id="coding",
            scope_id="workspace:test",
            requested_package="acme==1.0",
            requested_plugin_id="acme.plugin",
            source_locator=intent.source,
            policy_revision="policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=sha256(b"environment").hexdigest(),
        )


@dataclass
class _Transaction:
    owner: PackageLifecycleOwner
    calls: list[PackageProductEntrypoint] = field(default_factory=list)

    def execute(
        self,
        request: PackageProductRouteRequestV1,
        *,
        classified: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls.append(request.entrypoint)
        current = classified
        for phase in _PHASES:
            current = self.owner.advance(
                current.operation_id,
                next_phase=phase,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )
        return current


def _epoch_admission(
    tmp_path: Path,
) -> tuple[
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
    _LeaseAuthority,
]:
    journal = PackageEpochFenceJournal(tmp_path / "epoch.jsonl")
    fence = journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id="package-store:test",
            prior_fence=None,
            legacy_root_identity="1" * 64,
            fenced_root_identity="2" * 64,
            namespace_id="3" * 64,
            minimum_runtime_version="1.0.0",
            minimum_runtime_protocol_epoch=1,
            quiescence_receipt_id="4" * 64,
            snapshot_receipt_id="5" * 64,
            root_switch_receipt_id="6" * 64,
        )
    )
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:test",
        runtime_epoch=fence.epoch,
        store_root_identity=fence.fenced_root_identity,
        registration_receipt_id="7" * 64,
    )
    leases = _LeaseAuthority(
        PackageEpochLeaseSnapshotV1.create(
            store_id=fence.store_id,
            owner_revision=1,
            active_leases=(lease,),
        )
    )
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=fence,
        runtime_id=lease.runtime_id,
        runtime_version="1.0.0",
        runtime_protocol_epoch=1,
        runtime_epoch=lease.runtime_epoch,
        store_root_identity=lease.store_root_identity,
        lease_id=lease.lease_id,
    )
    return (
        PackageEpochRuntimeAdmissionOwner(fences=journal, leases=leases),
        request,
        leases,
    )


def _activation(
    tmp_path: Path,
    *,
    decision: str = "plugin_bound",
    recovery: _Recovery | None = None,
) -> tuple[PackageProductLifecycleActivation, _Transaction]:
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority(decision),
        enabled=True,
    )
    transaction = _Transaction(owner)
    admission, request, _leases = _epoch_admission(tmp_path)
    activation = compose_package_product_lifecycle(
        product_id="coding",
        owner=owner,
        transaction=transaction,
        ingress_factory=_IngressFactory(),
        runtime_admission=admission,
        admission_request=request,
        recoveries=(() if recovery is None else (recovery,)),
    )
    return activation, transaction


def _intent(operation_id: str = "operation:test") -> PackageProductLifecycleIntentV1:
    return PackageProductLifecycleIntentV1(
        operation_id=operation_id,
        action="install",
        source="https://user:secret@example.test/acme.whl?token=hidden",
        scope="project",
    )


def test_activation_recovers_then_admits_before_exposing_router(tmp_path: Path) -> None:
    events: list[str] = []
    activation, transaction = _activation(
        tmp_path,
        recovery=_Recovery(events),
    )

    with pytest.raises(PackageProductActivationError) as raised:
        activation.route(_intent(), entrypoint="cli")

    assert raised.value.code == "package_product_activation_required"
    assert events == []
    assert transaction.calls == []
    receipt = activation.activate()
    assert activation.activate() == receipt
    assert events == ["recovered"]


def test_all_product_entrypoints_share_one_request_identity_and_exact_replay(
    tmp_path: Path,
) -> None:
    activation, transaction = _activation(tmp_path)
    activation.activate()

    outcomes = tuple(
        activation.route(_intent(), entrypoint=entrypoint)
        for entrypoint in _ENTRYPOINTS
    )

    assert all(outcome.handled for outcome in outcomes)
    assert len({outcome.status for outcome in outcomes}) == 1
    assert {outcome.status.operation_id for outcome in outcomes} == {"operation:test"}
    assert transaction.calls == ["operations"]
    assert all("secret" not in repr(outcome.record) for outcome in outcomes)
    assert all(outcome.record is not None for outcome in outcomes)
    assert all(
        outcome.record.to_dict()["path"] == "" for outcome in outcomes if outcome.record
    )
    record = outcomes[0].record
    assert record is not None
    with pytest.raises(ValueError, match="changed lifecycle evidence"):
        replace(
            outcomes[0],
            record=replace(record, source_identity="foreign-source"),
        )


def test_explicit_non_plugin_is_the_only_legacy_fallback(tmp_path: Path) -> None:
    activation, transaction = _activation(tmp_path, decision="non_plugin")
    activation.activate()

    outcome = activation.route(_intent(), entrypoint="rpc")

    assert not outcome.handled
    assert outcome.record is None
    assert outcome.status.classification is not None
    assert outcome.status.classification.decision == "non_plugin"
    assert transaction.calls == []


def test_indeterminate_classification_fails_closed(tmp_path: Path) -> None:
    activation, transaction = _activation(tmp_path, decision="indeterminate")
    activation.activate()

    outcome = activation.route(_intent(), entrypoint="startup")

    assert outcome.handled
    assert outcome.record is not None
    assert outcome.record.lifecycle == "failed"
    assert outcome.record.failure_code == "package_target_classification_indeterminate"
    assert transaction.calls == []


def test_changed_runtime_epoch_deactivates_before_product_transaction(
    tmp_path: Path,
) -> None:
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority("plugin_bound"),
        enabled=True,
    )
    transaction = _Transaction(owner)
    admission, request, leases = _epoch_admission(tmp_path)
    activation = compose_package_product_lifecycle(
        product_id="coding",
        owner=owner,
        transaction=transaction,
        ingress_factory=_IngressFactory(),
        runtime_admission=admission,
        admission_request=request,
    )
    activation.activate()
    foreign_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:replacement",
        runtime_epoch=request.runtime_epoch,
        store_root_identity=request.store_root_identity,
        registration_receipt_id="8" * 64,
    )
    leases.snapshot_value = PackageEpochLeaseSnapshotV1.create(
        store_id=request.store_id,
        owner_revision=2,
        active_leases=(foreign_lease,),
    )

    with pytest.raises(PackageProductActivationError) as raised:
        activation.route(_intent(), entrypoint="rpc")

    assert raised.value.code == "package_runtime_epoch_unsupported"
    assert not activation.active
    assert transaction.calls == []


class _Materializer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.materialize_calls: list[str] = []

    async def materialize_remote_source(
        self, source: str
    ) -> PackageMaterializationRecord:
        self.materialize_calls.append(source)
        return PackageMaterializationRecord(
            source=source,
            name="legacy",
            lifecycle="installed",
            target_path=self.root / "legacy",
        )

    async def update_remote_source(self, source: str) -> PackageMaterializationRecord:
        return await self.materialize_remote_source(source)

    async def update_all_remote_sources(self) -> list[PackageMaterializationRecord]:
        return []

    def remove_remote_source(self, source: str) -> PackageMaterializationRecord:
        raise AssertionError("remove must not run")

    def forget_remote_source(self, source: str) -> None:
        raise AssertionError("forget must not run")

    def list_records(self) -> list[PackageMaterializationRecord]:
        return []


def _operations(
    materializer: _Materializer,
    activation: PackageProductLifecycleActivation,
) -> PackageOperationsRuntime:
    def mutation(source: str, scope: str) -> PackageSourceSettingsMutation:
        raise AssertionError(f"settings mutation must not run: {scope}:{source}")

    return PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=mutation,
        remove_source=mutation,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
    )


def test_operations_routes_plugin_before_legacy_materializer(tmp_path: Path) -> None:
    activation, transaction = _activation(tmp_path)
    activation.activate()
    materializer = _Materializer(tmp_path)

    record = asyncio.run(
        _operations(materializer, activation).materialize(
            _intent().source,
            entrypoint="cli",
            operation_id="operation:operations",
        )
    )

    assert record.lifecycle == "installed"
    assert materializer.materialize_calls == []
    assert transaction.calls == ["cli"]


@pytest.mark.parametrize("action", ("remove", "uninstall"))
def test_plugin_remove_and_uninstall_never_reach_legacy_delete(
    tmp_path: Path,
    action: str,
) -> None:
    activation, transaction = _activation(tmp_path)
    activation.activate()
    materializer = _Materializer(tmp_path)
    operations = _operations(materializer, activation)

    if action == "remove":
        record = operations.remove(
            _intent().source,
            operation_id="operation:remove",
        )
    else:
        record = asyncio.run(
            operations.uninstall(
                _intent().source,
                scope="project",
                operation_id="operation:uninstall",
            )
        )

    assert record.lifecycle == "remote_registered"
    assert materializer.materialize_calls == []
    assert transaction.calls == ["operations"]


def test_operations_preserves_only_explicit_non_plugin_behavior(tmp_path: Path) -> None:
    activation, _transaction = _activation(tmp_path, decision="non_plugin")
    activation.activate()
    materializer = _Materializer(tmp_path)

    record = asyncio.run(
        _operations(materializer, activation).materialize(
            "https://example.test/legacy.git",
            operation_id="operation:legacy",
        )
    )

    assert record.name == "legacy"
    assert materializer.materialize_calls == ["https://example.test/legacy.git"]


def test_active_product_bulk_update_routes_each_record_without_bulk_bypass(
    tmp_path: Path,
) -> None:
    source = _intent().source
    activation, transaction = _activation(tmp_path)
    activation.activate()

    class Materializer(_Materializer):
        async def update_all_remote_sources(self) -> list[PackageMaterializationRecord]:
            raise AssertionError("legacy bulk updater must not run")

        def list_records(self) -> list[PackageMaterializationRecord]:
            return [
                PackageMaterializationRecord(
                    source=source,
                    name="acme",
                    lifecycle="installed",
                    target_path=tmp_path / "legacy",
                )
            ]

    records = asyncio.run(
        _operations(Materializer(tmp_path), activation).update_all(entrypoint="session")
    )

    assert len(records) == 1
    assert records[0].lifecycle == "installed"
    assert transaction.calls == ["session"]


def test_cli_session_operations_chain_preserves_one_product_route(
    tmp_path: Path,
) -> None:
    activation, transaction = _activation(tmp_path)
    activation.activate()
    materializer = _Materializer(tmp_path)
    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=lambda: None,
        get_package_materializer=lambda: materializer,  # type: ignore[arg-type]
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: (_ for _ in ()).throw(
            AssertionError("legacy Resource refresh must not run")
        ),
        product_lifecycle=activation,
    )

    result = asyncio.run(
        run_package_lifecycle(
            controller,
            PackageLifecycleRequest(install=(_intent().source,)),
        )
    )

    assert transaction.calls == ["cli"]
    assert materializer.materialize_calls == []
    record = result.outputs[0]["record"]
    assert isinstance(record, dict)
    assert record["path"] == ""
    assert record["packageLifecycleDisposition"] == "committed"


def test_startup_routes_missing_plugin_before_sync_materializer(tmp_path: Path) -> None:
    source = "https://example.test/acme.whl"
    activation, transaction = _activation(tmp_path)
    activation.activate()

    class Settings:
        def get_project_settings(self) -> dict[str, object]:
            return {"packages": [source]}

        def get_global_settings(self) -> dict[str, object]:
            return {}

        def get_session_settings(self) -> dict[str, object]:
            return {}

    class Materializer:
        def get_record(self, _source: str) -> None:
            return None

        def materialize_remote_source_sync(self, value: str) -> object:
            raise AssertionError(f"legacy startup materializer used for {value}")

    result = PackageSourceResolver(
        settings_manager=Settings(),
        materializer=Materializer(),  # type: ignore[arg-type]
        session_id="session:test",
        product_lifecycle=activation,
    ).resolve_configured_sources_sync()

    assert len(result.records) == 1
    assert result.records[0].lifecycle == "installed"
    assert transaction.calls == ["startup"]
