from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.approval.plugin_activation import (
    OwnerComponentActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationDecisionRecordV1,
    PluginActivationJournalRecordCodecError,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
)
from loushang.harness.capabilities.component_admission import (
    CapabilityComponentCandidate,
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerPolicy,
    CapabilityComponentOwnerSnapshot,
)
from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentBindingSpec,
    CapabilityComponentDefinition,
)
from loushang.harness.capabilities.component_runtime import (
    CapabilityOwnerComponentBinder,
    CapabilityOwnerComponentBindingError,
    CapabilityOwnerComponentRuntime,
)
from loushang.harness.capabilities.component_selection import (
    CapabilityComponentSelectionChoice,
    CapabilityComponentSelectionPlan,
    ProductCapabilityComponentResolver,
    ResolvedCapabilityComponent,
    ResolvedCapabilityComponentSet,
)
from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.capabilities.owner_component_host import (
    CapabilityOwnerComponentHost,
)
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


def test_owner_component_host_defers_import_and_commits_distinct_subject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _owner_component_host_defers_import_and_commits_distinct_subject(
            tmp_path,
            monkeypatch,
        )
    )


async def _owner_component_host_defers_import_and_commits_distinct_subject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "owner-component.log"
    monkeypatch.setenv("LOUSHANG_OWNER_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path)
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    subject = host.activation_subject(
        fixture.resolved,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
    )
    assert isinstance(subject, OwnerComponentActivationApprovalSubject)
    assert subject.subject_kind == "capability_owner_component"
    decision = _approve(journal, subject)
    tampered = json.loads(json.dumps(decision.to_dict()))
    tampered["subject"]["subjectKind"] = "complete_bundle_provider"
    with pytest.raises(PluginActivationJournalRecordCodecError):
        PluginActivationDecisionRecordV1.from_dict(tampered)

    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )

    assert not marker.exists()
    assert journal.snapshot().activation_uses[0].state == "CONSUMED_NOT_STARTED"
    runtime = _runtime()
    binder = CapabilityOwnerComponentBinder()
    result = await binder.bind(runtime, fixture.resolved_set, (prepared.binding,))

    assert result.snapshot.generation == 1
    assert journal.snapshot().activation_uses[0].state == "STARTED"
    prepared.commit_after_owner_generation_publication()
    lease = runtime.capture_one("resource.source")
    assert lease.require() == {
        "label": "foundation",
        "runtime_id": "session:test",
    }
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
    ]
    assert journal.snapshot().activation_uses[0].state == "COMMITTED"

    assert await binder.dispose(runtime) == ()
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
    ]
    assert await lease.aclose() == ()
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
        "dispose:foundation",
    ]

    replayed = PluginActivationDecisionJournal(
        journal.path,
        scope_id="workspace:test",
        clock=lambda: 150,
    ).snapshot()
    assert replayed.decisions[0].subject == subject


def test_owner_component_host_disposes_invalid_payload_and_records_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _owner_component_host_disposes_invalid_payload_and_records_failure(
            tmp_path,
            monkeypatch,
        )
    )


async def _owner_component_host_disposes_invalid_payload_and_records_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "owner-component.log"
    monkeypatch.setenv("LOUSHANG_OWNER_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, invalid_payload=True)
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    decision = _approve(
        journal,
        host.activation_subject(
            fixture.resolved,
            owner_snapshot=fixture.owner_snapshot,
            trust_snapshot=fixture.trust_snapshot,
        ),
    )
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )

    with pytest.raises(CapabilityOwnerComponentBindingError) as failed:
        await CapabilityOwnerComponentBinder().bind(
            _runtime(),
            fixture.resolved_set,
            (prepared.binding,),
        )

    assert failed.value.diagnostic_codes == ("component_construction_failed",)
    assert journal.snapshot().activation_uses[0].state == "FAILED"
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create",
        "dispose:invalid",
    ]


def test_owner_component_host_revalidates_authority_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_owner_component_host_revalidates_authority_before_import(tmp_path, monkeypatch))


