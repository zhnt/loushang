from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.capabilities import (
    CapabilityGraphBindingError,
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
    RESOURCES_CAPABILITY_DEFINITION,
    RESOURCES_CAPABILITY_DEFINITION_V2,
    RESOURCES_CAPABILITY_DEFINITION_V3,
    RESOURCES_CATALOG_LOAD_REQUIREMENT,
    RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT,
)
from loushang.harness.capabilities.resources_provider import (
    resources_capability_provider_binding,
)
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources.activation import ResourceActivationRuntime
from loushang.harness.runtime import (
    RESOURCE_RUNTIME_SLOT,
    RuntimeCapabilityImplementation,
    RuntimeProfileResolver,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _profile():  # type: ignore[no-untyped-def]
    return RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )


def _fixture(tmp_path: Path) -> tuple[Path, tuple[object, ...], bytes]:
    workspace = tmp_path / "workspace"
    resource_root = workspace / ".loushang"
    skill_root = resource_root / "skills" / "review"
    skill_root.mkdir(parents=True)
    skill_body = (
        b"---\nname: review\ndescription: Review changes\n---\nReview carefully.\n"
    )
    (skill_root / "SKILL.md").write_bytes(skill_body)
    handles = (
        mint_native_resource_root_handle(
            handle_id="workspace-resources",
            root=resource_root,
            source_class="project_local",
            root_kind="standard",
            source_root_order=0,
        ),
    )
    return workspace, handles, skill_body


async def _prepare(candidate, handles, *, runtime_id: str) -> None:  # type: ignore[no-untyped-def]
    await prepare_first_party_resource_owner_generation(
        staged_candidate=candidate,
        product_id="coding",
        scope_id="workspace:test",
        runtime_id=runtime_id,
        product_policy_revision="coding-resource-catalog-v2",
        root_handles=handles,
        issued_at=10,
        expires_at=100,
        now=20,
    )


def _plan_for(binding, definition):  # type: ignore[no-untyped-def]
    return RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=(definition.capability_id,),
            definitions=(definition,),
            providers=(binding.provider,),
        )
    )


def _plan(binding):  # type: ignore[no-untyped-def]
    return _plan_for(binding, RESOURCES_CAPABILITY_DEFINITION_V2)


def _replace_resource_runtime(profile, implementation: str):  # type: ignore[no-untyped-def]
    capabilities = []
    for capability in profile.capabilities:
        if capability.slot.key != RESOURCE_RUNTIME_SLOT.key:
            capabilities.append(capability)
            continue
        selected = capability.selections[0]
        capabilities.append(
            replace(
                capability,
                selections=(
                    replace(
                        selected,
                        selection=replace(
                            selected.selection,
                            implementation=implementation,
                        ),
                    ),
                ),
            )
        )
    return replace(profile, capabilities=tuple(capabilities))


def test_v2_and_v3_resource_contract_shapes_remain_frozen() -> None:
    expected_facets = (
        "resource.runtime",
        "prompt.sections",
        "skill.activation",
        "tool.packs",
        "command.packs",
        "resource.catalog",
        "resource.load",
    )

    assert RESOURCES_CAPABILITY_DEFINITION_V2.contract_version == 2
    assert RESOURCES_CAPABILITY_DEFINITION_V2.facets == expected_facets
    assert RESOURCES_CAPABILITY_DEFINITION_V3.contract_version == 3
    assert RESOURCES_CAPABILITY_DEFINITION_V3.facets == expected_facets


