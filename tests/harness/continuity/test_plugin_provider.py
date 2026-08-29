from __future__ import annotations

import asyncio
import hashlib
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.continuity import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    AcceptedContinuityDeletion,
    CallbackPreparedActivationLease,
    ContinuityActivationPayload,
    ContinuityDeletionPlanV1,
    ContinuityDeletionReceiptV1,
    ContinuityHub,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
    ExperienceComposition,
    ExperienceDescriptor,
    ProviderPage,
    ProviderQuery,
    consume_prepared_activation,
)
from loushang.harness.continuity.composition import (
    BoundContinuityProvider,
    PluginContinuityProviderProvenance,
    _bind_gated_plugin_continuity_provider,
    _compose_experience_continuity_with_plugins,
    _create_plugin_continuity_provider_provenance,
    plugin_continuity_provider_source,
)
from loushang.harness.continuity.plugin_provider import (
    ContinuityPluginGenerationClosingError,
    ContinuityPluginGenerationGate,
    ContinuityPluginGenerationQuiesceError,
    ContinuityPluginMutationRecoveryError,
    ContinuityPluginProviderCallError,
    PluginContinuityProvider,
    recover_continuity_plugin_deletions,
)
from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginGeneration,
    ContinuityPluginLifecycleError,
    ContinuityPluginPublication,
    ContinuityPluginSecurityRetirementEvidence,
    ResolvedContinuityPluginSelection,
    _create_continuity_plugin_publication,
    publish_continuity_plugin_generation,
    publish_continuity_plugin_generation_with_mutations,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
    PluginInstanceLedgerContinuityFamilyAuthority,
)
from loushang.harness.plugin_management.continuity_mutation import (
    PluginContinuityDeletionAuthority,
    PluginContinuityDeletionJournal,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
)
from loushang.harness.runtime import (
    ProductRuntimePlan,
    ResolvedRuntimeSelection,
    RuntimeCapabilitySelection,
    RuntimeProfileResolver,
)


def test_generation_gate_linearizes_consume_before_security_close() -> None:
    asyncio.run(_generation_gate_linearizes_consume_before_security_close())


def test_installed_plugin_mutation_requires_product_authority(tmp_path) -> None:
    provider = _Provider()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_provenance(),
        gate=ContinuityPluginGenerationGate(),
    )
    assert wrapped.descriptor.supported_actions == ("activate",)

    mutation_provider = _Provider(supported_actions=("activate", "delete"))
    with pytest.raises(TypeError, match="Product authority"):
        PluginContinuityProvider(
            mutation_provider,
            bridge=_Bridge(),
            provenance=_mutation_provenance(),
            gate=ContinuityPluginGenerationGate(),
        )
    mutation_wrapped = PluginContinuityProvider(
        mutation_provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=PluginContinuityDeletionAuthority(
            PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
        ),
    )
    assert mutation_wrapped.descriptor.supported_actions == (
        "activate",
        "delete",
    )

    with pytest.raises(ValueError, match="admitted declaration"):
        PluginContinuityProvider(
            mutation_provider,
            bridge=_Bridge(),
            provenance=_provenance(),
            gate=ContinuityPluginGenerationGate(),
            deletion_authority=PluginContinuityDeletionAuthority(
                PluginContinuityDeletionJournal(tmp_path / "mismatch.jsonl")
            ),
        )
    with pytest.raises(TypeError, match="lacks prepare_delete"):
        PluginContinuityProvider(
            _MissingDeleteProvider(),
            bridge=_Bridge(),
            provenance=_mutation_provenance(),
            gate=ContinuityPluginGenerationGate(),
            deletion_authority=PluginContinuityDeletionAuthority(
                PluginContinuityDeletionJournal(tmp_path / "missing.jsonl")
            ),
        )


def test_installed_plugin_delete_is_durable_and_generation_gated(tmp_path) -> None:
    asyncio.run(_installed_plugin_delete_is_generation_gated(tmp_path))


def test_delete_completion_failure_exposes_exact_settlement_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_delete_completion_failure_exposes_retry(tmp_path, monkeypatch))


async def _delete_completion_failure_exposes_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(target=target, supported_actions=("activate", "delete"))
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    authority = PluginContinuityDeletionAuthority(journal)
    complete = journal.complete
    attempts = 0

    def fail_once(authorization_id, receipt):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic completion interruption")
        return complete(authorization_id, receipt)

    monkeypatch.setattr(journal, "complete", fail_once)
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        await wrapped.delete(target)
    pending = caught.value.pending_mutation
    assert pending is not None
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["commit"]
    assert tuple(item.event_kind for item in journal.records()) == ("accepted",)

    assert await pending.retry() is True
    assert provider.prepared_delete.events == ["commit", "close"]
    assert tuple(item.event_kind for item in journal.records()) == (
        "accepted",
        "completed",
    )


def test_delete_release_failure_retries_without_recommit(tmp_path) -> None:
    asyncio.run(_delete_release_failure_retries_without_recommit(tmp_path))


async def _delete_release_failure_retries_without_recommit(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_close_failures=1,
    )
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=PluginContinuityDeletionAuthority(journal),
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        await wrapped.delete(target)
    pending = caught.value.pending_mutation
    assert pending is not None
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["commit", "close"]
    assert tuple(item.event_kind for item in journal.records()) == (
        "accepted",
        "completed",
    )

    assert await pending.retry() is True
    assert provider.prepared_delete.events == ["commit", "close", "close"]


def test_graceful_quiesce_cancels_accepted_unstarted_delete(tmp_path) -> None:
    asyncio.run(_graceful_quiesce_cancels_unstarted_delete(tmp_path))


async def _graceful_quiesce_cancels_unstarted_delete(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
    )
    gate = ContinuityPluginGenerationGate()
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=gate,
        deletion_authority=authority,
    )
    await wrapped._prepare_delete(target)

    gate.begin_close(security=False)
    await gate.quiesce(timeout=1.0)

    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["abort", "close"]
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "cancelled",
    )


def test_generation_owns_failed_mutation_prepare_cleanup(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_generation_owns_failed_mutation_cleanup(tmp_path, monkeypatch))


async def _generation_owns_failed_mutation_cleanup(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_abort_failures=1,
    )
    gate = ContinuityPluginGenerationGate()
    journal = PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    authority = PluginContinuityDeletionAuthority(journal)
    monkeypatch.setattr(
        journal,
        "accept",
        lambda _plan, _source: (_ for _ in ()).throw(
            RuntimeError("secret at /private/journal")
        ),
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=gate,
        deletion_authority=authority,
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        await wrapped._prepare_delete(target)
    assert caught.value.pending_cleanup is not None
    assert "/private/journal" not in str(caught.value)

    gate.begin_close(security=False)
    await gate.quiesce(timeout=1.0)
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["abort", "abort", "close"]


def test_delete_close_race_is_owned_by_generation_quiesce(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_delete_close_race_is_owned_by_quiesce(tmp_path, monkeypatch))


async def _delete_close_race_is_owned_by_quiesce(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(target=target, supported_actions=("activate", "delete"))
    gate = ContinuityPluginGenerationGate()
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=gate,
        deletion_authority=authority,
    )
    lease = await wrapped._prepare_delete(target)

    async def prepare_then_close(_target: ContinuityTarget):  # type: ignore[no-untyped-def]
        gate.begin_close(security=False)
        return lease

    monkeypatch.setattr(wrapped, "_prepare_delete", prepare_then_close)
    with pytest.raises(ContinuityPluginGenerationClosingError):
        await wrapped.delete(target)

    await gate.quiesce(timeout=1.0)
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["abort", "close"]
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "cancelled",
    )


def test_delete_prepare_close_race_retains_failed_abort_for_quiesce(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_delete_prepare_close_race_retains_abort(tmp_path, monkeypatch))


