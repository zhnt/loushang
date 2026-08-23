from __future__ import annotations

import asyncio

import pytest

from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityOwnerGenerationBinding,
    SessionCapabilityOwnerGenerationStagingError,
    dispose_session_capability_owner_generations,
    stage_session_capability_owner_generations,
)


def test_owner_staging_preserves_generation_when_rollback_must_be_retried() -> None:
    asyncio.run(_owner_staging_preserves_generation_when_rollback_must_be_retried())


async def _owner_staging_preserves_generation_when_rollback_must_be_retried() -> None:
    first = _admission(owner_id="product.tools", contribution_id="tools-a")
    second = _admission(owner_id="product.tools", contribution_id="tools-b")
    disposal_attempts = 0

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
            stage=lambda _captures: object(),
            dispose=dispose_first,
        ),
        SessionCapabilityOwnerGenerationBinding(
            owner_id=second.owner_id,
            contribution_kind=second.contribution_kind,
            plugin_id=second.plugin_id,
            contribution_id=second.contribution_id,
            admission_fingerprint=second.fingerprint,
            stage=fail_second,
            dispose=lambda _value: None,
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
