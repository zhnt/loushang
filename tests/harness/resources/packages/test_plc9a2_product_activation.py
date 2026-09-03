from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import StringIO
from pathlib import Path

import pytest

from loushang.harness.cli.package_lifecycle import (
    PackageLifecycleRequest,
    run_package_lifecycle,
)
from loushang.harness.host.rpc.commands.packages import RpcPackageCommands
from loushang.harness.host.rpc.output import RpcOutput
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
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleEvidenceV1,
    PackageProductUpdateCheckRequestV1,
    PackageProductUpdateCheckV1,
    PackageProductUpdateManifestReceiptV1,
    PackageProductUpdateTargetV1,
)
from loushang.harness.resources.packages.product_inventory import (
    PackageProductUpdateManifestError,
    PackageProductUpdateManifestJournal,
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
    def scope_id(self, intent: PackageProductLifecycleIntentV1) -> str:
        return f"{intent.scope}:coding"

    def create(
        self,
        intent: PackageProductLifecycleIntentV1,
    ) -> PackageLifecycleIngressRequestV1:
        return PackageLifecycleIngressRequestV1(
            operation_id=intent.operation_id,
            action=intent.action,
            product_id="coding",
            scope_id=self.scope_id(intent),
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
    scope_ids: list[str] = field(default_factory=list)
    operation_ids: list[str] = field(default_factory=list)
    crash_after_phase: PackageLifecyclePhase | None = None
    crash_operation_id: str | None = None

    @property
    def owner_binding_id(self) -> str:
        return self.owner.binding_id

    def execute(
        self,
        request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls.append(request.entrypoint)
        self.scope_ids.append(request.ingress.scope_id)
        self.operation_ids.append(current.operation_id)
        remaining = (
            _PHASES[_PHASES.index(current.phase) + 1 :]
            if current.phase in _PHASES
            else _PHASES
        )
        for phase in remaining:
            current = self.owner.advance(
                current.operation_id,
                next_phase=phase,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )
            if phase == self.crash_after_phase and self.crash_operation_id in {
                None,
                current.operation_id,
            }:
                self.crash_after_phase = None
                raise RuntimeError("simulated transaction crash")
        return current


@dataclass
class _EpochGuard:
    entered: int = 0
    on_enter: Callable[[], None] | None = None

    @contextmanager
    def shared_runtime(self, *, store_id: str):
        assert store_id == "package-store:test"
        self.entered += 1
        if self.on_enter is not None:
            self.on_enter()
        try:
            yield
        finally:
            self.entered -= 1


@dataclass
class _Inventory:
    binding_id: str
    sources: tuple[str, ...] = ()
    manifests: PackageProductUpdateManifestJournal | None = None
    bound_targets: dict[str, tuple[str, tuple[str, ...]]] = field(
        default_factory=dict
    )
    check_requests: list[PackageProductUpdateCheckRequestV1] = field(
        default_factory=list
    )

    def list_update_targets(
        self,
        *,
        scope: str,
    ) -> tuple[PackageProductUpdateTargetV1, ...]:
        return tuple(
            PackageProductUpdateTargetV1(
                target_ref=f"sha256:{sha256(source.encode()).hexdigest()}",
                source=source,
                scope=scope,
            )
            for source in self.sources
        )

    def bind_update_targets(
        self,
        *,
        operation_id: str,
        scope: str,
        targets: tuple[PackageProductUpdateTargetV1, ...],
    ) -> PackageProductUpdateManifestReceiptV1:
        target_refs = tuple(target.target_ref for target in targets)
        if self.manifests is not None:
            return self.manifests.bind_receipt(
                operation_id=operation_id,
                scope=scope,
                target_refs=target_refs,
            )
        proposed = (scope, target_refs)
        current = self.bound_targets.setdefault(operation_id, proposed)
        if current != proposed:
            raise RuntimeError("Package Product update targets changed on replay")
        return PackageProductUpdateManifestReceiptV1.create(
            binding_id=self.binding_id,
            operation_id=operation_id,
            scope=scope,
            target_refs=target_refs,
        )

    async def check_updates(
        self,
        *,
        request: PackageProductUpdateCheckRequestV1,
    ) -> tuple[PackageProductUpdateCheckV1, ...]:
        self.check_requests.append(request)
        return tuple(
            PackageProductUpdateCheckV1(
                target_ref=f"sha256:{sha256(source.encode()).hexdigest()}",
                scope=request.scope,
                update_available=True,
            )
            for source in self.sources
        )


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
    ingress_factory: _IngressFactory | None = None,
    transaction_guard: _EpochGuard | None = None,
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
        ingress_factory=ingress_factory or _IngressFactory(),
        runtime_admission=admission,
        admission_request=request,
        transaction_guard=transaction_guard or _EpochGuard(),
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


@pytest.mark.parametrize(
    ("phase", "disposition"),
    (("future_phase", "active"), ("classified", "future_disposition")),
)
def test_product_evidence_rejects_unknown_kernel_state(
    phase: str,
    disposition: str,
) -> None:
    with pytest.raises(ValueError, match="Unsupported Package Product lifecycle"):
        PackageProductLifecycleEvidenceV1(
            operation_id="operation:future",
            request_ref=f"sha256:{'1' * 64}",
            source_ref=f"sha256:{'2' * 64}",
            display_name="plugin-future",
            classification="plugin_bound",
            phase=phase,  # type: ignore[arg-type]
            disposition=disposition,  # type: ignore[arg-type]
            failure_code=None,
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
    assert len({outcome.evidence for outcome in outcomes}) == 1
    assert {outcome.evidence.operation_id for outcome in outcomes} == {"operation:test"}
    assert transaction.calls == ["operations"]
    assert all("secret" not in repr(outcome.record) for outcome in outcomes)
    assert all(outcome.record is not None for outcome in outcomes)
    assert all(
        outcome.record.to_dict()["path"] == "" for outcome in outcomes if outcome.record
    )
    accepted = transaction.owner.journal.request("operation:test")
    assert accepted is not None
    assert accepted.resolution_environment_fingerprint == sha256(
        b"environment"
    ).hexdigest()
    assert accepted.runtime_admission_request_id is not None
    record = outcomes[0].record
    assert record is not None
    with pytest.raises(ValueError, match="changed source identity"):
        replace(
            outcomes[0],
            record=replace(record, source_identity=f"sha256:{'f' * 64}"),
        )


def test_explicit_non_plugin_is_the_only_legacy_fallback(tmp_path: Path) -> None:
    activation, transaction = _activation(tmp_path, decision="non_plugin")
    activation.activate()

    outcome = activation.route(_intent(), entrypoint="rpc")

    assert not outcome.handled
    assert outcome.record is None
    assert outcome.evidence.classification == "non_plugin"
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
        transaction_guard=_EpochGuard(),
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


def test_epoch_change_after_initial_admission_is_refused_inside_transaction_guard(
    tmp_path: Path,
) -> None:
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority("plugin_bound"),
        enabled=True,
    )
    transaction = _Transaction(owner)
    admission, request, leases = _epoch_admission(tmp_path)

    def replace_lease() -> None:
        foreign = PackageEpochRuntimeLeaseV1.create(
            runtime_id="runtime:cutover",
            runtime_epoch=request.runtime_epoch,
            store_root_identity=request.store_root_identity,
            registration_receipt_id="8" * 64,
        )
        leases.snapshot_value = PackageEpochLeaseSnapshotV1.create(
            store_id=request.store_id,
            owner_revision=2,
            active_leases=(foreign,),
        )

    activation = compose_package_product_lifecycle(
        product_id="coding",
        owner=owner,
        transaction=transaction,
        ingress_factory=_IngressFactory(),
        runtime_admission=admission,
        admission_request=request,
        transaction_guard=_EpochGuard(on_enter=replace_lease),
    )
    activation.activate()

    with pytest.raises(PackageProductActivationError) as raised:
        activation.route(_intent(), entrypoint="rpc")

    assert raised.value.code == "package_runtime_epoch_unsupported"
    assert transaction.calls == []
    assert owner.status(_intent().operation_id) is None


def test_active_operation_replay_resumes_to_terminal_state(tmp_path: Path) -> None:
    activation, transaction = _activation(tmp_path)
    activation.activate()
    intent = _intent("operation:resume")
    transaction.crash_after_phase = "acquired"

    with pytest.raises(RuntimeError, match="simulated transaction crash"):
        activation.route(intent, entrypoint="session")
    current = transaction.owner.status(intent.operation_id)
    assert current is not None and current.phase == "acquired"
    activation.activate()

    outcome = activation.route(intent, entrypoint="session")

    assert outcome.evidence.disposition == "committed"
    assert outcome.record is not None and outcome.record.lifecycle == "installed"
    assert transaction.calls == ["session", "session"]


def test_active_operation_cannot_resume_under_a_new_epoch(tmp_path: Path) -> None:
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority("plugin_bound"),
        enabled=True,
    )
    transaction = _Transaction(owner, crash_after_phase="acquired")
    admission, request, leases = _epoch_admission(tmp_path)
    first = compose_package_product_lifecycle(
        product_id="coding",
        owner=owner,
        transaction=transaction,
        ingress_factory=_IngressFactory(),
        runtime_admission=admission,
        admission_request=request,
        transaction_guard=_EpochGuard(),
    )
    first.activate()
    intent = _intent("operation:cross-epoch")
    with pytest.raises(RuntimeError, match="simulated transaction crash"):
        first.route(intent, entrypoint="session")

    epoch_journal = admission._fences  # type: ignore[attr-defined]
    assert isinstance(epoch_journal, PackageEpochFenceJournal)
    prior = epoch_journal.current(request.store_id)
    assert prior is not None
    successor = epoch_journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=prior.store_id,
            prior_fence=prior,
            legacy_root_identity=prior.fenced_root_identity,
            fenced_root_identity="8" * 64,
            namespace_id="9" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id="a" * 64,
            snapshot_receipt_id="b" * 64,
            root_switch_receipt_id="c" * 64,
        )
    )
    successor_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:successor",
        runtime_epoch=successor.epoch,
        store_root_identity=successor.fenced_root_identity,
        registration_receipt_id="d" * 64,
    )
    leases.snapshot_value = PackageEpochLeaseSnapshotV1.create(
        store_id=successor.store_id,
        owner_revision=2,
        active_leases=(successor_lease,),
    )
    successor_request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=successor,
        runtime_id=successor_lease.runtime_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        runtime_epoch=successor_lease.runtime_epoch,
        store_root_identity=successor_lease.store_root_identity,
        lease_id=successor_lease.lease_id,
    )
    replacement = compose_package_product_lifecycle(
        product_id="coding",
        owner=owner,
        transaction=transaction,
        ingress_factory=_IngressFactory(),
        runtime_admission=admission,
        admission_request=successor_request,
        transaction_guard=_EpochGuard(),
    )
    replacement.activate()

    outcome = replacement.route(intent, entrypoint="session")

    current = owner.status(intent.operation_id)
    assert current is not None and current.phase == "acquired"
    assert outcome.record is not None
    assert outcome.record.failure_code == "package_operation_identity_conflict"