async def _delete_prepare_close_race_retains_abort(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_abort_failures=1,
    )
    gate = ContinuityPluginGenerationGate()
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    authorize = PluginContinuityDeletionAuthority.authorize_delete

    async def authorize_then_close(self, plan, source):  # type: ignore[no-untyped-def]
        evidence = await authorize(self, plan, source)
        gate.begin_close(security=False)
        return evidence

    monkeypatch.setattr(
        PluginContinuityDeletionAuthority,
        "authorize_delete",
        authorize_then_close,
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=gate,
        deletion_authority=authority,
    )

    with pytest.raises(ContinuityPluginGenerationClosingError):
        await wrapped._prepare_delete(target)
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["abort"]

    await gate.quiesce(timeout=1.0)
    assert provider.prepared_delete.events == ["abort", "abort", "close"]
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "cancelled",
    )


async def _installed_plugin_delete_is_generation_gated(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_commit_started=commit_started,
        allow_delete_commit=allow_commit,
    )
    gate = ContinuityPluginGenerationGate()
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=gate,
        deletion_authority=authority,
    )
    base = _product_hub(_HungAbortProductProvider()).composition
    composition = _compose_experience_continuity_with_plugins(
        base,
        (
            _bind_gated_plugin_continuity_provider(
                wrapped,
                _mutation_provenance(),
            ),
        ),
    )
    hub = ContinuityHub(composition)
    deleting = asyncio.create_task(hub.delete(target))
    await commit_started.wait()

    gate.begin_close(security=True)
    quiescing = asyncio.create_task(gate.quiesce(timeout=1.0))
    await asyncio.sleep(0)
    assert not quiescing.done()

    allow_commit.set()
    assert await deleting is True
    await quiescing
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["commit", "close"]
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "completed",
    )
    await hub.close()


def test_repeated_hub_delete_replays_durable_result_without_recommit(tmp_path) -> None:
    asyncio.run(_repeated_hub_delete_replays_result(tmp_path))


async def _repeated_hub_delete_replays_result(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_dispositions=["applied", "not_found"],
    )
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )
    base = _product_hub(_HungAbortProductProvider()).composition
    hub = ContinuityHub(
        _compose_experience_continuity_with_plugins(
            base,
            (
                _bind_gated_plugin_continuity_provider(
                    wrapped,
                    _mutation_provenance(),
                ),
            ),
        )
    )

    assert await hub.delete(target) is True
    assert await hub.delete(target) is True

    assert [candidate.events for candidate in provider.delete_candidates] == [
        ["commit", "close"],
        ["abort", "close"],
    ]
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "completed",
    )
    await hub.close()


def test_concurrent_hub_delete_coalesces_across_execution_lock(tmp_path) -> None:
    asyncio.run(_concurrent_hub_delete_coalesces(tmp_path))


async def _concurrent_hub_delete_coalesces(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_dispositions=["applied", "not_found"],
        delete_commit_started=commit_started,
        allow_delete_commit=allow_commit,
    )
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )
    base = _product_hub(_HungAbortProductProvider()).composition
    hub = ContinuityHub(
        _compose_experience_continuity_with_plugins(
            base,
            (
                _bind_gated_plugin_continuity_provider(
                    wrapped,
                    _mutation_provenance(),
                ),
            ),
        )
    )
    first = asyncio.create_task(hub.delete(target))
    await commit_started.wait()
    second = asyncio.create_task(hub.delete(target))
    while len(provider.delete_candidates) < 2:
        await asyncio.sleep(0)

    allow_commit.set()
    assert await asyncio.gather(first, second) == [True, True]
    assert [candidate.events for candidate in provider.delete_candidates] == [
        ["commit", "close"],
        ["abort", "close"],
    ]
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "completed",
    )
    await hub.close()


def test_duplicate_delete_storm_cannot_starve_product_settlement(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_duplicate_delete_storm_cannot_starve_settlement(tmp_path, monkeypatch))


async def _duplicate_delete_storm_cannot_starve_settlement(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 512
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_dispositions=["applied", *(["not_found"] * (request_count - 1))],
        delete_commit_started=commit_started,
        allow_delete_commit=allow_commit,
    )
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    try_acquire = PluginContinuityDeletionAuthority._try_acquire_execution
    acquisition_attempts = 0

    def count_acquisition_attempts(self, plan, source):  # type: ignore[no-untyped-def]
        nonlocal acquisition_attempts
        acquisition_attempts += 1
        return try_acquire(self, plan, source)

    monkeypatch.setattr(
        PluginContinuityDeletionAuthority,
        "_try_acquire_execution",
        count_acquisition_attempts,
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )
    hub = ContinuityHub(
        _compose_experience_continuity_with_plugins(
            _product_hub(_HungAbortProductProvider()).composition,
            (
                _bind_gated_plugin_continuity_provider(
                    wrapped,
                    _mutation_provenance(),
                ),
            ),
        )
    )
    first = asyncio.create_task(hub.delete(target))
    await commit_started.wait()
    duplicates = tuple(
        asyncio.create_task(hub.delete(target)) for _index in range(request_count - 1)
    )
    while len(provider.delete_candidates) < request_count:
        await asyncio.sleep(0)

    allow_commit.set()
    results = await asyncio.wait_for(
        asyncio.gather(first, *duplicates),
        timeout=10.0,
    )

    assert results == [True] * request_count
    assert acquisition_attempts == 1
    assert (
        sum(
            candidate.events == ["commit", "close"]
            for candidate in provider.delete_candidates
        )
        == 1
    )
    assert (
        sum(
            candidate.events == ["abort", "close"]
            for candidate in provider.delete_candidates
        )
        == request_count - 1
    )
    assert tuple(item.event_kind for item in authority.journal.records()) == (
        "accepted",
        "completed",
    )
    await hub.close()


def test_startup_recovery_settles_before_generation_is_ready(tmp_path) -> None:
    asyncio.run(_startup_recovery_settles_before_ready(tmp_path))


