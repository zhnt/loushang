from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import pytest

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
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductEntrypoint,
    PackageProductLifecycleExecutionBinding,
    PackageProductLifecycleRouter,
    PackageProductPublishAttemptV1,
    PackageProductRouteContractError,
    PackageProductRouteRequestV1,
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

    def execute(
        self,
        _request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls += 1
        return current


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


def _admission() -> PackageEpochRuntimeAdmissionReceiptV1:
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
        runtime_id="runtime:test",
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
) -> PackageProductRouteRequestV1:
    admission = _admission()
    return PackageProductRouteRequestV1(
        entrypoint=entrypoint,
        ingress=PackageLifecycleIngressRequestV2.bind_runtime_admission(
            ingress or _ingress(),
            runtime_admission_request_id=(
                admission.request.admission_request_id
            ),
        ),
        admission=admission,
    )


def _router(
    tmp_path: Path,
    *,
    decision: str = "plugin_bound",
    enabled: bool = True,
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
            execution=PackageProductLifecycleExecutionBinding(owner, transaction)
        ),
        owner,
        journal,
        transaction,
    )


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