@pytest.mark.parametrize(
    "source",
    (
        "/home/alice/private/acme.whl",
        "file:///home/alice/private/acme.whl?token=secret",
    ),
)
def test_product_projection_redacts_local_and_file_uri_sources(
    tmp_path: Path,
    source: str,
) -> None:
    activation, _transaction = _activation(tmp_path)
    activation.activate()

    outcome = activation.route(
        replace(_intent("operation:redaction"), source=source),
        entrypoint="cli",
    )

    projected = outcome.record.to_dict() if outcome.record is not None else {}
    assert "/home/alice" not in repr((outcome, projected))
    assert "token=secret" not in repr((outcome, projected))
    assert str(projected["source"]).startswith("sha256:")


def test_untrusted_requested_plugin_id_cannot_become_public_display_name(
    tmp_path: Path,
) -> None:
    secret = "file:///home/alice/private/acme.whl?token=secret"

    @dataclass(frozen=True)
    class LeakingNameFactory(_IngressFactory):
        def create(
            self,
            intent: PackageProductLifecycleIntentV1,
        ) -> PackageLifecycleIngressRequestV1:
            return replace(super().create(intent), requested_plugin_id=secret)

    activation, _transaction = _activation(
        tmp_path,
        ingress_factory=LeakingNameFactory(),
    )
    activation.activate()

    outcome = activation.route(_intent("operation:display"), entrypoint="rpc")

    assert outcome.record is not None
    assert outcome.record.name.startswith("plugin-")
    assert secret not in repr((outcome, outcome.record.to_dict()))


