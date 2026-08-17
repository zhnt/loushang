from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from loushang.harness.continuity import (
    CallbackPreparedActivationLease,
    ContinuityCompositionError,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderPack,
    ContinuityTarget,
    ExperienceDescriptor,
    ProviderPage,
    ProviderQuery,
    compose_experience_continuity,
)
from loushang.harness.runtime import (
    CONTINUITY_PROVIDER_PACKS_SLOT,
    ProductRuntimePlan,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeProfileAdmissionPolicy,
    RuntimeProfileBinder,
    RuntimeProfileLayer,
    RuntimeProfileLayerGrant,
    RuntimeProfileResolver,
)


@dataclass
class _Provider:
    descriptor: ContinuityProviderDescriptor

    async def query(self, _request: ProviderQuery) -> ProviderPage:
        raise NotImplementedError

    async def preview(self, _target: ContinuityTarget) -> ContinuityPreview:
        raise NotImplementedError

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> CallbackPreparedActivationLease:
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=lambda: target,
        )


def _provider(provider_id: str, *domains: str) -> _Provider:
    return _Provider(
        descriptor=ContinuityProviderDescriptor(
            provider_id=provider_id,
            experience_id="studio",
            domain_ids=domains,
            primary_domain_id=domains[0],
            label=provider_id,
        )
    )


def _compose(*providers: _Provider):
    plan = ProductRuntimePlan(
        product_id="studio",
        slots=(CONTINUITY_PROVIDER_PACKS_SLOT,),
        defaults=(
            RuntimeCapabilitySelection(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="test-layout",
                implementation_version=1,
            ),
        ),
    )
    profile = RuntimeProfileResolver().resolve(plan)
    binding = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                    implementation="test-layout",
                    implementation_version=1,
                    create=lambda _selection, _context: ContinuityProviderPack(
                        providers=providers
                    ),
                ),
            )
        )
    ).bind_sync(profile)
    return compose_experience_continuity(
        experience=ExperienceDescriptor(
            experience_id="studio",
            label="Studio",
            domain_ids=("coding", "presentation", "design"),
        ),
        binding=binding,
    )


def test_process_scoped_provider_packs_bind_once_and_retain_provenance() -> None:
    created: list[str] = []
    coding = _provider("coding.sessions", "coding")
    aggregate = _provider("studio.projects", "coding", "design")
    plan = ProductRuntimePlan(
        product_id="studio",
        slots=(CONTINUITY_PROVIDER_PACKS_SLOT,),
        defaults=(
            RuntimeCapabilitySelection(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="studio-default",
                implementation_version=1,
            ),
        ),
    )
    oem_layer = RuntimeProfileLayer(
        source="oem",
        layer_id="oem:aggregate",
        selections=(
            RuntimeCapabilitySelection(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="studio-aggregate",
                implementation_version=1,
            ),
        ),
    )
    admission = RuntimeProfileAdmissionPolicy(
        grants=(
            RuntimeProfileLayerGrant(
                source="oem",
                layer_id="oem:aggregate",
                allowed_slots=frozenset({CONTINUITY_PROVIDER_PACKS_SLOT.key}),
                granted_permissions=frozenset({"continuity.provider"}),
            ),
        ),
        slot_permissions={
            CONTINUITY_PROVIDER_PACKS_SLOT.key: frozenset({"continuity.provider"})
        },
    ).admit(plan, (oem_layer,))
    profile = RuntimeProfileResolver().resolve(
        plan,
        layers=admission.require_valid(),
    )
    registry = RuntimeCapabilityRegistry(
        (
            RuntimeCapabilityImplementation(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="studio-default",
                implementation_version=1,
                create=lambda _selection, _context: (
                    created.append("default")
                    or ContinuityProviderPack(providers=(coding,))
                ),
            ),
            RuntimeCapabilityImplementation(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="studio-aggregate",
                implementation_version=1,
                create=lambda _selection, _context: (
                    created.append("aggregate")
                    or ContinuityProviderPack(providers=(aggregate,))
                ),
            ),
        )
    )
    binding = RuntimeProfileBinder(registry).bind_sync(profile)
    experience = ExperienceDescriptor(
        experience_id="studio",
        label="Studio",
        domain_ids=("coding", "design"),
        default_domain_id="coding",
    )

    first = compose_experience_continuity(experience=experience, binding=binding)
    second = compose_experience_continuity(experience=experience, binding=binding)

    assert created == ["default", "aggregate"]
    assert [
        item.provider.descriptor.provider_id for item in first.continuity_providers
    ] == [
        "coding.sessions",
        "studio.projects",
    ]
    assert first.continuity_providers[0].provenance.source == "product"
    assert first.continuity_providers[1].provenance.source == "oem"
    assert second.continuity_providers == first.continuity_providers


