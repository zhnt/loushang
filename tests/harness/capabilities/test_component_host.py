from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities.component_host import (
    CapabilityComponentHost,
)
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.graph_binding import (
    CapabilityGraphBindingError,
    RuntimeCapabilityGraphBinder,
)
from loushang.harness.capabilities.graph_planning import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphPlan,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.graph_runtime import (
    RuntimeCapabilityGraphRuntime,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderBindingSpec,
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
    CapabilityProviderOwnerSnapshot,
    CapabilityProviderSymbolLocator,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
    ResolvedCapabilityProvider,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.plugin_authoring.coordinator import (
    PluginDeclarationCoordinator,
)
from loushang.harness.plugin_authoring.evaluator import PluginDefinitionEvaluator
from loushang.harness.plugin_authoring.import_realm import (
    PluginImportRealm as PluginDefinitionImportRealm,
)
from loushang.harness.plugin_authoring.provider_admission import (
    prepare_capability_provider_candidate,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.dependencies import (
    lock_plugin_dependency_closure,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginPreflightPendingApprovalOutcome,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PublishedPluginPackage,
)

_AUTHOR_GUIDE = Path(
    "docs/internals/architecture/harness/plugin/plugin-authoring-guide.md"
)


def test_author_guide_provider_runs_through_component_host(tmp_path: Path) -> None:
    asyncio.run(_author_guide_provider_runs_through_component_host(tmp_path))


@pytest.mark.parametrize(
    "provider_source",
    (
        "import loushang.plugin.provider_runtime\n",
        "from loushang.harness import capabilities\n",
    ),
)
def test_component_host_rejects_parent_and_broad_runtime_imports(
    tmp_path: Path,
    provider_source: str,
) -> None:
    async def scenario() -> None:
        fixture = _fixture(
            tmp_path,
            returned_facet="query",
            provider_source=provider_source,
        )
        journal = _journal(tmp_path)
        host = _host(journal, fixture)
        subject = host.activation_subject(
            fixture.resolved,
            owner_snapshot=fixture.owner_snapshot,
            trust_snapshot=fixture.trust_snapshot,
        )
        decision = _approve(journal, subject)
        prepared = host.prepare_component(
            fixture.resolved,
            package=fixture.package,
            owner_snapshot=fixture.owner_snapshot,
            trust_snapshot=fixture.trust_snapshot,
            decision_id=decision.decision_id,
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="session:denied-import",
            profile_fingerprint="f" * 64,
        )

        with pytest.raises(CapabilityGraphBindingError):
            await RuntimeCapabilityGraphBinder().bind(
                runtime,
                fixture.plan,
                (prepared.binding,),
            )
        assert await prepared.abort_uncommitted() is False

    asyncio.run(scenario())


async def _author_guide_provider_runs_through_component_host(tmp_path: Path) -> None:
    guide = _AUTHOR_GUIDE.read_text(encoding="utf-8")
    definition_source = guide.split("```python\n", 1)[1].split("\n```", 1)[0]
    provider_source = guide.split("```python\n", 2)[2].split("\n```", 1)[0]
    fixture, plugin_runtime = _author_guide_fixture(
        tmp_path,
        definition_source=definition_source,
        provider_source=provider_source,
    )
    try:
        journal = _journal(tmp_path)
        host = _host(journal, fixture)
        subject = host.activation_subject(
            fixture.resolved,
            owner_snapshot=fixture.owner_snapshot,
            trust_snapshot=fixture.trust_snapshot,
        )
        decision = _approve(journal, subject)
        prepared = host.prepare_component(
            fixture.resolved,
            package=fixture.package,
            owner_snapshot=fixture.owner_snapshot,
            trust_snapshot=fixture.trust_snapshot,
            decision_id=decision.decision_id,
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="example",
            runtime_id="session:author-guide",
            profile_fingerprint="f" * 64,
        )
        binder = RuntimeCapabilityGraphBinder()
        await binder.bind(runtime, fixture.plan, (prepared.binding,))
        prepared.commit_after_graph_publication()
        consumer = runtime.capture(
            CapabilityRequirement(
                capability="example.echo",
                facets=("echo",),
                compatible_contract=CapabilityContractRange.exact(1),
            )
        )
        provider = consumer.require("echo")

        assert provider.echo("hello") == "hello"  # type: ignore[attr-defined]
        assert provider.closed is False  # type: ignore[attr-defined]

        await binder.dispose(runtime)

        assert provider.closed is True  # type: ignore[attr-defined]
    finally:
        plugin_runtime.close()


def test_component_host_defers_import_until_the_existing_binder_constructs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_defers_import_until_the_existing_binder_constructs(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_defers_import_until_the_existing_binder_constructs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, returned_facet="query")
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)

    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )

    assert not marker.exists()
    assert journal.snapshot().activation_uses[0].state == "CONSUMED_NOT_STARTED"

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, fixture.plan, (prepared.binding,))
    assert journal.snapshot().activation_uses[0].state == "STARTED"
    prepared.commit_after_graph_publication()

    consumer = runtime.capture(
        CapabilityRequirement(
            capability="coding.semantic",
            facets=("query",),
            compatible_contract=CapabilityContractRange.exact(1),
        )
    )
    assert consumer.require("query") == {
        "label": "foundation",
        "runtime_id": "session:test",
    }
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
    ]
    assert journal.snapshot().activation_uses[0].state == "COMMITTED"

    await binder.dispose(runtime)

    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
        "dispose",
    ]
    assert consumer.is_current is False