async def _startup_recovery_settles_before_ready(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    plan = ContinuityDeletionPlanV1(target)
    source = plugin_continuity_provider_source(
        provider_id=target.provider_id,
        implementation_version=1,
        provenance=_mutation_provenance(generation_fingerprint="e" * 64),
    )
    authority.journal.accept(plan, source)
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(generation_fingerprint="f" * 64),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    await recover_continuity_plugin_deletions((wrapped,), authority=authority)

    assert await authority.pending_deletions() == ()
    assert provider.prepared_delete is not None
    assert provider.prepared_delete.plan == plan


def test_startup_recovery_accepts_reconstructed_attempt_with_same_semantics(
    tmp_path,
) -> None:
    asyncio.run(_startup_recovery_accepts_reconstructed_attempt(tmp_path))


async def _startup_recovery_accepts_reconstructed_attempt(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    recovery_fingerprint = "9" * 64
    accepted = _mutation_provenance(
        generation_fingerprint="e" * 64,
        recovery_fingerprint=recovery_fingerprint,
    )
    authority.journal.accept(
        ContinuityDeletionPlanV1(target),
        plugin_continuity_provider_source(
            provider_id=target.provider_id,
            implementation_version=1,
            provenance=accepted,
        ),
    )
    provider = _Provider(target=target, supported_actions=("activate", "delete"))
    reconstructed = _mutation_provenance(
        generation_fingerprint="f" * 64,
        candidate_fingerprint="1" * 64,
        admission_fingerprint="2" * 64,
        selection_plan_fingerprint="3" * 64,
        binding_fingerprint="4" * 64,
        recovery_fingerprint=recovery_fingerprint,
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=reconstructed,
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    await recover_continuity_plugin_deletions((wrapped,), authority=authority)

    assert await authority.pending_deletions() == ()
    assert provider.prepared_delete is not None


def test_startup_recovery_preserves_phase5e_exact_attempt_rule(tmp_path) -> None:
    asyncio.run(_startup_recovery_preserves_phase5e_exact_attempt_rule(tmp_path))


async def _startup_recovery_preserves_phase5e_exact_attempt_rule(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    provenance = _mutation_provenance(generation_fingerprint="e" * 64)
    source = plugin_continuity_provider_source(
        provider_id=target.provider_id,
        implementation_version=1,
        provenance=provenance,
    )
    authority.journal.accept(
        ContinuityDeletionPlanV1(target),
        replace(source, owner_recovery_fingerprint=None),
    )
    provider = _Provider(target=target, supported_actions=("activate", "delete"))
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=provenance,
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    await recover_continuity_plugin_deletions((wrapped,), authority=authority)

    assert await authority.pending_deletions() == ()
    assert provider.prepared_delete is not None


@pytest.mark.parametrize(
    "change",
    (
        {"source_trust_policy_revision": "trust-2"},
        {"source_trust_class": "sandboxed-local"},
        {"plugin_id": "replacement"},
        {"contribution_id": "replacement-sessions"},
        {"instance_id": "example@workspace:replacement"},
        {"instance_revision": 2},
        {"component_id": "plugin:replacement:sessions"},
        {"candidate_fingerprint": "1" * 64},
        {"admission_fingerprint": "2" * 64},
        {"selection_plan_fingerprint": "3" * 64},
        {"binding_fingerprint": "4" * 64},
    ),
    ids=(
        "trust-policy",
        "trust-class",
        "plugin",
        "contribution",
        "instance",
        "instance-revision",
        "implementation",
        "candidate",
        "admission",
        "selection",
        "binding",
    ),
)
def test_startup_recovery_rejects_changed_owner_provenance(
    tmp_path,
    change: dict[str, object],
) -> None:
    asyncio.run(_startup_recovery_rejects_changed_owner_provenance(tmp_path, change))


async def _startup_recovery_rejects_changed_owner_provenance(
    tmp_path,
    change: dict[str, object],
) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    accepted_provenance = _mutation_provenance(generation_fingerprint="e" * 64)
    authority.journal.accept(
        ContinuityDeletionPlanV1(target),
        plugin_continuity_provider_source(
            provider_id=target.provider_id,
            implementation_version=1,
            provenance=accepted_provenance,
        ),
    )
    changed = _mutation_provenance(  # type: ignore[arg-type]
        generation_fingerprint="f" * 64,
        **change,
    )
    provider = _Provider(target=target, supported_actions=("activate", "delete"))
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=changed,
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    with pytest.raises(ContinuityPluginMutationRecoveryError):
        await recover_continuity_plugin_deletions((wrapped,), authority=authority)

    assert provider.prepared_delete is None
    assert len(await authority.pending_deletions()) == 1


@pytest.mark.parametrize(
    ("provider_id", "implementation_version"),
    (("replacement.sessions", 1), ("plugin.sessions", 2)),
    ids=("provider", "implementation-version"),
)
def test_startup_recovery_rejects_changed_provider_runtime_identity(
    tmp_path,
    provider_id: str,
    implementation_version: int,
) -> None:
    asyncio.run(
        _startup_recovery_rejects_changed_provider_runtime_identity(
            tmp_path,
            provider_id=provider_id,
            implementation_version=implementation_version,
        )
    )


async def _startup_recovery_rejects_changed_provider_runtime_identity(
    tmp_path,
    *,
    provider_id: str,
    implementation_version: int,
) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    accepted_provenance = _mutation_provenance(generation_fingerprint="e" * 64)
    authority.journal.accept(
        ContinuityDeletionPlanV1(target),
        plugin_continuity_provider_source(
            provider_id=target.provider_id,
            implementation_version=1,
            provenance=accepted_provenance,
        ),
    )
    provider = _Provider(
        target=target,
        provider_id=provider_id,
        implementation_version=implementation_version,
        supported_actions=("activate", "delete"),
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(generation_fingerprint="f" * 64),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    with pytest.raises(ContinuityPluginMutationRecoveryError):
        await recover_continuity_plugin_deletions((wrapped,), authority=authority)
    assert provider.prepared_delete is None
    assert len(await authority.pending_deletions()) == 1


def test_startup_recovery_rejects_multiple_exact_generation_owners(tmp_path) -> None:
    asyncio.run(_startup_recovery_rejects_multiple_owners(tmp_path))


async def _startup_recovery_rejects_multiple_owners(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    old = _mutation_provenance(generation_fingerprint="e" * 64)
    authority.journal.accept(
        ContinuityDeletionPlanV1(target),
        plugin_continuity_provider_source(
            provider_id=target.provider_id,
            implementation_version=1,
            provenance=old,
        ),
    )
    providers = tuple(
        _Provider(target=target, supported_actions=("activate", "delete"))
        for _index in range(2)
    )
    wrappers = tuple(
        PluginContinuityProvider(
            provider,
            bridge=_Bridge(),
            provenance=_mutation_provenance(generation_fingerprint="f" * 64),
            gate=ContinuityPluginGenerationGate(),
            deletion_authority=authority,
        )
        for provider in providers
    )

    with pytest.raises(ContinuityPluginMutationRecoveryError):
        await recover_continuity_plugin_deletions(wrappers, authority=authority)
    assert all(provider.prepared_delete is None for provider in providers)
    assert len(await authority.pending_deletions()) == 1


def test_startup_recovery_plan_mismatch_preserves_confirmed_intent(tmp_path) -> None:
    asyncio.run(_startup_recovery_plan_mismatch_preserves_intent(tmp_path))


async def _startup_recovery_plan_mismatch_preserves_intent(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    accepted_plan = ContinuityDeletionPlanV1(target)
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    old = _mutation_provenance(generation_fingerprint="e" * 64)
    authority.journal.accept(
        accepted_plan,
        plugin_continuity_provider_source(
            provider_id=target.provider_id,
            implementation_version=1,
            provenance=old,
        ),
    )
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
        delete_plan=ContinuityDeletionPlanV1(
            ContinuityTarget(target.provider_id, "different", target.revision)
        ),
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(generation_fingerprint="f" * 64),
        gate=ContinuityPluginGenerationGate(),
        deletion_authority=authority,
    )

    with pytest.raises(ContinuityPluginMutationRecoveryError):
        await recover_continuity_plugin_deletions((wrapped,), authority=authority)

    assert provider.prepared_delete is not None
    assert provider.prepared_delete.events == ["abort", "close"]
    assert await authority.pending_deletions() == (
        AcceptedContinuityDeletion(
            plan=accepted_plan,
            source=plugin_continuity_provider_source(
                provider_id=target.provider_id,
                implementation_version=1,
                provenance=old,
            ),
        ),
    )


def test_unpublished_generation_quiesces_mutations_before_releasing_ownership(
    tmp_path,
) -> None:
    asyncio.run(_unpublished_generation_quiesces_before_release(tmp_path))


async def _unpublished_generation_quiesces_before_release(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    provider = _Provider(target=target, supported_actions=("activate", "delete"))
    gate = ContinuityPluginGenerationGate()
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_mutation_provenance(),
        gate=gate,
        deletion_authority=authority,
    )
    await wrapped._prepare_delete(target)
    lifecycle: list[str] = []

    class Binder:
        async def dispose(self, _runtime: object) -> tuple[()]:
            assert await authority.pending_deletions() == ()
            assert provider.prepared_delete is not None
            assert provider.prepared_delete.events == ["abort", "close"]
            lifecycle.append("components")
            return ()

    class Family:
        async def close(self) -> None:
            lifecycle.append("family")

    class Reservation:
        def release(self) -> None:
            lifecycle.append("reservation")

    generation = object.__new__(ContinuityPluginGeneration)
    object.__setattr__(generation, "binder", Binder())
    object.__setattr__(generation, "runtime", object())
    object.__setattr__(generation, "instance_families", (Family(),))
    object.__setattr__(generation, "_reservation", Reservation())
    object.__setattr__(generation, "gate", gate)
    object.__setattr__(generation, "_published", False)
    object.__setattr__(generation, "_publishing", False)
    object.__setattr__(generation, "_publication_failed", False)
    object.__setattr__(generation, "_publication_lock", threading.Lock())
    object.__setattr__(generation, "_security_cleanup_evidence", None)
    object.__setattr__(generation, "_security_cleanup_prepared", False)
    object.__setattr__(generation, "_disposed", False)

    await generation.dispose()

    assert lifecycle == ["components", "family", "reservation"]
    assert generation._disposed is True


def test_mutation_publication_recovers_before_exposing_hub(tmp_path) -> None:
    asyncio.run(_mutation_publication_recovers_before_exposing_hub(tmp_path))


async def _mutation_publication_recovers_before_exposing_hub(tmp_path) -> None:
    target = ContinuityTarget("plugin.sessions", "one", "revision-1")
    authority = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    old_provenance = _mutation_provenance(generation_fingerprint="e" * 64)
    current_provenance = _mutation_provenance(generation_fingerprint="f" * 64)
    authority.journal.accept(
        ContinuityDeletionPlanV1(target),
        plugin_continuity_provider_source(
            provider_id=target.provider_id,
            implementation_version=1,
            provenance=old_provenance,
        ),
    )
    provider = _Provider(
        target=target,
        supported_actions=("activate", "delete"),
    )
    generation = object.__new__(ContinuityPluginGeneration)
    object.__setattr__(
        generation,
        "providers",
        ((provider, current_provenance),),
    )
    object.__setattr__(generation, "gate", ContinuityPluginGenerationGate())
    object.__setattr__(generation, "_published", False)
    object.__setattr__(generation, "_publishing", False)
    object.__setattr__(generation, "_publication_failed", False)
    object.__setattr__(generation, "_publication_lock", threading.Lock())
    object.__setattr__(generation, "_disposed", False)
    base = _product_hub(_HungAbortProductProvider()).composition

    publication = await publish_continuity_plugin_generation_with_mutations(
        base,
        generation,
        activation_bridge=_Bridge(),
        deletion_authority=authority,
    )

    assert generation._published is True
    assert await authority.pending_deletions() == ()
    plugin_bound = next(
        item
        for item in publication.composition.continuity_providers
        if item.provider.descriptor.provider_id == "plugin.sessions"
    )
    assert plugin_bound.provider.descriptor.supported_actions == (
        "activate",
        "delete",
    )
    await publication.hub.close()


def test_mutation_publication_reserves_generation_before_recovery_await(
    tmp_path,
) -> None:
    asyncio.run(_mutation_publication_reserves_before_await(tmp_path))


async def _mutation_publication_reserves_before_await(tmp_path) -> None:
    delegate = PluginContinuityDeletionAuthority(
        PluginContinuityDeletionJournal(tmp_path / "deletions.jsonl")
    )
    pending_started = asyncio.Event()
    allow_pending = asyncio.Event()

    class BlockingAuthority:
        async def authorize_delete(self, plan, source):  # type: ignore[no-untyped-def]
            return await delegate.authorize_delete(plan, source)

        async def complete_delete(self, authorization, receipt):  # type: ignore[no-untyped-def]
            await delegate.complete_delete(authorization, receipt)

        async def cancel_delete(self, authorization):  # type: ignore[no-untyped-def]
            await delegate.cancel_delete(authorization)

        async def pending_deletions(self):  # type: ignore[no-untyped-def]
            pending_started.set()
            await allow_pending.wait()
            return await delegate.pending_deletions()

    provider = _Provider()
    generation = object.__new__(ContinuityPluginGeneration)
    object.__setattr__(generation, "providers", ((provider, _provenance()),))
    object.__setattr__(generation, "gate", ContinuityPluginGenerationGate())
    object.__setattr__(generation, "_published", False)
    object.__setattr__(generation, "_publishing", False)
    object.__setattr__(generation, "_publication_failed", False)
    object.__setattr__(generation, "_publication_lock", threading.Lock())
    object.__setattr__(generation, "_disposed", False)
    base = _product_hub(_HungAbortProductProvider()).composition
    publishing = asyncio.create_task(
        publish_continuity_plugin_generation_with_mutations(
            base,
            generation,
            activation_bridge=_Bridge(),
            deletion_authority=BlockingAuthority(),  # type: ignore[arg-type]
        )
    )
    await pending_started.wait()

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        publish_continuity_plugin_generation(
            base,
            generation,
            activation_bridge=_Bridge(),
        )
    assert caught.value.code == "continuity_provider_generation_not_publishable"

    allow_pending.set()
    publication = await publishing
    assert generation._published is True
    await publication.hub.close()


def test_owner_lifecycle_handles_and_plugin_binding_are_not_caller_constructible() -> (
    None
):
    for record_type in (
        PluginContinuityProviderProvenance,
        ResolvedContinuityPluginSelection,
        ContinuityPluginGeneration,
        ContinuityPluginPublication,
    ):
        with pytest.raises(TypeError, match="owner-constructed"):
            record_type()

    base = _product_hub(_HungAbortProductProvider()).composition
    forged = BoundContinuityProvider(
        provider=_Provider(),  # type: ignore[arg-type]
        provenance=_provenance(),
    )
    with pytest.raises(TypeError, match="owner-derived provenance"):
        _compose_experience_continuity_with_plugins(base, (forged,))

    duplicate_base = _product_hub(
        _HungAbortProductProvider(provider_id="plugin.sessions")
    ).composition
    gated = _bind_gated_plugin_continuity_provider(
        _Provider(),  # type: ignore[arg-type]
        _provenance(),
    )
    with pytest.raises(ValueError, match="duplicate continuity provider ID"):
        _compose_experience_continuity_with_plugins(duplicate_base, (gated,))

    product_bound = base.continuity_providers[0]
    full_base = replace(
        base,
        continuity_providers=tuple(
            BoundContinuityProvider(
                provider=_HungAbortProductProvider(provider_id=f"product.{index}"),
                provenance=product_bound.provenance,
            )
            for index in range(32)
        ),
    )
    with pytest.raises(ValueError, match="exceeds its aggregate limit"):
        _compose_experience_continuity_with_plugins(full_base, (gated,))


async def _generation_gate_linearizes_consume_before_security_close() -> None:
    provider = _Provider()
    bridge = _Bridge()
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )
    lease = await wrapped.prepare(provider.target)
    consume = asyncio.create_task(lease.consume())
    await bridge.consume_started.wait()

    gate.begin_close(security=True)
    quiesce = asyncio.create_task(gate.quiesce(timeout=1.0))
    await asyncio.sleep(0)
    assert not quiesce.done()
    with pytest.raises(ContinuityPluginGenerationClosingError):
        await wrapped.preview(provider.target)

    bridge.allow_consume.set()
    assert await consume == "published"
    await quiesce
    assert gate.security_closing is True


def test_failed_plugin_activation_consume_aborts_product_candidate() -> None:
    asyncio.run(_failed_plugin_activation_consume_aborts_product_candidate())


async def _failed_plugin_activation_consume_aborts_product_candidate() -> None:
    provider = _Provider()
    bridge = _Bridge(consume_failure=True)
    bridge.allow_consume.set()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=ContinuityPluginGenerationGate(),
    )
    lease = await wrapped.prepare(provider.target)

    with pytest.raises(RuntimeError, match="synthetic consume failure"):
        await consume_prepared_activation(lease)
    assert bridge.aborted == 1
    assert bridge.abort_completed == 1


def test_security_close_aborts_unconsumed_activation_lease() -> None:
    asyncio.run(_security_close_aborts_unconsumed_activation_lease())


def test_generation_abort_intent_rejects_consume_before_cleanup_finishes() -> None:
    asyncio.run(_generation_abort_intent_rejects_consume_before_cleanup_finishes())


async def _generation_abort_intent_rejects_consume_before_cleanup_finishes() -> None:
    provider = _Provider()
    allow_abort = asyncio.Event()
    bridge = _Bridge(abort_gate=allow_abort)
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )
    lease = await wrapped.prepare(provider.target)
    gate.begin_close(security=True)
    cleanup = asyncio.create_task(gate.quiesce(timeout=1.0))
    while bridge.aborted == 0:
        await asyncio.sleep(0)

    with pytest.raises(Exception, match="closed"):
        await lease.consume()
    allow_abort.set()
    await cleanup
    assert bridge.abort_completed == 1


async def _security_close_aborts_unconsumed_activation_lease() -> None:
    provider = _Provider()
    bridge = _Bridge()
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )
    lease = await wrapped.prepare(provider.target)

    gate.begin_close(security=True)
    await gate.quiesce(timeout=1.0)

    assert bridge.aborted == 1
    with pytest.raises(Exception, match="closed"):
        await lease.consume()


@pytest.mark.parametrize("operation", ("query", "preview", "prepare"))
def test_plugin_call_failures_are_redacted(operation: str) -> None:
    asyncio.run(_plugin_call_failures_are_redacted(operation))


async def _plugin_call_failures_are_redacted(operation: str) -> None:
    provider = _Provider(fail_operation=operation)
    wrapped = PluginContinuityProvider(
        provider,
        bridge=_Bridge(),
        provenance=_provenance(),
        gate=ContinuityPluginGenerationGate(),
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        if operation == "query":
            await wrapped.query(
                ProviderQuery(
                    text="",
                    sort_id="updated",
                    descending=True,
                    limit=10,
                )
            )
        elif operation == "preview":
            await wrapped.preview(provider.target)
        else:
            await wrapped.prepare(provider.target)
    assert caught.value.code == f"continuity_plugin_provider_{operation}_failed"
    assert "secret" not in str(caught.value)
    assert "/private/source" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("malformed", "operation"),
    (
        ("query_invalid_page", "query"),
        ("preview_wrong_target", "preview"),
        ("source_invalid_lease", "prepare"),
        ("source_wrong_target", "prepare"),
        ("source_invalid_payload", "prepare"),
        ("bridge_invalid_lease", "prepare"),
        ("bridge_wrong_target", "prepare"),
    ),
)
def test_plugin_boundary_rejects_malformed_return_shapes(
    malformed: str,
    operation: str,
) -> None:
    asyncio.run(_plugin_boundary_rejects_malformed_return_shapes(malformed, operation))


async def _plugin_boundary_rejects_malformed_return_shapes(
    malformed: str,
    operation: str,
) -> None:
    provider = _Provider(malformed=malformed)
    bridge = _Bridge(malformed=malformed)
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        if operation == "query":
            await wrapped.query(
                ProviderQuery(
                    text="",
                    sort_id="updated",
                    descending=True,
                    limit=10,
                )
            )
        elif operation == "preview":
            await wrapped.preview(provider.target)
        else:
            await wrapped.prepare(provider.target)
    assert caught.value.code == f"continuity_plugin_provider_{operation}_failed"
    assert caught.value.pending_cleanup is None
    gate.begin_close(security=True)
    await gate.quiesce(timeout=1.0)
    if provider.prepared is not None:
        assert provider.prepared.closed is True
    if malformed == "bridge_wrong_target":
        assert bridge.abort_completed == 1


def test_cancelled_bridge_prepare_closes_source_lease() -> None:
    asyncio.run(_cancelled_bridge_prepare_closes_source_lease())


async def _cancelled_bridge_prepare_closes_source_lease() -> None:
    provider = _Provider()
    bridge = _Bridge(prepare_gate=asyncio.Event())
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=ContinuityPluginGenerationGate(),
    )

    prepare = asyncio.create_task(wrapped.prepare(provider.target))
    await bridge.prepare_started.wait()
    prepare.cancel()
    with pytest.raises(asyncio.CancelledError):
        await prepare
    assert provider.prepared is not None
    assert provider.prepared.closed is True


def test_close_race_retries_product_lease_abort_before_rejecting() -> None:
    asyncio.run(_close_race_retries_product_lease_abort_before_rejecting())


async def _close_race_retries_product_lease_abort_before_rejecting() -> None:
    provider = _Provider()
    prepare_gate = asyncio.Event()
    bridge = _Bridge(abort_failures=1, prepare_gate=prepare_gate)
    generation_gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=generation_gate,
    )
    prepare = asyncio.create_task(wrapped.prepare(provider.target))
    await bridge.prepare_started.wait()
    generation_gate.begin_close(security=True)
    prepare_gate.set()

    with pytest.raises(ContinuityPluginGenerationClosingError):
        await prepare
    assert bridge.aborted == 2
    assert bridge.abort_completed == 1


