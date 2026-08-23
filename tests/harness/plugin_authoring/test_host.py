from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, get_args

import pytest

from loushang.harness.plugin_authoring.host import (
    PluginDeclarationHost,
    PluginDeclarationHostResult,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginPreflightDeniedOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginPreflightRejectedOutcome,
    PluginSelection,
    PluginSelectionError,
    PluginSelectionPlanV2,
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


@dataclass(frozen=True, slots=True)
class _CurrentDecisionLookup:
    decision: PluginExecutionDecisionRecord

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        return PluginExecutionDecisionCurrent(decision=self.decision)


class _InvalidDecisionLookup:
    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> object:
        return object()


def test_host_composes_document_selection_without_exposing_accepted_preflight(
    published_document_plugin: _PublishedPlugin,
) -> None:
    fixture = published_document_plugin
    host = PluginDeclarationHost()
    plan = _plan(fixture)

    first = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    second = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )

    assert isinstance(first, PluginSelection)
    assert isinstance(second, PluginSelection)
    assert first.plan is plan
    assert len(first.candidates) == 1
    assert first.candidates[0].evidence.kind == "document_decoded"
    assert second.candidates[0].evidence.preflight_use_id != (
        first.candidates[0].evidence.preflight_use_id
    )
    assert not hasattr(host, "resolver")
    assert not hasattr(host, "coordinator")
    assert set(get_args(PluginDeclarationHostResult)) == {
        PluginSelection,
        PluginPreflightPendingApprovalOutcome,
        PluginPreflightDeniedOutcome,
        PluginPreflightRejectedOutcome,
    }


def test_host_returns_fresh_pending_outcomes_without_import_or_resume(
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    host = PluginDeclarationHost()
    plan = _plan(fixture)

    first = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    second = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )

    assert isinstance(first, PluginPreflightPendingApprovalOutcome)
    assert isinstance(second, PluginPreflightPendingApprovalOutcome)
    assert second.subjects == first.subjects
    assert second is not first
    assert not hasattr(first, "accepted")
    assert fixture.import_marker.exists() is False


def test_host_preserves_denied_and_rejected_preflight_arms(
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    host = PluginDeclarationHost()
    plan = _plan(fixture)
    pending = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects

    denied = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=_CurrentDecisionLookup(
            PluginExecutionDecisionRecord(
                decision_id="decision-denied",
                subject_digest=subject.digest,
                policy_revision=plan.context.policy_revision,
                disposition="denied",
            )
        ),
    )
    rejected = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=_InvalidDecisionLookup(),
    )

    assert isinstance(denied, PluginPreflightDeniedOutcome)
    assert denied.diagnostics[0].code == "plugin_execution_denied"
    assert isinstance(rejected, PluginPreflightRejectedOutcome)
    assert rejected.diagnostics[0].code == ("invalid_plugin_execution_decision_lookup")
    assert fixture.import_marker.exists() is False


def test_host_aborts_accepted_executable_until_evaluator_exists(
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin
    host = PluginDeclarationHost()
    plan = _plan(fixture)
    pending = host.resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects

    with pytest.raises(PluginSelectionError) as caught:
        host.resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=plan,
            decision_lookup=_CurrentDecisionLookup(
                PluginExecutionDecisionRecord(
                    decision_id="decision-approved",
                    subject_digest=subject.digest,
                    policy_revision=plan.context.policy_revision,
                    disposition="approved",
                )
            ),
        )

    assert caught.value.code == "execution_not_consumed"
    assert fixture.import_marker.exists() is False


def _plan(fixture: _PublishedPlugin) -> PluginSelectionPlanV2:
    plugin_id = fixture.package.manifest.name
    contribution_id = fixture.contribution.contribution_id
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{plugin_id}@product",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=(PluginContributionRef(plugin_id, contribution_id),),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=plugin_id,
                package_source_identity=fixture.binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=contribution_id,
                    configuration=dict(fixture.contribution.configuration),
                ),
            )
        ),
        allowed_authority_ceiling=fixture.contribution.requested_authorities,
    )
