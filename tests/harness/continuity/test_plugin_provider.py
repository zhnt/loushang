from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.continuity import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    CallbackPreparedActivationLease,
    ContinuityActivationPayload,
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
)
from loushang.harness.continuity.plugin_provider import (
    ContinuityPluginGenerationClosingError,
    ContinuityPluginGenerationGate,
    ContinuityPluginGenerationQuiesceError,
    ContinuityPluginProviderCallError,
    PluginContinuityProvider,
)
from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginGeneration,
    ContinuityPluginLifecycleError,
    ContinuityPluginPublication,
    ContinuityPluginSecurityRetirementEvidence,
    ResolvedContinuityPluginSelection,
    _create_continuity_plugin_publication,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
    PluginInstanceLedgerContinuityFamilyAuthority,
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
            PluginContinuitySecurityRetirementJournal.for_instance_runtime(
                runtime_path
            )
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
class _Provider:
    target: ContinuityTarget = field(
        default_factory=lambda: ContinuityTarget("plugin.sessions", "one")
    )
    fail_operation: str | None = None
    source_close_failures: int = 0
    prepared: _PreparedImport | None = None
    malformed: str | None = None

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id="plugin.sessions",
            experience_id="coding",
            domain_ids=("coding",),
            label="Plugin sessions",
            supported_actions=("activate",),
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


def _provenance() -> PluginContinuityProviderProvenance:
    return _create_plugin_continuity_provider_provenance(
        component_id="plugin:example:sessions",
        plugin_id="example",
        contribution_id="sessions",
        instance_id="example@workspace:test",
        instance_revision=1,
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        candidate_fingerprint="a" * 64,
        admission_fingerprint="b" * 64,
        selection_plan_fingerprint="c" * 64,
        binding_fingerprint="d" * 64,
        generation_fingerprint="e" * 64,
    )
