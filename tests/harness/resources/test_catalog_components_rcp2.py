from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.resource_catalog.components import (
    NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
    RESOURCE_CATALOG_ENGINE_COMPONENT_KIND,
    RESOURCE_CATALOG_ENGINE_DEFINITION,
    RESOURCE_SOURCE_COMPONENT_KIND,
    RESOURCE_SOURCE_DEFINITION,
    ResourceCatalogComponentError,
    ResourceCatalogCompositionControl,
    ResourceSourceComponent,
    validate_resource_catalog_proposal,
)
from loushang.harness.resource_catalog.shadow import (
    run_first_party_resource_catalog_shadow,
)
from loushang.harness.resources._catalog_engine import (
    compose_resource_catalog,
    default_resource_merge_policy,
)
from loushang.harness.resources._catalog_native_source import (
    NativeFilesystemResourceSource,
    NativeResourceDiscoveryBudget,
    NativeResourceSourceError,
    build_native_resource_discovery_request,
    mint_native_resource_root_handle,
)
from loushang.harness.resources._catalog_records import (
    ResourceComponentProducer,
    ResourceIdentity,
    build_activation_policy_snapshot,
)
from loushang.harness.resources.loader import ResourceLoader


def _fixture_workspace(tmp_path: Path) -> tuple[Path, Path, bytes]:
    workspace = tmp_path / "workspace"
    resource_root = workspace / ".loushang"
    (resource_root / "prompts").mkdir(parents=True)
    (resource_root / "skills" / "review").mkdir(parents=True)
    (resource_root / "skills" / "ignored").mkdir()
    (resource_root / "extensions").mkdir()
    (resource_root / "themes").mkdir()
    (workspace / "AGENTS.md").write_text("Workspace guidance.\n", encoding="utf-8")
    (resource_root / "AGENTS.md").write_text(
        "Must not widen the context-root handle.\n",
        encoding="utf-8",
    )
    (resource_root / "prompts" / "plan.md").write_text(
        "---\ndescription: Plan carefully\n---\nPlan.\n",
        encoding="utf-8",
    )
    skill_body = (
        b"---\nname: review\ndescription: Review changes\n---\nReview carefully.\n"
    )
    (resource_root / "skills" / "review" / "SKILL.md").write_bytes(skill_body)
    (resource_root / "skills" / ".ignore").write_text(
        "ignored/\n",
        encoding="utf-8",
    )
    (resource_root / "skills" / "ignored" / "SKILL.md").write_text(
        "---\nname: ignored\ndescription: Ignore me\n---\nIgnored.\n",
        encoding="utf-8",
    )
    (resource_root / "extensions" / "guard.py").write_text(
        "# inert shadow descriptor\n",
        encoding="utf-8",
    )
    (resource_root / "themes" / "clean.json").write_text(
        '{"background": "black"}\n',
        encoding="utf-8",
    )
    return workspace, resource_root, skill_body


def _root_handles(workspace: Path, resource_root: Path):  # type: ignore[no-untyped-def]
    return (
        mint_native_resource_root_handle(
            handle_id="workspace-context",
            root=workspace,
            source_class="project_local",
            root_kind="context",
            source_root_order=0,
        ),
        mint_native_resource_root_handle(
            handle_id="workspace-resources",
            root=resource_root,
            source_class="project_local",
            root_kind="standard",
            source_root_order=0,
        ),
    )


