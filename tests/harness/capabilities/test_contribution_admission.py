from __future__ import annotations

import pytest

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAdmissionError,
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_exact_owner_admits_resource_and_catalog_consumer_without_widening() -> None:
    resource = _candidate(
        ResourceContributionSpec(
            resource_kind="skill",
            locator="skills/review/SKILL.md",
            locator_kind="file",
            media_type="text/markdown",
            schema_id="loushang.skill",
            schema_version=1,
        ),
        owner_id="product.resources",
        contribution_id="review-skill",
    )
    tool = _candidate(
        CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("semantic.lookup",),
            requirements=(
                CapabilityRequirement(
                    capability="synthetic.semantic",
                    facets=("query",),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
        ),
        owner_id="product.tools",
        contribution_id="semantic-tools",
    )

    resource_admission = _authority(
        owner_id="product.resources",
        contribution_kind="resource_item",
        allowed_collection_ids=("loushang.skill",),
    ).admit(resource, issued_at=100, expires_at=200)
    tool_admission = _authority(
        owner_id="product.tools",
        contribution_kind="tool_pack",
        allowed_collection_ids=("product.tools",),
    ).admit(tool, issued_at=100, expires_at=200)

    assert resource_admission.admitted_identities == (
        "loushang.skill:skills/review/SKILL.md",
    )
    assert resource_admission.requirements == ()
    assert tool_admission.admitted_identities == (
        "product.tools:semantic.lookup",
    )
    assert tool_admission.requirements == tool.contribution.requirements
    assert tool_admission.to_dict()["candidate"]["sourceTrusted"] is True


def test_owner_records_are_closed_and_cross_owner_or_kind_fails_closed() -> None:
    with pytest.raises(TypeError, match="owner-constructed"):
        OwnerContributionAdmissionRecord()

    candidate = _candidate(
        CatalogConsumerContributionSpec(
            contribution_kind="command_pack",
            catalog_id="product.commands",
            catalog_revision=1,
            item_ids=("inspect",),
        ),
        owner_id="product.commands",
        contribution_id="inspect-commands",
    )
    wrong_owner = _authority(
        owner_id="other.commands",
        contribution_kind="command_pack",
        allowed_collection_ids=("product.commands",),
    )
    with pytest.raises(OwnerContributionAdmissionError) as owner_error:
        wrong_owner.admit(candidate, issued_at=100, expires_at=200)
    assert owner_error.value.code == "contribution_owner_mismatch"

    wrong_kind = _authority(
        owner_id="product.commands",
        contribution_kind="tool_pack",
        allowed_collection_ids=("product.commands",),
    )
    with pytest.raises(OwnerContributionAdmissionError) as kind_error:
        wrong_kind.admit(candidate, issued_at=100, expires_at=200)
    assert kind_error.value.code == "contribution_kind_mismatch"


def test_owner_rechecks_product_trust_collection_binding_and_interval() -> None:
    requirement = CapabilityRequirement(
        capability="synthetic.semantic",
        facets=("query",),
        compatible_contract=CapabilityContractRange.exact(1),
        binding="stable_reference",
    )
    candidate = _candidate(
        CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("semantic.lookup",),
            requirements=(requirement,),
        ),
        owner_id="product.tools",
        contribution_id="semantic-tools",
    )
    authority = _authority(
        owner_id="product.tools",
        contribution_kind="tool_pack",
        allowed_collection_ids=("product.tools",),
    )

    with pytest.raises(OwnerContributionAdmissionError) as binding_error:
        authority.admit(candidate, issued_at=100, expires_at=200)
    assert binding_error.value.code == "contribution_requirement_binding_denied"

    with pytest.raises(OwnerContributionAdmissionError) as product_error:
        _authority(
            owner_id="product.tools",
            contribution_kind="tool_pack",
            allowed_collection_ids=("product.tools",),
            product_id="other-product",
            allowed_requirement_bindings=("stable_reference",),
        ).admit(candidate, issued_at=100, expires_at=200)
    assert product_error.value.code == "contribution_product_mismatch"

    untrusted = _candidate(
        candidate.contribution,
        owner_id="product.tools",
        contribution_id="semantic-tools",
        source_trusted=False,
    )
    with pytest.raises(OwnerContributionAdmissionError) as trust_error:
        _authority(
            owner_id="product.tools",
            contribution_kind="tool_pack",
            allowed_collection_ids=("product.tools",),
            allowed_requirement_bindings=("stable_reference",),
        ).admit(untrusted, issued_at=100, expires_at=200)
    assert trust_error.value.code == "contribution_source_untrusted"


def _candidate(
    contribution: ResourceContributionSpec | CatalogConsumerContributionSpec,
    *,
    owner_id: str,
    contribution_id: str,
    source_trusted: bool = True,
) -> OwnerContributionCandidateEnvelope:
    return OwnerContributionCandidateEnvelope(
        owner_id=owner_id,
        plugin_id="foundation-sample",
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
            instance_id="foundation-sample@workspace:sample",
            plugin_id="foundation-sample",
            revision=1,
        ),
        package_source_identity="local:foundation-sample",
        source_trust_class="first_party",
        source_trust_policy_revision="trust-1",
        source_trusted=source_trusted,
    )


def _authority(
    *,
    owner_id: str,
    contribution_kind: str,
    allowed_collection_ids: tuple[str, ...],
    product_id: str = "coding",
    allowed_requirement_bindings: tuple[str, ...] = ("direct",),
) -> OwnerContributionAuthority:
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=owner_id,
            contribution_kind=contribution_kind,
            product_id=product_id,
            policy_revision="owner-policy-1",
            revocation_epoch=0,
            allowed_source_trust_classes=("first_party",),
            allowed_collection_ids=allowed_collection_ids,
            allowed_requirement_bindings=allowed_requirement_bindings,
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    )