def test_component_host_retries_provider_disposer_after_transient_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_retries_provider_disposer_after_transient_failure(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_retries_provider_disposer_after_transient_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(
        tmp_path,
        returned_facet="query",
        disposer_fails_once=True,
    )
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, fixture.plan, (prepared.binding,))
    prepared.commit_after_graph_publication()

    assert await binder.dispose(runtime) == ("provider_retirement_failed",)
    assert runtime.has_pending_retirements is True
    assert await binder.dispose(runtime) == ()
    assert runtime.has_pending_retirements is False
    assert marker.read_text(encoding="utf-8").splitlines().count("dispose") == 2


def test_component_host_disposes_invalid_bundle_and_records_failed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_disposes_invalid_bundle_and_records_failed_attempt(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_disposes_invalid_bundle_and_records_failed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, returned_facet="wrong")
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )

    with pytest.raises(CapabilityGraphBindingError) as caught:
        await RuntimeCapabilityGraphBinder().bind(
            runtime,
            fixture.plan,
            (prepared.binding,),
        )

    assert caught.value.diagnostic_codes == ("provider_construction_failed",)
    assert runtime.snapshot is None
    assert journal.snapshot().activation_uses[0].state == "FAILED"
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
        "dispose",
    ]


def test_component_host_retains_invalid_bundle_for_cleanup_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_retains_invalid_bundle_for_cleanup_retry(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_retains_invalid_bundle_for_cleanup_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(
        tmp_path,
        returned_facet="wrong",
        disposer_fails_once=True,
    )
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )

    with pytest.raises(CapabilityGraphBindingError):
        await RuntimeCapabilityGraphBinder().bind(
            runtime,
            fixture.plan,
            (prepared.binding,),
        )

    assert marker.read_text(encoding="utf-8").splitlines().count("dispose") == 1
    assert await prepared.abort_uncommitted() is True
    assert marker.read_text(encoding="utf-8").splitlines().count("dispose") == 2


