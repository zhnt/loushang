from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
)
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
    SessionCapabilityOwnerGenerationStagingError,
    StagedSessionCapabilityOwnerGeneration,
    commit_session_capability_owner_generations,
    dispose_session_capability_owner_generations,
    stage_session_capability_owner_generations,
)


def test_owner_binding_requires_explicit_transaction_callbacks() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")

    with pytest.raises(TypeError, match="commit"):
        SessionCapabilityOwnerGenerationBinding(  # type: ignore[call-arg]
            owner_id=admission.owner_id,
            contribution_kind=admission.contribution_kind,
            plugin_id=admission.plugin_id,
            contribution_id=admission.contribution_id,
            admission_fingerprint=admission.fingerprint,
            authority_gate=_authority_gate(admission),
            stage=lambda _captures: object(),
            dispose=lambda _value: None,
        )


def test_owner_commit_rolls_back_every_attempted_generation_in_reverse() -> None:
    asyncio.run(_owner_commit_rolls_back_every_attempted_generation_in_reverse())


async def _owner_commit_rolls_back_every_attempted_generation_in_reverse() -> None:
    first = _admission(owner_id="product.tools", contribution_id="tools-a")
    second = _admission(owner_id="product.tools", contribution_id="tools-b")
    events: list[str] = []
    authority_gate = _authority_gate(first, second)

    def fail_second(_value: object) -> None:
        events.append("commit:tools-b")
        raise RuntimeError("synthetic second owner commit failure")

    bindings = (
        SessionCapabilityOwnerGenerationBinding(
            owner_id=first.owner_id,
            contribution_kind=first.contribution_kind,
            plugin_id=first.plugin_id,
            contribution_id=first.contribution_id,
            admission_fingerprint=first.fingerprint,
            authority_gate=authority_gate,
            stage=lambda _captures: object(),
            dispose=lambda _value: None,
            retirement_receipt=_retirement_receipt(first),
            commit=lambda _value: events.append("commit:tools-a"),
            rollback_commit=lambda _value: events.append("rollback:tools-a"),
        ),
        SessionCapabilityOwnerGenerationBinding(
            owner_id=second.owner_id,
            contribution_kind=second.contribution_kind,
            plugin_id=second.plugin_id,
            contribution_id=second.contribution_id,
            admission_fingerprint=second.fingerprint,
            authority_gate=authority_gate,
            stage=lambda _captures: object(),
            dispose=lambda _value: None,
            retirement_receipt=_retirement_receipt(second),
            commit=fail_second,
            rollback_commit=lambda _value: events.append("rollback:tools-b"),
        ),
    )
    generations = await stage_session_capability_owner_generations(
        admissions=(first, second),
        bindings=bindings,
        captures=(),
    )

    with pytest.raises(RuntimeError, match="second owner commit"):
        commit_session_capability_owner_generations(generations)

    assert events == [
        "commit:tools-a",
        "commit:tools-b",
        "rollback:tools-b",
        "rollback:tools-a",
    ]
    assert all(not item.committed and not item.commit_started for item in generations)


def test_later_commit_batch_does_not_rollback_an_existing_generation() -> None:
    asyncio.run(_later_commit_batch_does_not_rollback_an_existing_generation())


async def _later_commit_batch_does_not_rollback_an_existing_generation() -> None:
    first = _admission(owner_id="product.tools", contribution_id="tools-a")
    second = _admission(owner_id="product.tools", contribution_id="tools-b")
    events: list[str] = []
    authority_gate = _authority_gate(first, second)

    def fail_second(_value: object) -> None:
        events.append("commit:tools-b")
        raise RuntimeError("synthetic later batch failure")

    bindings = (
        SessionCapabilityOwnerGenerationBinding(
            owner_id=first.owner_id,
            contribution_kind=first.contribution_kind,
            plugin_id=first.plugin_id,
            contribution_id=first.contribution_id,
            admission_fingerprint=first.fingerprint,
            authority_gate=authority_gate,
            stage=lambda _captures: object(),
            dispose=lambda _value: None,
            retirement_receipt=_retirement_receipt(first),
            commit=lambda _value: events.append("commit:tools-a"),
            rollback_commit=lambda _value: events.append("rollback:tools-a"),
        ),
        SessionCapabilityOwnerGenerationBinding(
            owner_id=second.owner_id,
            contribution_kind=second.contribution_kind,
            plugin_id=second.plugin_id,
            contribution_id=second.contribution_id,
            admission_fingerprint=second.fingerprint,
            authority_gate=authority_gate,
            stage=lambda _captures: object(),
            dispose=lambda _value: None,
            retirement_receipt=_retirement_receipt(second),
            commit=fail_second,
            rollback_commit=lambda _value: events.append("rollback:tools-b"),
        ),
    )
    generations = await stage_session_capability_owner_generations(
        admissions=(first, second),
        bindings=bindings,
        captures=(),
    )
    by_contribution = {
        item.binding.contribution_id: item for item in generations
    }
    first_generation = by_contribution["tools-a"]
    second_generation = by_contribution["tools-b"]
    commit_session_capability_owner_generations((first_generation,))

    with pytest.raises(RuntimeError, match="later batch failure"):
        commit_session_capability_owner_generations(
            (first_generation, second_generation)
        )

    assert events == [
        "commit:tools-a",
        "commit:tools-b",
        "rollback:tools-b",
    ]
    assert first_generation.committed is True
    assert first_generation.commit_started is True
    assert second_generation.committed is False
    assert second_generation.commit_started is False


