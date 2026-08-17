from __future__ import annotations

import asyncio
import hashlib

import pytest

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.graph_binding import (
    CapabilityGraphBindingError,
    RuntimeCapabilityGraphBinder,
)
from loushang.harness.capabilities.graph_planning import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphPlan,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.graph_projection import (
    RuntimeCapabilityGraphProjector,
)
from loushang.harness.capabilities.graph_runtime import (
    RuntimeCapabilityGraphRuntime,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationIdentity,
    RegistrationLease,
)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _definition(
    capability_id: str,
    *,
    facets: tuple[str, ...] = ("value",),
    scope: str = "session",
    phase: str = "final",
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=capability_id,
        owner_id=capability_id.split(".", maxsplit=1)[0],
        contract_version=1,
        facets=facets,
        scope=scope,
        refresh_boundary="sealed",
        phase=phase,
    )


def _provider(
    capability_id: str,
    *,
    facets: tuple[str, ...] = ("value",),
    requirements: tuple[CapabilityRequirement, ...] = (),
    provider_id: str | None = None,
) -> CapabilityBundleProvider:
    return CapabilityBundleProvider(
        capability_id=capability_id,
        provider_id=provider_id or f"test.{capability_id}",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=facets,
        requirements=requirements,
        source_id="test",
        selection_rule="test fixture",
    )


def _binding(
    provider: CapabilityBundleProvider,
    *,
    value: object | None = None,
    create=None,  # type: ignore[no-untyped-def]
    dispose=None,  # type: ignore[no-untyped-def]
    fingerprint: str | None = None,
) -> CapabilityBundleProviderBinding:
    if create is None:

        def create(_context: CapabilityProviderContext) -> CapabilityBundleValue:
            return CapabilityBundleValue(
                tuple(
                    CapabilityFacetBinding(facet_id, value)
                    for facet_id in provider.facets
                )
            )

    return CapabilityBundleProviderBinding(
        provider=provider,
        scope_instance_id="scope:test",
        binding_input_fingerprint=fingerprint or _fingerprint(provider.provider_id),
        create=create,
        dispose=dispose,
    )


def _plan(
    *,
    product_id: str,
    roots: tuple[str, ...],
    definitions: tuple[CapabilityDefinition, ...],
    providers: tuple[CapabilityBundleProvider, ...],
) -> RuntimeCapabilityGraphPlan:
    return RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id=product_id,
            roots=roots,
            definitions=definitions,
            providers=providers,
        )
    )


def test_bootstrap_to_final_bind_reuses_unchanged_workspace_mount() -> None:
    asyncio.run(_bootstrap_to_final_bind_reuses_unchanged_workspace_mount())


async def _bootstrap_to_final_bind_reuses_unchanged_workspace_mount() -> None:
    workspace_definition = _definition(
        "harness.workspace",
        scope="workspace",
        phase="bootstrap",
    )
    workspace_provider = _provider("harness.workspace")
    root_definition = _definition("research.session")
    workspace_requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    root_provider = _provider(
        "research.session",
        requirements=(workspace_requirement,),
    )
    constructed: list[str] = []

    def create_workspace(_context: CapabilityProviderContext) -> CapabilityBundleValue:
        constructed.append("workspace")
        return CapabilityBundleValue(
            (CapabilityFacetBinding("value", "workspace-value"),)
        )

    workspace_binding = _binding(workspace_provider, create=create_workspace)
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()

    bootstrap = await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(workspace_definition,),
            providers=(workspace_provider,),
        ),
        (workspace_binding,),
    )
    final = await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("research.session",),
            definitions=(workspace_definition, root_definition),
            providers=(workspace_provider, root_provider),
        ),
        (workspace_binding, _binding(root_provider)),
    )
    unchanged = await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("research.session",),
            definitions=(workspace_definition, root_definition),
            providers=(workspace_provider, root_provider),
        ),
        (workspace_binding, _binding(root_provider)),
    )

    assert constructed == ["workspace"]
    assert bootstrap.snapshot.generation == 1
    assert final.snapshot.generation == 2
    assert final.reused_capability_ids == ("harness.workspace",)
    assert final.created_capability_ids == ("research.session",)
    assert final.snapshot.nodes[0].mount_generation == 1
    assert unchanged.snapshot is final.snapshot
    assert unchanged.created_capability_ids == ()
    assert runtime.generation == 2

    equivalent_runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    equivalent = await binder.bind(
        equivalent_runtime,
        _plan(
            product_id="research",
            roots=("research.session",),
            definitions=(workspace_definition, root_definition),
            providers=(workspace_provider, root_provider),
        ),
        (workspace_binding, _binding(root_provider)),
    )
    assert equivalent.snapshot.assembly_fingerprint == (
        final.snapshot.assembly_fingerprint
    )


