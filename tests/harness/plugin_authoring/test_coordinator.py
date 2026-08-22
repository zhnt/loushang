from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

import pytest

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
    PluginSelection,
    PluginSelectionError,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
    build_execution_approval_subject,
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
        with resolver._gate:
            aggregate = resolver._active[accepted.preflight_use_id]
            assert aggregate.state == "closing_abort"
            assert aggregate.in_flight == 1
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
    subject = build_execution_approval_subject(
        fixture.package,
        fixture.contribution,
        plan=plan,
        binding=fixture.binding,
    )
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
