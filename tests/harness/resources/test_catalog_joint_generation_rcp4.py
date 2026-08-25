from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.capabilities import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphRuntime,
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.resources_consumers import (
    ResourceCatalogCapabilityConsumer,
)
from loushang.harness.capabilities.resources_contracts import (
    RESOURCES_CAPABILITY_DEFINITION_V2,
    RESOURCES_CATALOG_LOAD_REQUIREMENT,
)
from loushang.harness.capabilities.resources_provider import (
    resources_capability_provider_binding,
)
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import ExtensionRuntimeBindings
from loushang.harness.extensions.types import (
    ExtensionResourceContribution,
    LoadedExtension,
)
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resource_catalog.joint_generation import (
    JointGenerationDisposalError,
    JointResourcePublication,
    prepare_extension_resource_joint_generation,
)
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import (
    ResourceIdentity,
    build_activation_policy_snapshot,
)
from loushang.harness.resources.types import PromptFragmentDescriptor, ResourceBundle
from loushang.harness.runtime import RuntimeProfileResolver


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _ignore_async(_value: object) -> None:
    return None


def _bindings(tmp_path: Path) -> ExtensionRuntimeBindings:
    return ExtensionRuntimeBindings(
        cwd=str(tmp_path),
        get_active_tool_names=lambda: [],
        get_model_selection=lambda: None,
        set_active_tools=_ignore_async,  # type: ignore[arg-type]
        set_model=_ignore_async,
        request_resource_refresh=lambda: None,
        shutdown=lambda: None,
        record_diagnostic=lambda _diagnostic: None,
    )


def _extension(tmp_path: Path) -> LoadedExtension:
    def discover(_bundle, _context):  # type: ignore[no-untyped-def]
        return ExtensionResourceContribution(
            prompt_descriptors=[
                PromptFragmentDescriptor(
                    name="review",
                    source_path=tmp_path / "review.md",
                    text="joint extension prompt",
                )
            ]
        )

    return LoadedExtension(
        name="example.review",
        source_path=tmp_path / "extension.py",
        source_root=tmp_path,
        source_root_order=4,
        hooks={"resources_discover": [discover]},
    )


def _profile():  # type: ignore[no-untyped-def]
    return RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )


def _plan(binding):  # type: ignore[no-untyped-def]
    return RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=(RESOURCES_CAPABILITY_DEFINITION_V2.capability_id,),
            definitions=(RESOURCES_CAPABILITY_DEFINITION_V2,),
            providers=(binding.provider,),
        )
    )


async def _prepare_root_joint(
    tmp_path: Path,
    *,
    disable_extension_prompt: bool = False,
):  # type: ignore[no-untyped-def]
    extension_runtime = ExtensionRunner([])
    bindings = _bindings(tmp_path)
    await extension_runtime.activate_runtime_generation(bindings)
    extension_candidate = extension_runtime.prepare_generation([_extension(tmp_path)])
    profile = _profile()
    resource_candidate = stage_resource_composition_candidate(profile)

    async def prepare_resource(source_lease):  # type: ignore[no-untyped-def]
        await prepare_first_party_resource_owner_generation(
            staged_candidate=resource_candidate,
            product_id="coding",
            scope_id="session:joint",
            runtime_id="resource-owner:joint",
            product_policy_revision="resource-policy-v1",
            root_handles=(),
            issued_at=1,
            expires_at=10,
            now=2,
            extension_source_lease=source_lease,
            projection_cwd=tmp_path,
            activation_policy=(
                build_activation_policy_snapshot(
                    policy_revision="joint-disabled-prompt",
                    disabled_identities=(
                        ResourceIdentity(
                            resource_kind="prompt",
                            schema_id="loushang.resource.prompt",
                            schema_version=1,
                            public_id="review",
                        ),
                    ),
                )
                if disable_extension_prompt
                else None
            ),
        )

    joint = await prepare_extension_resource_joint_generation(
        extension_candidate=extension_candidate,
        staged_resource_candidate=resource_candidate,
        base_resource_bundle=ResourceBundle(cwd=tmp_path),
        bindings=bindings,
        product_id="coding",
        extension_set_fingerprint=_digest("joint-extension-set"),
        prepare_resource_generation=prepare_resource,
    )
    return extension_runtime, extension_candidate, profile, resource_candidate, joint