def test_owner_commit_rejects_async_publication_callback() -> None:
    asyncio.run(_owner_commit_rejects_async_publication_callback())


def test_owner_commit_revalidates_authority_after_async_staging() -> None:
    asyncio.run(_owner_commit_revalidates_authority_after_async_staging())


async def _owner_commit_revalidates_authority_after_async_staging() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")
    now = [150]
    gate = replace(_authority_gate(admission), clock=lambda: now[0])
    published: list[object] = []
    binding = SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=gate,
        stage=lambda _captures: asyncio.sleep(0, result=object()),
        dispose=lambda _value: None,
        retirement_receipt=_retirement_receipt(admission),
        commit=published.append,
        rollback_commit=lambda _value: None,
    )
    generations = await stage_session_capability_owner_generations(
        admissions=(admission,),
        bindings=(binding,),
        captures=(),
    )
    now[0] = 201

    with pytest.raises(ValueError, match="not current"):
        commit_session_capability_owner_generations(generations)

    assert published == []
    assert generations[0].commit_started is False
    assert generations[0].committed is False


async def _owner_commit_rejects_async_publication_callback() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")

    async def invalid_commit(_value: object) -> None:
        raise AssertionError("async commit body must never run")

    binding = SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=_authority_gate(admission),
        stage=lambda _captures: object(),
        dispose=lambda _value: None,
        retirement_receipt=_retirement_receipt(admission),
        commit=invalid_commit,  # type: ignore[arg-type]
        rollback_commit=lambda _value: None,
    )
    generations = await stage_session_capability_owner_generations(
        admissions=(admission,),
        bindings=(binding,),
        captures=(),
    )

    with pytest.raises(TypeError, match="commit must be synchronous"):
        commit_session_capability_owner_generations(generations)

    assert generations[0].committed is False
    assert generations[0].commit_started is False


def test_owner_commit_rejects_non_none_publication_result() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")
    binding = SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=_authority_gate(admission),
        stage=lambda _captures: object(),
        dispose=lambda _value: None,
        retirement_receipt=_retirement_receipt(admission),
        commit=lambda _value: "invalid",  # type: ignore[arg-type,return-value]
        rollback_commit=lambda _value: None,
    )
    generation = StagedSessionCapabilityOwnerGeneration(
        binding=binding,
        admission=admission,
        value=object(),
    )

    with pytest.raises(TypeError, match="commit must return None"):
        commit_session_capability_owner_generations((generation,))

    assert generation.committed is False
    assert generation.commit_started is False


def test_owner_rollback_rejects_async_publication_callback() -> None:
    asyncio.run(_owner_rollback_rejects_async_publication_callback())


async def _owner_rollback_rejects_async_publication_callback() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")

    async def invalid_rollback(_value: object) -> None:
        raise AssertionError("async rollback body must never run")

    binding = SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=_authority_gate(admission),
        stage=lambda _captures: object(),
        dispose=lambda _value: None,
        retirement_receipt=_retirement_receipt(admission),
        commit=lambda _value: None,
        rollback_commit=invalid_rollback,  # type: ignore[arg-type]
    )
    generations = await stage_session_capability_owner_generations(
        admissions=(admission,),
        bindings=(binding,),
        captures=(),
    )
    [generation] = generations
    generation.commit_once()

    with pytest.raises(TypeError, match="rollback commit must be synchronous"):
        generation.rollback_commit_once()

    assert generation.committed is True
    assert generation.commit_started is True


def test_owner_staging_preserves_generation_when_rollback_must_be_retried() -> None:
    asyncio.run(_owner_staging_preserves_generation_when_rollback_must_be_retried())