def test_tampered_scope_binding_is_refused_before_owner_effects(tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class ChangedScopeFactory(_IngressFactory):
        def create(
            self,
            intent: PackageProductLifecycleIntentV1,
        ) -> PackageLifecycleIngressRequestV1:
            return replace(super().create(intent), scope_id="foreign:scope")

    activation, transaction = _activation(
        tmp_path,
        ingress_factory=ChangedScopeFactory(),
    )
    activation.activate()

    with pytest.raises(PackageProductActivationError) as raised:
        activation.route(_intent(), entrypoint="cli")

    assert raised.value.code == "package_product_ingress_changed"
    assert transaction.owner.status(_intent().operation_id) is None


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
    *,
    inventory_sources: tuple[str, ...] = (),
    inventory: _Inventory | None = None,
) -> PackageOperationsRuntime:
    def mutation(source: str, scope: str) -> PackageSourceSettingsMutation:
        raise AssertionError(f"settings mutation must not run: {scope}:{source}")

    return PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=mutation,
        remove_source=mutation,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_inventory=(
            inventory
            if inventory is not None
            else _Inventory(activation.binding_id, inventory_sources)
        ),
        product_lifecycle_mode="enforced",
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


@pytest.mark.parametrize("transport", ("cli", "rpc"))
@pytest.mark.parametrize("action", ("install", "uninstall"))
def test_non_plugin_global_scope_reaches_global_legacy_settings(
    tmp_path: Path,
    transport: str,
    action: str,
) -> None:
    source = "https://example.test/non-plugin.whl"
    activation, _transaction = _activation(tmp_path, decision="non_plugin")
    activation.activate()
    mutations: list[tuple[str, bool]] = []

    class Settings:
        def begin_package_source_mutation(
            self,
            value: str,
            *,
            scope: str,
            present: bool,
        ) -> PackageSourceSettingsMutation:
            assert value == source
            mutations.append((scope, present))
            return PackageSourceSettingsMutation(
                source=value,
                scope=scope,
                changed=True,
                restore=lambda: None,
            )

    class Materializer(_Materializer):
        def remove_remote_source(self, value: str) -> PackageMaterializationRecord:
            return PackageMaterializationRecord(
                source=value,
                name="legacy",
                lifecycle="remote_registered",
                target_path=tmp_path / "legacy",
            )

        def forget_remote_source(self, value: str) -> None:
            assert value == source

    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=Settings,
        get_package_materializer=lambda: Materializer(tmp_path),
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_lifecycle_mode="enforced",
    )

    if transport == "cli":
        request = (
            PackageLifecycleRequest(install=(source,), scope="global")
            if action == "install"
            else PackageLifecycleRequest(uninstall=(source,), scope="global")
        )
        asyncio.run(run_package_lifecycle(controller, request))
    else:
        stdout = StringIO()
        commands = RpcPackageCommands(
            runtime=object(),
            get_session=lambda: controller,
            output=RpcOutput(stdout),
        )
        asyncio.run(
            dict(commands.bindings())[f"{action}_package"](
                "request:global",
                {"source": source, "scope": "global"},
            )
        )
        assert json.loads(stdout.getvalue())["success"] is True

    assert mutations == [("global", action == "install")]


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
        _operations(
            Materializer(tmp_path),
            activation,
            inventory_sources=(source,),
        ).update_all(entrypoint="session", operation_id="bulk:test")
    )

    assert len(records) == 1
    assert records[0].lifecycle == "installed"
    assert transaction.calls == ["session"]