def test_oem_provider_pack_requires_the_slot_permission() -> None:
    plan = ProductRuntimePlan(
        product_id="studio",
        slots=(CONTINUITY_PROVIDER_PACKS_SLOT,),
    )
    layer = RuntimeProfileLayer(
        source="oem",
        layer_id="oem:history",
        selections=(
            RuntimeCapabilitySelection(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="history",
                implementation_version=1,
            ),
        ),
    )

    admission = RuntimeProfileAdmissionPolicy(
        grants=(
            RuntimeProfileLayerGrant(
                source="oem",
                layer_id="oem:history",
                allowed_slots=frozenset({CONTINUITY_PROVIDER_PACKS_SLOT.key}),
            ),
        ),
        slot_permissions={
            CONTINUITY_PROVIDER_PACKS_SLOT.key: frozenset({"continuity.provider"})
        },
    ).admit(plan, (layer,))

    assert admission.layers == ()
    assert [item.code for item in admission.diagnostics] == [
        "runtime_slot_permission_denied"
    ]


def test_composition_rejects_provider_experience_mismatch() -> None:
    mismatched = _provider("coding.sessions", "coding")
    mismatched.descriptor = ContinuityProviderDescriptor(
        provider_id="coding.sessions",
        experience_id="another-product",
        domain_ids=("coding",),
        label="Coding",
    )
    plan = ProductRuntimePlan(
        product_id="studio",
        slots=(CONTINUITY_PROVIDER_PACKS_SLOT,),
        defaults=(
            RuntimeCapabilitySelection(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation="mismatched",
                implementation_version=1,
            ),
        ),
    )
    profile = RuntimeProfileResolver().resolve(plan)
    binding = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                    implementation="mismatched",
                    implementation_version=1,
                    create=lambda _selection, _context: ContinuityProviderPack(
                        providers=(mismatched,)
                    ),
                ),
            )
        )
    ).bind_sync(profile)

    with pytest.raises(ContinuityCompositionError, match="another-product"):
        compose_experience_continuity(
            experience=ExperienceDescriptor(
                experience_id="studio",
                label="Studio",
                domain_ids=("coding",),
            ),
            binding=binding,
        )


def test_composition_rejects_provider_version_mismatch() -> None:
    provider = _provider("presentation.decks", "presentation")
    provider.descriptor = replace(provider.descriptor, implementation_version=2)

    with pytest.raises(ContinuityCompositionError, match="version 2"):
        _compose(provider)


def test_composition_rejects_duplicate_provider_ids_across_packs() -> None:
    with pytest.raises(ContinuityCompositionError, match="duplicate"):
        _compose(
            _provider("design.canvases", "design"),
            _provider("design.canvases", "design"),
        )


@pytest.mark.parametrize(
    ("providers", "expected_ids"),
    (
        (
            (
                _provider("coding.sessions", "coding"),
                _provider("presentation.decks", "presentation"),
                _provider("design.canvases", "design"),
            ),
            ("coding.sessions", "presentation.decks", "design.canvases"),
        ),
        (
            (
                _provider(
                    "studio.projects",
                    "coding",
                    "presentation",
                    "design",
                ),
            ),
            ("studio.projects",),
        ),
        (
            (
                _provider("coding.sessions", "coding"),
                _provider("presentation.decks", "presentation"),
                _provider("design.canvases", "design"),
                _provider(
                    "studio.projects",
                    "coding",
                    "presentation",
                    "design",
                ),
            ),
            (
                "coding.sessions",
                "presentation.decks",
                "design.canvases",
                "studio.projects",
            ),
        ),
    ),
)
def test_oem_independent_unified_and_hybrid_layouts_compose(
    providers: tuple[_Provider, ...],
    expected_ids: tuple[str, ...],
) -> None:
    composition = _compose(*providers)

    assert (
        tuple(
            item.provider.descriptor.provider_id
            for item in composition.continuity_providers
        )
        == expected_ids
    )
