from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.continuity as coding_continuity_module
from loushang.coding.continuity import (
    CodingContinuityComposition,
    bind_coding_plugin_continuity,
    shutdown_coding_continuity,
)
from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
)
from loushang.harness.capabilities.component_admission import (
    CapabilityComponentAdmissionError,
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerPolicy,
)
from loushang.harness.capabilities.owner_component_host import (
    CapabilityOwnerComponentHost,
)
from loushang.harness.continuity import (
    ContinuityPreview,
    ContinuityQuery,
    consume_prepared_activation,
)
from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
    ContinuityProviderDeclarationPayload,
    continuity_provider_component_id,
    prepare_continuity_provider_component_candidate,
    validate_continuity_provider_component_payload,
)
from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginGenerationAuthority,
    ContinuityPluginInstanceFamilyLease,
    ContinuityPluginLifecycleError,
    ResolvedContinuityPluginSelection,
    construct_continuity_plugin_generation,
    resolve_continuity_plugin_selection,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PluginSymbolReference,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_authoring.semantic_fingerprint import (
    compile_plugin_contribution_semantic_fingerprint,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
    PluginInstanceLedgerContinuityFamilyAuthority,
    PluginInstanceLedgerContinuitySecurityRetirementAuthority,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceRevocationV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
    PluginInstanceRuntimeSnapshotV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import (
    PluginManagementAction,
    PluginManagementCommandV1,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredState,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.transcript import SessionIndexPage


@dataclass(frozen=True, slots=True)
class _ContinuityPlugin:
    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    payload: ContinuityProviderDeclarationPayload


@dataclass(frozen=True, slots=True)
class _RealPluginLifecycle:
    desired: PluginDesiredStateLedger
    intents: PluginRetirementIntentLedger
    sets: PluginRetirementSetLedger
    service: PluginManagementService
    runtime: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger
    security_acceptances: PluginContinuitySecurityRetirementJournal
    active: PluginInstanceRuntimeSnapshotV1


@pytest.fixture
def continuity_plugin(tmp_path: Path) -> Iterator[_ContinuityPlugin]:
    root = tmp_path / "source" / "continuity-example"
    declarations = root / "declarations"
    declarations.mkdir(parents=True)
    item = {
        "configuration": {"endpoint": "https://sessions.invalid"},
        "contributionExecutionModel": "in_process",
        "declarationSource": {
            "kind": "document",
            "locator": "declarations/continuity.json",
            "mediaType": "application/vnd.loushang.plugin-declarations+json",
            "schemaId": "loushang.plugin-declaration-document",
            "schemaVersion": 1,
            "sourceVersion": 1,
        },
        "id": "remote-sessions",
        "kind": "continuity_provider",
        "owner": "harness.continuity",
        "requestedAuthorities": ["network.read"],
        "required": True,
    }
    contribution = PluginContributionReservation.from_dict(item)
    payload = ContinuityProviderDeclarationPayload(
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            execution_model="in_process",
        ),
        binding_inputs={"endpoint": "https://sessions.invalid"},
    )
    declaration = PluginDeclaration(
        plugin_id="continuity-example",
        contribution_id=contribution.contribution_id,
        kind=contribution.kind,
        owner=contribution.owner,
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=(contribution.source_descriptor_fingerprint),
        source_kind=contribution.declaration_source.kind,
        payload=payload.to_dict(),
    )
    (declarations / "continuity.json").write_bytes(
        PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(declarations=(declaration,))
        )
    )
    (root / "provider.py").write_text(
        _provider_source(),
        encoding="utf-8",
    )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "continuity-example",
                "version": "1",
                "contributionIndex": {"items": [item], "version": 2},
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    try:
        yield _ContinuityPlugin(
            runtime=runtime,
            package=package,
            binding=binding,
            contribution=contribution,
            payload=payload,
        )
    finally:
        runtime.close()


def test_continuity_payload_codec_is_strict_and_requires_disposal() -> None:
    payload = _payload()

    assert ContinuityProviderDeclarationPayload.from_dict(payload.to_dict()) == payload
    assert len(payload.fingerprint) == 64
    with pytest.raises(TypeError):
        ContinuityProviderDeclarationPayload(
            factory=payload.factory,
            disposer=None,  # type: ignore[arg-type]
        )

    unknown = deepcopy(payload.to_dict())
    unknown["factoryCallback"] = "forged"
    with pytest.raises(PluginDeclarationCodecError) as caught:
        ContinuityProviderDeclarationPayload.from_dict(unknown)
    assert caught.value.code == "plugin_declaration_field_set_mismatch"

    unsupported = deepcopy(payload.to_dict())
    unsupported["payloadVersion"] = 2
    with pytest.raises(PluginDeclarationCodecError) as caught:
        ContinuityProviderDeclarationPayload.from_dict(unsupported)
    assert (
        caught.value.code
        == "unsupported_continuity_provider_declaration_payload_version"
    )