def test_source_close_failure_aborts_both_prepared_leases() -> None:
    asyncio.run(_source_close_failure_aborts_both_prepared_leases())


async def _source_close_failure_aborts_both_prepared_leases() -> None:
    provider = _Provider(source_close_failures=1)
    bridge = _Bridge()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=ContinuityPluginGenerationGate(),
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        await wrapped.prepare(provider.target)
    assert caught.value.code == "continuity_plugin_provider_prepare_failed"
    assert provider.prepared is not None
    assert provider.prepared.closed is True
    assert bridge.aborted == 1


def test_prepare_cleanup_failure_retains_exact_retry_handle() -> None:
    asyncio.run(_prepare_cleanup_failure_retains_exact_retry_handle())


async def _prepare_cleanup_failure_retains_exact_retry_handle() -> None:
    provider = _Provider(source_close_failures=2)
    bridge = _Bridge(abort_failures=1)
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=ContinuityPluginGenerationGate(),
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        await wrapped.prepare(provider.target)
    pending = caught.value.pending_cleanup
    assert pending is not None
    assert provider.prepared is not None
    assert provider.prepared.closed is False
    assert bridge.abort_completed == 0

    await pending.retry()
    assert provider.prepared.closed is True
    assert bridge.abort_completed == 1


def test_prepare_pending_cleanup_remains_in_generation_quiesce_inventory() -> None:
    asyncio.run(_prepare_pending_cleanup_remains_in_generation_quiesce_inventory())


