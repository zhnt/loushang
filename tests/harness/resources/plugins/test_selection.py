from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

import loushang.harness.resources.plugins.selection as plugin_selection
from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclaration,
    PluginDeclarationSource,
)
from loushang.harness.resources.plugins.selection import (
    AcceptedPluginPreflight,
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginDeclarationDataOnlyGate,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionMissing,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginPreflightDeniedOutcome,
    PluginPreflightOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginPreflightRejectedOutcome,
    PluginSelectionError,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
    build_execution_approval_subject,
)
from loushang.harness.resources.plugins.types import PluginSource


class _DecisionLookup:
    def __init__(self, *decisions: PluginExecutionDecisionRecord) -> None:
        self._decisions = {
            decision.subject_digest: decision for decision in decisions
        }
        self.subject_digests: list[str] = []

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        self.subject_digests.append(subject.digest)
        decision = self._decisions.get(subject.digest)
        if decision is None:
            return PluginExecutionDecisionMissing()
        return PluginExecutionDecisionCurrent(decision=decision)


def _accepted(outcome: PluginPreflightOutcome) -> AcceptedPluginPreflight:
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    return outcome.accepted


def test_preflight_and_finalize_are_inert_and_reservations_are_one_use(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    contribution = package.contribution_index.items[0]
    plan = _plan(binding.source_identity)
    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        binding=binding,
    )
    changed_subject = build_execution_approval_subject(
        package,
        contribution,
        plan=replace(
            plan,
            context=replace(plan.context, policy_revision="policy-2"),
        ),
        binding=binding,
    )
    assert changed_subject.digest != subject.digest
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-1",
        subject_digest=subject.digest,
        policy_revision=plan.context.policy_revision,
        disposition="approved",
    )
    resolver = PluginSelectionResolver()

    preflight = _accepted(
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decision_lookup=_DecisionLookup(decision),
        )
    )
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        source_kind=contribution.declaration_source.kind,
        payload=CapabilityProviderDeclarationPayload(
            provider=CapabilityBundleProvider(
                capability_id="coding.lsp",
                provider_id="review-lsp",
                implementation_version=1,
                compatible_contract=CapabilityContractRange.exact(1),
                facets=("semantic",),
                required_authorities=frozenset({"process"}),
                source_id="plugin:review-pack",
                selection_rule=PLUGIN_PROVIDER_SELECTION_RULE,
            ),
            factory=PluginSymbolReference(
                path="provider.py",
                symbol="create_provider",
                execution_model="in_process",
            ),
            disposer=None,
            binding_inputs=dict(contribution.configuration),
        ).to_dict(),
    )
    assert PluginDeclaration.from_dict(declaration.to_dict()) == declaration

    selection = resolver.finalize(preflight, (declaration,))

    assert len(selection.candidates) == 1
    assert selection.candidates[0].decision_id == "decision-1"
    assert len(selection.candidates[0].fingerprint) == 64
    assert (package.root / "imported.txt").exists() is False
    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(preflight, (declaration,))
    assert caught.value.code == "plugin_preflight_consumed"

    rolled_back = _accepted(
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decision_lookup=_DecisionLookup(decision),
        )
    )
    assert rolled_back.preflight_use_id != preflight.preflight_use_id
    assert (
        rolled_back.source_groups[0].source_group_fingerprint
        == preflight.source_groups[0].source_group_fingerprint
    )
    assert (
        rolled_back.source_groups[0].source_group_id
        != preflight.source_groups[0].source_group_id
    )
    resolver.rollback(rolled_back)
    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(rolled_back, (declaration,))
    assert caught.value.code == "plugin_preflight_consumed"
    runtime.close()


def test_preflight_rejects_disabled_plugin_without_importing_code(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, enabled=False)
    binding = runtime.bindings[0]
    resolver = PluginSelectionResolver()

    outcome = resolver.preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=_plan(binding.source_identity),
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )

    assert isinstance(outcome, PluginPreflightRejectedOutcome)
    assert outcome.diagnostics[0].code == "selected_plugin_disabled"
    assert (runtime.packages[0].root / "imported.txt").exists() is False
    runtime.close()