def test_finalized_selection_compiles_complete_owner_candidate(
    continuity_plugin: _ContinuityPlugin,
) -> None:
    selection = _selection(continuity_plugin)
    [plugin_candidate] = selection.candidates

    payload = ContinuityProviderDeclarationPayload.from_finalized_candidate(
        selection,
        plugin_candidate,
    )
    candidate = prepare_continuity_provider_component_candidate(
        selection,
        plugin_candidate,
    )

    assert payload == continuity_plugin.payload
    assert candidate.definition == CONTINUITY_PROVIDER_COMPONENT_DEFINITION
    assert candidate.component_id == continuity_provider_component_id(
        "continuity-example",
        "remote-sessions",
    )
    assert candidate.binding_spec.source_kind == "plugin"
    assert candidate.candidate_version == 2
    assert candidate.to_dict()["candidateVersion"] == 2
    assert candidate.to_dict()["pluginCandidateFingerprint"] == (
        plugin_candidate.fingerprint
    )
    assert candidate.binding_spec.factory_path == "provider.py"
    assert candidate.binding_spec.disposer_symbol == "dispose_provider"
    assert candidate.plugin_candidate_fingerprint == plugin_candidate.fingerprint
    assert candidate.declaration_fingerprint == plugin_candidate.declaration.fingerprint
    assert (
        candidate.declaration_evidence_fingerprint
        == plugin_candidate.evidence.fingerprint
    )
    assert candidate.allowed_authority_ceiling == ("network.read",)
    assert candidate.requested_authorities == ("network.read",)

    semantic = compile_plugin_contribution_semantic_fingerprint(
        plugin_candidate.declaration
    ).to_dict()
    assert semantic["kind"] == "continuity_provider"
    assert semantic["payloadSchema"] == {
        "id": "harness.continuity.continuity-provider",
        "version": 1,
    }


def test_compiler_rejects_candidate_outside_selection(
    continuity_plugin: _ContinuityPlugin,
) -> None:
    selection = _selection(continuity_plugin)
    other = replace(selection, candidates=())

    with pytest.raises(CapabilityComponentAdmissionError) as caught:
        prepare_continuity_provider_component_candidate(
            other,
            selection.candidates[0],
        )
    assert caught.value.code == "invalid_continuity_provider_declaration"


def test_compiler_rejects_effective_configuration_drift(
    continuity_plugin: _ContinuityPlugin,
) -> None:
    selection = _selection(
        continuity_plugin,
        configuration={"endpoint": "https://changed.invalid"},
    )

    with pytest.raises(CapabilityComponentAdmissionError) as caught:
        prepare_continuity_provider_component_candidate(
            selection,
            selection.candidates[0],
        )
    assert caught.value.code == "invalid_continuity_provider_declaration"


@pytest.mark.parametrize("candidate_count", (0, 2))
def test_owner_resolution_rejects_forged_final_candidate_set(
    continuity_plugin: _ContinuityPlugin,
    candidate_count: int,
) -> None:
    selection = _selection(continuity_plugin)
    forged = replace(
        selection,
        candidates=(selection.candidates[0],) * candidate_count,
    )

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        resolve_continuity_plugin_selection(
            forged,
            owner_authority=_owner_authority(
                continuity_provider_component_id(
                    "continuity-example",
                    "remote-sessions",
                )
            ),
            issued_at=100,
            expires_at=300,
            now=150,
        )
    assert caught.value.code == "continuity_provider_selection_mismatch"


def test_installed_plugin_traverses_owner_generation_and_product_bridge(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _installed_plugin_traverses_owner_generation_and_product_bridge(
            continuity_plugin,
            tmp_path,
            monkeypatch,
        )
    )


def test_real_generation_security_revoke_hands_off_package_cleanup(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _real_generation_security_revoke_hands_off_package_cleanup(
            continuity_plugin,
            tmp_path,
            monkeypatch,
        )
    )


