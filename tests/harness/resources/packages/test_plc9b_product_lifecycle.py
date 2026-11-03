from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest

from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseReader,
    PackageProductRebindLeaseReadError,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleIngressRequestV2,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeAdmissionReceiptV1,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecyclePhase,
    PackageLifecyclePinnedAdoptionRequestV1,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleStagingAdoptionRequestV1,
)
from loushang.harness.resources.packages.product_admission_binding import (
    PackageProductAdmissionBindingJournal,
    PackageProductAdmissionBindingJournalError,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductEntrypoint,
    PackageProductLifecycleExecutionBinding,
    PackageProductLifecycleRouter,
    PackageProductPinnedAdoptedRouteRequestV1,
    PackageProductPublishAttemptV1,
    PackageProductReboundRouteRequestV1,
    PackageProductRouteContractError,
    PackageProductRouteRequestV1,
    PackageProductStagingAdoptedRouteRequestV1,
    require_rebound_decision,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingError,
    PackageProductPinnedAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingError,
    PackageProductRebindAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingError,
    PackageProductStagingAdoptionBindingJournal,
)

TRANSACTION_ENTRYPOINTS: tuple[PackageProductEntrypoint, ...] = (
    "cli",
    "rpc",
    "session",
    "startup",
    "operations",
)
TRANSACTION_PHASES: tuple[PackageLifecyclePhase, ...] = (
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


@dataclass(frozen=True)
class _ClassificationAuthority:
    decision: str = "plugin_bound"

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
                    owner_revision=f"revision:{kind}:1",
                )
                for kind in kinds
            ),
            policy_revision="classification-policy:1",
            classifier_epoch=1,
        )