async def _prepare_pending_cleanup_remains_in_generation_quiesce_inventory() -> None:
    provider = _Provider(source_close_failures=10)
    bridge = _Bridge(abort_failures=10)
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )

    with pytest.raises(ContinuityPluginProviderCallError) as caught:
        await wrapped.prepare(provider.target)
    pending = caught.value.pending_cleanup
    assert pending is not None
    gate.begin_close(security=True)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await gate.quiesce(timeout=1.0)

    assert provider.prepared is not None
    provider.prepared.close_failures = provider.prepared.close_attempts
    bridge.abort_failures = bridge.aborted
    await gate.quiesce(timeout=1.0)
    await pending.retry()
    assert provider.prepared.closed is True
    assert bridge.abort_completed == 1


def test_failed_activation_abort_remains_registered_for_retry() -> None:
    asyncio.run(_failed_activation_abort_remains_registered_for_retry())


async def _failed_activation_abort_remains_registered_for_retry() -> None:
    provider = _Provider()
    bridge = _Bridge(abort_failures=1)
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )
    lease = await wrapped.prepare(provider.target)

    gate.begin_close(security=True)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await gate.quiesce(timeout=1.0)
    assert bridge.aborted == 1
    assert bridge.abort_completed == 0

    await gate.quiesce(timeout=1.0)
    assert bridge.aborted == 2
    assert bridge.abort_completed == 1
    with pytest.raises(Exception, match="closed"):
        await lease.consume()


def test_quiesce_timeout_bounds_a_hung_activation_abort() -> None:
    asyncio.run(_quiesce_timeout_bounds_a_hung_activation_abort())


async def _quiesce_timeout_bounds_a_hung_activation_abort() -> None:
    provider = _Provider()
    abort_gate = asyncio.Event()
    bridge = _Bridge(abort_gate=abort_gate)
    gate = ContinuityPluginGenerationGate()
    wrapped = PluginContinuityProvider(
        provider,
        bridge=bridge,
        provenance=_provenance(),
        gate=gate,
    )
    lease = await wrapped.prepare(provider.target)

    gate.begin_close(security=True)
    with pytest.raises(ContinuityPluginGenerationQuiesceError):
        await gate.quiesce(timeout=0.001)
    assert bridge.abort_completed == 0

    abort_gate.set()
    await gate.quiesce(timeout=1.0)
    assert bridge.abort_completed == 1
    with pytest.raises(Exception, match="closed"):
        await lease.consume()


def test_publication_security_order_is_retryable_after_quiesce_timeout() -> None:
    asyncio.run(_publication_security_order_is_retryable_after_quiesce_timeout())


def test_cancelled_security_acceptance_poison_is_cancellation_atomic() -> None:
    asyncio.run(_cancelled_security_acceptance_poison_is_cancellation_atomic())