def test_owner_generation_reservation_rejects_concurrent_construction(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _owner_generation_reservation_rejects_concurrent_construction(
            continuity_plugin,
            tmp_path,
            monkeypatch,
        )
    )


def test_owner_generation_authority_reopens_after_construction_rollback(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _owner_generation_authority_reopens_after_construction_rollback(
            continuity_plugin,
            tmp_path,
            monkeypatch,
        )
    )


async def _owner_generation_authority_reopens_after_construction_rollback(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LOUSHANG_CONTINUITY_PLUGIN_MARKER",
        str(tmp_path / "rollback-continuity-plugin.log"),
    )
    selection = _selection(continuity_plugin)
    component_id = continuity_provider_component_id(
        "continuity-example",
        "remote-sessions",
    )
    resolved, host, _journal, decisions = _owner_runtime_inputs(
        selection=selection,
        authority=_owner_authority(component_id),
        component_id=component_id,
        tmp_path=tmp_path,
    )
    generation_authority = ContinuityPluginGenerationAuthority(
        product_id="coding",
        runtime_id="coding-process:rollback",
    )
    families = _FailOnceFamilyAuthority()

    with pytest.raises(RuntimeError, match="synthetic family acquisition failure"):
        await construct_continuity_plugin_generation(
            resolved,
            component_host=host,
            activation_decision_ids=decisions,
            instance_family_authority=families,
            generation_authority=generation_authority,
        )
    generation = await construct_continuity_plugin_generation(
        resolved,
        component_host=host,
        activation_decision_ids=decisions,
        instance_family_authority=families,
        generation_authority=generation_authority,
    )
    await generation.dispose()


async def _owner_generation_reservation_rejects_concurrent_construction(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "concurrent-continuity-plugin.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    selection = _selection(continuity_plugin)
    component_id = continuity_provider_component_id(
        "continuity-example",
        "remote-sessions",
    )
    resolved, host, _journal, decisions = _owner_runtime_inputs(
        selection=selection,
        authority=_owner_authority(component_id),
        component_id=component_id,
        tmp_path=tmp_path,
    )
    families = _BlockingFamilyAuthority()
    generation_authority = ContinuityPluginGenerationAuthority(
        product_id="coding",
        runtime_id="coding-process:concurrent",
    )
    first = asyncio.create_task(
        construct_continuity_plugin_generation(
            resolved,
            component_host=host,
            activation_decision_ids=decisions,
            instance_family_authority=families,
            generation_authority=generation_authority,
        )
    )
    await families.started.wait()

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await construct_continuity_plugin_generation(
            resolved,
            component_host=host,
            activation_decision_ids=decisions,
            instance_family_authority=families,
            generation_authority=generation_authority,
        )
    assert caught.value.code == "continuity_provider_generation_already_reserved"

    families.allow.set()
    generation = await first
    assert families.acquire_calls == 1
    await generation.dispose()
    (
        replacement_resolved,
        replacement_host,
        _replacement_journal,
        replacement_decisions,
    ) = _owner_runtime_inputs(
        selection=selection,
        authority=_owner_authority(component_id),
        component_id=component_id,
        tmp_path=tmp_path / "replacement",
    )
    replacement = await construct_continuity_plugin_generation(
        replacement_resolved,
        component_host=replacement_host,
        activation_decision_ids=replacement_decisions,
        instance_family_authority=families,
        generation_authority=generation_authority,
    )
    assert families.acquire_calls == 2
    await replacement.dispose()


def test_coding_rejects_foreign_product_continuity_selection(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
) -> None:
    asyncio.run(
        _coding_rejects_foreign_product_continuity_selection(
            continuity_plugin,
            tmp_path,
        )
    )


async def _coding_rejects_foreign_product_continuity_selection(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
) -> None:
    selection = _selection(continuity_plugin)
    component_id = continuity_provider_component_id(
        "continuity-example",
        "remote-sessions",
    )
    resolved, host, _journal, decisions = _owner_runtime_inputs(
        selection=selection,
        authority=_owner_authority(component_id),
        component_id=component_id,
        tmp_path=tmp_path,
    )
    foreign_set = object.__new__(type(resolved.resolved_set))
    for name in resolved.resolved_set.__dataclass_fields__:
        object.__setattr__(
            foreign_set,
            name,
            (
                "design"
                if name == "product_id"
                else getattr(resolved.resolved_set, name)
            ),
        )
    foreign = object.__new__(ResolvedContinuityPluginSelection)
    for name in resolved.__dataclass_fields__:
        object.__setattr__(
            foreign,
            name,
            foreign_set if name == "resolved_set" else getattr(resolved, name),
        )
    runtime = _CodingRuntime(tmp_path / "sessions")

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await bind_coding_plugin_continuity(
            runtime,
            resolved_plugins=foreign,
            component_host=host,
            activation_decision_ids=decisions,
            instance_family_authority=_FamilyAuthority(),
            runtime_id="coding-process:foreign",
        )
    assert caught.value.code == "continuity_provider_generation_authority_mismatch"
    assert not hasattr(runtime, "_loushang_coding_continuity")


def test_failed_publication_cleanup_stays_runtime_owned_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _failed_publication_cleanup_stays_runtime_owned_for_retry(
            tmp_path,
            monkeypatch,
        )
    )