def test_document_source_accepts_without_execution_decision_or_copied_gate(
    tmp_path: Path,
) -> None:
    class _RejectLookup:
        def lookup_execution_decision(
            self,
            subject: PluginExecutionApprovalSubject,
        ) -> PluginExecutionDecisionLookupResult:
            raise AssertionError("data-only source must not query execution approval")

    runtime = _runtime(tmp_path, document_source=True)
    binding = runtime.bindings[0]
    resolver = PluginSelectionResolver()

    accepted = _accepted(
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=_plan(binding.source_identity),
            decision_lookup=_RejectLookup(),
        )
    )

    assert len(accepted.preflight_use_id) == 48
    assert len(accepted.host_boot_id) == 32
    assert accepted.host_epoch == accepted.host_boot_id
    assert len(accepted.source_groups) == 1
    group = accepted.source_groups[0]
    assert isinstance(group.gate, PluginDeclarationDataOnlyGate)
    assert group.declaration_source.kind == "document"
    assert group.reservations[0].source_group_id == group.source_group_id
    assert not hasattr(group.reservations[0], "approval_subject")
    assert not hasattr(group.reservations[0], "decision_id")
    resolver.rollback(accepted)
    runtime.close()


def test_expired_accepted_preflight_is_terminal_and_cannot_be_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path, document_source=True)
    binding = runtime.bindings[0]
    resolver = PluginSelectionResolver()
    monkeypatch.setattr(plugin_selection, "_PLUGIN_PREFLIGHT_TTL_SECONDS", 0.0)
    accepted = _accepted(
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=_plan(binding.source_identity),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
    )

    with pytest.raises(PluginSelectionError) as caught:
        resolver.rollback(accepted)
    assert caught.value.code == "preflight_expired"
    with pytest.raises(PluginSelectionError) as caught:
        resolver.rollback(accepted)
    assert caught.value.code == "plugin_preflight_consumed"
    runtime.close()


def test_preflight_requires_exact_approval_subject_and_binding(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    plan = _plan(binding.source_identity)
    contribution = package.contribution_index.items[0]
    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        binding=binding,
    )
    stale_decision = PluginExecutionDecisionRecord(
        decision_id="stale",
        subject_digest=subject.digest,
        policy_revision="policy-previous",
        disposition="approved",
    )
    denied_decision = replace(
        stale_decision,
        decision_id="denied",
        policy_revision=plan.context.policy_revision,
        disposition="denied",
    )

    outcome = PluginSelectionResolver().preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(outcome, PluginPreflightPendingApprovalOutcome)
    assert outcome.subjects == (subject,)

    outcome = PluginSelectionResolver().preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decision_lookup=_DecisionLookup(stale_decision),
    )
    assert isinstance(outcome, PluginPreflightRejectedOutcome)
    assert outcome.diagnostics[0].code == "invalid_plugin_execution_decision_lookup"

    outcome = PluginSelectionResolver().preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decision_lookup=_DecisionLookup(denied_decision),
    )
    assert isinstance(outcome, PluginPreflightDeniedOutcome)
    assert outcome.diagnostics[0].code == "plugin_execution_denied"

    outcome = PluginSelectionResolver().preflight(
        runtime.packages,
        bindings=(),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(outcome, PluginPreflightRejectedOutcome)
    assert outcome.diagnostics[0].code == "plugin_selection_package_mismatch"
    assert (package.root / "imported.txt").exists() is False
    runtime.close()


def test_preflight_looks_up_one_decision_per_complete_source_closure(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, include_source_sibling=True)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    plan = _plan(
        binding.source_identity,
        include_source_sibling=True,
        select_source_sibling=True,
    )
    subject = build_execution_approval_subject(
        package,
        package.contribution_index.items[0],
        plan=plan,
        binding=binding,
    )
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-source-closure",
        subject_digest=subject.digest,
        policy_revision=plan.context.policy_revision,
        disposition="approved",
    )
    lookup = _DecisionLookup(decision)
    resolver = PluginSelectionResolver()

    preflight = _accepted(
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decision_lookup=lookup,
        )
    )

    assert lookup.subject_digests == [subject.digest]
    assert len(preflight.source_groups) == 1
    assert len(preflight.reservations) == 2
    assert {
        item.source_group_id for item in preflight.reservations
    } == {preflight.source_groups[0].source_group_id}
    resolver.rollback(preflight)
    runtime.close()


def test_preflight_rejects_invalid_lookup_result(tmp_path: Path) -> None:
    class _InvalidLookup:
        def lookup_execution_decision(
            self,
            subject: PluginExecutionApprovalSubject,
        ) -> object:
            return object()

    runtime = _runtime(tmp_path)
    binding = runtime.bindings[0]

    outcome = PluginSelectionResolver().preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=_plan(binding.source_identity),
        decision_lookup=_InvalidLookup(),  # type: ignore[arg-type]
    )

    assert isinstance(outcome, PluginPreflightRejectedOutcome)
    assert outcome.diagnostics[0].code == "invalid_plugin_execution_decision_lookup"
    runtime.close()


