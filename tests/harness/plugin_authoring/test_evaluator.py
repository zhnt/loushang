from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pytest

from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.coordinator import (
    PluginDeclarationCoordinator,
)
from loushang.harness.plugin_authoring.evaluator import (
    PluginDefinitionEvaluationError,
    PluginDefinitionEvaluator,
)
from loushang.harness.plugin_authoring.import_realm import (
    PluginImportRealm,
    PluginImportRealmError,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.selection import (
    AcceptedPluginPreflight,
    PluginContributionRef,
    PluginDeclarationExecutionPreflightGate,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginPreflightPendingApprovalOutcome,
    PluginSelection,
    PluginSelectionError,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)


class _PublishedPlugin(Protocol):
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation


class _PublishedExecutablePlugin(_PublishedPlugin, Protocol):
    import_marker: Path
    undeclared_import_marker: Path
    undeclared_import_trigger: Path


@dataclass(slots=True)
class _FinalizeCounter:
    count: int = 0


def test_evaluator_uses_verified_bytes_and_attaches_exact_receipt_evidence(
    tmp_path: Path,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    resolver = PluginSelectionResolver()
    journal = _journal(tmp_path)
    accepted = _issue_and_accept(
        resolver,
        journal,
        (fixture,),
        plan=_plan(fixture),
    )
    source_root = fixture.package.source.path
    assert source_root is not None
    (source_root / "provider.py").write_text(
        "raise AssertionError('mutable source must never be reopened')\n",
        encoding="utf-8",
    )
    evaluator = PluginDefinitionEvaluator(
        decision_journal=journal,
        import_realm=PluginImportRealm(
            import_realm_id_factory=lambda: "4" * 32
        ),
        clock=lambda: 2_500,
    )

    selection = PluginDeclarationCoordinator(
        resolver,
        execution_evaluator=evaluator,
    ).finalize(accepted)

    assert isinstance(selection, PluginSelection)
    assert fixture.import_marker.read_text(encoding="utf-8") == "imported"
    [candidate] = selection.candidates
    evidence = candidate.evidence
    assert evidence.kind == "in_process_evaluated"
    receipt = evidence.consumption_receipt
    assert receipt.state == "EVALUATED"
    assert receipt.host_boot_id == accepted.host_boot_id
    assert receipt.import_realm_id == "4" * 32
    assert receipt.preflight_use_id == accepted.preflight_use_id
    assert receipt.source_group_id == accepted.source_groups[0].source_group_id
    assert evidence.to_dict()["consumptionReceipt"] == receipt.to_dict()
    snapshot = journal.snapshot()
    assert snapshot.journal_revision == 4
    assert snapshot.execution_uses[0].state == "EVALUATED"


def test_mixed_document_and_executable_groups_join_before_one_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published_document_plugin: _PublishedPlugin,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixtures = (published_document_plugin, published_synthetic_plugin)
    resolver = PluginSelectionResolver()
    journal = _journal(tmp_path)
    accepted = _issue_and_accept(
        resolver,
        journal,
        fixtures,
        plan=_plan(*fixtures),
    )
    finalize_counter = _FinalizeCounter()
    decode_counter = _FinalizeCounter()
    original_finalize = resolver._finalize
    original_decode = PluginDeclarationDocumentCodec.decode_bytes

    def finalize_once(
        preflight: AcceptedPluginPreflight,
        batches,
    ) -> PluginSelection:
        finalize_counter.count += 1
        return original_finalize(preflight, batches)

    def decode_once(value: bytes):
        decode_counter.count += 1
        return original_decode(value)

    monkeypatch.setattr(resolver, "_finalize", finalize_once)
    monkeypatch.setattr(
        PluginDeclarationDocumentCodec,
        "decode_bytes",
        decode_once,
    )
    evaluator = PluginDefinitionEvaluator(
        decision_journal=journal,
        import_realm=PluginImportRealm(
            import_realm_id_factory=lambda: "4" * 32
        ),
        clock=lambda: 2_500,
    )

    selection = PluginDeclarationCoordinator(
        resolver,
        execution_evaluator=evaluator,
    ).finalize(accepted)

    assert finalize_counter.count == 1
    assert decode_counter.count == 1
    assert published_synthetic_plugin.import_marker.exists()
    assert {
        candidate.evidence.kind for candidate in selection.candidates
    } == {"document_decoded", "in_process_evaluated"}
    assert len(selection.candidates) == 2
    assert journal.snapshot().execution_uses[0].state == "EVALUATED"


def test_failure_after_start_persists_failure_and_blocks_same_realm_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    decision_ids = iter(("1" * 48, "8" * 48))
    execution_use_ids = iter(("2" * 48, "9" * 48))
    journal = _journal(
        tmp_path,
        decision_id_factory=lambda: next(decision_ids),
        execution_use_id_factory=lambda: next(execution_use_ids),
    )
    resolver = PluginSelectionResolver()
    plan = _plan(fixture)
    accepted = _issue_and_accept(resolver, journal, (fixture,), plan=plan)
    [group] = accepted.source_groups
    assert isinstance(group.gate, PluginDeclarationExecutionPreflightGate)
    realm = PluginImportRealm(import_realm_id_factory=lambda: "4" * 32)
    evaluator = PluginDefinitionEvaluator(
        decision_journal=journal,
        import_realm=realm,
        clock=lambda: 2_500,
    )

    def fail_build(_builder: PluginDeclarationBuilder):
        raise RuntimeError("secret definition detail")

    monkeypatch.setattr(PluginDeclarationBuilder, "build", fail_build)
    with pytest.raises(PluginDefinitionEvaluationError) as caught:
        PluginDeclarationCoordinator(
            resolver,
            execution_evaluator=evaluator,
        ).finalize(accepted)

    assert caught.value.code == "plugin_definition_evaluation_failed"
    assert "secret" not in str(caught.value)
    assert fixture.import_marker.exists()
    assert journal.snapshot().execution_uses[0].state == "FAILED_AFTER_START"
    assert realm.snapshot().state == "polluted"

    fixture.import_marker.write_text("sentinel", encoding="utf-8")
    journal.issue_execution_decision(
        group.gate.subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:retry",
            source="test",
        ),
        revocation_epoch=0,
        issued_at_unix_ms=2_000,
        expires_at_unix_ms=5_000,
        expected_journal_revision=4,
    )
    retry_resolver = PluginSelectionResolver()
    retry = retry_resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=journal,
    )
    assert isinstance(retry, PluginPreflightAcceptedOutcome)
    with pytest.raises(PluginDefinitionEvaluationError) as retry_failure:
        PluginDeclarationCoordinator(
            retry_resolver,
            execution_evaluator=evaluator,
        ).finalize(retry.accepted)

    assert retry_failure.value.code == "plugin_import_realm_polluted"
    assert fixture.import_marker.read_text(encoding="utf-8") == "sentinel"
    retry_snapshot = journal.snapshot()
    assert retry_snapshot.journal_revision == 5
    assert retry_snapshot.decisions[-1].consumption_state == "AVAILABLE"
    assert len(retry_snapshot.execution_uses) == 1