async def _failed_publication_cleanup_stays_runtime_owned_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _CodingRuntime(tmp_path / "sessions")
    generation = _RetryGeneration()
    resolved_plugins = SimpleNamespace(
        resolved_set=SimpleNamespace(product_id="coding")
    )

    async def construct(*_args: object, **_kwargs: object) -> _RetryGeneration:
        return generation

    def publish(*_args: object, **_kwargs: object) -> object:
        raise ValueError("duplicate Provider metadata")

    monkeypatch.setattr(
        coding_continuity_module,
        "construct_continuity_plugin_generation",
        construct,
    )
    monkeypatch.setattr(
        coding_continuity_module,
        "publish_continuity_plugin_generation",
        publish,
    )

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await bind_coding_plugin_continuity(
            runtime,
            resolved_plugins=resolved_plugins,  # type: ignore[arg-type]
            component_host=object(),  # type: ignore[arg-type]
            activation_decision_ids={},
            instance_family_authority=object(),  # type: ignore[arg-type]
            runtime_id="coding-process:cleanup-retry",
        )
    assert caught.value.code == "coding_continuity_binding_cleanup_retryable"
    assert generation.dispose_calls == 1

    with pytest.raises(RuntimeError, match="already sealed"):
        await bind_coding_plugin_continuity(
            runtime,
            resolved_plugins=resolved_plugins,  # type: ignore[arg-type]
            component_host=object(),  # type: ignore[arg-type]
            activation_decision_ids={},
            instance_family_authority=object(),  # type: ignore[arg-type]
            runtime_id="coding-process:cleanup-retry",
        )

    await shutdown_coding_continuity(runtime)
    assert generation.dispose_calls == 2
    assert not hasattr(runtime, "_loushang_coding_continuity")


def test_shutdown_helper_retains_failed_plugin_composition() -> None:
    asyncio.run(_shutdown_helper_retains_failed_plugin_composition())


async def _shutdown_helper_retains_failed_plugin_composition() -> None:
    runtime = SimpleNamespace()
    publication = _RetryPublication()
    binder = _RetryBinder()
    composition = CodingContinuityComposition(
        binding=object(),  # type: ignore[arg-type]
        binder=binder,  # type: ignore[arg-type]
        hub=object(),  # type: ignore[arg-type]
        plugin_publication=publication,  # type: ignore[arg-type]
        runtime_owned=True,
    )
    setattr(runtime, "_loushang_coding_continuity", composition)

    with pytest.raises(RuntimeError, match="synthetic shutdown failure"):
        await shutdown_coding_continuity(runtime)
    assert getattr(runtime, "_loushang_coding_continuity") is composition
    assert binder.dispose_calls == 0

    await shutdown_coding_continuity(runtime)
    assert publication.shutdown_calls == 2
    assert binder.dispose_calls == 1
    assert not hasattr(runtime, "_loushang_coding_continuity")