def test_failed_binding_rolls_back_registrations_and_keeps_old_graph() -> None:
    asyncio.run(_failed_binding_rolls_back_registrations_and_keeps_old_graph())


async def _failed_binding_rolls_back_registrations_and_keeps_old_graph() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    original_provider = _provider("harness.workspace", provider_id="workspace.v1")
    replacement_provider = _provider("harness.workspace", provider_id="workspace.v2")
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    original = await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(original_provider,),
        ),
        (_binding(original_provider, value="still-live"),),
    )
    captured = runtime.capture(requirement)
    active_registrations: set[str] = set()

    def fail_after_registration(context: CapabilityProviderContext):  # type: ignore[no-untyped-def]
        identity = RegistrationIdentity.create(
            surface="tools",
            public_key="transient",
        )
        active_registrations.add(identity.registration_id)

        def remove() -> None:
            active_registrations.discard(identity.registration_id)

        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=remove,
            )
        )
        raise RuntimeError("secret provider failure")

    with pytest.raises(CapabilityGraphBindingError) as exc_info:
        await binder.bind(
            runtime,
            _plan(
                product_id="research",
                roots=("harness.workspace",),
                definitions=(definition,),
                providers=(replacement_provider,),
            ),
            (_binding(replacement_provider, create=fail_after_registration),),
        )

    assert exc_info.value.diagnostic_codes == ("provider_construction_failed",)
    assert active_registrations == set()
    assert runtime.snapshot is original.snapshot
    assert runtime.generation == 1
    assert captured.require("value") == "still-live"
    assert "secret provider failure" not in repr(runtime.last_attempt)


def test_cancelled_binding_rolls_back_before_preserving_old_authority() -> None:
    asyncio.run(_cancelled_binding_rolls_back_before_preserving_old_authority())


async def _cancelled_binding_rolls_back_before_preserving_old_authority() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    original_provider = _provider("harness.workspace", provider_id="workspace.v1")
    replacement_provider = _provider("harness.workspace", provider_id="workspace.v2")
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(original_provider,),
        ),
        (_binding(original_provider, value="old"),),
    )
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    captured = runtime.capture(requirement)
    registered = asyncio.Event()
    blocker = asyncio.Event()
    active_registrations: set[str] = set()

    async def create_waiting(context: CapabilityProviderContext):  # type: ignore[no-untyped-def]
        identity = RegistrationIdentity.create(surface="tools", public_key="waiting")
        active_registrations.add(identity.registration_id)
        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=lambda: active_registrations.discard(identity.registration_id),
            )
        )
        registered.set()
        await blocker.wait()
        return CapabilityBundleValue((CapabilityFacetBinding("value", "new"),))

    task = asyncio.create_task(
        binder.bind(
            runtime,
            _plan(
                product_id="research",
                roots=("harness.workspace",),
                definitions=(definition,),
                providers=(replacement_provider,),
            ),
            (_binding(replacement_provider, create=create_waiting),),
        )
    )
    await registered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert active_registrations == set()
    assert runtime.generation == 1
    assert runtime.last_attempt is not None
    assert runtime.last_attempt.state == "cancelled"
    assert captured.require("value") == "old"


def test_downstream_failure_reverse_disposes_staged_provider() -> None:
    asyncio.run(_downstream_failure_reverse_disposes_staged_provider())