async def _owner_component_host_revalidates_authority_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "owner-component.log"
    monkeypatch.setenv("LOUSHANG_OWNER_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path)
    journal = _journal(tmp_path)
    current_owner = [fixture.owner_snapshot]
    host = _host(
        journal,
        fixture,
        owner_snapshot_reader=lambda _capability, _kind: current_owner[0],
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
    current_owner[0] = _owner_snapshot(fixture, revocation_epoch=4)

    with pytest.raises(CapabilityOwnerComponentBindingError):
        await CapabilityOwnerComponentBinder().bind(
            _runtime(),
            fixture.resolved_set,
            (prepared.binding,),
        )

    assert not marker.exists()
    assert journal.snapshot().activation_uses[0].state == "CONSUMED_NOT_STARTED"
    assert await prepared.abort_uncommitted() is True
    assert journal.snapshot().activation_uses[0].state == "CANCELLED_BEFORE_START"


def test_owner_component_host_retains_payload_when_started_and_disposal_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _owner_component_host_retains_payload_when_started_and_disposal_fail(
            tmp_path,
            monkeypatch,
        )
    )


async def _owner_component_host_retains_payload_when_started_and_disposal_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "owner-component.log"
    monkeypatch.setenv("LOUSHANG_OWNER_COMPONENT_TEST_MARKER", str(marker))
    fixture = _fixture(tmp_path, disposer_fails_once=True)
    journal = _journal(tmp_path)
    host = _host(journal, fixture)
    decision = _approve(
        journal,
        host.activation_subject(
            fixture.resolved,
            owner_snapshot=fixture.owner_snapshot,
            trust_snapshot=fixture.trust_snapshot,
        ),
    )
    prepared = host.prepare_component(
        fixture.resolved,
        package=fixture.package,
        owner_snapshot=fixture.owner_snapshot,
        trust_snapshot=fixture.trust_snapshot,
        decision_id=decision.decision_id,
    )
    original_transition = journal.transition_activation_use

    def fail_started(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("target_state") == "STARTED":
            raise RuntimeError("synthetic STARTED persistence failure")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(journal, "transition_activation_use", fail_started)

    with pytest.raises(CapabilityOwnerComponentBindingError):
        await CapabilityOwnerComponentBinder().bind(
            _runtime(),
            fixture.resolved_set,
            (prepared.binding,),
        )

    assert journal.snapshot().activation_uses[0].state == "FAILED"
    assert marker.read_text(encoding="utf-8").splitlines().count(
        "dispose:foundation"
    ) == 1
    assert await prepared.abort_uncommitted() is True
    assert marker.read_text(encoding="utf-8").splitlines().count(
        "dispose:foundation"
    ) == 2


@dataclass(frozen=True)
class _Fixture:
    package: PublishedPluginPackage
    resolved: ResolvedCapabilityComponent
    resolved_set: ResolvedCapabilityComponentSet
    authority: CapabilityComponentOwnerAuthority
    owner_snapshot: CapabilityComponentOwnerSnapshot
    trust_snapshot: PluginSourceTrustSnapshotV1


def _fixture(
    tmp_path: Path,
    *,
    invalid_payload: bool = False,
    disposer_fails_once: bool = False,
) -> _Fixture:
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "foundation-source"}),
        encoding="utf-8",
    )
    (root / "source.py").write_text(
        _component_source(
            invalid_payload=invalid_payload,
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
    definition = CapabilityComponentDefinition(
        capability_id="harness.resources",
        owner_id="harness",
        component_kind="resource.source",
        payload_schema_id="loushang.resource.source/v1",
        payload_schema_version=1,
        compatible_bundle_contract=CapabilityContractRange.exact(1),
        multiplicity="aggregate",
        selection_policy="ordered_unique",
        minimum_count=1,
        maximum_count=None,
        disposer_contract="required",
    )
    authority = CapabilityComponentOwnerAuthority(
        definition,
        CapabilityComponentOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            component_kind=definition.component_kind,
            policy_revision="resources-owner-v1",
            revocation_epoch=3,
            allowed_component_ids=("foundation.source",),
            allowed_source_trust_classes=("host-equivalent-local",),
        ),
    )
    instance_ref = PluginInstanceRevisionRef(
        instance_id="foundation-source@workspace:test",
        plugin_id="foundation-source",
        revision=1,
    )
    candidate = CapabilityComponentCandidate(
        definition=definition,
        component_id="foundation.source",
        binding_spec=CapabilityComponentBindingSpec(
            source_kind="plugin",
            source_id="foundation-source",
            contribution_id="resource-source",
            source_revision_ref="foundation-source@1",
            content_digest=package.content_digest,
            plugin_id="foundation-source",
            dependency_lock_digest=package.dependency_lock.digest,
            factory_path="source.py",
            factory_symbol="create_source",
            disposer_path="source.py",
            disposer_symbol="dispose_source",
            binding_inputs={"label": "foundation"},
        ),
        product_id="coding",
        scope_id="workspace:test",
        product_policy_revision="coding-plugin-policy-1",
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        source_trusted=True,
        package_source_identity="local:foundation-source",
        instance_revision_ref=instance_ref,
    )
    admission = authority.admit(candidate, issued_at=120, expires_at=350)
    plan = CapabilityComponentSelectionPlan(
        product_id="coding",
        scope_id="workspace:test",
        capability_id="harness.resources",
        owner_id="harness",
        product_policy_revision="coding-plugin-policy-1",
        choices=(
            CapabilityComponentSelectionChoice(
                component_kind="resource.source",
                admission_fingerprints=(admission.fingerprint,),
            ),
        ),
    )
    resolved_set = ProductCapabilityComponentResolver().resolve(
        plan,
        definitions=(definition,),
        admissions=(admission,),
        owner_snapshots=(authority.snapshot(),),
        now=150,
    )
    return _Fixture(
        package=package,
        resolved=resolved_set.components[0],
        resolved_set=resolved_set,
        authority=authority,
        owner_snapshot=authority.snapshot(),
        trust_snapshot=PluginSourceTrustSnapshotV1(
            plugin_id="foundation-source",
            package_source_identity="local:foundation-source",
            source_trust_class="host-equivalent-local",
            source_trust_policy_revision="trust-1",
            trusted=True,
        ),
    )


def _host(
    journal: PluginActivationDecisionJournal,
    fixture: _Fixture,
    *,
    owner_snapshot_reader=None,  # type: ignore[no-untyped-def]
) -> CapabilityOwnerComponentHost:
    def validate_payload(payload: object) -> None:
        if not isinstance(payload, dict) or set(payload) != {"label", "runtime_id"}:
            raise TypeError("invalid Resource source payload")

    return CapabilityOwnerComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(import_realm_id_factory=lambda: "4" * 32),
        host_boot_id="3" * 32,
        clock=lambda: 150,
        owner_snapshot_reader=(
            owner_snapshot_reader
            or (lambda _capability, _kind: fixture.owner_snapshot)
        ),
        trust_snapshot_reader=lambda _plugin, _source: fixture.trust_snapshot,
        product_policy_revision_reader=(
            lambda _product, _scope: "coding-plugin-policy-1"
        ),
        payload_validator_reader=lambda _definition: validate_payload,
    )