def test_finalize_fails_closed_on_missing_or_changed_declaration(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    plan = _plan(binding.source_identity)
    contribution = package.contribution_index.items[0]
    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        binding=binding,
    )
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-1",
        subject_digest=subject.digest,
        policy_revision=plan.context.policy_revision,
        disposition="approved",
    )
    resolver = PluginSelectionResolver()
    preflight = _accepted(
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decision_lookup=_DecisionLookup(decision),
        )
    )

    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(preflight, ())
    assert caught.value.code == "plugin_declaration_reservation_mismatch"
    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(preflight, ())
    assert caught.value.code == "plugin_preflight_consumed"
    runtime.close()


def test_declaration_ir_rejects_callable_payload() -> None:
    with pytest.raises(ValueError):
        PluginDeclaration(
            plugin_id="review-pack",
            contribution_id="review-provider",
            kind="capability_provider",
            owner="coding.lsp",
            reservation_fingerprint="a" * 64,
            source_descriptor_fingerprint="b" * 64,
            source_kind="in_process",
            payload={"factory": lambda: None},
        )
    with pytest.raises(ValueError):
        PluginDeclaration.from_dict(
            {
                "pluginId": "review-pack",
                "contributionId": "review-provider",
                "kind": "capability_provider",
                "owner": "coding.lsp",
                "reservationFingerprint": "a" * 64,
                "payload": {},
                "irVersion": 1,
                "unknown": True,
            }
        )


def test_subject_v2_closes_over_every_contribution_from_the_same_source(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, include_source_sibling=True)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    contribution = package.contribution_index.items[0]
    plan = replace(
        _plan(binding.source_identity, include_source_sibling=True),
        allowed_authority_ceiling=("filesystem", "process"),
    )

    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        binding=binding,
    )
    closure = package.contribution_index.items
    expected_reservations = {
        "domain": "loushang.plugin-reservation-closure/v1",
        "reservations": [
            {
                "contributionId": item.contribution_id,
                "reservationFingerprint": item.fingerprint,
            }
            for item in closure
        ],
    }
    expected_configurations = {
        "configurations": [
            {
                "configuration": item.to_dict()["configuration"],
                "contributionId": item.contribution_id,
                "pluginId": "review-pack",
            }
            for item in closure
        ],
        "domain": "loushang.plugin-group-configuration/v1",
    }

    assert subject.requested_authorities == ("filesystem", "process")
    assert subject.reservation_closure_fingerprint == sha256(
        StrictPluginJsonCodec.encode(expected_reservations)
    ).hexdigest()
    assert subject.configuration_map_fingerprint == sha256(
        StrictPluginJsonCodec.encode(expected_configurations)
    ).hexdigest()
    runtime.close()


def test_subject_v2_hashes_product_effective_configuration(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    contribution = package.contribution_index.items[0]
    plan = _plan(binding.source_identity)
    baseline = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        binding=binding,
    )
    override_entry = PluginEffectiveConfigurationEntry(
        plugin_id="review-pack",
        contribution_id="review-provider",
        configuration={"mode": "product-override"},
    )
    override_plan = replace(
        plan,
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(override_entry,)
        ),
    )
    overridden = build_execution_approval_subject(
        package,
        contribution,
        plan=override_plan,
        binding=binding,
    )

    assert overridden.configuration_map_fingerprint != (
        baseline.configuration_map_fingerprint
    )
    assert overridden.digest != baseline.digest
    runtime.close()


def test_disjoint_source_configuration_does_not_change_another_subject(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, include_disjoint_source=True)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    contributions = {
        item.contribution_id: item for item in package.contribution_index.items
    }
    plan = _plan(binding.source_identity, include_disjoint_source=True)

    def subject_for(
        contribution_id: str,
        selected_plan: PluginSelectionPlanV2,
    ) -> PluginExecutionApprovalSubject:
        return build_execution_approval_subject(
            package,
            contributions[contribution_id],
            plan=selected_plan,
            binding=binding,
        )

    review_before = subject_for("review-provider", plan)
    arch_before = subject_for("z-arch-provider", plan)
    review_entry, arch_entry = plan.effective_configuration_set.entries
    changed_plan = replace(
        plan,
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                review_entry,
                replace(arch_entry, configuration={"depth": 9}),
            )
        ),
    )
    review_after = subject_for("review-provider", changed_plan)
    arch_after = subject_for("z-arch-provider", changed_plan)

    assert review_after == review_before
    assert arch_after.digest != arch_before.digest
    runtime.close()


