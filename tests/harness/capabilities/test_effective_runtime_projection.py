from __future__ import annotations

import asyncio
import hashlib
import json

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityFacetBinding,
    CapabilityGraphPlanRequest,
    CapabilityProviderContext,
    ModelSurfaceReference,
    RegistrationInventoryEntry,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphProjector,
    RuntimeCapabilityGraphRuntime,
)
from loushang.harness.capabilities.effective_runtime import (
    compose_registration_inventory,
)
from loushang.harness.runtime import (
    RegistrationIdentity,
    RegistrationLease,
    RuntimeProfileSnapshot,
    RuntimeProfileSnapshotCapability,
    RuntimeProfileSnapshotSelection,
)


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _profile(*, implementation: str, secret: str) -> RuntimeProfileSnapshot:
    return RuntimeProfileSnapshot(
        product_id="research",
        capabilities=(
            RuntimeProfileSnapshotCapability(
                slot="harness.workspace",
                shape="exclusive",
                scope="session",
                refresh_boundary="turn",
                variation_semantic="exclusive_replacement",
                selections=(
                    RuntimeProfileSnapshotSelection(
                        implementation=implementation,
                        implementation_version=1,
                        config={"credential": secret},
                        source="product",
                        layer_id="research",
                        layer_priority=100,
                        selection_priority=100,
                    ),
                ),
            ),
        ),
    )


def test_effective_view_explains_redacted_committed_facts_deterministically() -> None:
    async def scenario() -> None:
        profile = _profile(
            implementation="workspace.standard",
            secret="DO-NOT-PROJECT-profile-secret",
        )
        runtime, binder = await _runtime(
            profile=profile,
            provider_id="workspace.standard",
            provider_version=1,
            registration_id="registration-v1",
        )
        projector = RuntimeCapabilityGraphProjector(runtime)
        graph = projector.snapshot()
        registrations = projector.registration_inventory()
        assert compose_registration_inventory(registrations, ()) == registrations
        model_surface = ModelSurfaceReference(
            schema_version=1,
            snapshot_id="model-input-v1",
            product_id="research",
            runtime_id="session-42",
            profile_fingerprint=_fingerprint(profile.to_json()),
            mount_generation=graph.generation,
            registration_revision=registrations.revision,
        )

        first = projector.effective_view(profile, model_surface=model_surface)
        second = projector.effective_view(profile, model_surface=model_surface)
        projected = projector.to_json(first)

        assert first == second
        assert first.assembly_fingerprint == second.assembly_fingerprint
        assert first.skew == ()
        assert projected == projector.to_json(second)
        assert "DO-NOT-PROJECT" not in repr(projected)
        assert "SecretWorkspace" not in repr(projected)

        capability = projector.explain(
            "harness.workspace",
            profile=profile,
            model_surface=model_surface,
        )
        profile_slot = projector.explain_profile_slot(
            profile,
            "harness.workspace",
            model_surface=model_surface,
        )
        registration = projector.explain_registration(
            "registration-v1",
            profile=profile,
            model_surface=model_surface,
        )

        assert capability.node.provider_id == "workspace.standard"
        assert capability.registrations[0].registration_id == "registration-v1"
        assert profile_slot.slot.selections[0].implementation == "workspace.standard"
        assert registration.entry.owner_id == "harness.workspace"
        assert registration.clocks == first.clocks

        await binder.dispose(runtime)

    asyncio.run(scenario())


def test_effective_diff_keeps_four_clocks_and_labels_legitimate_skew() -> None:
    async def scenario() -> None:
        mounted_profile = _profile(
            implementation="workspace.standard",
            secret="old-secret",
        )
        current_profile = _profile(
            implementation="workspace.reconfigured",
            secret="new-secret",
        )
        runtime, binder = await _runtime(
            profile=mounted_profile,
            provider_id="workspace.standard",
            provider_version=1,
            registration_id="registration-v1",
        )
        projector = RuntimeCapabilityGraphProjector(runtime)
        before_graph = projector.snapshot()
        before_registrations = projector.registration_inventory()
        historical_model_surface = ModelSurfaceReference(
            schema_version=1,
            snapshot_id="model-input-v1",
            product_id="research",
            runtime_id="session-42",
            profile_fingerprint=_fingerprint(mounted_profile.to_json()),
            mount_generation=before_graph.generation,
            registration_revision=before_registrations.revision,
        )
        before = projector.effective_view(
            mounted_profile,
            model_surface=historical_model_surface,
        )

        await _rebind(
            runtime,
            binder,
            provider_id="workspace.replacement",
            provider_version=2,
            registration_id="registration-v2",
        )
        after = projector.effective_view(
            current_profile,
            model_surface=historical_model_surface,
        )
        diff = projector.diff(before, after)

        assert diff.profile_changed is True
        assert diff.mount_generation_changed is True
        assert diff.registration_revision_changed is True
        assert diff.model_surface_changed is False
        assert diff.replaced_capability_ids == ("harness.workspace",)
        assert diff.added_registration_ids == ("registration-v2",)
        assert diff.removed_registration_ids == ("registration-v1",)
        assert diff.before_clocks == before.clocks
        assert diff.after_clocks == after.clocks
        assert diff.before_skew == ()
        assert {item.code for item in diff.after_skew} == {
            "model_mount_reference_skew",
            "model_profile_reference_skew",
            "model_registration_reference_skew",
            "profile_mount_reference_skew",
        }
        assert all(item.classification == "clock_skew" for item in diff.after_skew)

        await binder.dispose(runtime)

    asyncio.run(scenario())