async def _real_generation_security_revoke_hands_off_package_cleanup(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "real-security-continuity-plugin.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    selection = _selection(continuity_plugin)
    component_id = continuity_provider_component_id(
        "continuity-example",
        "remote-sessions",
    )
    resolved, host, _activation_journal, activation_decision_ids = (
        _owner_runtime_inputs(
            selection=selection,
            authority=_owner_authority(component_id),
            component_id=component_id,
            tmp_path=tmp_path / "owner-runtime",
        )
    )
    lifecycle = _real_plugin_lifecycle(
        tmp_path / "plugin-lifecycle",
        continuity_plugin,
    )
    family_authority = PluginInstanceLedgerContinuityFamilyAuthority(
        ledger=lifecycle.runtime,
        package_lifecycle=lifecycle.packages,
        security_acceptance_journal=lifecycle.security_acceptances,
    )
    runtime = _CodingRuntime(tmp_path / "sessions")
    composition = await bind_coding_plugin_continuity(
        runtime,
        resolved_plugins=resolved,
        component_host=host,
        activation_decision_ids=activation_decision_ids,
        instance_family_authority=family_authority,
        runtime_id="coding-process:real-security",
        temporary_root=tmp_path / "continuity-temporary",
    )
    publication = composition.plugin_publication
    assert publication is not None
    [family] = publication.generation.instance_families
    active = lifecycle.active
    revocation = PluginInstanceRevocationV1.create(
        installation_key=active.installation_key,
        instance_revision_ref=active.instance_revision_ref,
        operation_id="continuity-real-security-revoke",
        idempotency_key="continuity-real-security-revoke-request",
        authority_reference="security:continuity",
        reason_code="source_revoked",
    )
    retirement = PluginInstanceLedgerContinuitySecurityRetirementAuthority(
        ledger=lifecycle.runtime,
        acceptance_journal=lifecycle.security_acceptances,
        revocations=(revocation,),
    )
    original_handoff = lifecycle.packages.handoff_cleanup_and_release
    handoff_attempts = 0

    def fail_after_first_durable_handoff(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal handoff_attempts
        result = original_handoff(*args, **kwargs)
        handoff_attempts += 1
        if handoff_attempts == 1:
            raise RuntimeError("synthetic post-handoff interruption")
        return result

    monkeypatch.setattr(
        lifecycle.packages,
        "handoff_cleanup_and_release",
        fail_after_first_durable_handoff,
    )

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await publication.security_revoke(retirement=retirement, quiesce_timeout=1.0)
    assert caught.value.code == "continuity_provider_security_cleanup_handoff_retryable"
    assert lifecycle.runtime.snapshot().family(family.family_id) is None
    [durable_cleanup] = lifecycle.packages.snapshot().cleanup_tasks
    assert durable_cleanup.lease_open is True

    await publication.security_revoke(retirement=retirement, quiesce_timeout=1.0)

    instance = lifecycle.runtime.snapshot().instance(active.instance_revision_ref)
    assert instance is not None
    assert instance.state == "REVOKING"
    assert lifecycle.runtime.snapshot().family(family.family_id) is None
    [cleanup] = lifecycle.packages.snapshot().cleanup_tasks
    assert cleanup.task.cleanup_kind == "continuity.owner.security_shutdown"
    assert cleanup.task.coordination_id == revocation.revocation_id
    assert cleanup.lease_open is True
    assert handoff_attempts == 2
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create:https://sessions.invalid",
        "dispose",
    ]
    await shutdown_coding_continuity(runtime)


async def _installed_plugin_traverses_owner_generation_and_product_bridge(
    continuity_plugin: _ContinuityPlugin,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "continuity-plugin.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    selection = _selection(continuity_plugin)
    component_id = continuity_provider_component_id(
        "continuity-example",
        "remote-sessions",
    )
    authority = _owner_authority(component_id)
    await _continue_installed_plugin_scenario(
        selection=selection,
        authority=authority,
        component_id=component_id,
        tmp_path=tmp_path,
        marker=marker,
    )


def _owner_authority(component_id: str) -> CapabilityComponentOwnerAuthority:
    return CapabilityComponentOwnerAuthority(
        CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
        CapabilityComponentOwnerPolicy(
            capability_id="harness.continuity",
            owner_id="harness",
            component_kind="continuity.provider",
            policy_revision="continuity-owner-1",
            revocation_epoch=0,
            allowed_component_ids=(component_id,),
            allowed_source_trust_classes=("host-equivalent-local",),
            authority_ceiling=("network.read",),
        ),
    )


def _real_plugin_lifecycle(
    root: Path,
    plugin: _ContinuityPlugin,
) -> _RealPluginLifecycle:
    root.mkdir(parents=True)
    operation_path = root / "operations.jsonl"
    desired = PluginDesiredStateLedger(
        root / "desired.jsonl",
        instance_id_factory=lambda: "continuity-example@workspace:test",
    )
    intents = PluginRetirementIntentLedger(root / "intents.jsonl")
    sets = PluginRetirementSetLedger(
        root / "sets.jsonl",
        retirement_intents=intents,
    )
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=operation_path,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    runtime_path = root / "instance-runtime.jsonl"
    security_acceptances = (
        PluginContinuitySecurityRetirementJournal.for_instance_runtime(runtime_path)
    )
    runtime = PluginInstanceRuntimeLedger(
        runtime_path,
        management_operation_journal_path=operation_path,
        desired_state=desired,
        retirement_intents=intents,
        retirement_sets=sets,
        security_acceptances=security_acceptances,
    )
    packages = PluginPackageLifecycleLedger(
        root / "packages.jsonl",
        startup_id="continuity-real-security-startup",
        desired_state=desired,
        instance_runtime=runtime,
        retirement_sets=sets,
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:test",
        plugin_id=plugin.package.manifest.name,
    )
    package_revision = PluginPackageRevisionRefV1(
        plugin_id=plugin.package.manifest.name,
        plugin_version=plugin.package.manifest.version,
        package_content_digest=plugin.package.content_digest,
        dependency_lock_digest=plugin.package.dependency_lock.digest,
        package_source_identity=plugin.binding.source_identity,
    )
    for action, revision, operation in (
        ("install", 0, 1),
        ("enable", 1, 2),
    ):
        service.submit(
            _real_lifecycle_command(
                key,
                action,
                package_revision=package_revision,
                revision=revision,
                operation=operation,
            )
        )
    active = runtime.activate_current(
        key,
        operation_id="continuity-real-security-activate",
        idempotency_key="continuity-real-security-activate-request",
        direct_host_reference="host:continuity-real-security",
    )
    return _RealPluginLifecycle(
        desired=desired,
        intents=intents,
        sets=sets,
        service=service,
        runtime=runtime,
        packages=packages,
        security_acceptances=security_acceptances,
        active=active,
    )


def _real_lifecycle_command(
    key: PluginInstallationKeyV1,
    action: PluginManagementAction,
    *,
    package_revision: PluginPackageRevisionRefV1,
    revision: int,
    operation: int,
) -> PluginManagementCommandV1:
    desired_states: dict[PluginManagementAction, PluginDesiredState] = {
        "install": "installed_disabled",
        "enable": "installed_enabled",
        "disable": "installed_disabled",
        "remove": "absent",
    }
    return PluginManagementCommandV1(
        action=action,
        mutation=PluginDesiredStateMutationV1(
            operation_id=f"continuity-real-management-{operation}",
            idempotency_key=f"continuity-real-management-request-{operation}",
            expected_inventory_revision=revision,
            installation_key=key,
            desired_state=desired_states[action],
            package_revision=package_revision if action == "install" else None,
            actor_id="product:coding",
            policy_revision="coding-continuity-policy-1",
        ),
    )


async def _continue_installed_plugin_scenario(
    *,
    selection: PluginSelection,
    authority: CapabilityComponentOwnerAuthority,
    component_id: str,
    tmp_path: Path,
    marker: Path,
) -> None:
    resolved, host, journal, activation_decision_ids = _owner_runtime_inputs(
        selection=selection,
        authority=authority,
        component_id=component_id,
        tmp_path=tmp_path,
    )
    families = _FamilyAuthority()
    runtime = _CodingRuntime(tmp_path / "sessions")
    composition = await bind_coding_plugin_continuity(
        runtime,
        resolved_plugins=resolved,
        component_host=host,
        activation_decision_ids=activation_decision_ids,
        instance_family_authority=families,
        runtime_id="coding-process:test",
        temporary_root=tmp_path / "continuity-temporary",
    )
    assert composition.plugin_publication is not None
    generation = composition.plugin_publication.generation
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create:https://sessions.invalid",
    ]
    assert journal.snapshot().activation_uses[0].state == "COMMITTED"
    assert families.events[0].startswith("acquire:continuity-example@workspace:test")

    assert tuple(
        item.provider.descriptor.provider_id
        for item in composition.hub.composition.continuity_providers
    ) == ("coding.sessions", "continuity.example")
    federated = await composition.hub.query(ContinuityQuery())
    assert [item.title for item in federated.items] == ["Remote session"]
    assert federated.provider_diagnostics == ()

    page = await composition.hub.query(
        ContinuityQuery(provider_ids=("continuity.example",))
    )
    [summary] = page.items
    assert summary.title == "Remote session"
    preview = await composition.hub.preview(summary.target)
    assert isinstance(preview, ContinuityPreview)
    assert preview.heading == "Remote session"

    lease = await composition.hub.prepare(summary.target)
    result = await consume_prepared_activation(lease)
    assert result == {"restored": True}
    assert runtime.prepared_payloads == [b'{"session":"remote-1"}\n']
    [plugin_bound] = [
        item
        for item in composition.hub.composition.continuity_providers
        if item.source.source == "plugin"
    ]
    assert plugin_bound.source.plugin_id == "continuity-example"
    assert plugin_bound.source.source_id == generation.snapshot.generation_fingerprint

    await shutdown_coding_continuity(runtime)
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create:https://sessions.invalid",
        "source-close",
        "dispose",
    ]
    assert families.events[-1].startswith("release:")