def test_product_bulk_update_rechecks_mutable_inventory_owner(
    tmp_path: Path,
) -> None:
    source = _intent().source
    activation, transaction = _activation(tmp_path)
    activation.activate()

    class Inventory(_Inventory):
        def list_update_targets(
            self,
            *,
            scope: str,
        ) -> tuple[PackageProductUpdateTargetV1, ...]:
            targets = super().list_update_targets(scope=scope)
            self.binding_id = "foreign-owner"
            return targets

    operations = _operations(
        _Materializer(tmp_path),
        activation,
        inventory=Inventory(activation.binding_id, (source,)),
    )

    with pytest.raises(RuntimeError, match="owner changed after listing"):
        asyncio.run(
            operations.update_all(
                entrypoint="session",
                operation_id="bulk:mutable-owner",
            )
        )

    assert transaction.calls == []
    assert not activation.active


def test_product_bulk_update_has_stable_children_and_exact_partial_replay(
    tmp_path: Path,
) -> None:
    sources = (
        "https://example.test/zeta.whl",
        "https://example.test/alpha.whl",
    )
    lifecycle_path = tmp_path / "lifecycle.jsonl"
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(lifecycle_path),
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
        transaction_guard=_EpochGuard(),
    )
    activation.activate()
    manifest_path = tmp_path / "update-manifests.jsonl"
    operations = _operations(
        _Materializer(tmp_path),
        activation,
        inventory=_Inventory(
            activation.binding_id,
            sources,
            PackageProductUpdateManifestJournal(
                manifest_path,
                binding_id=activation.binding_id,
            ),
        ),
    )
    target_refs = sorted(
        f"sha256:{sha256(source.encode()).hexdigest()}" for source in sources
    )
    child_ids = tuple(
        sha256(f"bulk:stable\0{target_ref}".encode()).hexdigest()
        for target_ref in target_refs
    )
    transaction.crash_after_phase = "acquired"
    transaction.crash_operation_id = child_ids[1]

    with pytest.raises(RuntimeError, match="simulated transaction crash"):
        asyncio.run(
            operations.update_all(
                entrypoint="session",
                operation_id="bulk:stable",
            )
        )
    assert transaction.operation_ids == [child_ids[0], child_ids[1]]
    first_status = transaction.owner.status(child_ids[0])
    second_status = transaction.owner.status(child_ids[1])
    assert first_status is not None and first_status.disposition == "committed"
    assert second_status is not None and second_status.phase == "acquired"

    restarted_owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(lifecycle_path),
        classification_authority=_ClassificationAuthority("plugin_bound"),
        enabled=True,
    )
    restarted_transaction = _Transaction(restarted_owner)
    restarted_activation = compose_package_product_lifecycle(
        product_id="coding",
        owner=restarted_owner,
        transaction=restarted_transaction,
        ingress_factory=_IngressFactory(),
        runtime_admission=PackageEpochRuntimeAdmissionOwner(
            fences=PackageEpochFenceJournal(tmp_path / "epoch.jsonl"),
            leases=leases,
        ),
        admission_request=request,
        transaction_guard=_EpochGuard(),
    )
    restarted_activation.activate()
    drifted_operations = _operations(
        _Materializer(tmp_path),
        restarted_activation,
        inventory=_Inventory(
            restarted_activation.binding_id,
            (sources[0],),
            PackageProductUpdateManifestJournal(
                manifest_path,
                binding_id=restarted_activation.binding_id,
            ),
        ),
    )
    with pytest.raises(
        PackageProductUpdateManifestError,
        match="targets changed",
    ):
        asyncio.run(
            drifted_operations.update_all(
                entrypoint="session",
                operation_id="bulk:stable",
            )
        )

    restarted_activation.activate()
    restarted_operations = _operations(
        _Materializer(tmp_path),
        restarted_activation,
        inventory=_Inventory(
            restarted_activation.binding_id,
            sources,
            PackageProductUpdateManifestJournal(
                manifest_path,
                binding_id=restarted_activation.binding_id,
            ),
        ),
    )
    replayed = asyncio.run(
        restarted_operations.update_all(
            entrypoint="session",
            operation_id="bulk:stable",
        )
    )

    assert len(replayed) == 2
    assert transaction.operation_ids == [child_ids[0], child_ids[1]]
    assert restarted_transaction.operation_ids == [child_ids[1]]
    assert all(record.lifecycle == "installed" for record in replayed)