def test_component_host_retains_valid_bundle_when_started_transition_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_retains_valid_bundle_when_started_transition_fails(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_retains_valid_bundle_when_started_transition_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, returned_facet="query")
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    original_transition = journal.transition_activation_use

    def fail_started_transition(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("target_state") == "STARTED":
            raise RuntimeError("synthetic STARTED persistence failure")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(journal, "transition_activation_use", fail_started_transition)
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )

    with pytest.raises(CapabilityGraphBindingError):
        await RuntimeCapabilityGraphBinder().bind(
            runtime,
            fixture.plan,
            (prepared.binding,),
        )

    assert marker.read_text(encoding="utf-8").splitlines() == ["import", "create"]
    assert await prepared.abort_uncommitted() is True
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
        "dispose",
    ]


def test_component_host_rechecks_current_authority_before_factory_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_rechecks_current_authority_before_factory_execution(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_rechecks_current_authority_before_factory_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, returned_facet="query")
    current_owner = [fixture.owner_snapshot]
    journal = _journal(tmp_path)
    host = _host(
        journal,
        fixture,
        owner_snapshot_reader=lambda _capability_id: current_owner[0],
    )
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    current_owner[0] = _authority(
        fixture.resolved.definition,
        revocation_epoch=4,
    ).snapshot()
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )

    with pytest.raises(CapabilityGraphBindingError):
        await RuntimeCapabilityGraphBinder().bind(
            runtime,
            fixture.plan,
            (prepared.binding,),
        )

    assert marker.exists() is False
    assert await prepared.abort_uncommitted() is True
    assert journal.snapshot().activation_uses[0].state == "CANCELLED_BEFORE_START"


def test_component_host_bootstrap_recovers_possibly_started_activation(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, returned_facet="query")
    journal = _journal(tmp_path)
    first_host = _host(journal, fixture)
    subject = first_host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    first_host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    [reservation] = journal.snapshot().activation_uses
    journal.transition_activation_use(
        reservation.activation_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=150,
        expected_journal_revision=2,
    )

    _host(
        journal,
        fixture,
        host_boot_id="8" * 32,
        import_realm_id="9" * 32,
    )

    assert journal.snapshot().activation_uses[0].state == "FAILED"


def test_component_host_rechecks_decision_expiry_at_factory_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _component_host_rechecks_decision_expiry_at_factory_boundary(
            tmp_path,
            monkeypatch,
        )
    )


async def _component_host_rechecks_decision_expiry_at_factory_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "activation.log"
    monkeypatch.setenv("LOUSHANG_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, returned_facet="query")
    now = [150]
    identities = iter(("1" * 48, "2" * 48))
    journal = PluginActivationDecisionJournal(
        tmp_path / "activation.jsonl",
        scope_id="workspace:test",
        identity_factory=lambda: next(identities),
        clock=lambda: now[0],
    )
    host = CapabilityComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(import_realm_id_factory=lambda: "4" * 32),
        host_boot_id="3" * 32,
        clock=lambda: now[0],
        owner_snapshot_reader=lambda _capability_id: fixture.owner_snapshot,
        trust_snapshot_reader=(
            lambda _plugin_id, _source_identity: fixture.trust_snapshot
        ),
        product_policy_revision_reader=(
            lambda _product_id, _scope_id: "coding-plugin-policy-1"
        ),
    )
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    decision = _approve(journal, subject)
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    now[0] = 301
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint="f" * 64,
    )

    with pytest.raises(CapabilityGraphBindingError):
        await RuntimeCapabilityGraphBinder().bind(
            runtime,
            fixture.plan,
            (prepared.binding,),
        )

    assert marker.exists() is False
    assert await prepared.abort_uncommitted() is True


@dataclass(frozen=True)
class _Fixture:
    package: PublishedPluginPackage
    resolved: ResolvedCapabilityProvider
    owner_snapshot: CapabilityProviderOwnerSnapshot
    trust_snapshot: PluginSourceTrustSnapshotV1
    plan: RuntimeCapabilityGraphPlan