async def _downstream_failure_reverse_disposes_staged_provider() -> None:
    workspace_definition = _definition(
        "harness.workspace",
        scope="workspace",
        phase="bootstrap",
    )
    root_definition = _definition("research.session")
    original_provider = _provider("harness.workspace", provider_id="workspace.v1")
    replacement_provider = _provider("harness.workspace", provider_id="workspace.v2")
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    failing_root_provider = _provider(
        "research.session",
        requirements=(requirement,),
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(workspace_definition,),
            providers=(original_provider,),
        ),
        (_binding(original_provider, value="old"),),
    )
    old_facets = runtime.capture(requirement)
    active: set[str] = set()
    disposal_order: list[str] = []

    def create_workspace(context: CapabilityProviderContext) -> CapabilityBundleValue:
        identity = RegistrationIdentity.create(surface="tools", public_key="new")
        active.add(identity.registration_id)

        def unregister() -> None:
            active.discard(identity.registration_id)
            disposal_order.append("registration")

        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=unregister,
            )
        )
        return CapabilityBundleValue((CapabilityFacetBinding("value", "candidate"),))

    def dispose_workspace(_value: CapabilityBundleValue) -> None:
        assert active == set()
        disposal_order.append("provider")

    def fail_root(_context: CapabilityProviderContext):  # type: ignore[no-untyped-def]
        raise RuntimeError("root failed")

    with pytest.raises(CapabilityGraphBindingError):
        await binder.bind(
            runtime,
            _plan(
                product_id="research",
                roots=("research.session",),
                definitions=(workspace_definition, root_definition),
                providers=(replacement_provider, failing_root_provider),
            ),
            (
                _binding(
                    replacement_provider,
                    create=create_workspace,
                    dispose=dispose_workspace,
                ),
                _binding(failing_root_provider, create=fail_root),
            ),
        )

    assert active == set()
    assert disposal_order == ["registration", "provider"]
    assert runtime.generation == 1
    assert old_facets.require("value") == "old"


def test_provider_receives_only_declared_dependency_facets() -> None:
    asyncio.run(_provider_receives_only_declared_dependency_facets())


async def _provider_receives_only_declared_dependency_facets() -> None:
    dependency = _definition(
        "harness.workspace",
        facets=("read", "write"),
        scope="workspace",
        phase="bootstrap",
    )
    root = _definition("research.query")
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("read",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    dependency_provider = _provider(
        "harness.workspace",
        facets=("read", "write"),
    )
    root_provider = _provider(
        "research.query",
        requirements=(requirement,),
    )

    def create_root(context: CapabilityProviderContext) -> CapabilityBundleValue:
        view = context.dependency("harness.workspace")
        assert view.require("read") == "workspace"
        with pytest.raises(KeyError):
            view.require("write")
        assert not hasattr(context, "graph_runtime")
        assert not hasattr(context.registrations, "commit")
        assert not hasattr(context.registrations, "dispose")
        return CapabilityBundleValue((CapabilityFacetBinding("value", "query"),))

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    await RuntimeCapabilityGraphBinder().bind(
        runtime,
        _plan(
            product_id="research",
            roots=("research.query",),
            definitions=(dependency, root),
            providers=(dependency_provider, root_provider),
        ),
        (
            _binding(dependency_provider, value="workspace"),
            _binding(root_provider, create=create_root),
        ),
    )


def test_binder_fails_closed_before_constructing_stable_reference_plan() -> None:
    asyncio.run(_binder_fails_closed_before_constructing_stable_reference_plan())


async def _binder_fails_closed_before_constructing_stable_reference_plan() -> None:
    dependency = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    root = _definition("research.query")
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
        binding="stable_reference",
    )
    dependency_provider = _provider("harness.workspace")
    root_provider = _provider("research.query", requirements=(requirement,))
    constructed: list[str] = []

    def create(_context: CapabilityProviderContext) -> CapabilityBundleValue:
        constructed.append("constructed")
        return CapabilityBundleValue((CapabilityFacetBinding("value", object()),))

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    with pytest.raises(CapabilityGraphBindingError) as exc_info:
        await RuntimeCapabilityGraphBinder().bind(
            runtime,
            _plan(
                product_id="research",
                roots=("research.query",),
                definitions=(dependency, root),
                providers=(dependency_provider, root_provider),
            ),
            (
                _binding(dependency_provider, create=create),
                _binding(root_provider, create=create),
            ),
        )

    assert exc_info.value.diagnostic_codes == (
        "stable_reference_binding_not_implemented",
    )
    assert constructed == []
    assert runtime.snapshot is None


def test_cancellation_after_publication_joins_old_generation_retirement() -> None:
    asyncio.run(_cancellation_after_publication_joins_old_generation_retirement())