def test_product_update_manifest_repairs_partial_tail_and_stays_private(
    tmp_path: Path,
) -> None:
    path = tmp_path / "update-manifests.jsonl"
    journal = PackageProductUpdateManifestJournal(path, binding_id="owner:test")
    target_ref = f"sha256:{'1' * 64}"
    accepted = journal.bind(
        operation_id="bulk:durable",
        scope="project",
        target_refs=(target_ref,),
    )
    with path.open("ab") as stream:
        stream.write(b'{"partial"')

    replay = PackageProductUpdateManifestJournal(
        path,
        binding_id="owner:test",
    ).bind(
        operation_id="bulk:durable",
        scope="project",
        target_refs=(target_ref,),
    )

    assert replay == accepted
    assert path.stat().st_mode & 0o077 == 0
    assert PackageProductUpdateManifestJournal(
        path,
        binding_id="owner:test",
    ).records() == (accepted,)


def test_product_update_manifest_is_bound_to_exact_owner(tmp_path: Path) -> None:
    path = tmp_path / "update-manifests.jsonl"
    target_ref = f"sha256:{'2' * 64}"
    owner = PackageProductUpdateManifestJournal(path, binding_id="owner:one")
    receipt = owner.bind_receipt(
        operation_id="bulk:owner",
        scope="project",
        target_refs=(target_ref,),
    )

    assert receipt == PackageProductUpdateManifestReceiptV1.create(
        binding_id="owner:one",
        operation_id="bulk:owner",
        scope="project",
        target_refs=(target_ref,),
    )
    with pytest.raises(PackageProductUpdateManifestError) as raised:
        PackageProductUpdateManifestJournal(
            path,
            binding_id="owner:two",
        ).records()
    assert raised.value.code == "package_product_update_manifest_corrupt"


