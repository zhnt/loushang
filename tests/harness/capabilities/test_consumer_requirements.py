from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.harness.capabilities.consumer_requirements import (
    ProductCapabilityOptionalRequirementChoice,
    ProductCompositionAuthorityContext,
    ProductCompositionCompiler,
    ProductCompositionError,
)
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)


def test_compiler_preserves_per_consumer_requirements_and_explicit_optional_roots() -> None:
    required = _admission(
        owner_id="product.tools",
        contribution_id="query-tools",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("query",),
            requirements=(_requirement("synthetic.query", "query"),),
        ),
    )
    optional = _admission(
        owner_id="product.commands",
        contribution_id="index-commands",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="command_pack",
            catalog_id="product.commands",
            catalog_revision=1,
            item_ids=("index",),
            requirements=(
                _requirement("synthetic.index", "status", optional=True),
            ),
        ),
    )
    resource = _admission(
        owner_id="product.resources",
        contribution_id="review-skill",
        contribution=ResourceContributionSpec(
            resource_kind="skill",
            locator="skills/review/SKILL.md",
            locator_kind="file",
            media_type="text/markdown",
            schema_id="loushang.skill",
            schema_version=1,
        ),
    )
    preview = ProductCompositionCompiler().preview_optional_choices(
        authority_context=_context(required, optional, resource),
        mandatory_roots=("harness.model_input",),
        admissions=(required, optional, resource),
        definitions=_definitions(),
    )
    [optional_entry] = preview.optional_entries
    compiled = ProductCompositionCompiler().compile(
        authority_context=_context(required, optional, resource),
        mandatory_roots=("harness.model_input",),
        admissions=(required, optional, resource),
        definitions=_definitions(),
        optional_choices=(
            ProductCapabilityOptionalRequirementChoice(
                requirement_fingerprint=optional_entry.fingerprint,
                satisfied=True,
            ),
        ),
    )

    assert compiled.resource_admissions == (resource,)
    assert compiled.consumer_requirements.roots == (
        "harness.model_input",
        "synthetic.index",
        "synthetic.query",
    )
    assert {
        entry.admission_fingerprint
        for entry in compiled.consumer_requirements.entries
    } == {required.fingerprint, optional.fingerprint}
    assert compiled.consumer_requirements.satisfied_entries == (
        *compiled.consumer_requirements.entries,
    )


def test_optional_requirement_requires_one_exact_choice_and_unsatisfied_adds_no_root() -> None:
    optional = _admission(
        owner_id="product.tools",
        contribution_id="optional-tools",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("optional",),
            requirements=(
                _requirement("synthetic.index", "status", optional=True),
            ),
        ),
    )
    compiler = ProductCompositionCompiler()
    preview = compiler.preview_optional_choices(
        authority_context=_context(optional),
        mandatory_roots=("harness.model_input",),
        admissions=(optional,),
        definitions=_definitions(),
    )
    [entry] = preview.optional_entries

    with pytest.raises(ProductCompositionError) as missing:
        compiler.compile(
            authority_context=_context(optional),
            mandatory_roots=("harness.model_input",),
            admissions=(optional,),
            definitions=_definitions(),
            optional_choices=(),
        )
    assert missing.value.code == "missing_optional_consumer_decision"

    compiled = compiler.compile(
        authority_context=_context(optional),
        mandatory_roots=("harness.model_input",),
        admissions=(optional,),
        definitions=_definitions(),
        optional_choices=(
            ProductCapabilityOptionalRequirementChoice(
                requirement_fingerprint=entry.fingerprint,
                satisfied=False,
            ),
        ),
    )
    assert compiled.consumer_requirements.roots == ("harness.model_input",)
    assert compiled.consumer_requirements.satisfied_entries == ()


def test_duplicate_owner_identity_and_incompatible_requirement_fail_with_provenance() -> None:
    first = _admission(
        owner_id="product.tools",
        contribution_id="tools-a",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("query",),
        ),
    )
    duplicate = _admission(
        owner_id="product.tools",
        contribution_id="tools-b",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("query",),
        ),
    )
    with pytest.raises(ProductCompositionError) as duplicated:
        ProductCompositionCompiler().compile(
            authority_context=_context(first, duplicate),
            mandatory_roots=("harness.model_input",),
            admissions=(first, duplicate),
            definitions=_definitions(),
            optional_choices=(),
        )
    assert duplicated.value.code == "duplicate_owner_contribution_identity"
    assert duplicated.value.admission_fingerprints == tuple(
        sorted((first.fingerprint, duplicate.fingerprint))
    )

    incompatible = _admission(
        owner_id="product.tools",
        contribution_id="bad-tools",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("bad",),
            requirements=(_requirement("synthetic.query", "missing"),),
        ),
    )
    with pytest.raises(ProductCompositionError) as mismatch:
        ProductCompositionCompiler().compile(
            authority_context=_context(incompatible),
            mandatory_roots=("harness.model_input",),
            admissions=(incompatible,),
            definitions=_definitions(),
            optional_choices=(),
        )
    assert mismatch.value.code == "consumer_requirement_facet_mismatch"
    assert mismatch.value.admission_fingerprints == (incompatible.fingerprint,)


