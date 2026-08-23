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
from loushang.harness.resources.plugins.dependencies import (
    lock_plugin_dependency_closure,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage


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


def _fixture(
    tmp_path: Path,
    *,
    returned_facet: str,
    disposer_fails_once: bool = False,
) -> _Fixture:
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "foundation-sample"}),
        encoding="utf-8",
    )
    (root / "provider.py").write_text(
        _provider_source(
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
        facets=("query",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )
    provider = CapabilityBundleProvider(
        capability_id=definition.capability_id,
        provider_id="org.loushang.synthetic/default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=("query",),
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
from pathlib import Path

from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
)

MARKER = Path(os.environ["LOUSHANG_COMPONENT_TEST_MARKER"])
DISPOSER_FAILS_ONCE = {disposer_fails_once!r}
with MARKER.open("a", encoding="utf-8") as stream:
    stream.write("import\\n")

def create_provider(context):
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("create\\n")
    return CapabilityBundleValue((CapabilityFacetBinding(
        {returned_facet!r},
        {{
            "label": context.binding_inputs["label"],
            "runtime_id": context.runtime_id,
        }},
    ),))

def dispose_provider(_value):
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("dispose\\n")
    if (
        DISPOSER_FAILS_ONCE
        and MARKER.read_text(encoding="utf-8").splitlines().count("dispose") == 1
    ):
        raise RuntimeError("synthetic transient disposal failure")
'''