async def _cancellation_after_publication_joins_old_generation_retirement() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    original_provider = _provider("harness.workspace", provider_id="workspace.v1")
    replacement_provider = _provider("harness.workspace", provider_id="workspace.v2")
    retirement_started = asyncio.Event()
    allow_retirement = asyncio.Event()
    retired: list[str] = []

    async def dispose_original(_value: CapabilityBundleValue) -> None:
        retirement_started.set()
        await allow_retirement.wait()
        retired.append("old")

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(original_provider,),
        ),
        (_binding(original_provider, value="old", dispose=dispose_original),),
    )

    replacement_task = asyncio.create_task(
        binder.bind(
            runtime,
            _plan(
                product_id="research",
                roots=("harness.workspace",),
                definitions=(definition,),
                providers=(replacement_provider,),
            ),
            (_binding(replacement_provider, value="new"),),
        )
    )
    await retirement_started.wait()
    assert runtime.generation == 2
    replacement_task.cancel()
    await asyncio.sleep(0)
    assert not replacement_task.done()
    allow_retirement.set()
    with pytest.raises(asyncio.CancelledError):
        await replacement_task

    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
    )
    assert retired == ["old"]
    assert runtime.capture(requirement).require("value") == "new"
    assert runtime.last_attempt is not None
    assert runtime.last_attempt.state == "committed"


def test_graph_dispose_retries_retryable_provider_cleanup() -> None:
    asyncio.run(_graph_dispose_retries_retryable_provider_cleanup())


async def _graph_dispose_retries_retryable_provider_cleanup() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    provider = _provider("harness.workspace")
    attempts: list[str] = []

    def dispose(_value: CapabilityBundleValue) -> None:
        attempts.append("dispose")
        if len(attempts) == 1:
            raise RuntimeError("transient cleanup failure")

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(provider,),
        ),
        (_binding(provider, value="workspace", dispose=dispose),),
    )

    assert await binder.dispose(runtime) == ("provider_retirement_failed",)
    assert runtime.is_closed
    assert await binder.dispose(runtime) == ()
    assert attempts == ["dispose", "dispose"]


def test_failed_construction_retains_retryable_registration_cleanup() -> None:
    asyncio.run(_failed_construction_retains_retryable_registration_cleanup())


async def _failed_construction_retains_retryable_registration_cleanup() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    provider = _provider("harness.workspace")
    active: set[str] = set()
    disposal_attempts: list[str] = []

    def fail_after_registration(context: CapabilityProviderContext):  # type: ignore[no-untyped-def]
        identity = RegistrationIdentity.create(
            surface="tools",
            public_key="retryable-construction",
        )
        active.add(identity.registration_id)

        def unregister() -> RegistrationDisposalResult:
            disposal_attempts.append(identity.registration_id)
            if len(disposal_attempts) == 1:
                return RegistrationDisposalResult(state="failed_retryable")
            active.discard(identity.registration_id)
            return RegistrationDisposalResult(state="removed")

        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=unregister,
            )
        )
        raise RuntimeError("construction failed")

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()

    with pytest.raises(CapabilityGraphBindingError) as exc_info:
        await binder.bind(
            runtime,
            _plan(
                product_id="research",
                roots=("harness.workspace",),
                definitions=(definition,),
                providers=(provider,),
            ),
            (_binding(provider, create=fail_after_registration),),
        )

    assert exc_info.value.diagnostic_codes == (
        "provider_construction_failed",
        "registration_rollback_failed",
    )
    assert len(active) == 1
    assert runtime.snapshot is None
    assert runtime.registration_inventory is not None
    assert [entry.public_key for entry in runtime.registration_inventory.entries] == [
        "retryable-construction"
    ]
    assert [entry.state for entry in runtime.registration_inventory.entries] == [
        "failed_retryable"
    ]
    assert [entry.attachment for entry in runtime.registration_inventory.entries] == [
        "pending_retirement"
    ]

    assert await binder.dispose(runtime) == ()
    assert active == set()
    assert len(disposal_attempts) == 2
    assert runtime.registration_inventory is not None
    assert runtime.registration_inventory.entries == ()


def test_graph_dispose_inventory_tracks_retryable_registration_cleanup() -> None:
    asyncio.run(_graph_dispose_inventory_tracks_retryable_registration_cleanup())