def _journal(tmp_path: Path) -> PluginActivationDecisionJournal:
    identities = iter(("1" * 48, "2" * 48))
    return PluginActivationDecisionJournal(
        tmp_path / "owner-component-activation.jsonl",
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
            source="owner-component-host-test",
        ),
        issued_at_unix_ms=140,
        expires_at_unix_ms=300,
        expected_journal_revision=0,
    )


def _runtime() -> CapabilityOwnerComponentRuntime:
    return CapabilityOwnerComponentRuntime(
        capability_id="harness.resources",
        owner_id="harness",
        product_id="coding",
        runtime_id="session:test",
    )


def _owner_snapshot(
    fixture: _Fixture,
    *,
    revocation_epoch: int,
) -> CapabilityComponentOwnerSnapshot:
    policy = fixture.authority.policy
    return CapabilityComponentOwnerAuthority(
        fixture.authority.definition,
        CapabilityComponentOwnerPolicy(
            capability_id=policy.capability_id,
            owner_id=policy.owner_id,
            component_kind=policy.component_kind,
            policy_revision=policy.policy_revision,
            revocation_epoch=revocation_epoch,
            allowed_component_ids=policy.allowed_component_ids,
            allowed_source_trust_classes=policy.allowed_source_trust_classes,
            authority_ceiling=policy.authority_ceiling,
        ),
    ).snapshot()


def _component_source(
    *,
    invalid_payload: bool,
    disposer_fails_once: bool,
) -> str:
    payload = "'invalid'" if invalid_payload else (
        "{'label': context.binding_inputs['label'], "
        "'runtime_id': context.runtime_id}"
    )
    return f'''\
import json
import os
from pathlib import Path

MARKER = Path(os.environ["LOUSHANG_OWNER_COMPONENT_TEST_MARKER"])
DISPOSER_FAILS_ONCE = {disposer_fails_once!r}
with MARKER.open("a", encoding="utf-8") as stream:
    stream.write("import\\n")

def create_source(context):
    journal_path = MARKER.parent / "owner-component-activation.jsonl"
    records = [json.loads(line) for line in journal_path.read_text(
        encoding="utf-8"
    ).splitlines()]
    if records[-1]["payload"]["reservation"]["state"] != "STARTING":
        raise AssertionError("factory executed outside STARTING state")
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("create\\n")
    return {payload}

def dispose_source(payload):
    label = payload if isinstance(payload, str) else payload["label"]
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write(f"dispose:{{label}}\\n")
    if (
        DISPOSER_FAILS_ONCE
        and MARKER.read_text(encoding="utf-8").splitlines().count(
            f"dispose:{{label}}"
        ) == 1
    ):
        raise RuntimeError("synthetic transient disposal failure")
'''