def test_registration_refresh_does_not_synthesize_a_mount_generation() -> None:
    async def scenario() -> None:
        profile = _profile(
            implementation="workspace.standard",
            secret="not-projected",
        )
        runtime, binder = await _runtime(
            profile=profile,
            provider_id="workspace.standard",
            provider_version=1,
            registration_id="registration-v1",
        )
        projector = RuntimeCapabilityGraphProjector(runtime)
        base = projector.registration_inventory()
        model_surface = ModelSurfaceReference(
            schema_version=1,
            snapshot_id="model-input-v1",
            product_id="research",
            runtime_id="session-42",
            profile_fingerprint=_fingerprint(profile.to_json()),
            mount_generation=projector.snapshot().generation,
            registration_revision=base.revision,
        )
        before = projector.effective_view(
            profile,
            model_surface=model_surface,
        )
        refreshed = compose_registration_inventory(
            base,
            (
                RegistrationInventoryEntry(
                    registration_id="extension-command-v1",
                    surface="command",
                    public_key="review",
                    owner_kind="extension",
                    owner_id="review-extension",
                    runtime_id="session-42",
                    owner_generation=2,
                    attachment="effective",
                    state="active",
                ),
            ),
        )
        after = projector.effective_view(
            profile,
            model_surface=model_surface,
            registrations=refreshed,
        )
        diff = projector.diff(before, after)

        assert before.clocks.mount == after.clocks.mount
        assert diff.mount_generation_changed is False
        assert diff.profile_changed is False
        assert diff.registration_revision_changed is True
        assert diff.model_surface_changed is False
        assert diff.added_registration_ids == ("extension-command-v1",)
        assert [item.code for item in after.skew] == [
            "model_registration_reference_skew"
        ]

        await binder.dispose(runtime)

    asyncio.run(scenario())


def test_historical_model_surface_from_fork_is_runtime_skew() -> None:
    async def scenario() -> None:
        profile = _profile(
            implementation="workspace.standard",
            secret="not-projected",
        )
        runtime, binder = await _runtime(
            profile=profile,
            provider_id="workspace.standard",
            provider_version=1,
            registration_id="registration-v1",
        )
        projector = RuntimeCapabilityGraphProjector(runtime)
        registrations = projector.registration_inventory()
        view = projector.effective_view(
            profile,
            model_surface=ModelSurfaceReference(
                schema_version=1,
                snapshot_id="model-input-from-parent-session",
                product_id="research",
                runtime_id="session-parent",
                profile_fingerprint=_fingerprint(profile.to_json()),
                mount_generation=projector.snapshot().generation,
                registration_revision=registrations.revision,
            ),
        )

        assert [item.code for item in view.skew] == [
            "model_runtime_reference_skew"
        ]

        await binder.dispose(runtime)

    asyncio.run(scenario())


async def _runtime(
    *,
    profile: RuntimeProfileSnapshot,
    provider_id: str,
    provider_version: int,
    registration_id: str,
) -> tuple[RuntimeCapabilityGraphRuntime, RuntimeCapabilityGraphBinder]:
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="session-42",
        profile_fingerprint=_fingerprint(profile.to_json()),
    )
    binder = RuntimeCapabilityGraphBinder()
    await _rebind(
        runtime,
        binder,
        provider_id=provider_id,
        provider_version=provider_version,
        registration_id=registration_id,
    )
    return runtime, binder


async def _rebind(
    runtime: RuntimeCapabilityGraphRuntime,
    binder: RuntimeCapabilityGraphBinder,
    *,
    provider_id: str,
    provider_version: int,
    registration_id: str,
) -> None:
    definition = CapabilityDefinition(
        capability_id="harness.workspace",
        owner_id="harness",
        contract_version=1,
        facets=("read",),
        scope="session",
        refresh_boundary="sealed",
        phase="bootstrap",
    )
    provider = CapabilityBundleProvider(
        capability_id=definition.capability_id,
        provider_id=provider_id,
        implementation_version=provider_version,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=definition.facets,
        source_id="research",
        selection_rule="Product selection",
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=(definition.capability_id,),
            definitions=(definition,),
            providers=(provider,),
        )
    )

    class SecretWorkspace:
        def __repr__(self) -> str:
            return "DO-NOT-PROJECT-live-secret"

    def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=RegistrationIdentity(
                    surface="tools",
                    public_key="read",
                    registration_id=registration_id,
                ),
                dispose=lambda: None,
            )
        )
        return CapabilityBundleValue(
            (CapabilityFacetBinding("read", SecretWorkspace()),)
        )

    await binder.bind(
        runtime,
        plan,
        (
            CapabilityBundleProviderBinding(
                provider=provider,
                scope_instance_id="session:42",
                binding_input_fingerprint=_fingerprint(provider_id),
                create=create,
            ),
        ),
    )