def _owner_runtime_inputs(
    *,
    selection: PluginSelection,
    authority: CapabilityComponentOwnerAuthority,
    component_id: str,
    tmp_path: Path,
) -> tuple[
    ResolvedContinuityPluginSelection,
    CapabilityOwnerComponentHost,
    PluginActivationDecisionJournal,
    dict[str, str],
]:
    resolved = resolve_continuity_plugin_selection(
        selection,
        owner_authority=authority,
        issued_at=100,
        expires_at=300,
        now=150,
    )
    journal = PluginActivationDecisionJournal(
        tmp_path / "continuity-activation.jsonl",
        scope_id="workspace:test",
        identity_factory=iter(("1" * 48, "2" * 48)).__next__,
        clock=lambda: 150,
    )
    trust = selection.plan.source_trust_snapshots[0]
    host = CapabilityOwnerComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(import_realm_id_factory=lambda: "3" * 32),
        host_boot_id="4" * 32,
        clock=lambda: 150,
        owner_snapshot_reader=lambda _capability, _kind: authority.snapshot(),
        trust_snapshot_reader=lambda _plugin, _source: trust,
        product_policy_revision_reader=(
            lambda _product, _scope: "coding-continuity-policy-1"
        ),
        payload_validator_reader=(
            lambda _definition: validate_continuity_provider_component_payload
        ),
    )
    [component] = resolved.resolved_set.components
    subject = host.activation_subject(
        component,
        owner_snapshot=resolved.owner_snapshot,
        trust_snapshot=trust,
    )
    decision = journal.issue_activation_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="product:coding",
            source="continuity-plugin-test",
        ),
        issued_at_unix_ms=120,
        expires_at_unix_ms=280,
        expected_journal_revision=0,
    )
    return resolved, host, journal, {component_id: decision.decision_id}