def test_compiler_rejects_cross_scope_and_expired_owner_admission() -> None:
    admission = _admission(
        owner_id="product.tools",
        contribution_id="query-tools",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product.tools",
            catalog_revision=1,
            item_ids=("query",),
        ),
    )
    compiler = ProductCompositionCompiler()
    context = _context(admission)

    with pytest.raises(ProductCompositionError) as wrong_scope:
        compiler.compile(
            authority_context=replace(context, scope_id="workspace:other"),
            mandatory_roots=("harness.model_input",),
            admissions=(admission,),
            definitions=_definitions(),
            optional_choices=(),
        )
    assert wrong_scope.value.code == "contribution_admission_scope_mismatch"

    with pytest.raises(ProductCompositionError) as expired:
        compiler.compile(
            authority_context=replace(context, evaluated_at=200),
            mandatory_roots=("harness.model_input",),
            admissions=(admission,),
            definitions=_definitions(),
            optional_choices=(),
        )
    assert expired.value.code == "contribution_admission_not_current"


def test_compiler_rejects_public_catalog_identity_owned_by_two_owners() -> None:
    first = _admission(
        owner_id="product.tools.a",
        contribution_id="tools-a",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product-a.tools",
            catalog_revision=1,
            item_ids=("query",),
        ),
    )
    second = _admission(
        owner_id="product.tools.b",
        contribution_id="tools-b",
        contribution=CatalogConsumerContributionSpec(
            contribution_kind="tool_pack",
            catalog_id="product-b.tools",
            catalog_revision=1,
            item_ids=("query",),
        ),
    )

    with pytest.raises(ProductCompositionError) as caught:
        ProductCompositionCompiler().compile(
            authority_context=_context(first, second),
            mandatory_roots=("harness.model_input",),
            admissions=(first, second),
            definitions=_definitions(),
            optional_choices=(),
        )

    assert caught.value.code == "duplicate_owner_contribution_identity"
    assert caught.value.admission_fingerprints == tuple(
        sorted((first.fingerprint, second.fingerprint))
    )


def _requirement(
    capability: str,
    facet: str,
    *,
    optional: bool = False,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        capability=capability,
        facets=(facet,),
        compatible_contract=CapabilityContractRange.exact(1),
        optional=optional,
    )


def _definitions() -> tuple[CapabilityDefinition, ...]:
    return (
        CapabilityDefinition(
            capability_id="harness.model_input",
            owner_id="harness",
            contract_version=1,
            facets=("prepare",),
            scope="session",
            refresh_boundary="sealed",
            phase="final",
        ),
        CapabilityDefinition(
            capability_id="synthetic.index",
            owner_id="synthetic",
            contract_version=1,
            facets=("status",),
            scope="session",
            refresh_boundary="sealed",
            phase="final",
        ),
        CapabilityDefinition(
            capability_id="synthetic.query",
            owner_id="synthetic",
            contract_version=1,
            facets=("query",),
            scope="session",
            refresh_boundary="sealed",
            phase="final",
        ),
    )


def _admission(
    *,
    owner_id: str,
    contribution_id: str,
    contribution: ResourceContributionSpec | CatalogConsumerContributionSpec,
):
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
    collection_id = contribution.collection_id
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=owner_id,
            contribution_kind=contribution.contribution_kind,
            product_id="coding",
            policy_revision="owner-policy-1",
            revocation_epoch=0,
            allowed_source_trust_classes=("first_party",),
            allowed_collection_ids=(collection_id,),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(candidate, issued_at=100, expires_at=200)


def _context(*admissions):  # type: ignore[no-untyped-def]
    owner_snapshots = []
    trust_snapshots = []
    seen_owners = set()
    seen_trust = set()
    for admission in admissions:
        candidate = admission.candidate
        owner_key = (
            admission.owner_id,
            admission.contribution_kind,
            admission.product_id,
        )
        if owner_key not in seen_owners:
            seen_owners.add(owner_key)
            owner_snapshots.append(
                OwnerContributionAuthority(
                    OwnerContributionPolicy(
                        owner_id=admission.owner_id,
                        contribution_kind=admission.contribution_kind,
                        product_id=admission.product_id,
                        policy_revision=admission.owner_policy_revision,
                        revocation_epoch=admission.revocation_epoch,
                        allowed_source_trust_classes=(
                            candidate.source_trust_class,
                        ),
                        allowed_collection_ids=(
                            candidate.contribution.collection_id,
                        ),
                        allowed_requirement_bindings=("direct",),
                        consumer_scope=admission.consumer_scope,
                        consumer_refresh_boundary=(
                            admission.consumer_refresh_boundary
                        ),
                    )
                ).snapshot()
            )
        trust_key = (candidate.plugin_id, candidate.package_source_identity)
        if trust_key not in seen_trust:
            seen_trust.add(trust_key)
            trust_snapshots.append(
                PluginSourceTrustSnapshotV1(
                    plugin_id=candidate.plugin_id,
                    package_source_identity=candidate.package_source_identity,
                    source_trust_class=candidate.source_trust_class,
                    source_trust_policy_revision=(
                        candidate.source_trust_policy_revision
                    ),
                    trusted=True,
                )
            )
    return ProductCompositionAuthorityContext(
        product_id="coding",
        scope_id="workspace:sample",
        product_policy_revision="product-policy-1",
        evaluated_at=150,
        owner_snapshots=tuple(owner_snapshots),
        trust_snapshots=tuple(trust_snapshots),
    )