def test_product_update_manifest_rejects_permissive_or_symlink_storage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "update-manifests.jsonl"
    journal = PackageProductUpdateManifestJournal(path, binding_id="owner:test")
    journal.bind(
        operation_id="bulk:private",
        scope="project",
        target_refs=(f"sha256:{'3' * 64}",),
    )
    path.chmod(0o666)
    try:
        with pytest.raises(PackageProductUpdateManifestError) as permissive:
            journal.records()
        assert (
            permissive.value.code
            == "package_product_update_manifest_storage_unsafe"
        )
    finally:
        path.chmod(0o600)

    linked = tmp_path / "linked-manifests.jsonl"
    linked.symlink_to(path)
    with pytest.raises(PackageProductUpdateManifestError) as symlinked:
        PackageProductUpdateManifestJournal(
            linked,
            binding_id="owner:test",
        ).records()
    assert symlinked.value.code == "package_product_update_manifest_storage_unsafe"


def test_product_update_check_uses_product_inventory_without_materializer(
    tmp_path: Path,
) -> None:
    source = "https://example.test/acme.whl"
    activation, transaction = _activation(tmp_path)
    activation.activate()
    inventory = _Inventory(activation.binding_id, (source,))
    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=lambda: None,
        get_package_materializer=lambda: (_ for _ in ()).throw(
            AssertionError("legacy materializer must not be queried")
        ),
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_inventory=inventory,
        product_lifecycle_mode="enforced",
    )

    updates = asyncio.run(
        controller.execute_package_lifecycle_collection(
            "check",
            entrypoint="rpc",
            operation_id="check:stable",
            scope="global",
        )
    )

    digest = sha256(source.encode()).hexdigest()
    assert updates == [
        {
            "checkVersion": 1,
            "errorCode": "",
            "name": f"plugin-{digest[:12]}",
            "scope": "user",
            "source": f"sha256:{digest}",
            "updateAvailable": True,
        }
    ]
    assert transaction.calls == []
    assert inventory.check_requests == [
        PackageProductUpdateCheckRequestV1(
            operation_id="check:stable",
            entrypoint="rpc",
            scope="user",
        )
    ]