@dataclass
class _CommittingTransaction:
    owner: PackageLifecycleOwner
    calls: list[PackageProductEntrypoint] = field(default_factory=list)
    before_execute: Callable[[], None] | None = None

    @property
    def owner_binding_id(self) -> str:
        return self.owner.binding_id

    def finalize_committed(
        self,
        _request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None:
        assert (current.phase, current.disposition) == ("committed", "committed")

    def execute(
        self,
        request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        if self.before_execute is not None:
            self.before_execute()
        self.calls.append(request.entrypoint)
        remaining = (
            TRANSACTION_PHASES[TRANSACTION_PHASES.index(current.phase) + 1 :]
            if current.phase in TRANSACTION_PHASES
            else TRANSACTION_PHASES
        )
        for phase in remaining:
            current = self.owner.advance(
                current.operation_id,
                next_phase=phase,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )
        return current


@dataclass
class _InvalidTransaction:
    owner: PackageLifecycleOwner
    calls: int = 0

    @property
    def owner_binding_id(self) -> str:
        return self.owner.binding_id

    def finalize_committed(
        self,
        _request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None:
        assert current.disposition == "committed"

    def execute(
        self,
        _request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls += 1
        return current


@dataclass
class _FinalizingTransaction(_CommittingTransaction):
    finalization_calls: int = 0
    interrupt_once: bool = True

    def finalize_committed(
        self,
        _request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None:
        assert (current.phase, current.disposition) == ("committed", "committed")
        self.finalization_calls += 1
        if self.interrupt_once:
            self.interrupt_once = False
            raise RuntimeError("handoff interrupted before journal open")


def _ingress(
    *, operation_id: str = "product-route-operation"
) -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id=operation_id,
        action="install",
        product_id="coding",
        scope_id="workspace:product-route",
        requested_package="acme==1.0",
        requested_plugin_id="acme.plugin",
        source_locator="https://user:secret@packages.example.test/acme.whl?token=secret",
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint=sha256(b"product-route-env").hexdigest(),
    )


def _admission(
    *, runtime_id: str = "runtime:test"
) -> PackageEpochRuntimeAdmissionReceiptV1:
    fence = PackageEpochFenceReceiptV1.create(
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
        runtime_id=runtime_id,
        runtime_epoch=fence.epoch,
        store_root_identity=fence.fenced_root_identity,
        registration_receipt_id="7" * 64,
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
    return PackageEpochRuntimeAdmissionReceiptV1.create(
        request,
        snapshot=PackageEpochLeaseSnapshotV1.create(
            store_id=fence.store_id,
            owner_revision=1,
            active_leases=(lease,),
        ),
    )


def _route_request(
    entrypoint: PackageProductEntrypoint,
    ingress: PackageLifecycleIngressRequestV1 | None = None,
    *,
    admission: PackageEpochRuntimeAdmissionReceiptV1 | None = None,
) -> PackageProductRouteRequestV1:
    admission = admission or _admission()
    return PackageProductRouteRequestV1(
        entrypoint=entrypoint,
        ingress=PackageLifecycleIngressRequestV2.bind_runtime_admission(
            ingress or _ingress(),
            runtime_admission_request_id=(admission.request.admission_request_id),
        ),
        admission=admission,
    )


def _router(
    tmp_path: Path,
    *,
    decision: str = "plugin_bound",
    enabled: bool = True,
    admission_binding: PackageProductAdmissionBindingJournal | None = None,
) -> tuple[
    PackageProductLifecycleRouter,
    PackageLifecycleOwner,
    PackageLifecycleJournal,
    _CommittingTransaction,
]:
    journal = PackageLifecycleJournal(tmp_path / "package-product-route.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal,
        classification_authority=_ClassificationAuthority(decision),
        enabled=enabled,
    )
    transaction = _CommittingTransaction(owner)
    return (
        PackageProductLifecycleRouter(
            execution=PackageProductLifecycleExecutionBinding(owner, transaction),
            admission_binding=admission_binding,
        ),
        owner,
        journal,
        transaction,
    )


def test_selected_pinned_adoption_blocks_original_product_route(
    tmp_path: Path,
) -> None:
    router, owner, journal, transaction = _router(tmp_path)
    request = _route_request("cli")
    status = owner.submit(request.ingress)
    for phase in (
        "acquiring", "acquired", "inspecting", "extracted",
        "resolving_closure", "closure_verified", "transaction_pinned",
    ):
        status = owner.advance(
            status.operation_id,
            next_phase=phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    decision = PackageLifecyclePinnedAdoptionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
        expected_attempt_revision=status.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        closure_plan_fingerprint="4" * 64,
        pin_receipt_id="5" * 64,
        lease_snapshot_id="6" * 64,
    )
    journal.record_pinned_adoption(decision)
    with pytest.raises(PackageProductRouteContractError) as blocked:
        router.route(request)
    assert blocked.value.code == "package_pinned_adoption_route_required"
    assert transaction.calls == []
    reopened = PackageLifecycleJournal(journal.path)
    observed = reopened.read_operation(status.operation_id)
    assert observed is not None
    with pytest.raises(PackageProductRouteContractError) as replay_blocked:
        require_rebound_decision(request, observed[1], reopened)
    assert replay_blocked.value.code == "package_pinned_adoption_route_required"


def test_product_admission_binding_persists_original_lease_before_transaction(
    tmp_path: Path,
) -> None:
    binding = PackageProductAdmissionBindingJournal(tmp_path / "admission.jsonl")
    lock = binding.path.with_name(f"{binding.path.name}.lock")
    assert binding.read_binding("missing") is None
    assert not binding.path.exists()
    assert not lock.exists()

    router, owner, lifecycle, transaction = _router(tmp_path, admission_binding=binding)
    admission = _admission()
    route_request = _route_request("cli", admission=admission)
    accepted_before_binding = owner.submit(route_request.ingress)
    assert accepted_before_binding.disposition == "active"
    assert binding.read_binding(accepted_before_binding.operation_id) is None

    def require_binding_before_transaction() -> None:
        assert binding.read_binding(accepted_before_binding.operation_id) is not None

    transaction.before_execute = require_binding_before_transaction
    routed = router.route(route_request)
    assert routed.disposition == "committed"
    assert transaction.calls == ["cli"]
    original = lifecycle.read_operation(routed.operation_id)
    assert original is not None
    request, status = original
    assert isinstance(request, PackageLifecycleRequestV2)
    recorded = binding.read_binding(routed.operation_id)
    assert recorded is not None
    assert (
        PackageProductAdmissionBindingJournal(binding.path).read_binding(
            routed.operation_id
        )
        == recorded
    )
    assert recorded.request_fingerprint == request.request_fingerprint
    assert recorded.admission.request.lease_id == admission.request.lease_id
    assert recorded.admission.request.admission_request_id == (
        request.runtime_admission_request_id
    )
    before_replay = binding.path.read_bytes()
    assert binding.bind(request, status, admission) == recorded
    assert binding.path.read_bytes() == before_replay
    same_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=admission.request.runtime_id,
        runtime_epoch=admission.request.runtime_epoch,
        store_root_identity=admission.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    refreshed_receipt = PackageEpochRuntimeAdmissionReceiptV1.create(
        admission.request,
        snapshot=PackageEpochLeaseSnapshotV1.create(
            store_id=admission.request.store_id,
            owner_revision=2,
            active_leases=(same_lease,),
        ),
    )
    assert refreshed_receipt != admission
    assert binding.bind(request, status, refreshed_receipt) == recorded
    assert binding.path.read_bytes() == before_replay

    with pytest.raises(PackageProductAdmissionBindingJournalError) as changed:
        binding.bind(request, status, _admission(runtime_id="runtime:other"))
    assert changed.value.code == "package_product_admission_binding_conflict"
    assert binding.path.read_bytes() == before_replay

    with binding.path.open("ab") as output:
        output.write(b'{"partial":')
    corrupted = binding.path.read_bytes()
    with pytest.raises(PackageProductAdmissionBindingJournalError) as invalid:
        binding.read_binding(routed.operation_id)
    assert invalid.value.code == "package_product_admission_binding_corrupt"
    assert binding.path.read_bytes() == corrupted


def test_product_rebind_proposal_binds_full_admission_before_package_decision(
    tmp_path: Path,
) -> None:
    journal = PackageProductRebindAdmissionBindingJournal(
        tmp_path / "rebind-admissions.jsonl"
    )
    admission = _admission(runtime_id="runtime:new")
    decision = PackageLifecycleRebindRequestV1(
        operation_id="operation:rebind",
        request_fingerprint="1" * 64,
        expected_attempt_epoch=1,
        expected_attempt_revision=3,
        new_runtime_admission_request_id=admission.request.admission_request_id,
        source_proof_ref="2" * 64,
        cleanup_evidence_ref="3" * 64,
        lease_snapshot_id=admission.lease_snapshot_id,
    )
    lock = journal.path.with_name(f"{journal.path.name}.lock")
    assert journal.read_decision(decision.decision_id) is None
    assert journal.read_operation(decision.operation_id) == ()
    assert not journal.path.exists()
    assert not lock.exists()

    proposal = journal.bind(decision, admission)
    assert proposal.admission.request.lease_id == admission.request.lease_id
    assert proposal.decision == decision
    assert (
        PackageProductRebindAdmissionBindingJournal(journal.path).read_decision(
            decision.decision_id
        )
        == proposal
    )
    assert journal.read_operation(decision.operation_id) == (proposal,)
    before = journal.path.read_bytes()
    assert journal.bind(decision, admission) == proposal
    assert journal.path.read_bytes() == before

    with pytest.raises(PackageProductRebindAdmissionBindingError) as changed:
        journal.bind(decision, _admission(runtime_id="runtime:other"))
    assert changed.value.code == "package_product_rebind_admission_invalid"
    assert journal.path.read_bytes() == before

    with journal.path.open("ab") as output:
        output.write(b'{"partial":')
    corrupt = journal.path.read_bytes()
    with pytest.raises(PackageProductRebindAdmissionBindingError) as invalid:
        journal.read_decision(decision.decision_id)
    assert invalid.value.code == "package_product_rebind_admission_corrupt"
    assert journal.path.read_bytes() == corrupt


def test_product_pinned_adoption_proposal_is_durable_and_inert(
    tmp_path: Path,
) -> None:
    proposals = PackageProductPinnedAdoptionBindingJournal(
        tmp_path / "pinned-admissions.jsonl"
    )
    admission = _admission(runtime_id="runtime:new-pinned")
    decision = PackageLifecyclePinnedAdoptionRequestV1(
        operation_id="operation:pinned",
        request_fingerprint="1" * 64,
        expected_journal_revision=9,
        expected_attempt_epoch=2,
        expected_attempt_revision=4,
        new_runtime_admission_request_id=admission.request.admission_request_id,
        source_proof_ref="2" * 64,
        closure_plan_fingerprint="3" * 64,
        pin_receipt_id="4" * 64,
        lease_snapshot_id=admission.lease_snapshot_id,
    )
    lock = proposals.path.with_name(f"{proposals.path.name}.lock")
    assert proposals.read_decision(decision.decision_id) is None
    assert not proposals.path.exists()
    assert not lock.exists()
    recorded = proposals.bind(decision, admission)
    assert recorded.decision == decision
    assert recorded.admission.request == admission.request
    assert PackageProductPinnedAdoptionBindingJournal(
        proposals.path
    ).read_decision(decision.decision_id) == recorded
    before = proposals.path.read_bytes()
    assert proposals.bind(decision, admission) == recorded
    assert proposals.path.read_bytes() == before
    with pytest.raises(PackageProductPinnedAdoptionBindingError) as changed:
        proposals.bind(decision, _admission(runtime_id="runtime:different"))
    assert changed.value.code == "package_product_pinned_adoption_binding_invalid"
    assert proposals.path.read_bytes() == before
    with proposals.path.open("ab") as output:
        output.write(b'{"partial":')
    corrupt = proposals.path.read_bytes()
    with pytest.raises(PackageProductPinnedAdoptionBindingError) as invalid:
        proposals.read_decision(decision.decision_id)
    assert invalid.value.code == "package_product_pinned_adoption_binding_corrupt"
    assert proposals.path.read_bytes() == corrupt


def test_product_staging_adoption_proposal_is_durable_and_inert(
    tmp_path: Path,
) -> None:
    proposals = PackageProductStagingAdoptionBindingJournal(
        tmp_path / "staging-admissions.jsonl"
    )
    admission = _admission(runtime_id="runtime:new-staging")
    decision = PackageLifecycleStagingAdoptionRequestV1(
        operation_id="operation:staging",
        request_fingerprint="1" * 64,
        expected_journal_revision=9,
        expected_attempt_epoch=2,
        expected_attempt_revision=4,
        new_runtime_admission_request_id=admission.request.admission_request_id,
        source_proof_ref="2" * 64,
        closure_plan_fingerprint="3" * 64,
        pin_receipt_id="4" * 64,
        staging_checkpoint_id="5" * 64,
        lease_snapshot_id=admission.lease_snapshot_id,
        previous_selected_decision_id="6" * 64,
    )
    lock = proposals.path.with_name(f"{proposals.path.name}.lock")
    assert proposals.read_decision(decision.decision_id) is None
    assert not proposals.path.exists()
    assert not lock.exists()
    recorded = proposals.bind(decision, admission)
    assert recorded.decision == decision
    assert recorded.admission == admission
    assert PackageProductStagingAdoptionBindingJournal(
        proposals.path
    ).read_decision(decision.decision_id) == recorded
    before = proposals.path.read_bytes()
    assert proposals.bind(decision, admission) == recorded
    assert proposals.path.read_bytes() == before
    with pytest.raises(PackageProductStagingAdoptionBindingError) as changed:
        proposals.bind(decision, _admission(runtime_id="runtime:different"))
    assert changed.value.code == "package_product_staging_adoption_binding_invalid"
    assert proposals.path.read_bytes() == before
    with proposals.path.open("ab") as output:
        output.write(b'{"partial":')
    corrupt = proposals.path.read_bytes()
    with pytest.raises(PackageProductStagingAdoptionBindingError) as invalid:
        proposals.read_decision(decision.decision_id)
    assert invalid.value.code == "package_product_staging_adoption_binding_corrupt"
    assert proposals.path.read_bytes() == corrupt


def test_pinned_lease_reader_requires_selected_product_proposal(
    tmp_path: Path,
) -> None:
    original_admission = _admission(runtime_id="runtime:original-pinned")
    rebound_admission = _admission(runtime_id="runtime:rebound-pinned")
    adopted_admission = _admission(runtime_id="runtime:adopted-pinned")
    lifecycle = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=lifecycle,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    ingress = _route_request("cli", admission=original_admission).ingress
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original_request = lifecycle.request(failed.operation_id)
    assert isinstance(original_request, PackageLifecycleRequestV2)
    original_bindings = PackageProductAdmissionBindingJournal(
        tmp_path / "original.jsonl"
    )
    original_bindings.bind(original_request, failed, original_admission)
    rebound_bindings = PackageProductRebindAdmissionBindingJournal(
        tmp_path / "rebound.jsonl"
    )
    rebound_decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id=(
            rebound_admission.request.admission_request_id
        ),
        source_proof_ref="2" * 64,
        cleanup_evidence_ref="3" * 64,
        lease_snapshot_id=rebound_admission.lease_snapshot_id,
    )
    rebound_bindings.bind(rebound_decision, rebound_admission)
    rebound_record = lifecycle.record_rebind(rebound_decision)
    status = owner.resume_rebind(
        rebound_decision,
        expected_rebind_record_revision=rebound_record.record_revision,
    )
    for phase in (
        "acquiring", "acquired", "inspecting", "extracted",
        "resolving_closure", "closure_verified", "transaction_pinned",
    ):
        status = owner.advance(
            status.operation_id,
            next_phase=phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    adopted_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=adopted_admission.request.runtime_id,
        runtime_epoch=adopted_admission.request.runtime_epoch,
        store_root_identity=adopted_admission.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )

    @dataclass
    class Snapshots:
        value: PackageEpochLeaseSnapshotV1

        def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
            assert store_id == adopted_admission.request.store_id
            return self.value

    pinned_bindings = PackageProductPinnedAdoptionBindingJournal(
        tmp_path / "pinned.jsonl"
    )
    snapshots = Snapshots(
        PackageEpochLeaseSnapshotV1.create(
            store_id=adopted_admission.request.store_id,
            owner_revision=1,
            active_leases=(adopted_lease,),
        )
    )
    reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=original_bindings,
        proposed_bindings=rebound_bindings,
        pinned_bindings=pinned_bindings,
        snapshots=snapshots,
        current_admission_request=adopted_admission.request,
    )
    before_selection = reader.observe_pinned_claim(status.operation_id)
    assert before_selection.pending_pinned_decision_id is None
    decision = PackageLifecyclePinnedAdoptionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
        expected_attempt_revision=status.attempt_revision,
        new_runtime_admission_request_id=(
            adopted_admission.request.admission_request_id
        ),
        source_proof_ref="4" * 64,
        closure_plan_fingerprint="5" * 64,
        pin_receipt_id="6" * 64,
        lease_snapshot_id=adopted_admission.lease_snapshot_id,
    )
    lifecycle.record_pinned_adoption(decision)
    with pytest.raises(PackageProductRebindLeaseReadError) as absent:
        reader.observe_pinned_claim(status.operation_id)
    assert absent.value.code == "package_pinned_adoption_binding_missing"
    bound = pinned_bindings.bind(decision, adopted_admission)
    selected = reader.observe_pinned_claim(status.operation_id)
    assert selected.pending_pinned_decision_id == decision.decision_id
    assert selected.prior_pinned_binding_id == bound.binding_id
    assert selected.prior_pinned_lease_id == adopted_lease.lease_id

    later_admission = _admission(runtime_id="runtime:later-pinned")
    later_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=later_admission.request.runtime_id,
        runtime_epoch=later_admission.request.runtime_epoch,
        store_root_identity=later_admission.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    selected_record = lifecycle.latest_pinned_adoption(status.operation_id)
    assert selected_record is not None
    replacement = replace(
        decision,
        expected_attempt_revision=selected_record.status.attempt_revision,
        new_runtime_admission_request_id=(
            later_admission.request.admission_request_id
        ),
        lease_snapshot_id=later_admission.lease_snapshot_id,
    )
    pinned_bindings.bind(replacement, later_admission)
    lifecycle.supersede_pinned_adoption(
        replacement,
        supersedes_decision_id=decision.decision_id,
        expected_prior_record_revision=selected_record.record_revision,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=adopted_admission.request.store_id,
        owner_revision=2,
        active_leases=(adopted_lease, later_lease),
    )
    later_reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=original_bindings,
        proposed_bindings=rebound_bindings,
        pinned_bindings=pinned_bindings,
        snapshots=snapshots,
        current_admission_request=later_admission.request,
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as prior_live:
        later_reader.observe_pinned_claim(status.operation_id)
    assert prior_live.value.code == "package_pinned_adoption_prior_lease_active"

    stage_admission = _admission(runtime_id="runtime:staging")
    stage_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=stage_admission.request.runtime_id,
        runtime_epoch=stage_admission.request.runtime_epoch,
        store_root_identity=stage_admission.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=stage_admission.request.store_id,
        owner_revision=3,
        active_leases=(stage_lease,),
    )
    staging_bindings = PackageProductStagingAdoptionBindingJournal(
        tmp_path / "staging.jsonl"
    )
    stage_reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=original_bindings,
        proposed_bindings=rebound_bindings,
        pinned_bindings=pinned_bindings,
        staging_bindings=staging_bindings,
        snapshots=snapshots,
        current_admission_request=stage_admission.request,
    )
    before_stage = stage_reader.observe_pinned_claim(status.operation_id)
    assert before_stage.pending_staging_decision_id is None
    selected_pin = lifecycle.latest_pinned_adoption(status.operation_id)
    assert selected_pin is not None
    stage_decision = PackageLifecycleStagingAdoptionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
        expected_attempt_revision=selected_pin.status.attempt_revision,
        new_runtime_admission_request_id=(
            stage_admission.request.admission_request_id
        ),
        source_proof_ref="4" * 64,
        closure_plan_fingerprint="5" * 64,
        pin_receipt_id="6" * 64,
        staging_checkpoint_id="8" * 64,
        lease_snapshot_id=stage_admission.lease_snapshot_id,
        previous_selected_decision_id=selected_pin.decision.decision_id,
    )
    lifecycle.record_staging_adoption(stage_decision)
    with pytest.raises(PackageProductRebindLeaseReadError) as unbound_stage:
        stage_reader.observe_pinned_claim(status.operation_id)
    assert unbound_stage.value.code == "package_staging_adoption_binding_missing"
    staged_binding = staging_bindings.bind(stage_decision, stage_admission)
    selected_stage = stage_reader.observe_pinned_claim(status.operation_id)
    assert selected_stage.pending_staging_decision_id == stage_decision.decision_id
    assert selected_stage.prior_staging_binding_id == staged_binding.binding_id
    assert selected_stage.prior_staging_lease_id == stage_lease.lease_id
    intact_proposals = staging_bindings.path.read_bytes()
    with staging_bindings.path.open("ab") as output:
        output.write(b'{"partial":')
    with pytest.raises(PackageProductStagingAdoptionBindingError) as corrupt_stage:
        stage_reader.observe_pinned_claim(status.operation_id)
    assert corrupt_stage.value.code == "package_product_staging_adoption_binding_corrupt"
    assert staging_bindings.path.read_bytes() == intact_proposals + b'{"partial":'
    staging_bindings.path.write_bytes(intact_proposals)

    newest_admission = _admission(runtime_id="runtime:after-staging")
    newest_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=newest_admission.request.runtime_id,
        runtime_epoch=newest_admission.request.runtime_epoch,
        store_root_identity=newest_admission.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=stage_admission.request.store_id,
        owner_revision=4,
        active_leases=(stage_lease, newest_lease),
    )
    newest_reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=original_bindings,
        proposed_bindings=rebound_bindings,
        pinned_bindings=pinned_bindings,
        staging_bindings=staging_bindings,
        snapshots=snapshots,
        current_admission_request=newest_admission.request,
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as stage_still_live:
        newest_reader.observe_pinned_claim(status.operation_id)
    assert stage_still_live.value.code == "package_staging_adoption_prior_lease_active"