def test_prepared_generation_is_one_candidate_child_and_root_cleanup_is_async(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _workspace, handles, _skill_body = _fixture(tmp_path)
        candidate = stage_resource_composition_candidate(_profile())
        await _prepare(candidate, handles, runtime_id="resource-owner:first")

        assert candidate.ownership_state == "root_owned"
        assert candidate.prepared_owner_generation_state == "root_owned"
        assert candidate.has_prepared_owner_generation is True
        with pytest.raises(
            RuntimeError, match="already has a prepared owner generation"
        ):
            await _prepare(candidate, handles, runtime_id="resource-owner:duplicate")
        with pytest.raises(RuntimeError, match="dispose_root_owned"):
            candidate.dispose()

        await candidate.dispose_root_owned()
        assert candidate.ownership_state == "disposed"
        assert candidate.prepared_owner_generation_state == "disposed"

    asyncio.run(scenario())


def test_v2_provider_adopts_generation_and_serves_exact_catalog_load(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _workspace, handles, skill_body = _fixture(tmp_path)
        profile = _profile()
        candidate = stage_resource_composition_candidate(profile)
        await _prepare(candidate, handles, runtime_id="resource-owner:mounted")
        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=candidate,
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="coding-session",
            profile_fingerprint=_sha("profile"),
        )
        binder = RuntimeCapabilityGraphBinder()

        await binder.bind(runtime, _plan(binding), (binding,))

        assert binding.provider.implementation_version == 2
        assert candidate.ownership_state == "graph_owned"
        assert candidate.prepared_owner_generation_state == "graph_owned"
        catalog = ResourceCatalogCapabilityConsumer(
            runtime.capture(RESOURCES_CATALOG_LOAD_REQUIREMENT)
        )
        with pytest.raises(RuntimeError, match="contract is incompatible"):
            runtime.capture(RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT)
        assert not hasattr(catalog, "projection")
        assert not hasattr(
            catalog.facets.require("resource.catalog"),
            "projection",
        )
        assert not hasattr(
            catalog.facets.require("resource.catalog"),
            "skill_projection",
        )
        assert not hasattr(
            catalog.facets.require("resource.catalog"),
            "skill_status_projection",
        )
        snapshot = catalog.snapshot
        identity = next(
            entry.identity
            for entry in snapshot.effective_entries
            if entry.identity.resource_kind == "skill"
        )
        loaded = await catalog.load(catalog.load_handle(identity))

        assert loaded.body == skill_body
        assert loaded.receipt.snapshot_fingerprint == snapshot.snapshot_fingerprint
        assert await binder.dispose(runtime) == ()
        assert candidate.ownership_state == "disposed"
        assert candidate.prepared_owner_generation_state == "disposed"

    asyncio.run(scenario())


def test_v1_binding_cannot_adopt_a_generation_attached_after_binding(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _workspace, handles, _skill_body = _fixture(tmp_path)
        profile = _profile()
        candidate = stage_resource_composition_candidate(profile)
        v1_binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=candidate,
        )
        await _prepare(candidate, handles, runtime_id="resource-owner:late")
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="coding-session",
            profile_fingerprint=_sha("profile"),
        )

        assert v1_binding.provider.implementation_version == 1
        with pytest.raises(CapabilityGraphBindingError):
            await RuntimeCapabilityGraphBinder().bind(
                runtime,
                _plan_for(v1_binding, RESOURCES_CAPABILITY_DEFINITION),
                (v1_binding,),
            )

        assert candidate.ownership_state == "root_owned"
        assert candidate.prepared_owner_generation_state == "root_owned"
        assert runtime.snapshot is None
        await candidate.dispose_root_owned()

    asyncio.run(scenario())


def test_v2_provider_construction_failure_returns_the_whole_candidate_to_root(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _workspace, handles, _skill_body = _fixture(tmp_path)
        profile = _profile()
        candidate = stage_resource_composition_candidate(profile)
        await _prepare(candidate, handles, runtime_id="resource-owner:rollback")

        def fail_commit() -> None:
            raise RuntimeError("reject adoption")

        candidate._commit_graph_ownership = fail_commit  # type: ignore[method-assign]
        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=candidate,
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="coding-session",
            profile_fingerprint=_sha("profile"),
        )

        with pytest.raises(CapabilityGraphBindingError):
            await RuntimeCapabilityGraphBinder().bind(
                runtime,
                _plan(binding),
                (binding,),
            )

        assert candidate.ownership_state == "root_owned"
        assert candidate.prepared_owner_generation_state == "root_owned"
        assert runtime.snapshot is None
        await candidate.dispose_root_owned()

    asyncio.run(scenario())


