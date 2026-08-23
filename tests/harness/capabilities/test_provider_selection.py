from __future__ import annotations

import pytest

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityGraphPlanRequest,
    CapabilityRequirement,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
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
    ProviderSelectionError,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_product_resolver_selects_required_closure_and_records_optional_absence() -> None:
    admissions, snapshots, definitions = _admitted_graph()
    plan = _plan(
        _choice(admissions, "app.root"),
        _choice(admissions, "harness.base"),
    )

    resolved = ProductCapabilityProviderResolver().resolve(
        plan,
        definitions=definitions,
        admissions=admissions,
        owner_snapshots=snapshots,
        evaluated_at=150,
    )

    assert tuple(item.capability_id for item in resolved.entries) == (
        "app.root",
        "harness.base",
    )
    assert tuple(provider.capability_id for provider in resolved.providers) == (
        "app.root",
        "harness.base",
    )
    assert [(item.capability_id, item.satisfied) for item in resolved.optional_decisions] == [
        ("harness.optional", False)
    ]
    assert resolved.closure_fingerprint == resolved.to_dict()["closureFingerprint"]
    assert not _contains_callable(resolved.to_dict())
    with pytest.raises(TypeError, match="Resolver-constructed"):
        ResolvedCapabilityProviderSet()

    graph = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="app",
            roots=plan.roots,
            definitions=definitions,
            providers=resolved.providers,
        )
    )
    assert graph.binding_order == ("harness.base", "app.root")


def test_product_resolver_includes_an_explicitly_selected_optional_dependency() -> None:
    admissions, snapshots, definitions = _admitted_graph()
    resolved = ProductCapabilityProviderResolver().resolve(
        _plan(
            _choice(admissions, "app.root"),
            _choice(admissions, "harness.base"),
            _choice(admissions, "harness.optional"),
        ),
        definitions=definitions,
        admissions=admissions,
        owner_snapshots=snapshots,
        evaluated_at=150,
    )

    assert tuple(item.capability_id for item in resolved.entries) == (
        "app.root",
        "harness.base",
        "harness.optional",
    )
    assert [(item.capability_id, item.satisfied) for item in resolved.optional_decisions] == [
        ("harness.optional", True)
    ]


@pytest.mark.parametrize(
    ("choices", "code"),
    [
        (("app.root",), "missing_provider_selection"),
        (
            ("app.root", "harness.base", "harness.base"),
            "multiple_provider_selections",
        ),
        (
            (
                "app.root",
                "harness.base",
                "harness.optional",
                "harness.optional",
            ),
            "multiple_provider_selections",
        ),
        (
            ("app.root", "harness.base", "unused.extra"),
            "extra_provider_selection",
        ),
    ],
)
def test_product_resolver_rejects_missing_multiple_and_extra_closure_members(
    choices: tuple[str, ...],
    code: str,
) -> None:
    admissions, snapshots, definitions = _admitted_graph(include_unused=True)
    plan = _plan(*(_choice(admissions, item) for item in choices))

    with pytest.raises(ProviderSelectionError) as caught:
        ProductCapabilityProviderResolver().resolve(
            plan,
            definitions=definitions,
            admissions=admissions,
            owner_snapshots=snapshots,
            evaluated_at=150,
        )

    assert caught.value.code == code


def test_product_resolver_rejects_fingerprint_policy_epoch_and_expiry_skew() -> None:
    admissions, snapshots, definitions = _admitted_graph()
    root = _choice(admissions, "app.root")
    dependency = _choice(admissions, "harness.base")
    skewed = ProductCapabilityProviderChoice(
        capability_id=root.capability_id,
        provider_id=root.provider_id,
        candidate_fingerprint="f" * 64,
    )

    with pytest.raises(ProviderSelectionError) as fingerprint:
        ProductCapabilityProviderResolver().resolve(
            _plan(skewed, dependency),
            definitions=definitions,
            admissions=admissions,
            owner_snapshots=snapshots,
            evaluated_at=150,
        )
    assert fingerprint.value.code == "selected_provider_not_admitted"

    with pytest.raises(ProviderSelectionError) as duplicate:
        ProductCapabilityProviderResolver().resolve(
            _plan(root, dependency),
            definitions=definitions,
            admissions=(admissions[0], *admissions),
            owner_snapshots=snapshots,
            evaluated_at=150,
        )
    assert duplicate.value.code == "multiple_admitted_provider_matches"

    revoked_authority = _owner_authority(
        definitions[0],
        admissions[0].provider.provider_id,
        policy_revision="app-owner-1",
        revocation_epoch=2,
    )
    revoked_snapshots = tuple(
        revoked_authority.snapshot() if item.owner_id == "app" else item
        for item in snapshots
    )
    with pytest.raises(ProviderSelectionError) as revoked:
        ProductCapabilityProviderResolver().resolve(
            _plan(root, dependency),
            definitions=definitions,
            admissions=admissions,
            owner_snapshots=revoked_snapshots,
            evaluated_at=150,
        )
    assert revoked.value.code == "provider_admission_policy_stale"

    revised_authority = _owner_authority(
        definitions[0],
        admissions[0].provider.provider_id,
        policy_revision="app-owner-2",
        revocation_epoch=1,
    )
    revised_snapshots = tuple(
        revised_authority.snapshot() if item.owner_id == "app" else item
        for item in snapshots
    )
    with pytest.raises(ProviderSelectionError) as revised:
        ProductCapabilityProviderResolver().resolve(
            _plan(root, dependency),
            definitions=definitions,
            admissions=admissions,
            owner_snapshots=revised_snapshots,
            evaluated_at=150,
        )
    assert revised.value.code == "provider_admission_policy_stale"

    with pytest.raises(ProviderSelectionError) as expiry:
        ProductCapabilityProviderResolver().resolve(
            _plan(root, dependency),
            definitions=definitions,
            admissions=admissions,
            owner_snapshots=snapshots,
            evaluated_at=200,
        )
    assert expiry.value.code == "provider_admission_expired"