async def _prepare_joint(tmp_path: Path):  # type: ignore[no-untyped-def]
    (
        extension_runtime,
        extension_candidate,
        profile,
        resource_candidate,
        joint,
    ) = await _prepare_root_joint(tmp_path)
    binding = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id="session:joint",
        staged_candidate=resource_candidate,
    )
    graph = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:joint",
        profile_fingerprint=_digest("joint-profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(graph, _plan(binding), (binding,))
    return (
        extension_runtime,
        extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    )


def test_root_owned_joint_rollback_releases_resource_borrow_and_extension_owner(
    tmp_path: Path,
) -> None:
    asyncio.run(_root_owned_joint_rollback(tmp_path))


async def _root_owned_joint_rollback(tmp_path: Path) -> None:
    (
        extension_runtime,
        _extension_candidate,
        _profile_value,
        resource_candidate,
        joint,
    ) = await _prepare_root_joint(tmp_path)

    await joint.rollback()

    assert extension_runtime.generation == 1
    assert resource_candidate.ownership_state == "disposed"
    assert joint.extension_source_generation.is_disposed is True
    assert joint.state == "disposed"


def test_failed_resource_preparation_releases_unclaimed_extension_source(
    tmp_path: Path,
) -> None:
    asyncio.run(_failed_resource_preparation_releases_source(tmp_path))


async def _failed_resource_preparation_releases_source(tmp_path: Path) -> None:
    extension_runtime = ExtensionRunner([])
    bindings = _bindings(tmp_path)
    await extension_runtime.activate_runtime_generation(bindings)
    extension_candidate = extension_runtime.prepare_generation([_extension(tmp_path)])
    resource_candidate = stage_resource_composition_candidate(_profile())
    observed_source = None

    async def fail_resource(source_lease):  # type: ignore[no-untyped-def]
        nonlocal observed_source
        observed_source = source_lease
        raise RuntimeError("resource preparation failed")

    with pytest.raises(RuntimeError, match="resource preparation failed"):
        await prepare_extension_resource_joint_generation(
            extension_candidate=extension_candidate,
            staged_resource_candidate=resource_candidate,
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            bindings=bindings,
            product_id="coding",
            extension_set_fingerprint=_digest("failed-extension-set"),
            prepare_resource_generation=fail_resource,
        )

    assert observed_source is not None
    assert observed_source.is_released is True
    assert extension_candidate.lifecycle_state == "rolled_back"
    assert resource_candidate.has_prepared_owner_generation is False
    assert resource_candidate.ownership_state == "disposed"


def test_joint_projection_uses_catalog_selection_not_extension_hook_pass(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_projection_uses_catalog_selection(tmp_path))


async def _joint_projection_uses_catalog_selection(tmp_path: Path) -> None:
    (
        _extension_runtime,
        extension_candidate,
        _profile_value,
        resource_candidate,
        joint,
    ) = await _prepare_root_joint(tmp_path, disable_extension_prompt=True)
    hook_pass = extension_candidate.resource_catalog_preparation
    assert hook_pass is not None
    assert [item.text for item in hook_pass.projection.prompt_descriptors] == [
        "joint extension prompt"
    ]

    assert joint.projection.to_compatibility_bundle().prompt_descriptors == []

    await joint.rollback()
    assert resource_candidate.ownership_state == "disposed"


def test_joint_preparation_rejects_claimed_but_unbound_extension_lease(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_preparation_rejects_unbound_lease(tmp_path))


async def _joint_preparation_rejects_unbound_lease(tmp_path: Path) -> None:
    extension_runtime = ExtensionRunner([])
    bindings = _bindings(tmp_path)
    await extension_runtime.activate_runtime_generation(bindings)
    extension_candidate = extension_runtime.prepare_generation([_extension(tmp_path)])
    resource_candidate = stage_resource_composition_candidate(_profile())
    observed_source = None

    async def prepare_unrelated_resource(source_lease):  # type: ignore[no-untyped-def]
        nonlocal observed_source
        observed_source = source_lease
        source_lease.claim()
        await prepare_first_party_resource_owner_generation(
            staged_candidate=resource_candidate,
            product_id="coding",
            scope_id="session:unbound",
            runtime_id="resource-owner:unbound",
            product_policy_revision="resource-policy-v1",
            root_handles=(),
            issued_at=1,
            expires_at=10,
            now=2,
        )

    with pytest.raises(RuntimeError, match="exact Extension source lease"):
        await prepare_extension_resource_joint_generation(
            extension_candidate=extension_candidate,
            staged_resource_candidate=resource_candidate,
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            bindings=bindings,
            product_id="coding",
            extension_set_fingerprint=_digest("unbound-extension-set"),
            prepare_resource_generation=prepare_unrelated_resource,
        )

    assert observed_source is not None
    assert observed_source.is_released is True
    assert extension_candidate.lifecycle_state == "rolled_back"
    assert resource_candidate.ownership_state == "disposed"


def test_failed_joint_preparation_preserves_graph_owned_source_lease(
    tmp_path: Path,
) -> None:
    asyncio.run(_failed_joint_preparation_preserves_graph_borrow(tmp_path))


async def _failed_joint_preparation_preserves_graph_borrow(tmp_path: Path) -> None:
    extension_runtime = ExtensionRunner([])
    bindings = _bindings(tmp_path)
    await extension_runtime.activate_runtime_generation(bindings)
    extension_candidate = extension_runtime.prepare_generation([_extension(tmp_path)])
    profile = _profile()
    resource_candidate = stage_resource_composition_candidate(profile)
    graph = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:escaped-preparation",
        profile_fingerprint=_digest("escaped-preparation-profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    observed_lease = None

    async def escape_to_graph(source_lease):  # type: ignore[no-untyped-def]
        nonlocal observed_lease
        observed_lease = source_lease
        await prepare_first_party_resource_owner_generation(
            staged_candidate=resource_candidate,
            product_id="coding",
            scope_id="session:escaped-preparation",
            runtime_id="resource-owner:escaped-preparation",
            product_policy_revision="resource-policy-v1",
            root_handles=(),
            issued_at=1,
            expires_at=10,
            now=2,
            extension_source_lease=source_lease,
            projection_cwd=tmp_path,
        )
        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:escaped-preparation",
            staged_candidate=resource_candidate,
        )
        await binder.bind(graph, _plan(binding), (binding,))

    with pytest.raises(RuntimeError, match="not root-owned") as caught:
        await prepare_extension_resource_joint_generation(
            extension_candidate=extension_candidate,
            staged_resource_candidate=resource_candidate,
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            bindings=bindings,
            product_id="coding",
            extension_set_fingerprint=_digest("escaped-preparation-set"),
            prepare_resource_generation=escape_to_graph,
        )

    assert any(
        "joint_resource_retirement_pending" in note
        for note in caught.value.__notes__
    )
    assert observed_lease is not None
    assert observed_lease.is_released is False
    prepared_catalog = extension_candidate.resource_catalog_preparation
    assert prepared_catalog is not None
    assert prepared_catalog.source_generation.is_retiring is True
    consumer = ResourceCatalogCapabilityConsumer(
        graph.capture(RESOURCES_CATALOG_LOAD_REQUIREMENT)
    )
    identity = ResourceIdentity(
        resource_kind="prompt",
        schema_id="loushang.resource.prompt",
        schema_version=1,
        public_id="review",
    )
    assert (await consumer.load(consumer.load_handle(identity))).body == (
        b"joint extension prompt"
    )

    assert await binder.dispose(graph) == ()
    assert resource_candidate.ownership_state == "disposed"
    assert observed_lease.is_released is True
    assert prepared_catalog.source_generation.is_disposed is True
    await extension_runtime.dispose_runtime_generation()


def test_joint_generation_publishes_extension_catalog_and_projection_once(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_generation_publishes_once(tmp_path))


async def _joint_generation_publishes_once(tmp_path: Path) -> None:
    (
        extension_runtime,
        _extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    ) = await _prepare_joint(tmp_path)
    previous_projection = "previous-projection"
    visible: dict[str, object] = {
        "catalog": "previous-catalog",
        "projection": previous_projection,
    }
    commits = 0

    def commit(catalog: object, projection: ResourceCatalogProjection) -> None:
        nonlocal commits
        commits += 1
        visible["catalog"] = catalog
        visible["projection"] = projection

    publication = JointResourcePublication(
        capture=lambda: (visible["catalog"], visible["projection"]),
        commit=commit,
        restore=lambda previous: visible.update(
            catalog=previous[0],  # type: ignore[index]
            projection=previous[1],  # type: ignore[index]
        ),
    )
    retirement = joint.publish(publication)

    assert commits == 1
    assert extension_runtime.generation == 2
    assert resource_candidate.ownership_state == "graph_owned"
    assert visible["catalog"] is resource_candidate.resource_catalog_snapshot
    assert visible["projection"] is joint.projection
    assert [
        descriptor.text
        for descriptor in joint.projection.to_compatibility_bundle().prompt_descriptors
    ] == ["joint extension prompt"]
    assert joint.extension_source_generation.is_disposed is False

    await retirement.retire()
    await extension_runtime.dispose_runtime_generation()
    assert joint.extension_source_generation.is_retiring is True
    assert joint.extension_source_generation.is_disposed is False
    consumer = ResourceCatalogCapabilityConsumer(
        graph.capture(RESOURCES_CATALOG_LOAD_REQUIREMENT)
    )
    identity = ResourceIdentity(
        resource_kind="prompt",
        schema_id="loushang.resource.prompt",
        schema_version=1,
        public_id="review",
    )
    assert (await consumer.load(consumer.load_handle(identity))).body == (
        b"joint extension prompt"
    )
    assert await binder.dispose(graph) == ()
    assert joint.extension_source_generation.is_disposed is True


def test_joint_publication_failure_restores_projection_and_rolls_back_both_owners(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_publication_failure_rolls_back_both_owners(tmp_path))


async def _joint_publication_failure_rolls_back_both_owners(tmp_path: Path) -> None:
    (
        extension_runtime,
        _extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    ) = await _prepare_joint(tmp_path)
    previous_projection = "previous-projection"
    visible: dict[str, object] = {
        "catalog": "previous-catalog",
        "projection": previous_projection,
    }

    def fail_commit(
        catalog: object,
        projection: ResourceCatalogProjection,
    ) -> None:
        visible["catalog"] = catalog
        visible["projection"] = projection
        raise RuntimeError("projection publication failed")

    publication = JointResourcePublication(
        capture=lambda: (visible["catalog"], visible["projection"]),
        commit=fail_commit,
        restore=lambda previous: visible.update(
            catalog=previous[0],  # type: ignore[index]
            projection=previous[1],  # type: ignore[index]
        ),
    )

    with pytest.raises(RuntimeError, match="projection publication failed"):
        joint.publish(publication)
    await joint.rollback(dispose_graph=lambda: binder.dispose(graph))

    assert visible == {
        "catalog": "previous-catalog",
        "projection": previous_projection,
    }
    assert extension_runtime.generation == 1
    assert resource_candidate.ownership_state == "disposed"
    assert joint.extension_source_generation.is_disposed is True
    assert joint.state == "disposed"


def test_joint_publication_rejects_async_commit_before_visibility_changes(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_publication_rejects_async_commit(tmp_path))


async def _joint_publication_rejects_async_commit(tmp_path: Path) -> None:
    (
        extension_runtime,
        _extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    ) = await _prepare_joint(tmp_path)
    restored: list[object] = []

    async def async_commit(
        _catalog: object,
        _projection: ResourceCatalogProjection,
    ) -> None:
        raise AssertionError("async publication body must never execute")

    publication = JointResourcePublication(
        capture=lambda: "previous",
        commit=async_commit,
        restore=lambda previous: restored.append(previous),
    )

    with pytest.raises(TypeError, match="must be synchronous"):
        joint.publish(publication)
    await joint.rollback(dispose_graph=lambda: binder.dispose(graph))

    assert restored == ["previous"]
    assert extension_runtime.generation == 1
    assert resource_candidate.ownership_state == "disposed"


def test_joint_graph_rollback_retains_retryable_source_drain_debt(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_graph_rollback_retries_source_drain(tmp_path))


async def _joint_graph_rollback_retries_source_drain(tmp_path: Path) -> None:
    (
        extension_runtime,
        extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    ) = await _prepare_joint(tmp_path)

    async def retain_graph() -> tuple[str, ...]:
        return ("provider_retirement_failed",)

    with pytest.raises(JointGenerationDisposalError) as pending:
        await joint.rollback(dispose_graph=retain_graph)

    assert "joint_resource_retirement_pending" in pending.value.diagnostic_codes
    assert "joint_extension_source_retirement_pending" in (
        pending.value.diagnostic_codes
    )
    assert extension_runtime.generation == 1
    assert resource_candidate.ownership_state == "graph_owned"
    assert joint.extension_source_generation.is_retiring is True
    assert joint.state == "retiring"

    await joint.rollback(dispose_graph=lambda: binder.dispose(graph))
    assert resource_candidate.ownership_state == "disposed"
    assert joint.extension_source_generation.is_disposed is True
    assert joint.state == "disposed"


def test_joint_rollback_retries_extension_cleanup_after_rolled_back_state(
    tmp_path: Path,
) -> None:
    asyncio.run(_joint_rollback_retries_extension_cleanup(tmp_path))


async def _joint_rollback_retries_extension_cleanup(tmp_path: Path) -> None:
    (
        _extension_runtime,
        extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    ) = await _prepare_joint(tmp_path)
    rollback = extension_candidate.rollback
    attempts = 0

    async def fail_first_report():  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        reports = await rollback()
        if attempts == 1:
            return (*reports, SimpleNamespace(has_failures=True))
        return reports

    extension_candidate.rollback = fail_first_report  # type: ignore[method-assign]

    with pytest.raises(JointGenerationDisposalError) as pending:
        await joint.rollback(dispose_graph=lambda: binder.dispose(graph))

    assert "joint_extension_retirement_pending" in pending.value.diagnostic_codes
    assert attempts == 1
    assert extension_candidate.lifecycle_state == "rolled_back"

    await joint.rollback(dispose_graph=lambda: binder.dispose(graph))

    assert attempts == 2
    assert resource_candidate.ownership_state == "disposed"
    assert joint.extension_source_generation.is_disposed is True
    assert joint.state == "disposed"


def test_cancelled_joint_rollback_finishes_graph_and_source_cleanup(
    tmp_path: Path,
) -> None:
    asyncio.run(_cancelled_joint_rollback_finishes_cleanup(tmp_path))


async def _cancelled_joint_rollback_finishes_cleanup(tmp_path: Path) -> None:
    (
        _extension_runtime,
        _extension_candidate,
        resource_candidate,
        joint,
        graph,
        binder,
    ) = await _prepare_joint(tmp_path)
    disposal_started = asyncio.Event()
    release_disposal = asyncio.Event()

    async def dispose_graph() -> tuple[str, ...]:
        disposal_started.set()
        await release_disposal.wait()
        return await binder.dispose(graph)

    rollback = asyncio.create_task(joint.rollback(dispose_graph=dispose_graph))
    await disposal_started.wait()
    rollback.cancel()
    release_disposal.set()

    with pytest.raises(asyncio.CancelledError):
        await rollback
    assert resource_candidate.ownership_state == "disposed"
    assert joint.extension_source_generation.is_disposed is True
    assert joint.state == "disposed"