async def _owner_staging_preserves_generation_when_rollback_must_be_retried() -> None:
    first = _admission(owner_id="product.tools", contribution_id="tools-a")
    second = _admission(owner_id="product.tools", contribution_id="tools-b")
    disposal_attempts = 0
    authority_gate = _authority_gate(first, second)

    async def dispose_first(_value: object) -> None:
        nonlocal disposal_attempts
        disposal_attempts += 1
        if disposal_attempts == 1:
            raise RuntimeError("synthetic transient owner cleanup failure")

    async def fail_second(_captures: tuple[object, ...]) -> object:
        raise RuntimeError("synthetic second owner staging failure")

    bindings = (
        SessionCapabilityOwnerGenerationBinding(
            owner_id=first.owner_id,
            contribution_kind=first.contribution_kind,
            plugin_id=first.plugin_id,
            contribution_id=first.contribution_id,
            admission_fingerprint=first.fingerprint,
            authority_gate=authority_gate,
            stage=lambda _captures: object(),
            dispose=dispose_first,
            retirement_receipt=_retirement_receipt(first),
            commit=lambda _value: None,
            rollback_commit=lambda _value: None,
        ),
        SessionCapabilityOwnerGenerationBinding(
            owner_id=second.owner_id,
            contribution_kind=second.contribution_kind,
            plugin_id=second.plugin_id,
            contribution_id=second.contribution_id,
            admission_fingerprint=second.fingerprint,
            authority_gate=authority_gate,
            stage=fail_second,
            dispose=lambda _value: None,
            retirement_receipt=_retirement_receipt(second),
            commit=lambda _value: None,
            rollback_commit=lambda _value: None,
        ),
    )

    with pytest.raises(SessionCapabilityOwnerGenerationStagingError) as caught:
        await stage_session_capability_owner_generations(
            admissions=(first, second),
            bindings=bindings,
            captures=(),
        )

    pending = caught.value.pending_generations
    assert len(pending) == 1
    assert pending[0].binding.admission_fingerprint == first.fingerprint
    assert pending[0].disposed is False
    await dispose_session_capability_owner_generations(pending)
    assert pending[0].disposed is True
    assert disposal_attempts == 2


def test_owner_staging_rechecks_expiry_before_live_generation() -> None:
    asyncio.run(_owner_staging_rechecks_expiry_before_live_generation())


async def _owner_staging_rechecks_expiry_before_live_generation() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")
    staged = False

    def stage(_captures: tuple[object, ...]) -> object:
        nonlocal staged
        staged = True
        return object()

    binding = SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=_authority_gate(admission, now=200),
        stage=stage,
        dispose=lambda _value: None,
        retirement_receipt=_retirement_receipt(admission),
        commit=lambda _value: None,
        rollback_commit=lambda _value: None,
    )

    with pytest.raises(ValueError, match="not current"):
        await stage_session_capability_owner_generations(
            admissions=(admission,),
            bindings=(binding,),
            captures=(),
        )
    assert staged is False


def test_owner_authority_gate_rejects_wrong_current_snapshot_identities() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")
    wrong = _admission(owner_id="product.tools.other", contribution_id="tools-b")
    gate = _authority_gate(admission)
    wrong_candidate = wrong.candidate
    wrong_owner = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=wrong.owner_id,
            contribution_kind=wrong.contribution_kind,
            product_id=wrong.product_id,
            policy_revision=admission.owner_policy_revision,
            revocation_epoch=admission.revocation_epoch,
            allowed_source_trust_classes=(wrong_candidate.source_trust_class,),
            allowed_collection_ids=(wrong_candidate.contribution.collection_id,),
            allowed_requirement_bindings=("direct",),
            consumer_scope=wrong.consumer_scope,
            consumer_refresh_boundary=wrong.consumer_refresh_boundary,
        )
    ).snapshot()
    wrong_trust = PluginSourceTrustSnapshotV1(
        plugin_id=wrong.plugin_id,
        package_source_identity=wrong_candidate.package_source_identity,
        source_trust_class=admission.candidate.source_trust_class,
        source_trust_policy_revision=(
            admission.candidate.source_trust_policy_revision
        ),
        trusted=True,
    )

    with pytest.raises(ValueError, match="identity"):
        replace(
            gate,
            owner_snapshot_reader=lambda _owner, _kind, _product: wrong_owner,
            trust_snapshot_reader=lambda _plugin, _source: wrong_trust,
        ).validate(admission)


def test_owner_generation_disposal_is_single_flight() -> None:
    asyncio.run(_owner_generation_disposal_is_single_flight())