def _admitted_graph(
    *, include_unused: bool = False
) -> tuple[
    tuple[CapabilityProviderAdmissionRecord, ...],
    tuple[CapabilityProviderOwnerSnapshot, ...],
    tuple[CapabilityDefinition, ...],
]:
    base = _definition("harness.base")
    optional = _definition("harness.optional")
    root = _definition("app.root")
    specs = [
        (
            root,
            _provider(
                root,
                requirements=(
                    CapabilityRequirement(
                        capability="harness.base",
                        facets=("default",),
                        compatible_contract=CapabilityContractRange.exact(1),
                    ),
                    CapabilityRequirement(
                        capability="harness.optional",
                        facets=("default",),
                        compatible_contract=CapabilityContractRange.exact(1),
                        optional=True,
                    ),
                ),
            ),
        ),
        (base, _provider(base)),
        (optional, _provider(optional)),
    ]
    if include_unused:
        unused = _definition("unused.extra")
        specs.append((unused, _provider(unused)))

    admissions: list[CapabilityProviderAdmissionRecord] = []
    snapshots: list[CapabilityProviderOwnerSnapshot] = []
    definitions: list[CapabilityDefinition] = []
    for index, (definition, provider) in enumerate(specs):
        candidate = _candidate(definition, provider, marker=str(index + 1))
        authority = _owner_authority(
            definition,
            provider.provider_id,
            policy_revision=f"{definition.owner_id}-owner-1",
            revocation_epoch=1,
        )
        grant = authority.grant_eligibility(
            candidate,
            issued_at=100,
            expires_at=220,
        )
        admissions.append(
            authority.admit(
                candidate,
                eligibility=grant,
                issued_at=120,
                expires_at=200,
            )
        )
        snapshots.append(authority.snapshot())
        definitions.append(definition)
    return tuple(admissions), tuple(snapshots), tuple(definitions)


def _candidate(
    definition: CapabilityDefinition,
    provider: CapabilityBundleProvider,
    *,
    marker: str,
) -> CapabilityProviderCandidateEnvelope:
    plugin_id = f"{definition.owner_id}-provider"
    binding = CapabilityProviderBindingSpec(
        plugin_id=plugin_id,
        contribution_id=f"{definition.owner_id}-contribution",
        package_content_digest=marker * 64,
        dependency_lock_digest=marker * 64,
        factory=CapabilityProviderSymbolLocator(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=None,
        binding_inputs={},
    )
    return CapabilityProviderCandidateEnvelope(
        definition=definition,
        provider=provider,
        binding_spec=binding,
        plugin_candidate_fingerprint=marker * 64,
        declaration_fingerprint=marker * 64,
        declaration_evidence_fingerprint=marker * 64,
        product_id="app",
        scope_id="workspace:test",
        product_policy_revision="product-1",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id=f"{plugin_id}@app",
            plugin_id=plugin_id,
            revision=1,
        ),
        package_source_identity=f"source:{plugin_id}",
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        source_trusted=True,
        allowed_authority_ceiling=(),
    )


def _definition(capability_id: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=capability_id,
        owner_id=capability_id.split(".", maxsplit=1)[0],
        contract_version=1,
        facets=("default",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )


def _provider(
    definition: CapabilityDefinition,
    *,
    requirements: tuple[CapabilityRequirement, ...] = (),
) -> CapabilityBundleProvider:
    return CapabilityBundleProvider(
        capability_id=definition.capability_id,
        provider_id=f"org.loushang.{definition.owner_id}/default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=("default",),
        requirements=requirements,
        source_id=f"plugin:{definition.owner_id}-provider",
        selection_rule="Plugin declaration candidate",
    )


def _owner_authority(
    definition: CapabilityDefinition,
    provider_id: str,
    *,
    policy_revision: str,
    revocation_epoch: int,
) -> CapabilityProviderOwnerAuthority:
    return CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision=policy_revision,
            revocation_epoch=revocation_epoch,
            allowed_provider_ids=(provider_id,),
            allowed_source_trust_classes=("host-equivalent-local",),
            authority_ceiling=(),
        )
    )


def _choice(
    admissions: tuple[CapabilityProviderAdmissionRecord, ...],
    capability_id: str,
) -> ProductCapabilityProviderChoice:
    admission = next(
        item for item in admissions if item.capability_id == capability_id
    )
    return ProductCapabilityProviderChoice(
        capability_id=capability_id,
        provider_id=admission.provider.provider_id,
        candidate_fingerprint=admission.candidate_fingerprint,
    )


def _plan(
    *choices: ProductCapabilityProviderChoice,
) -> ProductCapabilityProviderSelectionPlanV1:
    return ProductCapabilityProviderSelectionPlanV1(
        product_id="app",
        roots=("app.root",),
        choices=choices,
        policy_revision="product-provider-1",
    )


def _contains_callable(value: object) -> bool:
    if callable(value):
        return True
    if isinstance(value, dict):
        return any(_contains_callable(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_callable(item) for item in value)
    return False