def test_rebound_product_route_requires_selected_resumed_attempt(
    tmp_path: Path,
) -> None:
    original = _admission(runtime_id="runtime:original")
    rebound = _admission(runtime_id="runtime:rebound")
    ingress = _route_request("cli", admission=original).ingress
    _router_instance, owner, journal, _transaction = _router(tmp_path)
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    decision = PackageLifecycleRebindRequestV1(
        operation_id=ingress.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id=rebound.request.admission_request_id,
        source_proof_ref="2" * 64,
        cleanup_evidence_ref="3" * 64,
        lease_snapshot_id="4" * 64,
    )
    route = PackageProductReboundRouteRequestV1(
        entrypoint="operations",
        ingress=ingress,
        admission=rebound,
        decision=decision,
    )
    assert route.ingress.runtime_admission_request_id == (
        original.request.admission_request_id
    )
    assert route.admission.request.admission_request_id == (
        rebound.request.admission_request_id
    )
    record = journal.record_rebind(decision)
    with pytest.raises(PackageProductRouteContractError) as pending:
        require_rebound_decision(route, record.status, journal)
    assert pending.value.code == "package_rebind_execution_not_available"
    resumed = owner.resume_rebind(
        decision, expected_rebind_record_revision=record.record_revision
    )
    require_rebound_decision(route, resumed, journal)
    pinned = resumed
    for phase in (
        "acquiring", "acquired", "inspecting", "extracted",
        "resolving_closure", "closure_verified", "transaction_pinned",
    ):
        pinned = owner.advance(
            pinned.operation_id,
            next_phase=phase,
            expected_phase=pinned.phase,
            expected_journal_revision=pinned.journal_revision,
            expected_attempt_epoch=pinned.attempt_epoch,
        )
    later_admission = _admission(runtime_id="runtime:later")
    pinned_selection = journal.record_pinned_adoption(
        PackageLifecyclePinnedAdoptionRequestV1(
            operation_id=pinned.operation_id,
            request_fingerprint=pinned.request_fingerprint,
            expected_journal_revision=pinned.journal_revision,
            expected_attempt_epoch=pinned.attempt_epoch,
            expected_attempt_revision=pinned.attempt_revision,
            new_runtime_admission_request_id=(
                later_admission.request.admission_request_id
            ),
            source_proof_ref="5" * 64,
            closure_plan_fingerprint="6" * 64,
            pin_receipt_id="7" * 64,
            lease_snapshot_id=later_admission.lease_snapshot_id,
        )
    )
    selected = journal.read_operation(pinned.operation_id)
    assert selected is not None
    with pytest.raises(PackageProductRouteContractError) as old_rebound:
        require_rebound_decision(route, selected[1], journal)
    assert old_rebound.value.code == "package_pinned_adoption_route_required"
    adopted_route = PackageProductPinnedAdoptedRouteRequestV1(
        entrypoint="operations",
        ingress=ingress,
        admission=later_admission,
        decision=pinned_selection.decision,
    )
    require_rebound_decision(adopted_route, selected[1], journal)
    refreshed_admission = PackageEpochRuntimeAdmissionReceiptV1.create(
        later_admission.request,
        snapshot=PackageEpochLeaseSnapshotV1.create(
            store_id=later_admission.request.store_id,
            owner_revision=2,
            active_leases=(
                PackageEpochRuntimeLeaseV1.create(
                    runtime_id=later_admission.request.runtime_id,
                    runtime_epoch=later_admission.request.runtime_epoch,
                    store_root_identity=(
                        later_admission.request.store_root_identity
                    ),
                    registration_receipt_id="7" * 64,
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="identity changed"):
        PackageProductPinnedAdoptedRouteRequestV1(
            entrypoint="operations",
            ingress=ingress,
            admission=refreshed_admission,
            decision=pinned_selection.decision,
        )
    with pytest.raises(PackageProductRouteContractError) as stale_adoption:
        require_rebound_decision(adopted_route, pinned, journal)
    assert stale_adoption.value.code == "package_pinned_adoption_execution_not_available"
    with pytest.raises(ValueError, match="identity changed"):
        PackageProductReboundRouteRequestV1(
            entrypoint="operations",
            ingress=ingress,
            admission=original,
            decision=decision,
        )
    with pytest.raises(ValueError, match="entrypoint"):
        PackageProductReboundRouteRequestV1(
            entrypoint="direct_materializer",
            ingress=ingress,
            admission=rebound,
            decision=decision,
        )
    stage_admission = _admission(runtime_id="runtime:stage")
    staged_selection = journal.record_staging_adoption(
        PackageLifecycleStagingAdoptionRequestV1(
            operation_id=pinned.operation_id,
            request_fingerprint=pinned.request_fingerprint,
            expected_journal_revision=pinned.journal_revision,
            expected_attempt_epoch=pinned.attempt_epoch,
            expected_attempt_revision=pinned_selection.status.attempt_revision,
            new_runtime_admission_request_id=(
                stage_admission.request.admission_request_id
            ),
            source_proof_ref="5" * 64,
            closure_plan_fingerprint="6" * 64,
            pin_receipt_id="7" * 64,
            staging_checkpoint_id="9" * 64,
            lease_snapshot_id=stage_admission.lease_snapshot_id,
            previous_selected_decision_id=(pinned_selection.decision.decision_id),
        )
    )
    with pytest.raises(PackageProductRouteContractError) as old_pin_route:
        require_rebound_decision(adopted_route, staged_selection.status, journal)
    assert old_pin_route.value.code == "package_staging_adoption_route_required"
    stage_route = PackageProductStagingAdoptedRouteRequestV1(
        entrypoint="operations",
        ingress=ingress,
        admission=stage_admission,
        decision=staged_selection.decision,
    )
    require_rebound_decision(stage_route, staged_selection.status, journal)
    with pytest.raises(ValueError, match="missing nodes"):
        replace(stage_route, missing_node_ids=("root", "root"))
    with pytest.raises(PackageProductRouteContractError) as early_stage:
        require_rebound_decision(stage_route, pinned_selection.status, journal)
    assert early_stage.value.code == "package_staging_adoption_execution_not_available"
    with pytest.raises(ValueError, match="identity changed"):
        PackageProductStagingAdoptedRouteRequestV1(
            entrypoint="operations",
            ingress=ingress,
            admission=later_admission,
            decision=staged_selection.decision,
        )


def test_corrupt_original_admission_binding_refuses_before_transaction(
    tmp_path: Path,
) -> None:
    binding = PackageProductAdmissionBindingJournal(tmp_path / "admission.jsonl")
    binding.path.write_text('{"unexpected":1}\n', encoding="utf-8")
    original_bytes = binding.path.read_bytes()
    router, _owner, lifecycle, transaction = _router(
        tmp_path, admission_binding=binding
    )
    route_request = _route_request("cli")

    with pytest.raises(PackageProductAdmissionBindingJournalError) as corrupt:
        router.route(route_request)

    assert corrupt.value.code == "package_product_admission_binding_corrupt"
    assert transaction.calls == []
    assert binding.path.read_bytes() == original_bytes
    accepted = lifecycle.read_operation(route_request.ingress.operation_id)
    assert accepted is not None
    assert accepted[1].phase == "classified"
    assert accepted[1].disposition == "active"


def test_rebind_lease_read_requires_old_lease_absent_and_new_lease_live(
    tmp_path: Path,
) -> None:
    old_admission = _admission(runtime_id="runtime:old")
    new_admission = _admission(runtime_id="runtime:new")
    lifecycle = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=lifecycle,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    ingress = _route_request("cli", admission=old_admission).ingress
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original = lifecycle.read_operation(failed.operation_id)
    assert original is not None
    request, status = original
    assert isinstance(request, PackageLifecycleRequestV2)
    bindings = PackageProductAdmissionBindingJournal(tmp_path / "admission.jsonl")
    binding = bindings.bind(request, status, old_admission)

    def lease_for(
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageEpochRuntimeLeaseV1:
        return PackageEpochRuntimeLeaseV1.create(
            runtime_id=admission.request.runtime_id,
            runtime_epoch=admission.request.runtime_epoch,
            store_root_identity=admission.request.store_root_identity,
            registration_receipt_id="7" * 64,
        )

    old_lease = lease_for(old_admission)
    new_lease = lease_for(new_admission)

    @dataclass
    class Snapshots:
        value: PackageEpochLeaseSnapshotV1

        def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
            assert store_id == new_admission.request.store_id
            return self.value

    snapshots = Snapshots(
        PackageEpochLeaseSnapshotV1.create(
            store_id=new_admission.request.store_id,
            owner_revision=3,
            active_leases=(new_lease,),
        )
    )
    reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=bindings,
        snapshots=snapshots,
        current_admission_request=new_admission.request,
    )
    before = (lifecycle.path.read_bytes(), bindings.path.read_bytes())
    observed = reader.observe(failed.operation_id)
    assert observed.original_binding_id == binding.binding_id
    assert observed.original_admission_request_id == (
        old_admission.request.admission_request_id
    )
    assert observed.new_admission_request_id == (
        new_admission.request.admission_request_id
    )
    assert observed.old_lease_id == old_lease.lease_id
    assert observed.new_lease_id == new_lease.lease_id
    assert observed.lease_snapshot_id == snapshots.value.snapshot_id
    assert (lifecycle.path.read_bytes(), bindings.path.read_bytes()) == before

    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=2,
        active_leases=(old_lease, new_lease),
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as old_live:
        reader.observe(failed.operation_id)
    assert old_live.value.code == "package_rebind_old_lease_active"

    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=4,
        active_leases=(old_lease,),
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as new_missing:
        reader.observe(failed.operation_id)
    assert new_missing.value.code == "package_rebind_new_lease_absent"

    missing_binding = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=PackageProductAdmissionBindingJournal(
            tmp_path / "missing-admission.jsonl"
        ),
        snapshots=snapshots,
        current_admission_request=new_admission.request,
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as missing:
        missing_binding.observe(failed.operation_id)
    assert missing.value.code == "package_rebind_original_admission_missing"

    proposals = PackageProductRebindAdmissionBindingJournal(
        tmp_path / "rebind-admissions.jsonl"
    )
    decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id=new_admission.request.admission_request_id,
        source_proof_ref="a" * 64,
        cleanup_evidence_ref="b" * 64,
        lease_snapshot_id=observed.lease_snapshot_id,
    )
    proposal = proposals.bind(decision, new_admission)
    lifecycle.record_rebind(decision)
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=5,
        active_leases=(new_lease,),
    )
    pending_reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=bindings,
        proposed_bindings=proposals,
        snapshots=snapshots,
        current_admission_request=new_admission.request,
    )
    pending = pending_reader.observe(failed.operation_id)
    assert pending.pending_decision_id == decision.decision_id
    assert pending.prior_proposed_binding_id == proposal.binding_id

    third_admission = _admission(runtime_id="runtime:third")
    third_lease = lease_for(third_admission)
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=6,
        active_leases=(new_lease, third_lease),
    )
    third_reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=bindings,
        proposed_bindings=proposals,
        snapshots=snapshots,
        current_admission_request=third_admission.request,
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as prior_live:
        third_reader.observe(failed.operation_id)
    assert prior_live.value.code == "package_rebind_prior_lease_active"

    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=7,
        active_leases=(third_lease,),
    )
    supersession = third_reader.observe(failed.operation_id)
    assert supersession.pending_decision_id == decision.decision_id
    assert supersession.prior_proposed_lease_id == new_lease.lease_id
    assert supersession.new_lease_id == third_lease.lease_id

    missing_proposal = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=bindings,
        proposed_bindings=PackageProductRebindAdmissionBindingJournal(
            tmp_path / "missing-rebind-admissions.jsonl"
        ),
        snapshots=snapshots,
        current_admission_request=third_admission.request,
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as unbound:
        missing_proposal.observe(failed.operation_id)
    assert unbound.value.code == "package_rebind_proposed_admission_missing"

    first_record = lifecycle.latest_rebind(failed.operation_id)
    assert first_record is not None
    next_decision = replace(
        decision,
        expected_attempt_revision=first_record.status.attempt_revision,
        new_runtime_admission_request_id=third_admission.request.admission_request_id,
        lease_snapshot_id=supersession.lease_snapshot_id,
    )
    proposals.bind(next_decision, third_admission)
    lifecycle.supersede_rebind(
        next_decision,
        supersedes_decision_id=decision.decision_id,
        expected_prior_rebind_record_revision=first_record.record_revision,
    )
    fourth_admission = _admission(runtime_id="runtime:fourth")
    fourth_lease = lease_for(fourth_admission)
    fourth_reader = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=bindings,
        proposed_bindings=proposals,
        snapshots=snapshots,
        current_admission_request=fourth_admission.request,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=8,
        active_leases=(new_lease, fourth_lease),
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as first_proposal_live:
        fourth_reader.observe(failed.operation_id)
    assert first_proposal_live.value.code == "package_rebind_prior_lease_active"
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=new_admission.request.store_id,
        owner_revision=9,
        active_leases=(fourth_lease,),
    )
    fourth = fourth_reader.observe(failed.operation_id)
    assert fourth.prior_proposed_lease_id == third_lease.lease_id
    assert fourth.pending_decision_id == next_decision.decision_id