async def _first_party_components_run_in_unpublished_owner_generation_and_match_loader(
    tmp_path: Path,
) -> None:
    workspace, resource_root, skill_body = _fixture_workspace(tmp_path)
    root_handles = _root_handles(workspace, resource_root)
    legacy_loader = ResourceLoader(user_resource_roots=())
    legacy_bundle = legacy_loader.discover_resources(workspace)

    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:test",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=root_handles,
        issued_at=10,
        expires_at=100,
        now=20,
    )

    legacy_identities = {
        *(
            ("context", item.id)
            for item in legacy_bundle.prompt_descriptors
            if item.prompt_kind != "prompt_asset"
        ),
        *(
            ("prompt", item.id)
            for item in legacy_bundle.prompt_descriptors
            if item.prompt_kind == "prompt_asset"
        ),
        *(("skill", item.id) for item in legacy_bundle.skills),
        *(("extension", item.id) for item in legacy_bundle.extensions),
        *(("theme", item.id) for item in legacy_bundle.themes),
    }
    shadow_identities = {
        (entry.identity.resource_kind, entry.identity.public_id)
        for entry in shadow.catalog_snapshot.effective_entries
    }

    assert shadow.owner_generation == 1
    assert shadow.catalog_snapshot.catalog_generation == 1
    assert shadow_identities == legacy_identities
    assert tuple(
        entry.component_kind
        for entry in shadow._runtime.snapshot.entries  # type: ignore[union-attr]
    ) == (RESOURCE_CATALOG_ENGINE_COMPONENT_KIND, RESOURCE_SOURCE_COMPONENT_KIND)
    assert all(
        candidate.binding_spec.source_kind == "first_party"
        and candidate.instance_revision_ref is None
        and candidate.package_source_identity is None
        for candidate in shadow.resolution.candidates
    )
    producer = shadow.source_snapshots[0].source_generation_ref.producer
    assert isinstance(producer, ResourceComponentProducer)
    assert producer.component_contribution_id == NATIVE_RESOURCE_SOURCE_COMPONENT_ID
    assert producer.component_candidate_fingerprint == (
        shadow.resolution.candidates[1].fingerprint
    )

    skill_identity = next(
        entry.identity
        for entry in shadow.catalog_snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    )
    handle = shadow.load_handle(skill_identity)
    (resource_root / "skills" / "review" / "SKILL.md").write_text(
        "changed after discovery",
        encoding="utf-8",
    )
    loaded = await shadow.load(handle)

    assert loaded.body == skill_body
    assert loaded.receipt.content_digest == handle.expected_content_digest
    assert await shadow.dispose() == ()
    assert shadow.is_disposed is True
    with pytest.raises(RuntimeError, match="disposed"):
        await shadow.load(handle)


def test_first_party_components_run_in_unpublished_owner_generation_and_match_loader(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _first_party_components_run_in_unpublished_owner_generation_and_match_loader(
            tmp_path
        )
    )


async def _native_source_preserves_project_over_user_precedence(tmp_path: Path) -> None:
    workspace, resource_root, project_skill_body = _fixture_workspace(tmp_path)
    user_root = tmp_path / "user-resources"
    (user_root / "skills" / "review").mkdir(parents=True)
    (user_root / "skills" / "review" / "SKILL.md").write_text(
        "---\nname: review\ndescription: User review\n---\nUser rules.\n",
        encoding="utf-8",
    )
    user_handle = mint_native_resource_root_handle(
        handle_id="user-resources",
        root=user_root,
        source_class="user_global",
        root_kind="combined",
        source_root_order=0,
    )
    legacy = ResourceLoader(user_resource_roots=(user_root,)).discover_resources(
        workspace
    )
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:precedence",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=(*_root_handles(workspace, resource_root), user_handle),
        issued_at=10,
        expires_at=100,
        now=20,
    )
    skill_entry = next(
        entry
        for entry in shadow.catalog_snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    )
    winner = shadow.catalog_snapshot.candidate_by_fingerprint(
        skill_entry.primary_candidate_fingerprint
    )

    assert len(legacy.skills) == 1
    assert legacy.skills[0].source_kind == "project_local"
    assert winner.source_class == "project_local"
    assert (await shadow.load(shadow.load_handle(skill_entry.identity))).body == (
        project_skill_body
    )
    assert await shadow.dispose() == ()


def test_native_source_preserves_project_over_user_precedence(tmp_path: Path) -> None:
    asyncio.run(_native_source_preserves_project_over_user_precedence(tmp_path))


async def _native_source_discovery_is_sync_budgeted_and_cancellation_propagates(
    tmp_path: Path,
) -> None:
    workspace, resource_root, _skill_body = _fixture_workspace(tmp_path)
    root_handles = _root_handles(workspace, resource_root)

    assert (
        inspect.iscoroutinefunction(NativeFilesystemResourceSource.discover_initial)
        is False
    )
    with pytest.raises(NativeResourceSourceError) as exhausted:
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:budget",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=root_handles,
            issued_at=10,
            expires_at=100,
            now=20,
            discovery_budget=NativeResourceDiscoveryBudget(maximum_entries=1),
        )
    assert exhausted.value.code == "resource_source_discovery_budget_exceeded"
    assert exhausted.value.reason == "entry_count_exceeded"

    with pytest.raises(asyncio.CancelledError):
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:cancel",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=root_handles,
            issued_at=10,
            expires_at=100,
            now=20,
            discovery_cancellation_probe=lambda: True,
        )


def test_native_source_discovery_is_sync_budgeted_and_cancellation_propagates(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _native_source_discovery_is_sync_budgeted_and_cancellation_propagates(tmp_path)
    )