def test_cli_and_rpc_preserve_real_product_check_correlation(
    tmp_path: Path,
) -> None:
    source = "https://example.test/acme.whl"
    activation, _transaction = _activation(tmp_path)
    activation.activate()
    inventory = _Inventory(activation.binding_id, (source,))
    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=lambda: None,
        get_package_materializer=lambda: None,
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_inventory=inventory,
        product_lifecycle_mode="enforced",
    )

    cli_result = asyncio.run(
        run_package_lifecycle(
            controller,
            PackageLifecycleRequest(check_updates=True, scope="global"),
        )
    )
    stdout = StringIO()
    rpc = RpcPackageCommands(
        runtime=object(),
        get_session=lambda: controller,
        output=RpcOutput(stdout),
    )
    handler = dict(rpc.bindings())["check_package_updates"]
    asyncio.run(handler("request:check", {"scope": "global"}))
    asyncio.run(handler("request:check", {"scope": "global"}))

    cli_request, first_rpc, second_rpc = inventory.check_requests
    assert cli_request.entrypoint == "cli"
    assert len(cli_request.operation_id) == 32
    assert first_rpc == second_rpc == PackageProductUpdateCheckRequestV1(
        operation_id=sha256(
            b"rpc:check_package_updates:request:check"
        ).hexdigest(),
        entrypoint="rpc",
        scope="user",
    )
    assert cli_request.scope == "user"
    assert cli_result.outputs[0]["records"][0]["source"].startswith("sha256:")
    assert all(
        json.loads(line)["success"]
        for line in stdout.getvalue().splitlines()
    )


def test_product_update_check_redacts_inventory_failure_detail(tmp_path: Path) -> None:
    secret = "file:///home/alice/private/acme.whl?token=secret"
    source = "https://example.test/acme.whl"
    activation, _transaction = _activation(tmp_path)
    activation.activate()

    class Inventory(_Inventory):
        async def check_updates(
            self,
            *,
            request: PackageProductUpdateCheckRequestV1,
        ) -> tuple[PackageProductUpdateCheckV1, ...]:
            return (
                PackageProductUpdateCheckV1(
                    target_ref=f"sha256:{sha256(source.encode()).hexdigest()}",
                    scope=request.scope,
                    update_available=False,
                    failure_code=secret,
                ),
            )

    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=lambda: None,
        get_package_materializer=lambda: None,
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_inventory=Inventory(activation.binding_id, (source,)),
        product_lifecycle_mode="enforced",
    )

    updates = asyncio.run(controller.check_package_updates())

    assert secret not in repr(updates)
    assert updates[0]["errorCode"] == "package_update_check_failed"
    assert str(updates[0]["name"]).startswith("plugin-")