async def _cancelled_security_acceptance_poison_is_cancellation_atomic() -> None:
    events: list[str] = []
    generation = _Generation(events)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=_Hub(generation.gate, events),  # type: ignore[arg-type]
    )
    allow_accept = asyncio.Event()
    retirement = _SecurityRetirement(
        generation.instance,
        events,
        accept_gate=allow_accept,
    )
    security = asyncio.create_task(
        publication.security_revoke(
            retirement=retirement,
            quiesce_timeout=1.0,
        )
    )
    await retirement.accept_started.wait()
    security.cancel()
    allow_accept.set()
    with pytest.raises(asyncio.CancelledError):
        await security

    assert generation.gate.security_closing is True
    assert events == ["accept"]
    await publication.security_revoke(retirement=retirement, quiesce_timeout=1.0)
    assert events == ["accept", "hub-close", "revoking", "dispose"]


async def _publication_security_order_is_retryable_after_quiesce_timeout() -> None:
    events: list[str] = []
    generation = _Generation(events)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=_Hub(generation.gate, events),  # type: ignore[arg-type]
    )
    retirement = _SecurityRetirement(generation.instance, events)
    in_flight = generation.gate.admit()

    with pytest.raises(ContinuityPluginGenerationQuiesceError):
        await publication.security_revoke(
            retirement=retirement,
            quiesce_timeout=0.001,
        )
    assert events == ["accept", "hub-close"]
    assert generation.gate.security_closing is True

    in_flight.complete()
    await publication.security_revoke(
        retirement=retirement,
        quiesce_timeout=1.0,
    )
    assert events == ["accept", "hub-close", "hub-close", "revoking", "dispose"]


def test_security_request_upgrades_concurrent_graceful_close() -> None:
    asyncio.run(_security_request_upgrades_concurrent_graceful_close())


async def _security_request_upgrades_concurrent_graceful_close() -> None:
    events: list[str] = []
    generation = _Generation(events)
    hub = _BlockingHub(generation.gate, events)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=hub,  # type: ignore[arg-type]
    )
    retirement = _SecurityRetirement(generation.instance, events)

    graceful = asyncio.create_task(publication.shutdown(quiesce_timeout=1.0))
    await hub.started.wait()
    security = asyncio.create_task(
        publication.security_revoke(
            retirement=retirement,
            quiesce_timeout=1.0,
        )
    )
    await asyncio.sleep(0)
    hub.allow_close.set()
    await asyncio.gather(graceful, security)

    assert events == ["hub-close", "accept", "revoking", "dispose"]
    assert generation.gate.security_closing is True


def test_security_request_during_linearized_disposal_fails_retryably() -> None:
    asyncio.run(_security_request_during_linearized_disposal_fails_retryably())


def test_security_request_after_graceful_close_never_reports_success() -> None:
    asyncio.run(_security_request_after_graceful_close_never_reports_success())


async def _security_request_after_graceful_close_never_reports_success() -> None:
    events: list[str] = []
    generation = _Generation(events)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=_Hub(generation.gate, events),  # type: ignore[arg-type]
    )
    await publication.shutdown(quiesce_timeout=1.0)

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await publication.security_revoke(
            retirement=_SecurityRetirement(generation.instance, events),
        )
    assert caught.value.code == (
        "continuity_provider_security_retirement_after_graceful_close"
    )
    assert events == ["hub-close", "dispose"]


async def _security_request_during_linearized_disposal_fails_retryably() -> None:
    events: list[str] = []
    dispose_started = asyncio.Event()
    allow_dispose = asyncio.Event()
    generation = _Generation(
        events,
        dispose_started=dispose_started,
        allow_dispose=allow_dispose,
    )
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=_Hub(generation.gate, events),  # type: ignore[arg-type]
    )
    graceful = asyncio.create_task(publication.shutdown(quiesce_timeout=1.0))
    await dispose_started.wait()

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await publication.security_revoke(
            retirement=_SecurityRetirement(generation.instance, events),
        )
    assert caught.value.code == "continuity_provider_generation_disposal_in_progress"

    allow_dispose.set()
    await graceful


def test_security_budget_covers_hub_close_and_retries_same_authority() -> None:
    asyncio.run(_security_budget_covers_hub_close_and_retries_same_authority())


def test_security_retirement_requires_exact_generation_member_set() -> None:
    asyncio.run(_security_retirement_requires_exact_generation_member_set())


async def _security_retirement_requires_exact_generation_member_set() -> None:
    events: list[str] = []
    generation = _Generation(events)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=_Hub(generation.gate, events),  # type: ignore[arg-type]
    )
    other = PluginInstanceRevisionRef(
        "other@workspace:test",
        "other",
        1,
    )

    with pytest.raises(ContinuityPluginLifecycleError) as caught:
        await publication.security_revoke(
            retirement=_SecurityRetirement(other, events),
        )
    assert getattr(caught.value, "code", None) == (
        "continuity_provider_security_retirement_set_mismatch"
    )
    assert events == []


async def _security_budget_covers_hub_close_and_retries_same_authority() -> None:
    events: list[str] = []
    generation = _Generation(events)
    hub = _BlockingHub(generation.gate, events)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=object(),  # type: ignore[arg-type]
        hub=hub,  # type: ignore[arg-type]
    )
    retirement = _SecurityRetirement(generation.instance, events)

    with pytest.raises(ContinuityPluginGenerationQuiesceError):
        await publication.security_revoke(
            retirement=retirement,
            quiesce_timeout=0.001,
        )
    assert events == ["accept", "hub-close"]
    assert generation.gate.security_closing is True

    hub.allow_close.set()
    await publication.security_revoke(
        retirement=retirement,
        quiesce_timeout=1.0,
    )
    assert events == ["accept", "hub-close", "hub-close", "revoking", "dispose"]


def test_security_budget_covers_real_hub_product_activation_abort() -> None:
    asyncio.run(_security_budget_covers_real_hub_product_activation_abort())


async def _security_budget_covers_real_hub_product_activation_abort() -> None:
    events: list[str] = []
    generation = _Generation(events)
    product = _HungAbortProductProvider()
    hub = _product_hub(product)
    publication = _create_continuity_plugin_publication(
        generation=generation,  # type: ignore[arg-type]
        composition=hub.composition,
        hub=hub,
    )
    retirement = _SecurityRetirement(generation.instance, events)
    await hub.prepare(product.target)

    with pytest.raises(ContinuityPluginGenerationQuiesceError):
        await publication.security_revoke(
            retirement=retirement,
            quiesce_timeout=0.001,
        )
    assert product.abort_started.is_set()
    assert product.abort_completed is False
    assert events == ["accept"]

    product.allow_abort.set()
    await publication.security_revoke(
        retirement=retirement,
        quiesce_timeout=1.0,
    )
    assert product.abort_completed is True
    assert events == ["accept", "revoking", "dispose"]


def test_instance_ledger_adapter_resolves_exact_active_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _instance_ledger_adapter_resolves_exact_active_revision(
            tmp_path,
            monkeypatch,
        )
    )