def test_v2_graph_reuse_leaves_new_content_generation_root_owned(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace, handles, _skill_body = _fixture(tmp_path)
        profile = _profile()
        first = stage_resource_composition_candidate(profile)
        await _prepare(first, handles, runtime_id="resource-owner:first")
        first_binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=first,
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="coding-session",
            profile_fingerprint=_sha("profile"),
        )
        binder = RuntimeCapabilityGraphBinder()
        await binder.bind(runtime, _plan(first_binding), (first_binding,))

        (workspace / ".loushang" / "skills" / "review" / "SKILL.md").write_text(
            "changed content generation",
            encoding="utf-8",
        )
        second = stage_resource_composition_candidate(profile)
        await _prepare(second, handles, runtime_id="resource-owner:second")
        second_binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=second,
        )
        reused = await binder.bind(
            runtime,
            _plan(second_binding),
            (second_binding,),
        )

        assert second_binding.binding_input_fingerprint == (
            first_binding.binding_input_fingerprint
        )
        assert reused.created_capability_ids == ()
        assert reused.reused_capability_ids == ("harness.resources",)
        assert first.ownership_state == "graph_owned"
        assert second.ownership_state == "root_owned"
        assert second.prepared_owner_generation_state == "root_owned"

        await second.dispose_root_owned()
        assert await binder.dispose(runtime) == ()
        assert first.ownership_state == "disposed"

    asyncio.run(scenario())


def test_v2_provider_retry_keeps_graph_retirement_custody(tmp_path: Path) -> None:
    async def scenario() -> None:
        _workspace, handles, _skill_body = _fixture(tmp_path)
        attempts: list[str] = []
        profile = _replace_resource_runtime(_profile(), "coding.retryable-resource")

        def dispose_resource(_value, _context):  # type: ignore[no-untyped-def]
            attempts.append("resource")
            if len(attempts) == 1:
                raise RuntimeError("transient Resource mechanism disposal failure")

        implementation = RuntimeCapabilityImplementation(
            slot=RESOURCE_RUNTIME_SLOT.key,
            implementation="coding.retryable-resource",
            implementation_version=1,
            create=lambda _selection, _context: ResourceActivationRuntime(),
            dispose=dispose_resource,
        )
        candidate = stage_resource_composition_candidate(
            profile,
            additional_implementations=(implementation,),
        )
        await _prepare(candidate, handles, runtime_id="resource-owner:retry")
        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=candidate,
            additional_implementations=(implementation,),
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="coding-session",
            profile_fingerprint=_sha("profile"),
        )
        binder = RuntimeCapabilityGraphBinder()
        await binder.bind(runtime, _plan(binding), (binding,))

        assert await binder.dispose(runtime) == ("provider_retirement_failed",)
        assert candidate.ownership_state == "retiring"
        assert candidate.prepared_owner_generation_state == "disposed"
        assert await binder.dispose(runtime) == ()
        assert candidate.ownership_state == "disposed"
        assert attempts == ["resource", "resource"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("cancellation_point", "state_after_bind"),
    (("graph_constructing", "root_owned"), ("prepublication", "disposed")),
)
def test_v2_cancellation_has_one_generation_cleanup_owner(
    tmp_path: Path,
    cancellation_point: str,
    state_after_bind: str,
) -> None:
    async def scenario() -> None:
        _workspace, handles, _skill_body = _fixture(tmp_path)
        profile = _profile()
        candidate = stage_resource_composition_candidate(profile)
        await _prepare(
            candidate,
            handles,
            runtime_id=f"resource-owner:cancel:{cancellation_point}",
        )
        original_commit = candidate._commit_graph_ownership

        def cancel_during_commit() -> None:
            if cancellation_point == "graph_constructing":
                raise asyncio.CancelledError
            original_commit()
            task = asyncio.current_task()
            assert task is not None
            task.cancel()

        candidate._commit_graph_ownership = cancel_during_commit  # type: ignore[method-assign]
        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            staged_candidate=candidate,
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="coding",
            runtime_id="coding-session",
            profile_fingerprint=_sha("profile"),
        )

        with pytest.raises(asyncio.CancelledError):
            await RuntimeCapabilityGraphBinder().bind(
                runtime,
                _plan(binding),
                (binding,),
            )

        assert candidate.ownership_state == state_after_bind
        assert candidate.prepared_owner_generation_state == state_after_bind
        if state_after_bind == "root_owned":
            await candidate.dispose_root_owned()
        assert candidate.ownership_state == "disposed"
        assert runtime.snapshot is None

    asyncio.run(scenario())