def test_preflight_rejects_extra_effective_configuration_entry(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    binding = runtime.bindings[0]
    plan = _plan(binding.source_identity)
    extra_plan = replace(
        plan,
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                *plan.effective_configuration_set.entries,
                PluginEffectiveConfigurationEntry(
                    plugin_id="review-pack",
                    contribution_id="z-ghost-provider",
                    configuration={},
                ),
            )
        ),
    )

    outcome = PluginSelectionResolver().preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=extra_plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )

    assert isinstance(outcome, PluginPreflightRejectedOutcome)
    assert outcome.diagnostics[0].code == "invalid_plugin_effective_configuration"
    runtime.close()


def _runtime(
    tmp_path: Path,
    *,
    enabled: bool = True,
    include_source_sibling: bool = False,
    include_disjoint_source: bool = False,
    document_source: bool = False,
) -> PluginRuntimeResolution:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "provider.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('imported.txt').write_text('imported')\n",
        encoding="utf-8",
    )
    if include_disjoint_source:
        (root / "arch.py").write_text("def declare():\n    return None\n", encoding="utf-8")
    if document_source:
        (root / "declarations").mkdir()
        (root / "declarations" / "providers.json").write_text(
            '{"declarations":[],"documentVersion":1}',
            encoding="utf-8",
        )
    declaration_source = (
        PluginDeclarationSource.document("declarations/providers.json").to_dict()
        if document_source
        else PluginDeclarationSource.in_process("provider.py:declare").to_dict()
    )
    items = [
        {
            "id": "review-provider",
            "kind": "capability_provider",
            "owner": "coding.lsp",
            "contributionExecutionModel": "in_process",
            "declarationSource": declaration_source,
            "requestedAuthorities": ["process"],
            "configuration": {"mode": "review"},
            "required": True,
        }
    ]
    if include_source_sibling:
        items.append(
            {
                "id": "review-tools",
                "kind": "capability_provider",
                "owner": "coding.tools",
                "contributionExecutionModel": "in_process",
                "declarationSource": {
                    "entrypoint": "provider.py:declare",
                    "kind": "in_process",
                    "sourceVersion": 1,
                },
                "requestedAuthorities": ["filesystem"],
                "configuration": {"mode": "tools"},
                "required": False,
            }
        )
    if include_disjoint_source:
        items.append(
            {
                "id": "z-arch-provider",
                "kind": "capability_provider",
                "owner": "coding.arch",
                "contributionExecutionModel": "in_process",
                "declarationSource": {
                    "entrypoint": "arch.py:declare",
                    "kind": "in_process",
                    "sourceVersion": 1,
                },
                "requestedAuthorities": ["process"],
                "configuration": {"depth": 3},
                "required": True,
            }
        )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "review-pack",
                "enabled": enabled,
                "contributionIndex": {
                    "version": 2,
                    "items": items,
                },
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    return authority.publish_runtime((inspection,), binding_store=materializer)


def _plan(
    source_identity: str,
    *,
    include_source_sibling: bool = False,
    select_source_sibling: bool = False,
    include_disjoint_source: bool = False,
) -> PluginSelectionPlanV2:
    if select_source_sibling and not include_source_sibling:
        raise ValueError("Selecting the source sibling requires its fixture")
    configuration_entries = [
        PluginEffectiveConfigurationEntry(
            plugin_id="review-pack",
            contribution_id="review-provider",
            configuration={"mode": "review"},
        )
    ]
    if include_source_sibling:
        configuration_entries.append(
            PluginEffectiveConfigurationEntry(
                plugin_id="review-pack",
                contribution_id="review-tools",
                configuration={"mode": "tools"},
            )
        )
    selected_contributions = [
        PluginContributionRef("review-pack", "review-provider")
    ]
    if select_source_sibling:
        selected_contributions.append(
            PluginContributionRef("review-pack", "review-tools")
        )
    if include_disjoint_source:
        selected_contributions.append(
            PluginContributionRef("review-pack", "z-arch-provider")
        )
        configuration_entries.append(
            PluginEffectiveConfigurationEntry(
                plugin_id="review-pack",
                contribution_id="z-arch-provider",
                configuration={"depth": 3},
            )
        )
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="review-pack@product",
                    plugin_id="review-pack",
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=("review-pack",),
        selected_contributions=tuple(selected_contributions),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id="review-pack",
                package_source_identity=source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(configuration_entries)
        ),
        allowed_authority_ceiling=(
            ("filesystem", "process")
            if include_source_sibling
            else ("process",)
        ),
    )