async def _instance_ledger_adapter_resolves_exact_active_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = object.__new__(PluginInstanceRuntimeLedger)
    runtime_path = tmp_path / "instance-runtime.jsonl"
    ledger._path = runtime_path  # type: ignore[attr-defined]
    ledger._operation_path = tmp_path / "operations.jsonl"  # type: ignore[attr-defined]
    instance = PluginInstanceRevisionRef("example@workspace:test", "example", 2)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:test",
        plugin_id="example",
    )
    package = PluginPackageRevisionRefV1(
        plugin_id="example",
        plugin_version="2",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity="local:example",
    )
    family = PluginInstanceLeaseFamilyV1.create(
        lease_kind="owner_generation",
        operation_id="acquire",
        idempotency_key="acquire",
        holder_reference="continuity-owner-generation:test",
        parent_family_id=None,
        source_inventory_revision=3,
        member_subjects=((key, instance, package),),
    )
    releases: list[object] = []
    monkeypatch.setattr(
        ledger,
        "snapshot",
        lambda: SimpleNamespace(
            instance=lambda ref: (
                SimpleNamespace(state="ACTIVE", installation_key=key)
                if ref == instance
                else None
            )
        ),
    )

    def acquire(keys, **kwargs):  # type: ignore[no-untyped-def]
        assert keys == (key,)
        assert kwargs["lease_kind"] == "owner_generation"
        assert kwargs["holder_reference"] == "continuity-owner-generation:test"
        return family

    monkeypatch.setattr(ledger, "acquire_current_family", acquire)
    monkeypatch.setattr(ledger, "release_family", releases.append)
    monkeypatch.setattr(
        ledger,
        "bind_security_acceptance_source",
        lambda _source: None,
    )
    package_lifecycle = object.__new__(PluginPackageLifecycleLedger)
    package_lifecycle._path = tmp_path / "packages.jsonl"  # type: ignore[attr-defined]
    package_lifecycle._instance_runtime = ledger  # type: ignore[attr-defined]
    authority = PluginInstanceLedgerContinuityFamilyAuthority(
        ledger=ledger,
        package_lifecycle=package_lifecycle,
        security_acceptance_journal=(
            PluginContinuitySecurityRetirementJournal.for_instance_runtime(runtime_path)
        ),
    )

    lease = await authority.acquire(
        instance,
        holder_reference="continuity-owner-generation:test",
    )
    assert lease.instance_revision_ref == instance
    await lease.close()
    assert len(releases) == 1
    assert releases[0].family_id == family.family_id


@dataclass(slots=True)
class _PreparedImport:
    target: ContinuityTarget
    payload: ContinuityActivationPayload = field(
        default_factory=lambda: ContinuityActivationPayload.from_bytes(
            b"{}\n",
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
        )
    )
    closed: bool = False
    close_failures: int = 0
    close_attempts: int = 0

    async def abort(self) -> None:
        await self.close()

    async def close(self) -> None:
        self.close_attempts += 1
        if self.close_attempts <= self.close_failures:
            raise RuntimeError("secret source close at /private/source")
        self.closed = True


@dataclass(slots=True)
class _PreparedDelete:
    plan: ContinuityDeletionPlanV1
    events: list[str] = field(default_factory=list)
    commit_started: asyncio.Event | None = None
    allow_commit: asyncio.Event | None = None
    abort_failures: int = 0
    close_failures: int = 0
    disposition: str = "applied"
    _receipt: ContinuityDeletionReceiptV1 | None = field(default=None, init=False)

    @property
    def target(self) -> ContinuityTarget:
        return self.plan.target

    async def commit(
        self,
        plan: ContinuityDeletionPlanV1,
    ) -> ContinuityDeletionReceiptV1:
        if self._receipt is None:
            self.events.append("commit")
            if self.commit_started is not None:
                self.commit_started.set()
            if self.allow_commit is not None:
                await self.allow_commit.wait()
            self._receipt = ContinuityDeletionReceiptV1(
                target=plan.target,
                plan_fingerprint=plan.fingerprint,
                disposition=self.disposition,  # type: ignore[arg-type]
            )
        return self._receipt

    async def abort(self) -> None:
        self.events.append("abort")
        if self.abort_failures:
            self.abort_failures -= 1
            raise RuntimeError("secret at /private/delete")

    async def close(self) -> None:
        self.events.append("close")
        if self.close_failures:
            self.close_failures -= 1
            raise RuntimeError("secret at /private/delete-release")


@dataclass(slots=True)
class _Provider:
    target: ContinuityTarget = field(
        default_factory=lambda: ContinuityTarget("plugin.sessions", "one")
    )
    fail_operation: str | None = None
    provider_id: str = "plugin.sessions"
    implementation_version: int = 1
    source_close_failures: int = 0
    prepared: _PreparedImport | None = None
    malformed: str | None = None
    supported_actions: tuple[str, ...] = ("activate",)
    delete_commit_started: asyncio.Event | None = None
    allow_delete_commit: asyncio.Event | None = None
    delete_abort_failures: int = 0
    delete_close_failures: int = 0
    delete_plan: ContinuityDeletionPlanV1 | None = None
    delete_dispositions: list[str] = field(default_factory=list)
    prepared_delete: _PreparedDelete | None = None
    delete_candidates: list[_PreparedDelete] = field(default_factory=list)

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id=self.provider_id,
            experience_id="coding",
            domain_ids=("coding",),
            label="Plugin sessions",
            implementation_version=self.implementation_version,
            supported_actions=self.supported_actions,  # type: ignore[arg-type]
        )

    async def query(self, _request: ProviderQuery) -> ProviderPage:
        if self.fail_operation == "query":
            raise RuntimeError("secret at /private/source")
        page = ProviderPage(
            items=(),
            has_more=False,
            index_state="fresh",
            index_generation="g1",
            query_snapshot="q1",
        )
        if self.malformed == "query_invalid_page":
            return object()  # type: ignore[return-value]
        return page

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        if self.fail_operation == "preview":
            raise RuntimeError("secret at /private/source")
        return ContinuityPreview(
            target=(
                ContinuityTarget(target.provider_id, "other")
                if self.malformed == "preview_wrong_target"
                else target
            ),
            revision=None,
            heading="Plugin session",
            sections=(),
        )

    async def prepare_import(
        self,
        target: ContinuityTarget,
    ) -> _PreparedImport:
        if self.fail_operation == "prepare":
            raise RuntimeError("secret at /private/source")
        if self.malformed == "source_invalid_lease":
            return object()  # type: ignore[return-value]
        self.prepared = _PreparedImport(
            (
                ContinuityTarget(target.provider_id, "other")
                if self.malformed == "source_wrong_target"
                else target
            ),
            close_failures=self.source_close_failures,
        )
        if self.malformed == "source_invalid_payload":
            self.prepared.payload = object()  # type: ignore[assignment]
        return self.prepared

    async def prepare_delete(
        self,
        target: ContinuityTarget,
    ) -> _PreparedDelete:
        disposition = (
            self.delete_dispositions.pop(0) if self.delete_dispositions else "applied"
        )
        self.prepared_delete = _PreparedDelete(
            self.delete_plan or ContinuityDeletionPlanV1(target),
            commit_started=self.delete_commit_started,
            allow_commit=self.allow_delete_commit,
            abort_failures=self.delete_abort_failures,
            close_failures=self.delete_close_failures,
            disposition=disposition,
        )
        self.delete_candidates.append(self.prepared_delete)
        return self.prepared_delete


@dataclass(slots=True)
class _MissingDeleteProvider:
    inner: _Provider = field(
        default_factory=lambda: _Provider(supported_actions=("activate", "delete"))
    )

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return self.inner.descriptor

    async def query(self, request: ProviderQuery) -> ProviderPage:
        return await self.inner.query(request)

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        return await self.inner.preview(target)

    async def prepare_import(self, target: ContinuityTarget) -> _PreparedImport:
        return await self.inner.prepare_import(target)


@dataclass(slots=True)
class _Bridge:
    consume_started: asyncio.Event = field(default_factory=asyncio.Event)
    allow_consume: asyncio.Event = field(default_factory=asyncio.Event)
    aborted: int = 0
    abort_completed: int = 0
    abort_failures: int = 0
    abort_gate: asyncio.Event | None = None
    prepare_gate: asyncio.Event | None = None
    prepare_started: asyncio.Event = field(default_factory=asyncio.Event)
    consume_failure: bool = False
    malformed: str | None = None

    async def prepare(
        self,
        target: ContinuityTarget,
        _payload: ContinuityActivationPayload,
        _source: ContinuityProviderSourceDescriptor,
    ) -> CallbackPreparedActivationLease:
        self.prepare_started.set()
        if self.prepare_gate is not None:
            await self.prepare_gate.wait()
        if self.malformed == "bridge_invalid_lease":
            return object()  # type: ignore[return-value]

        async def consume() -> str:
            self.consume_started.set()
            await self.allow_consume.wait()
            if self.consume_failure:
                raise RuntimeError("synthetic consume failure")
            return "published"

        async def abort() -> None:
            self.aborted += 1
            if self.abort_gate is not None:
                await self.abort_gate.wait()
            if self.aborted <= self.abort_failures:
                raise RuntimeError("synthetic abort failure")
            self.abort_completed += 1

        return CallbackPreparedActivationLease(
            target=(
                ContinuityTarget(target.provider_id, "other")
                if self.malformed == "bridge_wrong_target"
                else target
            ),
            disposition="in_place",
            consume=consume,
            abort=abort,
        )