async def _owner_generation_disposal_is_single_flight() -> None:
    admission = _admission(owner_id="product.tools", contribution_id="tools-a")
    started = asyncio.Event()
    release = asyncio.Event()
    attempts = 0

    async def dispose(_value: object) -> None:
        nonlocal attempts
        attempts += 1
        started.set()
        await release.wait()

    binding = SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=_authority_gate(admission),
        stage=lambda _captures: object(),
        dispose=dispose,
        retirement_receipt=_retirement_receipt(admission),
        commit=lambda _value: None,
        rollback_commit=lambda _value: None,
    )
    generation = StagedSessionCapabilityOwnerGeneration(
        binding=binding,
        admission=admission,
        value=object(),
    )
    first = asyncio.create_task(generation.dispose_once())
    await started.wait()
    second = asyncio.create_task(generation.dispose_once())
    await asyncio.sleep(0)
    assert attempts == 1
    release.set()
    await asyncio.gather(first, second)
    assert generation.disposed is True
    assert attempts == 1


def _retirement_receipt(admission):  # type: ignore[no-untyped-def]
    return lambda _value: OwnerGenerationRetirementReceipt(
        owner_reference=f"owner:{admission.owner_id}",
        owner_generation_reference=f"generation:{admission.fingerprint}",
        retirement_handle=f"retirement:{admission.fingerprint}",
        contribution_ids=(admission.contribution_id,),
    )


def _admission(*, owner_id: str, contribution_id: str):  # type: ignore[no-untyped-def]
    contribution = CatalogConsumerContributionSpec(
        contribution_kind="tool_pack",
        catalog_id=owner_id,
        catalog_revision=1,
        item_ids=(contribution_id,),
    )
    candidate = OwnerContributionCandidateEnvelope(
        owner_id=owner_id,
        plugin_id=f"plugin-{contribution_id}",
        contribution_id=contribution_id,
        contribution=contribution,
        plugin_candidate_fingerprint="1" * 64,
        declaration_fingerprint="2" * 64,
        declaration_evidence_fingerprint="3" * 64,
        package_content_digest="4" * 64,
        dependency_lock_digest="5" * 64,
        product_id="coding",
        scope_id="workspace:sample",
        product_policy_revision="product-policy-1",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id=f"plugin-{contribution_id}@workspace:sample",
            plugin_id=f"plugin-{contribution_id}",
            revision=1,
        ),
        package_source_identity=f"local:plugin-{contribution_id}",
        source_trust_class="first_party",
        source_trust_policy_revision="trust-1",
        source_trusted=True,
    )
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=owner_id,
            contribution_kind="tool_pack",
            product_id="coding",
            policy_revision="owner-policy-1",
            revocation_epoch=0,
            allowed_source_trust_classes=("first_party",),
            allowed_collection_ids=(owner_id,),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(candidate, issued_at=100, expires_at=200)


def _authority_gate(*admissions, now: int = 150):  # type: ignore[no-untyped-def]
    snapshots = {}
    trust_snapshots = {}
    for admission in admissions:
        candidate = admission.candidate
        authority = OwnerContributionAuthority(
            OwnerContributionPolicy(
                owner_id=admission.owner_id,
                contribution_kind=admission.contribution_kind,
                product_id=admission.product_id,
                policy_revision=admission.owner_policy_revision,
                revocation_epoch=admission.revocation_epoch,
                allowed_source_trust_classes=(candidate.source_trust_class,),
                allowed_collection_ids=(candidate.contribution.collection_id,),
                allowed_requirement_bindings=("direct",),
                consumer_scope=admission.consumer_scope,
                consumer_refresh_boundary=admission.consumer_refresh_boundary,
            )
        )
        snapshots[
            (admission.owner_id, admission.contribution_kind, admission.product_id)
        ] = authority.snapshot()
        trust = PluginSourceTrustSnapshotV1(
            plugin_id=admission.plugin_id,
            package_source_identity=candidate.package_source_identity,
            source_trust_class=candidate.source_trust_class,
            source_trust_policy_revision=candidate.source_trust_policy_revision,
            trusted=True,
        )
        trust_snapshots[(admission.plugin_id, candidate.package_source_identity)] = trust
    context = ProductCompositionAuthorityContext(
        product_id="coding",
        scope_id="workspace:sample",
        product_policy_revision="product-policy-1",
        evaluated_at=150,
        owner_snapshots=tuple(snapshots.values()),
        trust_snapshots=tuple(trust_snapshots.values()),
    )
    return SessionCapabilityOwnerAuthorityGate(
        authority_context=context,
        owner_snapshot_reader=lambda owner, kind, product: snapshots[
            (owner, kind, product)
        ],
        trust_snapshot_reader=lambda plugin, source: trust_snapshots[
            (plugin, source)
        ],
        product_policy_revision_reader=(
            lambda _product, _scope: "product-policy-1"
        ),
        clock=lambda: now,
    )