def _author_guide_fixture(
    tmp_path: Path,
    *,
    definition_source: str,
    provider_source: str,
) -> tuple[_Fixture, PluginRuntimeResolution]:
    plugin_id = "author-guide"
    contribution_id = "echo-provider"
    root = tmp_path / "author-guide-plugin"
    root.mkdir()
    (root / "definition.py").write_text(definition_source, encoding="utf-8")
    (root / "provider.py").write_text(provider_source, encoding="utf-8")
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "1",
                "contributionIndex": {
                    "version": 2,
                    "items": [
                        {
                            "id": contribution_id,
                            "kind": "capability_provider",
                            "owner": "example.echo",
                            "contributionExecutionModel": "in_process",
                            "declarationSource": {
                                "entrypoint": "definition.py:declare",
                                "kind": "in_process",
                                "sourceVersion": 1,
                            },
                            "requestedAuthorities": [],
                            "configuration": {},
                            "required": True,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    resolution_authority = PluginResolutionAuthority()
    inspection = resolution_authority.inspect(PluginSource(path=root))
    plugin_runtime = resolution_authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=tmp_path / "author-guide-installed",
            plugin_revision_root=tmp_path / "author-guide-revisions",
        ),
    )
    [package] = plugin_runtime.packages
    [source_binding] = plugin_runtime.bindings
    [contribution] = package.contribution_index.items
    trust_snapshot = PluginSourceTrustSnapshotV1(
        plugin_id=plugin_id,
        package_source_identity=source_binding.source_identity,
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        trusted=True,
    )
    selection_plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="example",
            scope_id="workspace:test",
            policy_revision="coding-plugin-policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{plugin_id}@workspace:test",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=(
            PluginContributionRef(plugin_id, contribution_id),
        ),
        source_trust_snapshots=(trust_snapshot,),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=contribution_id,
                    configuration={},
                ),
            )
        ),
        allowed_authority_ceiling=(),
    )
    selection_resolver = PluginSelectionResolver()
    execution_journal = PluginExecutionDecisionJournal(
        tmp_path / "author-guide-execution.jsonl",
        scope_kind="workspace",
        scope_id="workspace:test",
        decision_id_factory=lambda: "a" * 48,
        execution_use_id_factory=lambda: "b" * 48,
        clock=lambda: 2_500,
    )
    pending = selection_resolver.preflight(
        (package,),
        bindings=(source_binding,),
        plan=selection_plan,
        decision_lookup=execution_journal,
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [execution_subject] = pending.subjects
    execution_journal.issue_execution_decision(
        execution_subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:author-guide",
            source="component-host-test",
        ),
        revocation_epoch=0,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=5_000,
        expected_journal_revision=0,
    )
    accepted = selection_resolver.preflight(
        (package,),
        bindings=(source_binding,),
        plan=selection_plan,
        decision_lookup=execution_journal,
    )
    assert isinstance(accepted, PluginPreflightAcceptedOutcome)
    selection = PluginDeclarationCoordinator(
        selection_resolver,
        execution_evaluator=PluginDefinitionEvaluator(
            decision_journal=execution_journal,
            import_realm=PluginDefinitionImportRealm(
                import_realm_id_factory=lambda: "c" * 32
            ),
            clock=lambda: 2_500,
        ),
    ).finalize(accepted.accepted)
    [selected] = selection.candidates
    definition = CapabilityDefinition(
        capability_id="example.echo",
        owner_id="example",
        contract_version=1,
        facets=("echo",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )
    candidate = prepare_capability_provider_candidate(
        selection,
        selected,
        definition=definition,
    )
    owner_authority = CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision="coding-owner-1",
            revocation_epoch=3,
            allowed_provider_ids=("org.example.echo/default",),
            allowed_source_trust_classes=("host-equivalent-local",),
            authority_ceiling=(),
        )
    )
    eligibility = owner_authority.grant_eligibility(
        candidate,
        issued_at=100,
        expires_at=400,
    )
    admission = owner_authority.admit(
        candidate,
        eligibility=eligibility,
        issued_at=120,
        expires_at=350,
    )
    owner_snapshot = owner_authority.snapshot()
    resolved_set = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id="example",
            roots=(definition.capability_id,),
            choices=(
                ProductCapabilityProviderChoice(
                    capability_id=definition.capability_id,
                    provider_id=candidate.provider.provider_id,
                    candidate_fingerprint=admission.candidate_fingerprint,
                ),
            ),
            policy_revision="coding-plugin-policy-1",
        ),
        definitions=(definition,),
        admissions=(admission,),
        owner_snapshots=(owner_snapshot,),
        evaluated_at=150,
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="example",
            roots=resolved_set.roots,
            definitions=(definition,),
            providers=resolved_set.providers,
        )
    )
    assert contribution.contribution_id == contribution_id
    return (
        _Fixture(
            package=package,
            resolved=resolved_set.entries[0],
            owner_snapshot=owner_snapshot,
            trust_snapshot=trust_snapshot,
            plan=plan,
        ),
        plugin_runtime,
    )