def _payload() -> ContinuityProviderDeclarationPayload:
    return ContinuityProviderDeclarationPayload(
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            execution_model="in_process",
        ),
        binding_inputs={"endpoint": "https://sessions.invalid"},
    )


def _selection(
    fixture: _ContinuityPlugin,
    *,
    configuration: dict[str, object] | None = None,
) -> PluginSelection:
    plugin_id = fixture.package.manifest.name
    contribution_id = fixture.contribution.contribution_id
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="coding-continuity-policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="continuity-example@workspace:test",
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
                    configuration=(
                        dict(fixture.contribution.configuration)
                        if configuration is None
                        else configuration
                    ),
                ),
            )
        ),
        allowed_authority_ceiling=("network.read",),
    )
    selection = PluginDeclarationHost().resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(selection, PluginSelection)
    return selection


@dataclass(slots=True)
class _FamilyLease:
    instance_revision_ref: PluginInstanceRevisionRef
    events: list[str]
    family_id: str = "f" * 64
    closed: bool = False

    async def security_handoff(
        self,
        _evidence: object,
    ) -> None:
        self.events.append(f"security-handoff:{self.family_id}")
        self.closed = True

    async def close(self) -> None:
        if self.closed:
            return
        self.events.append(f"release:{self.family_id}")
        self.closed = True


@dataclass(slots=True)
class _FamilyAuthority:
    events: list[str] = field(default_factory=list)

    async def acquire(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
        *,
        holder_reference: str,
    ) -> ContinuityPluginInstanceFamilyLease:
        self.events.append(
            f"acquire:{instance_revision_ref.instance_id}:{holder_reference}"
        )
        return _FamilyLease(instance_revision_ref, self.events)