async def _native_source_handles_are_narrow_and_discovery_is_generation_exact(
    tmp_path: Path,
) -> None:
    workspace, resource_root, _skill_body = _fixture_workspace(tmp_path)
    root_handles = _root_handles(workspace, resource_root)
    with pytest.raises(TypeError, match="Host-minted"):
        type(root_handles[0])()
    symlink = tmp_path / "resource-link"
    symlink.symlink_to(resource_root, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symlink"):
        mint_native_resource_root_handle(
            handle_id="symlink-root",
            root=symlink,
            source_class="project_local",
            root_kind="standard",
        )

    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:exact",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=root_handles,
        issued_at=10,
        expires_at=100,
        now=20,
    )
    source_lease = shadow._runtime.capture_one(RESOURCE_SOURCE_COMPONENT_KIND)
    try:
        source = source_lease.require()
        assert isinstance(source, ResourceSourceComponent)
        foreign_source_ref = replace(
            source.source_generation_ref,
            generation="foreign-generation",
        )
        foreign_request = build_native_resource_discovery_request(
            product_id="coding",
            source_generation_ref=foreign_source_ref,
            root_handle_ids=tuple(item.handle_id for item in root_handles),
        )
        with pytest.raises(NativeResourceSourceError) as rejected:
            source.discover_initial(foreign_request)
        assert rejected.value.code == "resource_catalog_generation_stale"
        assert rejected.value.reason == "foreign_source_generation"
    finally:
        await source_lease.aclose()
    assert await shadow.dispose() == ()

    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (resource_root / "prompts" / "escape.md").symlink_to(outside)
    with pytest.raises(NativeResourceSourceError) as escaped:
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:symlink",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=root_handles,
            issued_at=10,
            expires_at=100,
            now=20,
        )
    assert escaped.value.code == "resource_source_discovery_failed"
    assert escaped.value.reason == "symlink_not_allowed"


def test_native_source_handles_are_narrow_and_discovery_is_generation_exact(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _native_source_handles_are_narrow_and_discovery_is_generation_exact(tmp_path)
    )


async def _owner_validator_rejects_a_policy_divergent_engine_proposal(
    tmp_path: Path,
) -> None:
    workspace, resource_root, _skill_body = _fixture_workspace(tmp_path)
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:validator",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=_root_handles(workspace, resource_root),
        issued_at=10,
        expires_at=100,
        now=20,
    )
    different_activation = build_activation_policy_snapshot(
        policy_revision="different-activation-policy",
        disabled_identities=(
            ResourceIdentity(
                resource_kind="skill",
                schema_id="loushang.resource.skill",
                schema_version=1,
                public_id="review/SKILL.md",
            ),
        ),
    )
    divergent = compose_resource_catalog(
        shadow.source_snapshots,
        catalog_generation=shadow.catalog_snapshot.catalog_generation,
        engine_binding_fingerprint=shadow.catalog_snapshot.engine_binding_fingerprint,
        merge_policy=default_resource_merge_policy(),
        activation_policy=different_activation,
    )

    with pytest.raises(ResourceCatalogComponentError) as rejected:
        validate_resource_catalog_proposal(
            divergent,
            source_snapshots=shadow.source_snapshots,
            catalog_generation=shadow.catalog_snapshot.catalog_generation,
            engine_binding_fingerprint=(
                shadow.catalog_snapshot.engine_binding_fingerprint
            ),
            merge_policy=default_resource_merge_policy(),
            activation_policy=build_activation_policy_snapshot(
                policy_revision="resource-activation-policy-v2-rcp2-shadow"
            ),
        )
    assert rejected.value.code == "resource_catalog_proposal_invalid"
    assert rejected.value.reason == "owner_policy_mismatch"
    assert await shadow.dispose() == ()


def test_owner_validator_rejects_a_policy_divergent_engine_proposal(
    tmp_path: Path,
) -> None:
    asyncio.run(_owner_validator_rejects_a_policy_divergent_engine_proposal(tmp_path))


def test_resource_component_definitions_are_narrow_and_match_bundle_v1() -> None:
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.multiplicity == "exclusive"
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.selection_policy == "exactly_one"
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.compatible_bundle_contract.minimum == 1
    assert RESOURCE_SOURCE_DEFINITION.multiplicity == "aggregate"
    assert RESOURCE_SOURCE_DEFINITION.selection_policy == "ordered_unique"
    assert RESOURCE_SOURCE_DEFINITION.disposer_contract == "required"
    with pytest.raises(asyncio.CancelledError):
        ResourceCatalogCompositionControl(cancelled=True).check()
    with pytest.raises(ResourceCatalogComponentError) as deadline:
        ResourceCatalogCompositionControl(deadline_exceeded=True).check()
    assert deadline.value.reason == "deadline_exceeded"