def test_retryable_product_operation_resumes_exact_attempt_and_runs_transaction(
    tmp_path: Path,
) -> None:
    router, owner, journal, transaction = _router(tmp_path)
    request = _route_request("cli")
    classified = owner.submit(request.ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    assert failed.disposition == "retryable_failure"
    assert failed.failure is not None
    assert failed.failure.operator_action == "retry"

    committed = router.retry(
        request,
        request_fingerprint=classified.request_fingerprint,
        expected_attempt_epoch=classified.attempt_epoch,
    )

    assert committed.disposition == "committed"
    assert committed.attempt_epoch == classified.attempt_epoch + 1
    assert journal.status(classified.operation_id) == committed
    assert transaction.calls == ["cli"]


@pytest.mark.parametrize(
    "case",
    (
        "stale_attempt",
        "changed_source",
        "new_runtime_admission",
        "direct_route",
    ),
)
def test_product_retry_refuses_mismatched_evidence_before_owner_mutation(
    tmp_path: Path, case: str
) -> None:
    router, owner, journal, transaction = _router(tmp_path)
    request = _route_request("cli")
    classified = owner.submit(request.ingress)
    owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    before = journal.records()
    if case == "changed_source":
        request = _route_request(
            "cli",
            replace(
                _ingress(), source_locator="https://packages.example.test/other.whl"
            ),
        )
    elif case == "new_runtime_admission":
        request = _route_request(
            "cli", admission=_admission(runtime_id="runtime:other")
        )
    elif case == "direct_route":
        request = _route_request("direct_materializer")

    with pytest.raises(PackageProductRouteContractError):
        router.retry(
            request,
            request_fingerprint=classified.request_fingerprint,
            expected_attempt_epoch=(
                classified.attempt_epoch + 1
                if case == "stale_attempt"
                else classified.attempt_epoch
            ),
        )
    assert journal.records() == before
    assert transaction.calls == []


def test_product_retry_refuses_terminal_operation_without_new_attempt(
    tmp_path: Path,
) -> None:
    router, _owner, journal, transaction = _router(tmp_path)
    request = _route_request("cli")
    committed = router.route(request)
    before = journal.records()

    with pytest.raises(PackageProductRouteContractError):
        router.retry(
            request,
            request_fingerprint=committed.request_fingerprint,
            expected_attempt_epoch=committed.attempt_epoch,
        )

    assert journal.records() == before
    assert transaction.calls == ["cli"]


@pytest.mark.parametrize("entrypoint", TRANSACTION_ENTRYPOINTS)
def test_product_entrypoint_commits_once_and_exact_replay_is_read_only(
    entrypoint: PackageProductEntrypoint,
    tmp_path: Path,
) -> None:
    router, _owner, journal, transaction = _router(tmp_path)
    route = _route_request(entrypoint)

    committed = router.route(route)
    before = journal.records()
    replay = router.route(route)

    assert replay == committed
    assert (committed.phase, committed.disposition) == ("committed", "committed")
    assert transaction.calls == [entrypoint]
    assert journal.records() == before
    assert "secret" not in repr((route, committed, before))


def test_product_route_request_rejects_mismatched_runtime_admission() -> None:
    admission = _admission()
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(),
        runtime_admission_request_id="f" * 64,
    )

    with pytest.raises(ValueError, match="admission identity is inconsistent"):
        PackageProductRouteRequestV1(
            entrypoint="rpc",
            ingress=ingress,
            admission=admission,
        )