def test_product_update_check_rechecks_mutable_inventory_owner(tmp_path: Path) -> None:
    activation, _transaction = _activation(tmp_path)
    activation.activate()

    class Inventory(_Inventory):
        async def check_updates(
            self,
            *,
            request: PackageProductUpdateCheckRequestV1,
        ) -> tuple[PackageProductUpdateCheckV1, ...]:
            self.binding_id = "foreign-owner"
            return ()

    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=lambda: None,
        get_package_materializer=lambda: None,
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_inventory=Inventory(activation.binding_id),
        product_lifecycle_mode="enforced",
    )

    with pytest.raises(RuntimeError, match="owner changed"):
        asyncio.run(controller.check_package_updates())
    assert not activation.active


def test_deactivated_product_never_reads_update_inventory(tmp_path: Path) -> None:
    activation, transaction = _activation(tmp_path)
    activation.activate()
    transaction.crash_after_phase = "acquired"
    checks = 0

    class Inventory(_Inventory):
        async def check_updates(
            self,
            *,
            request: PackageProductUpdateCheckRequestV1,
        ) -> tuple[PackageProductUpdateCheckV1, ...]:
            nonlocal checks
            checks += 1
            return ()

    controller = SessionPackageController(
        get_session_id=lambda: "session:test",
        get_cwd=lambda: str(tmp_path),
        get_settings_manager=lambda: None,
        get_package_materializer=lambda: None,
        get_resource_loader=lambda: None,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: None,
        product_lifecycle=activation,
        product_inventory=Inventory(activation.binding_id),
        product_lifecycle_mode="enforced",
    )
    with pytest.raises(RuntimeError, match="simulated transaction crash"):
        asyncio.run(
            controller.execute_package_lifecycle(
                "update",
                _intent().source,
                entrypoint="session",
                operation_id="operation:deactivate",
            )
        )

    with pytest.raises(PackageProductActivationError) as raised:
        asyncio.run(controller.check_package_updates())

    assert raised.value.code == "package_product_activation_required"
    assert checks == 0


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
        product_lifecycle_mode="enforced",
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


def test_cli_preserves_scope_for_every_typed_single_source_action() -> None:
    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def execute_package_lifecycle(
            self,
            action: str,
            source: str,
            *,
            entrypoint: str,
            operation_id: str,
            scope: str,
        ) -> dict[str, object]:
            del source, operation_id
            assert entrypoint == "cli"
            self.calls.append((action, scope))
            return {"lifecycle": "installed"}

    session = Session()
    asyncio.run(
        run_package_lifecycle(
            session,
            PackageLifecycleRequest(
                install=("install",),
                materialize=("materialize",),
                update=("update",),
                remove=("remove",),
                uninstall=("uninstall",),
                scope="session",
            ),
        )
    )

    assert session.calls == [
        ("install", "session"),
        ("materialize", "session"),
        ("update", "session"),
        ("remove", "session"),
        ("uninstall", "session"),
    ]


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
        product_lifecycle_mode="enforced",
    ).resolve_configured_sources_sync()

    assert len(result.records) == 1
    assert result.records[0].lifecycle == "installed"
    assert transaction.calls == ["startup"]


def test_startup_preserves_project_user_and_session_source_scopes(
    tmp_path: Path,
) -> None:
    sources = {
        "project": "https://example.test/project.whl",
        "user": "https://example.test/user.whl",
        "session": "https://example.test/session.whl",
    }
    activation, transaction = _activation(tmp_path)
    activation.activate()

    class Settings:
        def get_project_settings(self) -> dict[str, object]:
            return {"packages": [sources["project"]]}

        def get_global_settings(self) -> dict[str, object]:
            return {"packages": [sources["user"]]}

        def get_session_settings(self) -> dict[str, object]:
            return {"packages": [sources["session"]]}

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
        product_lifecycle_mode="enforced",
    ).resolve_configured_sources_sync()

    assert len(result.records) == 3
    assert transaction.scope_ids == [
        "project:coding",
        "user:coding",
        "session:coding",
    ]