@dataclass(slots=True)
class _BlockingFamilyAuthority(_FamilyAuthority):
    started: asyncio.Event = field(default_factory=asyncio.Event)
    allow: asyncio.Event = field(default_factory=asyncio.Event)
    acquire_calls: int = 0

    async def acquire(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
        *,
        holder_reference: str,
    ) -> ContinuityPluginInstanceFamilyLease:
        self.acquire_calls += 1
        self.started.set()
        await self.allow.wait()
        return await _FamilyAuthority.acquire(
            self,
            instance_revision_ref,
            holder_reference=holder_reference,
        )


@dataclass(slots=True)
class _FailOnceFamilyAuthority(_FamilyAuthority):
    failed: bool = False

    async def acquire(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
        *,
        holder_reference: str,
    ) -> ContinuityPluginInstanceFamilyLease:
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic family acquisition failure")
        return await _FamilyAuthority.acquire(
            self,
            instance_revision_ref,
            holder_reference=holder_reference,
        )


@dataclass(slots=True)
class _RetryGeneration:
    dispose_calls: int = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1
        if self.dispose_calls == 1:
            raise RuntimeError("synthetic generation cleanup failure")


@dataclass(slots=True)
class _RetryPublication:
    shutdown_calls: int = 0

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.shutdown_calls == 1:
            raise RuntimeError("synthetic shutdown failure")


@dataclass(slots=True)
class _RetryBinder:
    dispose_calls: int = 0

    async def dispose(self, _binding: object) -> None:
        self.dispose_calls += 1


@dataclass
class _CodingRuntime:
    session_dir: Path
    prepared_payloads: list[bytes] = field(default_factory=list)

    def get_current_session_ref(self) -> None:
        return None

    def try_query_session_index_page(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> SessionIndexPage:
        return SessionIndexPage(
            items=(),
            has_more=False,
            index_state="fresh",
            index_generation="coding-g1",
            query_snapshot="coding-q1",
        )

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        **_kwargs: object,
    ) -> object:
        self.prepared_payloads.append(Path(session_id).read_bytes())

        class _Candidate:
            async def consume(self) -> object:
                return {"restored": True}

            async def abort(self) -> None:
                return None

        return _Candidate()


def _provider_source() -> str:
    return """\
import hashlib
import os
from pathlib import Path

from loushang.harness.continuity.import_provider import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
    ContinuityImportProviderPack,
)
from loushang.harness.continuity.types import (
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuitySummary,
    ContinuityTarget,
    ProviderPage,
    ProviderPageItem,
)

MARKER = Path(os.environ["LOUSHANG_CONTINUITY_PLUGIN_MARKER"])
with MARKER.open("a", encoding="utf-8") as stream:
    stream.write("import\\n")

TARGET = ContinuityTarget("continuity.example", "remote-1", "r1")

class Prepared:
    def __init__(self):
        self._closed = False

    @property
    def target(self):
        return TARGET

    @property
    def payload(self):
        return ContinuityActivationPayload.from_bytes(
            b'{"session":"remote-1"}\\n',
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            cwd_override="/remote/project",
        )

    async def abort(self):
        await self.close()

    async def close(self):
        if not self._closed:
            with MARKER.open("a", encoding="utf-8") as stream:
                stream.write("source-close\\n")
            self._closed = True

class Provider:
    @property
    def descriptor(self):
        return ContinuityProviderDescriptor(
            provider_id="continuity.example",
            experience_id="coding",
            domain_ids=("coding",),
            primary_domain_id="coding",
            label="Remote sessions",
            supported_actions=("activate",),
        )

    async def query(self, request):
        return ProviderPage(
            items=(ProviderPageItem(
                summary=ContinuitySummary(
                    target=TARGET,
                    domain_ids=("coding",),
                    primary_domain_id="coding",
                    title="Remote session",
                    updated_at="2026-08-28T10:00:00Z",
                    actions=("activate",),
                ),
                after_cursor="remote-1",
            ),),
            has_more=False,
            index_state="fresh",
            index_generation="g1",
            query_snapshot="q1",
        )

    async def preview(self, target):
        return ContinuityPreview(
            target=target,
            revision=target.revision,
            heading="Remote session",
            sections=(ContinuityPreviewSection(kind="text", text="ready"),),
        )

    async def prepare_import(self, target):
        if target != TARGET:
            raise ValueError("stale target")
        return Prepared()

def create_provider(context):
    endpoint = context.binding_inputs["endpoint"]
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write(f"create:{endpoint}\\n")
    return ContinuityImportProviderPack((Provider(),))

def dispose_provider(value):
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("dispose\\n")
"""