def test_lifecycle_v1_journal_remains_readable_after_v2_is_added(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "v1-lifecycle.jsonl"
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(journal_path),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )

    accepted = owner.submit(_ingress())
    request = owner.journal.request(accepted.operation_id)
    assert request is not None
    assert request.to_dict()["requestVersion"] == 1
    assert "runtimeAdmissionRequestId" not in request.to_dict()

    reloaded = PackageLifecycleJournal(journal_path).request(accepted.operation_id)
    assert reloaded == request
    assert type(reloaded) is type(request)


def test_direct_materializer_is_rejected_without_transaction_fallback(
    tmp_path: Path,
) -> None:
    router, _owner, journal, transaction = _router(tmp_path)
    route = _route_request("direct_materializer")

    refused = router.route(route)
    before = journal.records()
    replay = router.route(route)

    assert replay == refused
    assert (refused.phase, refused.disposition) == ("classified", "rejected")
    assert refused.failure is not None
    assert refused.failure.code == "package_route_unavailable"
    assert transaction.calls == []
    assert journal.records() == before


def test_committed_replay_retries_required_product_handoff(tmp_path: Path) -> None:
    journal = PackageLifecycleJournal(tmp_path / "product-handoff-replay.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    transaction = _FinalizingTransaction(owner)
    router = PackageProductLifecycleRouter(
        execution=PackageProductLifecycleExecutionBinding(owner, transaction)
    )
    route = _route_request("cli")

    with pytest.raises(RuntimeError, match="handoff interrupted"):
        router.route(route)
    committed = owner.status(route.ingress.operation_id)
    assert committed is not None
    assert (committed.phase, committed.disposition) == ("committed", "committed")
    assert transaction.calls == ["cli"]
    assert transaction.finalization_calls == 1

    assert router.route(route) == committed
    assert transaction.calls == ["cli"]
    assert transaction.finalization_calls == 2


def test_product_route_keeps_reference_gate_through_handoff(tmp_path: Path) -> None:
    journal = PackageLifecycleJournal(tmp_path / "gated-product-route.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    gate = PluginPackageGcReservationJournal(tmp_path / "gc-reservations.jsonl")
    entered_handoff = Event()
    release_handoff = Event()
    writer_started = Event()
    writer_entered = Event()

    class BlockingFinalization(_CommittingTransaction):
        def finalize_committed(
            self,
            _request: PackageProductRouteRequestV1,
            *,
            current: PackageLifecycleStatusV1,
        ) -> None:
            assert current.disposition == "committed"
            entered_handoff.set()
            assert release_handoff.wait(5)

    transaction = BlockingFinalization(owner)
    router = PackageProductLifecycleRouter(
        execution=PackageProductLifecycleExecutionBinding(owner, transaction),
        reference_guard=gate.guard,
    )

    def competing_writer() -> None:
        writer_started.set()
        with gate.guard():
            writer_entered.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        route = pool.submit(router.route, _route_request("cli"))
        assert entered_handoff.wait(5)
        writer = pool.submit(competing_writer)
        assert writer_started.wait(5)
        assert not writer_entered.wait(0.2)
        release_handoff.set()
        assert route.result(timeout=5).disposition == "committed"
        writer.result(timeout=5)
        assert writer_entered.is_set()


def test_direct_publish_is_durably_refused_without_publication_port(
    tmp_path: Path,
) -> None:
    router, owner, journal, transaction = _router(tmp_path)
    current = owner.submit(_ingress())
    for phase in TRANSACTION_PHASES[:-2]:
        current = owner.advance(
            current.operation_id,
            next_phase=phase,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
    assert current.phase == "staging"
    before = journal.records()
    attempt = PackageProductPublishAttemptV1(status=current)

    refused = router.refuse_direct_publish(attempt)
    after = journal.records()
    replay = router.refuse_direct_publish(attempt)

    assert replay == refused
    assert (refused.phase, refused.disposition) == ("staging", "rejected")
    assert refused.failure is not None
    assert refused.failure.code == "package_route_unavailable"
    assert transaction.calls == []
    assert len(after) == len(before) + 1
    assert journal.records() == after
    assert owner.status(current.operation_id) == refused


def test_disabled_owner_fails_closed_without_journal_or_transaction(
    tmp_path: Path,
) -> None:
    router, _owner, journal, transaction = _router(tmp_path, enabled=False)

    refused = router.route(_route_request("session"))

    assert refused.failure is not None
    assert refused.failure.code == "package_route_unavailable"
    assert transaction.calls == []
    assert journal.records() == ()
    assert not journal.path.exists()


def test_non_plugin_classification_never_reaches_plugin_transaction(
    tmp_path: Path,
) -> None:
    router, _owner, _journal, transaction = _router(tmp_path, decision="non_plugin")

    classified = router.route(_route_request("operations"))

    assert classified.classification is not None
    assert classified.classification.decision == "non_plugin"
    assert classified.disposition == "active"
    assert transaction.calls == []


def test_router_rejects_a_transaction_that_did_not_reach_durable_terminal_state(
    tmp_path: Path,
) -> None:
    journal = PackageLifecycleJournal(tmp_path / "invalid-route.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal,
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    transaction = _InvalidTransaction(owner)
    router = PackageProductLifecycleRouter(
        execution=PackageProductLifecycleExecutionBinding(owner, transaction)
    )

    with pytest.raises(PackageProductRouteContractError):
        router.route(_route_request("rpc"))

    assert transaction.calls == 1
    current = owner.status(_ingress().operation_id)
    assert current is not None
    assert (current.phase, current.disposition) == ("classified", "active")


def test_execution_binding_rejects_transaction_from_a_different_owner(
    tmp_path: Path,
) -> None:
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "owner.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    foreign = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "foreign.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )

    with pytest.raises(
        PackageProductRouteContractError,
        match="different owner",
    ):
        PackageProductLifecycleExecutionBinding(
            owner,
            _CommittingTransaction(foreign),
        )

    assert not owner.journal.path.exists()
    assert not foreign.journal.path.exists()


def test_execution_binding_rejects_missing_committed_handoff(
    tmp_path: Path,
) -> None:
    owner = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "missing-handoff.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )

    class MissingFinalizer:
        owner_binding_id = owner.binding_id

        def execute(
            self,
            _request: PackageProductRouteRequestV1,
            *,
            current: PackageLifecycleStatusV1,
        ) -> PackageLifecycleStatusV1:
            return current

    with pytest.raises(PackageProductRouteContractError, match="handoff"):
        PackageProductLifecycleExecutionBinding(owner, MissingFinalizer())


def test_router_rechecks_mutable_transaction_owner_before_execution(
    tmp_path: Path,
) -> None:
    router, owner, _journal, transaction = _router(tmp_path)
    foreign = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "foreign.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    transaction.owner = foreign

    with pytest.raises(PackageProductRouteContractError, match="changed"):
        router.route(_route_request("session"))

    assert transaction.calls == []
    assert not foreign.journal.path.exists()
    current = owner.status(_ingress().operation_id)
    assert current is not None and current.phase == "classified"