def _fixture(
    tmp_path: Path,
    *,
    returned_facet: str,
    disposer_fails_once: bool = False,
    declared_facet: str = "query",
    provider_source: str | None = None,
) -> _Fixture:
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "foundation-sample"}),
        encoding="utf-8",
    )
    (root / "provider.py").write_text(
        provider_source
        if provider_source is not None
        else _provider_source(
            returned_facet,
            disposer_fails_once=disposer_fails_once,
        ),
        encoding="utf-8",
    )
    verified = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(root)
    )
    package = PublishedPluginPackage.from_verified_revision(
        verified,
        dependency_lock=lock_plugin_dependency_closure(
            package_content_digest=verified.content_digest,
            installed_distributions=(),
        ),
    )
    definition = CapabilityDefinition(
        capability_id="coding.semantic",
        owner_id="coding",
        contract_version=1,
        facets=(declared_facet,),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )
    provider = CapabilityBundleProvider(
        capability_id=definition.capability_id,
        provider_id="org.loushang.synthetic/default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=(declared_facet,),
        source_id="plugin:foundation-sample",
        selection_rule="Product exact Plugin choice",
    )
    candidate = CapabilityProviderCandidateEnvelope(
        definition=definition,
        provider=provider,
        binding_spec=CapabilityProviderBindingSpec(
            plugin_id="foundation-sample",
            contribution_id="semantic-provider",
            package_content_digest=package.content_digest,
            dependency_lock_digest=package.dependency_lock.digest,
            factory=CapabilityProviderSymbolLocator(
                path="provider.py",
                symbol="create_provider",
                execution_model="in_process",
            ),
            disposer=CapabilityProviderSymbolLocator(
                path="provider.py",
                symbol="dispose_provider",
                execution_model="in_process",
            ),
            binding_inputs={"label": "foundation"},
        ),
        plugin_candidate_fingerprint="1" * 64,
        declaration_fingerprint="2" * 64,
        declaration_evidence_fingerprint="3" * 64,
        product_id="coding",
        scope_id="workspace:test",
        product_policy_revision="coding-plugin-policy-1",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="foundation-sample@workspace:test",
            plugin_id="foundation-sample",
            revision=1,
        ),
        package_source_identity="local:foundation-sample",
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        source_trusted=True,
        allowed_authority_ceiling=(),
    )
    authority = _authority(definition, revocation_epoch=3)
    eligibility = authority.grant_eligibility(
        candidate,
        issued_at=100,
        expires_at=400,
    )
    admission = authority.admit(
        candidate,
        eligibility=eligibility,
        issued_at=120,
        expires_at=350,
    )
    owner_snapshot = authority.snapshot()
    choice = ProductCapabilityProviderChoice(
        capability_id=definition.capability_id,
        provider_id=provider.provider_id,
        candidate_fingerprint=admission.candidate_fingerprint,
    )
    resolved_set = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id="coding",
            roots=(definition.capability_id,),
            choices=(choice,),
            policy_revision="coding-plugin-policy-1",
        ),
        definitions=(definition,),
        admissions=(admission,),
        owner_snapshots=(owner_snapshot,),
        evaluated_at=150,
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=resolved_set.roots,
            definitions=(definition,),
            providers=resolved_set.providers,
        )
    )
    return _Fixture(
        package=package,
        resolved=resolved_set.entries[0],
        owner_snapshot=owner_snapshot,
        trust_snapshot=PluginSourceTrustSnapshotV1(
            plugin_id="foundation-sample",
            package_source_identity="local:foundation-sample",
            source_trust_class="host-equivalent-local",
            source_trust_policy_revision="trust-1",
            trusted=True,
        ),
        plan=plan,
    )


