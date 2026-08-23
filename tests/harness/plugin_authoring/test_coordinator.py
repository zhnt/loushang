from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

import pytest

import loushang.harness.resources.plugins.selection as plugin_selection
from loushang.harness.plugin_authoring.coordinator import (
    PluginDeclarationCoordinator,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.selection import (
    AcceptedPluginPreflight,
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginDeclarationBatch,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionRecord,
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


class _PublishedDocumentPlugin(_PublishedPlugin, Protocol):
    declaration: PluginDeclaration


class _PublishedExecutablePlugin(_PublishedPlugin, Protocol):
    import_marker: Path


@dataclass
class _CurrentDecisionLookup:
    decision: PluginExecutionDecisionRecord

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        return PluginExecutionDecisionCurrent(decision=self.decision)


def test_document_coordinator_decodes_once_and_finalizes_evidenced_candidate(
    published_document_plugin: _PublishedDocumentPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = published_document_plugin
    resolver = PluginSelectionResolver()
    accepted = _accepted_document(resolver, fixture)
    decode_calls = 0
    decode_bytes = PluginDeclarationDocumentCodec.decode_bytes

    def _decode_once(encoded: bytes) -> PluginDeclarationDocument:
        nonlocal decode_calls
        decode_calls += 1
        return decode_bytes(encoded)

    monkeypatch.setattr(PluginDeclarationDocumentCodec, "decode_bytes", _decode_once)

    selection = PluginDeclarationCoordinator(resolver).finalize(accepted)

    assert decode_calls == 1
    assert len(selection.candidates) == 1
    candidate = selection.candidates[0]
    assert candidate.declaration == fixture.declaration
    assert candidate.evidence.kind == "document_decoded"
    assert candidate.evidence.preflight_use_id == accepted.preflight_use_id
    assert candidate.evidence.source_group_id == accepted.source_groups[0].source_group_id
    assert not hasattr(candidate, "decision_id")
    with pytest.raises(PluginSelectionError) as caught:
        PluginDeclarationCoordinator(resolver).finalize(accepted)
    assert caught.value.code == "preflight_already_finalized"


def test_document_decode_failure_aborts_attempt_once(
    published_document_plugin: _PublishedDocumentPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = PluginSelectionResolver()
    accepted = _accepted_document(resolver, published_document_plugin)

    def _reject_document(encoded: bytes) -> PluginDeclarationDocument:
        raise PluginDeclarationCodecError(
            "rejected document",
            code="plugin_declaration_field_value_mismatch",
        )

    monkeypatch.setattr(
        PluginDeclarationDocumentCodec,
        "decode_bytes",
        _reject_document,
    )
    coordinator = PluginDeclarationCoordinator(resolver)

    with pytest.raises(PluginDeclarationCodecError):
        coordinator.finalize(accepted)
    with pytest.raises(PluginSelectionError) as caught:
        coordinator.finalize(accepted)
    assert caught.value.code == "preflight_already_aborted"


def test_racing_document_finalizers_publish_exactly_once(
    published_document_plugin: _PublishedDocumentPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = PluginSelectionResolver()
    accepted = _accepted_document(resolver, published_document_plugin)
    decode_started = Event()
    allow_decode = Event()
    decode_bytes = PluginDeclarationDocumentCodec.decode_bytes

    def _blocking_decode(encoded: bytes) -> PluginDeclarationDocument:
        decode_started.set()
        assert allow_decode.wait(timeout=5.0)
        return decode_bytes(encoded)

    monkeypatch.setattr(
        PluginDeclarationDocumentCodec,
        "decode_bytes",
        _blocking_decode,
    )
    coordinator = PluginDeclarationCoordinator(resolver)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(coordinator.finalize, accepted)
        assert decode_started.wait(timeout=5.0)
        second = pool.submit(coordinator.finalize, accepted)
        allow_decode.set()
        outcomes: list[PluginSelection | str] = []
        for future in (first, second):
            try:
                outcomes.append(future.result(timeout=5.0))
            except PluginSelectionError as exc:
                outcomes.append(exc.code)

    assert sum(isinstance(item, PluginSelection) for item in outcomes) == 1
    assert outcomes.count("preflight_already_finalized") == 1


def test_abort_waits_for_claimed_document_group_to_settle(
    published_document_plugin: _PublishedDocumentPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = PluginSelectionResolver()
    accepted = _accepted_document(resolver, published_document_plugin)
    decode_started = Event()
    allow_decode = Event()
    decode_bytes = PluginDeclarationDocumentCodec.decode_bytes

    def _blocking_decode(encoded: bytes) -> PluginDeclarationDocument:
        decode_started.set()
        assert allow_decode.wait(timeout=5.0)
        return decode_bytes(encoded)

    monkeypatch.setattr(
        PluginDeclarationDocumentCodec,
        "decode_bytes",
        _blocking_decode,
    )
    coordinator = PluginDeclarationCoordinator(resolver)

    with ThreadPoolExecutor(max_workers=2) as pool:
        finalizer = pool.submit(coordinator.finalize, accepted)
        assert decode_started.wait(timeout=5.0)
        aborter = pool.submit(resolver._abort, accepted)
        assert _wait_for_closing_abort(resolver, accepted) == 1
        assert aborter.done() is False
        allow_decode.set()
        assert aborter.result(timeout=5.0) is None
        with pytest.raises(PluginSelectionError) as caught:
            finalizer.result(timeout=5.0)

    assert caught.value.code == "preflight_already_aborted"
    with resolver._gate:
        terminal = resolver._terminal[accepted.preflight_use_id]
        assert terminal.late_group_results == (
            (accepted.source_groups[0].source_group_id, "completed"),
        )


def test_execution_start_permit_wins_before_close_and_close_waits_for_worker(
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    resolver = PluginSelectionResolver()
    accepted = _accepted_executable(resolver, published_synthetic_plugin)
    group = accepted.source_groups[0]
    claim = resolver._claim_group(accepted, group)

    permit = resolver._issue_execution_start_permit(claim)

    assert permit.preflight_use_id == accepted.preflight_use_id
    assert permit.source_group_id == group.source_group_id
    assert permit.host_boot_id == accepted.host_boot_id
    with ThreadPoolExecutor(max_workers=1) as pool:
        aborter = pool.submit(resolver._abort, accepted)
        assert _wait_for_closing_abort(resolver, accepted) == 1
        assert aborter.done() is False
        with pytest.raises(PluginSelectionError) as caught:
            resolver._settle_group(claim, succeeded=False)
        assert caught.value.code == "preflight_already_aborted"
        assert aborter.result(timeout=5.0) is None


def test_close_before_execution_start_permit_forbids_start_and_waits_for_settle(
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    resolver = PluginSelectionResolver()
    accepted = _accepted_executable(resolver, published_synthetic_plugin)
    claim = resolver._claim_group(accepted, accepted.source_groups[0])

    with ThreadPoolExecutor(max_workers=1) as pool:
        aborter = pool.submit(resolver._abort, accepted)
        assert _wait_for_closing_abort(resolver, accepted) == 1
        with pytest.raises(PluginSelectionError) as caught:
            resolver._issue_execution_start_permit(claim)
        assert caught.value.code == "preflight_closing"
        assert aborter.done() is False
        with pytest.raises(PluginSelectionError) as settled:
            resolver._settle_group(claim, succeeded=False)
        assert settled.value.code == "preflight_already_aborted"
        assert aborter.result(timeout=5.0) is None


def test_execution_start_permit_is_single_use_and_executable_only(
    published_document_plugin: _PublishedDocumentPlugin,
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    executable_resolver = PluginSelectionResolver()
    executable = _accepted_executable(
        executable_resolver,
        published_synthetic_plugin,
    )
    executable_claim = executable_resolver._claim_group(
        executable,
        executable.source_groups[0],
    )
    executable_resolver._issue_execution_start_permit(executable_claim)

    with pytest.raises(PluginSelectionError) as repeated:
        executable_resolver._issue_execution_start_permit(executable_claim)
    assert repeated.value.code == "plugin_execution_start_permit_consumed"
    executable_resolver._settle_group(executable_claim, succeeded=False)
    executable_resolver._abort(executable)

    document_resolver = PluginSelectionResolver()
    document = _accepted_document(document_resolver, published_document_plugin)
    document_claim = document_resolver._claim_group(
        document,
        document.source_groups[0],
    )
    with pytest.raises(PluginSelectionError) as not_applicable:
        document_resolver._issue_execution_start_permit(document_claim)
    assert not_applicable.value.code == "plugin_execution_start_not_applicable"
    document_resolver._settle_group(document_claim, succeeded=False)
    document_resolver._abort(document)


def test_execution_start_permit_rejects_the_exact_aggregate_deadline(
    published_synthetic_plugin: _PublishedExecutablePlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = PluginSelectionResolver()
    accepted = _accepted_executable(resolver, published_synthetic_plugin)
    claim = resolver._claim_group(accepted, accepted.source_groups[0])
    monkeypatch.setattr(
        plugin_selection,
        "monotonic",
        lambda: accepted.expires_at,
    )

    with pytest.raises(PluginSelectionError) as caught:
        resolver._issue_execution_start_permit(claim)
    assert caught.value.code == "preflight_closing"
    with pytest.raises(PluginSelectionError) as settled:
        resolver._settle_group(claim, succeeded=False)
    assert settled.value.code == "preflight_expired"


def test_plc1b_coordinator_aborts_executable_group_without_finalization_or_import(
    published_synthetic_plugin: _PublishedExecutablePlugin,
) -> None:
    fixture = published_synthetic_plugin

    class _CountingResolver(PluginSelectionResolver):
        def __init__(self) -> None:
            super().__init__()
            self.finalize_calls = 0

        def _finalize(
            self,
            accepted: AcceptedPluginPreflight,
            batches: tuple[PluginDeclarationBatch, ...],
        ) -> PluginSelection:
            self.finalize_calls += 1
            return super()._finalize(accepted, batches)

    resolver = _CountingResolver()
    plan = _plan(fixture)
    pending = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects
    outcome = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=_CurrentDecisionLookup(
            PluginExecutionDecisionRecord(
                decision_id="decision-1",
                subject_digest=subject.digest,
                policy_revision=plan.context.policy_revision,
                disposition="approved",
            )
        ),
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)

    with pytest.raises(PluginSelectionError) as caught:
        PluginDeclarationCoordinator(resolver).finalize(outcome.accepted)

    assert caught.value.code == "execution_not_consumed"
    assert resolver.finalize_calls == 0
    assert fixture.import_marker.exists() is False


def _accepted_document(
    resolver: PluginSelectionResolver,
    fixture: _PublishedDocumentPlugin,
) -> AcceptedPluginPreflight:
    outcome = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=_plan(fixture),
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    return outcome.accepted


def _accepted_executable(
    resolver: PluginSelectionResolver,
    fixture: _PublishedExecutablePlugin,
) -> AcceptedPluginPreflight:
    plan = _plan(fixture)
    pending = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects
    outcome = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=_CurrentDecisionLookup(
            PluginExecutionDecisionRecord(
                decision_id="decision-1",
                subject_digest=subject.digest,
                policy_revision=plan.context.policy_revision,
                disposition="approved",
            )
        ),
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    return outcome.accepted


def _wait_for_closing_abort(
    resolver: PluginSelectionResolver,
    accepted: AcceptedPluginPreflight,
) -> int:
    with resolver._gate:
        assert resolver._gate.wait_for(
            lambda: (
                accepted.preflight_use_id in resolver._active
                and resolver._active[accepted.preflight_use_id].state
                == "closing_abort"
            ),
            timeout=5.0,
        )
        return resolver._active[accepted.preflight_use_id].in_flight


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