def test_undeclared_local_import_fails_after_start_without_loading_helper(
    tmp_path: Path,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    resolver = PluginSelectionResolver()
    journal = _journal(tmp_path)
    accepted = _issue_and_accept(
        resolver,
        journal,
        (fixture,),
        plan=_plan(fixture),
    )
    fixture.undeclared_import_trigger.write_text("enabled", encoding="utf-8")
    realm = PluginImportRealm(import_realm_id_factory=lambda: "4" * 32)

    with pytest.raises(PluginDefinitionEvaluationError) as caught:
        PluginDeclarationCoordinator(
            resolver,
            execution_evaluator=PluginDefinitionEvaluator(
                decision_journal=journal,
                import_realm=realm,
                clock=lambda: 2_500,
            ),
        ).finalize(accepted)

    assert caught.value.code == "plugin_definition_evaluation_failed"
    assert fixture.undeclared_import_marker.exists() is False
    assert fixture.import_marker.exists() is False
    assert journal.snapshot().execution_uses[0].state == "FAILED_AFTER_START"
    assert realm.snapshot().state == "polluted"


def test_later_executable_failure_aborts_mixed_aggregate_without_finalizing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published_document_plugin: _PublishedPlugin,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixtures = (published_document_plugin, published_synthetic_plugin)
    resolver = PluginSelectionResolver()
    journal = _journal(tmp_path)
    accepted = _issue_and_accept(
        resolver,
        journal,
        fixtures,
        plan=_plan(*fixtures),
    )
    finalize_counter = _FinalizeCounter()
    original_finalize = resolver._finalize

    def count_finalize(
        preflight: AcceptedPluginPreflight,
        batches,
    ) -> PluginSelection:
        finalize_counter.count += 1
        return original_finalize(preflight, batches)

    def fail_build(_builder: PluginDeclarationBuilder):
        raise RuntimeError("later Definition failed")

    monkeypatch.setattr(resolver, "_finalize", count_finalize)
    monkeypatch.setattr(PluginDeclarationBuilder, "build", fail_build)
    coordinator = PluginDeclarationCoordinator(
        resolver,
        execution_evaluator=PluginDefinitionEvaluator(
            decision_journal=journal,
            import_realm=PluginImportRealm(
                import_realm_id_factory=lambda: "4" * 32
            ),
            clock=lambda: 2_500,
        ),
    )

    with pytest.raises(PluginDefinitionEvaluationError):
        coordinator.finalize(accepted)

    assert finalize_counter.count == 0
    assert journal.snapshot().execution_uses[0].state == "FAILED_AFTER_START"
    with pytest.raises(PluginSelectionError) as repeated:
        coordinator.finalize(accepted)
    assert repeated.value.code == "preflight_already_aborted"


def test_realm_reservation_race_cancels_consumed_use_before_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    resolver = PluginSelectionResolver()
    journal = _journal(tmp_path)
    accepted = _issue_and_accept(
        resolver,
        journal,
        (fixture,),
        plan=_plan(fixture),
    )
    realm = PluginImportRealm(import_realm_id_factory=lambda: "4" * 32)

    def lose_reservation(**_kwargs: object) -> object:
        raise PluginImportRealmError(
            "Plugin import realm became busy.",
            code="plugin_import_realm_busy",
        )

    monkeypatch.setattr(realm, "reserve", lose_reservation)
    with pytest.raises(PluginDefinitionEvaluationError) as caught:
        PluginDeclarationCoordinator(
            resolver,
            execution_evaluator=PluginDefinitionEvaluator(
                decision_journal=journal,
                import_realm=realm,
                clock=lambda: 2_500,
            ),
        ).finalize(accepted)

    assert caught.value.code == "plugin_import_realm_busy"
    snapshot = journal.snapshot()
    assert snapshot.journal_revision == 3
    assert snapshot.execution_uses[0].state == "CANCELLED_BEFORE_START"
    assert fixture.import_marker.exists() is False
    assert realm.snapshot().state == "clean"


def _journal(
    tmp_path: Path,
    *,
    decision_id_factory=lambda: "1" * 48,
    execution_use_id_factory=lambda: "2" * 48,
) -> PluginExecutionDecisionJournal:
    return PluginExecutionDecisionJournal(
        tmp_path / "plugin-execution-decisions.jsonl",
        scope_kind="workspace",
        scope_id="workspace:test",
        decision_id_factory=decision_id_factory,
        execution_use_id_factory=execution_use_id_factory,
        clock=lambda: 2_500,
    )


def _issue_and_accept(
    resolver: PluginSelectionResolver,
    journal: PluginExecutionDecisionJournal,
    fixtures: tuple[_PublishedPlugin, ...],
    *,
    plan: PluginSelectionPlanV2,
) -> AcceptedPluginPreflight:
    packages = tuple(fixture.package for fixture in fixtures)
    bindings = tuple(fixture.binding for fixture in fixtures)
    pending = resolver.preflight(
        packages,
        bindings=bindings,
        plan=plan,
        decision_lookup=journal,
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    expected_revision = 0
    for subject in pending.subjects:
        journal.issue_execution_decision(
            subject,
            disposition="approved",
            authorization=PluginApprovalAuthorizationV1.direct(
                actor_id="operator:test",
                source="test",
            ),
            revocation_epoch=0,
            issued_at_unix_ms=1_000,
            expires_at_unix_ms=5_000,
            expected_journal_revision=expected_revision,
        )
        expected_revision += 1
    outcome = resolver.preflight(
        packages,
        bindings=bindings,
        plan=plan,
        decision_lookup=journal,
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    return outcome.accepted


def _plan(*fixtures: _PublishedPlugin) -> PluginSelectionPlanV2:
    ordered = tuple(
        sorted(fixtures, key=lambda item: item.package.manifest.name)
    )
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=tuple(
                PluginInstanceRevisionRef(
                    instance_id=f"{fixture.package.manifest.name}@product",
                    plugin_id=fixture.package.manifest.name,
                    revision=1,
                )
                for fixture in ordered
            ),
        ),
        selected_plugin_ids=tuple(
            fixture.package.manifest.name for fixture in ordered
        ),
        selected_contributions=tuple(
            PluginContributionRef(
                fixture.package.manifest.name,
                fixture.contribution.contribution_id,
            )
            for fixture in ordered
        ),
        source_trust_snapshots=tuple(
            PluginSourceTrustSnapshotV1(
                plugin_id=fixture.package.manifest.name,
                package_source_identity=fixture.binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            )
            for fixture in ordered
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=fixture.package.manifest.name,
                    contribution_id=fixture.contribution.contribution_id,
                    configuration=dict(fixture.contribution.configuration),
                )
                for fixture in ordered
            )
        ),
        allowed_authority_ceiling=tuple(
            sorted(
                {
                    authority
                    for fixture in ordered
                    for authority in fixture.contribution.requested_authorities
                }
            )
        ),
    )