async def _graph_dispose_inventory_tracks_retryable_registration_cleanup() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    provider = _provider("harness.workspace")
    active: set[str] = set()
    disposal_attempts: list[str] = []

    def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
        identity = RegistrationIdentity.create(
            surface="tools",
            public_key="retryable-dispose",
        )
        active.add(identity.registration_id)

        def unregister() -> RegistrationDisposalResult:
            disposal_attempts.append(identity.registration_id)
            if len(disposal_attempts) == 1:
                return RegistrationDisposalResult(state="failed_retryable")
            active.discard(identity.registration_id)
            return RegistrationDisposalResult(state="removed")

        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=unregister,
            )
        )
        return CapabilityBundleValue((CapabilityFacetBinding("value", "workspace"),))

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(provider,),
        ),
        (_binding(provider, create=create),),
    )

    assert await binder.dispose(runtime) == ("registration_retirement_failed",)
    assert len(active) == 1
    assert runtime.registration_inventory is not None
    assert [entry.public_key for entry in runtime.registration_inventory.entries] == [
        "retryable-dispose"
    ]
    assert [entry.state for entry in runtime.registration_inventory.entries] == [
        "failed_retryable"
    ]
    assert [entry.attachment for entry in runtime.registration_inventory.entries] == [
        "pending_retirement"
    ]

    assert await binder.dispose(runtime) == ()
    assert active == set()
    assert len(disposal_attempts) == 2
    assert runtime.registration_inventory is not None
    assert runtime.registration_inventory.entries == ()


def test_rebind_inventory_tracks_failed_old_generation_retirement() -> None:
    asyncio.run(_rebind_inventory_tracks_failed_old_generation_retirement())


async def _rebind_inventory_tracks_failed_old_generation_retirement() -> None:
    definition = _definition("harness.workspace", scope="workspace", phase="bootstrap")
    original_provider = _provider("harness.workspace", provider_id="workspace.v1")
    replacement_provider = _provider("harness.workspace", provider_id="workspace.v2")
    active: set[str] = set()
    disposal_attempts: list[str] = []

    def create_original(context: CapabilityProviderContext) -> CapabilityBundleValue:
        identity = RegistrationIdentity.create(
            surface="tools",
            public_key="old-generation",
        )
        active.add(identity.registration_id)

        def unregister() -> RegistrationDisposalResult:
            disposal_attempts.append(identity.registration_id)
            if len(disposal_attempts) == 1:
                return RegistrationDisposalResult(state="failed_retryable")
            active.discard(identity.registration_id)
            return RegistrationDisposalResult(state="removed")

        context.registrations.add(
            RegistrationLease(
                owner=context.registrations.owner,
                identity=identity,
                dispose=unregister,
            )
        )
        return CapabilityBundleValue((CapabilityFacetBinding("value", "old"),))

    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="runtime-1",
        profile_fingerprint=_fingerprint("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(original_provider,),
        ),
        (_binding(original_provider, create=create_original),),
    )

    replacement = await binder.bind(
        runtime,
        _plan(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(definition,),
            providers=(replacement_provider,),
        ),
        (_binding(replacement_provider, value="new"),),
    )

    assert replacement.retirement_diagnostic_codes == (
        "registration_retirement_failed",
    )
    assert len(active) == 1
    assert runtime.registration_inventory is not None
    assert [entry.public_key for entry in runtime.registration_inventory.entries] == [
        "old-generation"
    ]
    assert [entry.state for entry in runtime.registration_inventory.entries] == [
        "failed_retryable"
    ]
    assert [entry.attachment for entry in runtime.registration_inventory.entries] == [
        "pending_retirement"
    ]
    pending_registration = runtime.registration_inventory.entries[0]
    assert (
        RuntimeCapabilityGraphProjector(runtime)
        .explain_registration(pending_registration.registration_id)
        .owner_node
        is None
    )
    assert (
        RuntimeCapabilityGraphProjector(runtime)
        .explain("harness.workspace")
        .registration_ids
        == ()
    )

    assert await binder.dispose(runtime) == ()
    assert active == set()
    assert len(disposal_attempts) == 2
    assert runtime.registration_inventory is not None
    assert runtime.registration_inventory.entries == ()
