from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecyclePhase,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductEntrypoint,
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

    def execute(
        self,
        request: PackageProductRouteRequestV1,
        *,
        classified: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls.append(request.entrypoint)
        current = classified
        for phase in TRANSACTION_PHASES:
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
    calls: int = 0

    def execute(
        self,
        _request: PackageProductRouteRequestV1,
        *,
        classified: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls += 1
        return classified


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
        PackageProductLifecycleRouter(owner=owner, transaction=transaction),
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
    route = PackageProductRouteRequestV1(entrypoint=entrypoint, ingress=_ingress())

    committed = router.route(route)
    before = journal.records()
    replay = router.route(route)

    assert replay == committed
    assert (committed.phase, committed.disposition) == ("committed", "committed")
    assert transaction.calls == [entrypoint]
    assert journal.records() == before
    assert "secret" not in repr((route, committed, before))


def test_direct_materializer_is_rejected_without_transaction_fallback(
    tmp_path: Path,
) -> None:
    router, _owner, journal, transaction = _router(tmp_path)
    route = PackageProductRouteRequestV1(
        entrypoint="direct_materializer",
        ingress=_ingress(),
    )

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

    refused = router.route(
        PackageProductRouteRequestV1(entrypoint="session", ingress=_ingress())
    )

    assert refused.failure is not None
    assert refused.failure.code == "package_route_unavailable"
    assert transaction.calls == []
    assert journal.records() == ()
    assert not journal.path.exists()


def test_non_plugin_classification_never_reaches_plugin_transaction(
    tmp_path: Path,
) -> None:
    router, _owner, _journal, transaction = _router(tmp_path, decision="non_plugin")

    classified = router.route(
        PackageProductRouteRequestV1(entrypoint="operations", ingress=_ingress())
    )

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
    transaction = _InvalidTransaction()
    router = PackageProductLifecycleRouter(owner=owner, transaction=transaction)

    with pytest.raises(PackageProductRouteContractError):
        router.route(PackageProductRouteRequestV1(entrypoint="rpc", ingress=_ingress()))

    assert transaction.calls == 1
    current = owner.status(_ingress().operation_id)
    assert current is not None
    assert (current.phase, current.disposition) == ("classified", "active")