@dataclass(slots=True)
class _Generation:
    events: list[str]
    gate: ContinuityPluginGenerationGate = field(
        default_factory=ContinuityPluginGenerationGate
    )
    instance: PluginInstanceRevisionRef = field(
        default_factory=lambda: PluginInstanceRevisionRef(
            "example@workspace:test",
            "example",
            1,
        )
    )
    dispose_started: asyncio.Event | None = None
    allow_dispose: asyncio.Event | None = None

    @property
    def resolved(self) -> object:
        candidate = SimpleNamespace(instance_revision_ref=self.instance)
        admission = SimpleNamespace(candidate=candidate)
        component = SimpleNamespace(admission=admission)
        return SimpleNamespace(resolved_set=SimpleNamespace(components=(component,)))

    async def dispose(self) -> None:
        self.events.append("dispose")
        if self.dispose_started is not None:
            self.dispose_started.set()
        if self.allow_dispose is not None:
            await self.allow_dispose.wait()

    def authorize_security_cleanup(
        self,
        _evidence: ContinuityPluginSecurityRetirementEvidence,
    ) -> None:
        return


@dataclass(slots=True)
class _Hub:
    gate: ContinuityPluginGenerationGate
    events: list[str]

    async def close(self) -> None:
        assert self.gate.closing
        self.events.append("hub-close")


@dataclass(slots=True)
class _BlockingHub:
    gate: ContinuityPluginGenerationGate
    events: list[str]
    started: asyncio.Event = field(default_factory=asyncio.Event)
    allow_close: asyncio.Event = field(default_factory=asyncio.Event)

    async def close(self) -> None:
        assert self.gate.closing
        self.events.append("hub-close")
        self.started.set()
        await self.allow_close.wait()


@dataclass(slots=True)
class _HungAbortProductProvider:
    provider_id: str = "product.sessions"
    target: ContinuityTarget = field(
        default_factory=lambda: ContinuityTarget("product.sessions", "one")
    )
    abort_started: asyncio.Event = field(default_factory=asyncio.Event)
    allow_abort: asyncio.Event = field(default_factory=asyncio.Event)
    abort_completed: bool = False

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id=self.provider_id,
            experience_id="coding",
            domain_ids=("coding",),
            primary_domain_id="coding",
            label="Product sessions",
            supported_actions=("activate",),
        )

    async def query(self, _request: ProviderQuery) -> ProviderPage:
        raise AssertionError("query is not used")

    async def preview(self, _target: ContinuityTarget) -> ContinuityPreview:
        raise AssertionError("preview is not used")

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> CallbackPreparedActivationLease:
        async def abort() -> None:
            self.abort_started.set()
            await self.allow_abort.wait()
            self.abort_completed = True

        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=lambda: None,
            abort=abort,
        )


def _product_hub(provider: _HungAbortProductProvider) -> ContinuityHub:
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(product_id="coding", slots=())
    )
    provenance = ResolvedRuntimeSelection(
        selection=RuntimeCapabilitySelection(
            slot="continuity.provider_packs",
            implementation="test-product",
            implementation_version=1,
        ),
        source="product",
        layer_id="product:coding",
        layer_priority=0,
    )
    return ContinuityHub(
        ExperienceComposition(
            experience=ExperienceDescriptor(
                experience_id="coding",
                label="Coding",
                domain_ids=("coding",),
            ),
            capability_profile=profile,
            continuity_providers=(
                BoundContinuityProvider(provider=provider, provenance=provenance),
            ),
        )
    )


@dataclass(slots=True)
class _SecurityRetirement:
    instance: PluginInstanceRevisionRef
    events: list[str]
    accept_gate: asyncio.Event | None = None
    accept_started: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def instance_revision_refs(self) -> tuple[PluginInstanceRevisionRef, ...]:
        return (self.instance,)

    async def accept_revocation(
        self,
    ) -> ContinuityPluginSecurityRetirementEvidence:
        self.events.append("accept")
        self.accept_started.set()
        if self.accept_gate is not None:
            await self.accept_gate.wait()
        return ContinuityPluginSecurityRetirementEvidence._issue(
            self,
            instance_revision_refs=self.instance_revision_refs,
            phase="accepted",
            evidence_fingerprint="a" * 64,
        )

    async def enter_revoking(
        self,
        _acceptance: ContinuityPluginSecurityRetirementEvidence,
    ) -> ContinuityPluginSecurityRetirementEvidence:
        self.events.append("revoking")
        return ContinuityPluginSecurityRetirementEvidence._issue(
            self,
            instance_revision_refs=self.instance_revision_refs,
            phase="revoking",
            evidence_fingerprint="b" * 64,
        )


def _provenance(
    *,
    component_id: str = "plugin:example:sessions",
    plugin_id: str = "example",
    contribution_id: str = "sessions",
    instance_id: str = "example@workspace:test",
    instance_revision: int = 1,
    generation_fingerprint: str = "e" * 64,
    candidate_fingerprint: str = "a" * 64,
    admission_fingerprint: str = "b" * 64,
    selection_plan_fingerprint: str = "c" * 64,
    binding_fingerprint: str = "d" * 64,
    recovery_fingerprint: str | None = None,
    source_trust_policy_revision: str = "trust-1",
    source_trust_class: str = "host-equivalent-local",
    supported_actions: tuple[str, ...] = ("activate",),
) -> PluginContinuityProviderProvenance:
    if recovery_fingerprint is None:
        recovery_fingerprint = hashlib.sha256(
            repr(
                (
                    component_id,
                    plugin_id,
                    contribution_id,
                    instance_id,
                    instance_revision,
                    candidate_fingerprint,
                    admission_fingerprint,
                    selection_plan_fingerprint,
                    binding_fingerprint,
                    source_trust_policy_revision,
                    source_trust_class,
                    supported_actions,
                )
            ).encode("utf-8")
        ).hexdigest()
    return _create_plugin_continuity_provider_provenance(
        component_id=component_id,
        plugin_id=plugin_id,
        contribution_id=contribution_id,
        instance_id=instance_id,
        instance_revision=instance_revision,
        source_trust_class=source_trust_class,
        source_trust_policy_revision=source_trust_policy_revision,
        supported_actions=supported_actions,
        candidate_fingerprint=candidate_fingerprint,
        admission_fingerprint=admission_fingerprint,
        selection_plan_fingerprint=selection_plan_fingerprint,
        binding_fingerprint=binding_fingerprint,
        recovery_fingerprint=recovery_fingerprint,
        generation_fingerprint=generation_fingerprint,
    )


def _mutation_provenance(
    *,
    component_id: str = "plugin:example:sessions",
    plugin_id: str = "example",
    contribution_id: str = "sessions",
    instance_id: str = "example@workspace:test",
    instance_revision: int = 1,
    generation_fingerprint: str = "e" * 64,
    candidate_fingerprint: str = "a" * 64,
    admission_fingerprint: str = "b" * 64,
    selection_plan_fingerprint: str = "c" * 64,
    binding_fingerprint: str = "d" * 64,
    recovery_fingerprint: str | None = None,
    source_trust_policy_revision: str = "trust-1",
    source_trust_class: str = "host-equivalent-local",
) -> PluginContinuityProviderProvenance:
    return _provenance(
        component_id=component_id,
        plugin_id=plugin_id,
        contribution_id=contribution_id,
        instance_id=instance_id,
        instance_revision=instance_revision,
        generation_fingerprint=generation_fingerprint,
        candidate_fingerprint=candidate_fingerprint,
        admission_fingerprint=admission_fingerprint,
        selection_plan_fingerprint=selection_plan_fingerprint,
        binding_fingerprint=binding_fingerprint,
        recovery_fingerprint=recovery_fingerprint,
        source_trust_policy_revision=source_trust_policy_revision,
        source_trust_class=source_trust_class,
        supported_actions=("activate", "delete"),
    )
