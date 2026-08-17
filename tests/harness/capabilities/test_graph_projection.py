from __future__ import annotations

import hashlib
from dataclasses import asdict

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.graph_binding import RuntimeCapabilityGraphBinder
from loushang.harness.capabilities.graph_planning import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.graph_projection import (
    RuntimeCapabilityGraphProjector,
)
from loushang.harness.capabilities.graph_runtime import RuntimeCapabilityGraphRuntime
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.runtime.registration import (
    RegistrationIdentity,
    RegistrationLease,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_projector_explains_committed_graph_without_live_values() -> None:
    import asyncio

    asyncio.run(_projector_explains_committed_graph_without_live_values())


async def _projector_explains_committed_graph_without_live_values() -> None:
    workspace = CapabilityDefinition(
        capability_id="harness.workspace",
        owner_id="harness",
        contract_version=1,
        facets=("read",),
        scope="workspace",
        refresh_boundary="sealed",
        phase="bootstrap",
    )
    query = CapabilityDefinition(
        capability_id="research.query",
        owner_id="research",
        contract_version=1,
        facets=("answer",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("read",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    workspace_provider = CapabilityBundleProvider(
        capability_id="harness.workspace",
        provider_id="virtual.workspace",
        implementation_version=3,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=("read",),
        source_id="non-coding-product",
        selection_rule="explicit fake Provider",
    )
    query_provider = CapabilityBundleProvider(
        capability_id="research.query",
        provider_id="research.query.standard",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=("answer",),
        requirements=(requirement,),
        source_id="research",
        selection_rule="Product default",
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=("research.query",),
            definitions=(query, workspace),
            providers=(query_provider, workspace_provider),
        )
    )
    live_registrations: set[str] = set()

    class SecretWorkspace:
        def __repr__(self) -> str:
            return "DO-NOT-PROJECT-secret-token"

    def create_workspace(context: CapabilityProviderContext) -> CapabilityBundleValue:
        identity = RegistrationIdentity.create(
            surface="tools",
            public_key="read",
        )
        live_registrations.add(identity.registration_id)
        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=lambda: live_registrations.discard(identity.registration_id),
            )
        )
        return CapabilityBundleValue(
            (CapabilityFacetBinding("read", SecretWorkspace()),)
        )

    def create_query(context: CapabilityProviderContext) -> CapabilityBundleValue:
        assert context.dependency("harness.workspace").require("read") is not None
        return CapabilityBundleValue((CapabilityFacetBinding("answer", object()),))

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="session-42",
        profile_fingerprint=_sha("persisted-profile-snapshot"),
    )
    binder = RuntimeCapabilityGraphBinder()
    provider_cleanup_observations: list[str] = []

    def dispose_workspace(_value: CapabilityBundleValue) -> None:
        assert live_registrations == set()
        provider_cleanup_observations.append("workspace-provider")

    await binder.bind(
        runtime,
        plan,
        (
            CapabilityBundleProviderBinding(
                provider=workspace_provider,
                scope_instance_id="workspace:/virtual",
                binding_input_fingerprint=_sha("virtual workspace inputs"),
                create=create_workspace,
                dispose=dispose_workspace,
            ),
            CapabilityBundleProviderBinding(
                provider=query_provider,
                scope_instance_id="session:42",
                binding_input_fingerprint=_sha("query inputs"),
                create=create_query,
            ),
        ),
    )
    projector = RuntimeCapabilityGraphProjector(runtime)

    snapshot = projector.snapshot(runtime.graph_id)
    explanation = projector.explain("harness.workspace")
    inventory = projector.registration_inventory()

    assert snapshot.profile_fingerprint == _sha("persisted-profile-snapshot")
    assert explanation.dependencies == ()
    assert explanation.dependents == ("research.query",)
    assert projector.dependencies("research.query") == ("harness.workspace",)
    assert projector.impact("harness.workspace") == ("research.query",)
    assert len(explanation.registration_ids) == 1
    assert inventory.entries[0].owner_id == "harness.workspace"
    assert inventory.entries[0].public_key == "read"
    assert inventory.entries[0].attachment == "effective"
    assert "DO-NOT-PROJECT" not in repr(asdict(snapshot))
    assert "secret-token" not in repr(asdict(explanation))

    await binder.dispose(runtime)
    assert live_registrations == set()
    assert provider_cleanup_observations == ["workspace-provider"]