def _authority(
    definition: CapabilityDefinition,
    *,
    revocation_epoch: int,
) -> CapabilityProviderOwnerAuthority:
    return CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision="coding-owner-1",
            revocation_epoch=revocation_epoch,
            allowed_provider_ids=("org.loushang.synthetic/default",),
            allowed_source_trust_classes=("host-equivalent-local",),
            authority_ceiling=(),
        )
    )


def _host(
    journal: PluginActivationDecisionJournal,
    fixture: _Fixture,
    *,
    owner_snapshot_reader=None,  # type: ignore[no-untyped-def]
    host_boot_id: str = "3" * 32,
    import_realm_id: str = "4" * 32,
) -> CapabilityComponentHost:
    return CapabilityComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(
            import_realm_id_factory=lambda: import_realm_id
        ),
        host_boot_id=host_boot_id,
        clock=lambda: 150,
        owner_snapshot_reader=(
            owner_snapshot_reader
            or (lambda _capability_id: fixture.owner_snapshot)
        ),
        trust_snapshot_reader=(
            lambda _plugin_id, _source_identity: fixture.trust_snapshot
        ),
        product_policy_revision_reader=(
            lambda _product_id, _scope_id: "coding-plugin-policy-1"
        ),
    )


def _journal(tmp_path: Path) -> PluginActivationDecisionJournal:
    identities = iter(("1" * 48, "2" * 48))
    return PluginActivationDecisionJournal(
        tmp_path / "activation.jsonl",
        scope_id="workspace:test",
        identity_factory=lambda: next(identities),
        clock=lambda: 150,
    )


def _approve(journal, subject):  # type: ignore[no-untyped-def]
    return journal.issue_activation_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:test",
            source="component-host-test",
        ),
        issued_at_unix_ms=140,
        expires_at_unix_ms=300,
        expected_journal_revision=0,
    )


def _provider_source(
    returned_facet: str,
    *,
    disposer_fails_once: bool = False,
) -> str:
    return f'''\
import os
import json
from pathlib import Path

from loushang.plugin.provider_runtime import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
)

MARKER = Path(os.environ["LOUSHANG_COMPONENT_TEST_MARKER"])
DISPOSER_FAILS_ONCE = {disposer_fails_once!r}
with MARKER.open("a", encoding="utf-8") as stream:
    stream.write("import\\n")

def create_provider(context):
    journal_path = MARKER.parent / "activation.jsonl"
    records = [json.loads(line) for line in journal_path.read_text(
        encoding="utf-8"
    ).splitlines()]
    if records[-1]["payload"]["reservation"]["state"] != "STARTING":
        raise AssertionError("factory executed outside STARTING state")
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("create\\n")
    return CapabilityBundleValue((CapabilityFacetBinding(
        {returned_facet!r},
        {{
            "label": context.binding_inputs["label"],
            "runtime_id": context.runtime_id,
        }},
    ),))

async def dispose_provider(_value):
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("dispose\\n")
    if (
        DISPOSER_FAILS_ONCE
        and MARKER.read_text(encoding="utf-8").splitlines().count("dispose") == 1
    ):
        raise RuntimeError("synthetic transient disposal failure")
'''
