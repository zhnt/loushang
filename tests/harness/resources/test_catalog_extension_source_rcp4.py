from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

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
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.resources import ExtensionResourceRuntime
from loushang.harness.extensions.types import (
    ExtensionResourceContribution,
    LoadedExtension,
)
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resource_catalog.shadow import (
    run_first_party_resource_catalog_shadow,
)
from loushang.harness.resources._catalog_extension_source import (
    ExtensionResourceRouteContribution,
    ExtensionResourceSourceError,
    freeze_extension_resource_source_generation,
)
from loushang.harness.resources._catalog_records import (
    ExtensionOutputOrigin,
    ExtensionOwnerProducer,
    ResourceCatalogHandle,
    ResourceIdentity,
    ResourceLoadHandle,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    ResourceSourceKind,
    SkillDescriptor,
)
from loushang.harness.runtime import RuntimeProfileResolver


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _profile():  # type: ignore[no-untyped-def]
    return RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )


def _prompt(path: Path, *, text: str = "extension prompt") -> PromptFragmentDescriptor:
    return PromptFragmentDescriptor(
        name="review",
        source_path=path,
        text=text,
        description="Review the current change",
        source="extension",
        source_kind="project_local",
        source_scope="project",
        source_root=path.parent,
        source_root_order=3,
    )


def _skill(path: Path, *, content: str | None) -> SkillDescriptor:
    return SkillDescriptor(
        name="audit",
        source_path=path,
        content=content,
        description="Audit one change",
        source="extension",
        source_kind="project_local",
        source_scope="project",
        source_root=path.parent,
        source_root_order=3,
    )


def _route(
    *,
    prompts: tuple[PromptFragmentDescriptor, ...] = (),
    skills: tuple[SkillDescriptor, ...] = (),
    diagnostics: tuple[DiagnosticDraft, ...] = (),
    source_class: ResourceSourceKind = "project_local",
) -> ExtensionResourceRouteContribution:
    return ExtensionResourceRouteContribution(
        extension_id="example.review",
        route_id="example.review:resources_discover:resources",
        source_class=source_class,
        scope_id="project",
        source_root_order=3,
        route_order=0,
        prompt_descriptors=prompts,
        skills=skills,
        diagnostics=diagnostics,
    )


def test_extension_generation_freezes_exact_provenance_and_body_bytes(
    tmp_path: Path,
) -> None:
    prompt_path = tmp_path / "review.md"
    prompt_path.write_text("extension prompt", encoding="utf-8")
    metadata = {"state": "frozen"}
    prompt = replace(_prompt(prompt_path), metadata=metadata)
    generation = freeze_extension_resource_source_generation(
        product_id="coding",
        runtime_id="extension-runtime-1",
        extension_generation=2,
        extension_set_fingerprint=_digest("extension-set"),
        route_contributions=(_route(prompts=(prompt,)),),
    )

    snapshot = generation.source_snapshot
    assert snapshot.complete is True
    assert len(snapshot.candidate_summaries) == 1
    candidate = snapshot.candidate_summaries[0]
    assert isinstance(snapshot.source_generation_ref.producer, ExtensionOwnerProducer)
    assert snapshot.source_generation_ref.producer.runtime_id == "extension-runtime-1"
    assert snapshot.source_generation_ref.producer.extension_generation == "2"
    assert isinstance(candidate.content_origin, ExtensionOutputOrigin)
    assert candidate.content_origin.extension_generation_ref == "2"
    assert candidate.content_origin.extension_id == "example.review"
    assert candidate.content_origin.route_id.endswith(":resources")
    assert candidate.expected_content_digest == _digest("extension prompt")
    metadata["state"] = "mutated"
    frozen_metadata = generation.descriptor_bindings[0].descriptor.metadata
    assert frozen_metadata["state"] == "frozen"

    # The retained body belongs to the frozen generation, not the mutable path.
    prompt_path.write_text("changed after discovery", encoding="utf-8")
    handle = ResourceLoadHandle.from_catalog(
        catalog_handle=ResourceCatalogHandle(
            catalog_generation=7,
            snapshot_fingerprint=_digest("catalog"),
            identity=candidate.identity,
            candidate_fingerprint=candidate.candidate_fingerprint,
        ),
        candidate=candidate,
    )
    body = generation.load(handle)
    assert body.body == b"extension prompt"
    assert body.observed_content_digest == _digest("extension prompt")


def test_extension_generation_rejects_unfrozen_body_and_foreign_source_facts(
    tmp_path: Path,
) -> None:
    with pytest.raises(ExtensionResourceSourceError) as missing_body:
        freeze_extension_resource_source_generation(
            product_id="coding",
            runtime_id="extension-runtime-1",
            extension_generation=2,
            extension_set_fingerprint=_digest("extension-set"),
            route_contributions=(
                _route(skills=(_skill(tmp_path / "SKILL.md", content=None),)),
            ),
        )
    assert missing_body.value.code == "resource_source_snapshot_invalid"
    assert missing_body.value.reason == "extension_body_identity_missing"

    with pytest.raises(ExtensionResourceSourceError) as foreign_source:
        freeze_extension_resource_source_generation(
            product_id="coding",
            runtime_id="extension-runtime-1",
            extension_generation=2,
            extension_set_fingerprint=_digest("extension-set"),
            route_contributions=(
                _route(
                    prompts=(_prompt(tmp_path / "review.md"),),
                    source_class="user_global",
                ),
            ),
        )
    assert foreign_source.value.code == "resource_source_snapshot_invalid"
    assert foreign_source.value.reason == "extension_source_facts_mismatch"


def test_extension_generation_binds_exact_route_execution_order(tmp_path: Path) -> None:
    first = _route(prompts=(_prompt(tmp_path / "first.md", text="first"),))
    second = replace(
        _route(skills=(_skill(tmp_path / "SKILL.md", content="second"),)),
        extension_id="example.audit",
        route_id="example.audit:resources_discover:resources",
        route_order=1,
    )
    original = freeze_extension_resource_source_generation(
        product_id="coding",
        runtime_id="extension-runtime-order",
        extension_generation=1,
        extension_set_fingerprint=_digest("extension-set-order"),
        route_contributions=(first, second),
    )
    reordered = freeze_extension_resource_source_generation(
        product_id="coding",
        runtime_id="extension-runtime-order",
        extension_generation=1,
        extension_set_fingerprint=_digest("extension-set-order"),
        route_contributions=(
            replace(first, route_order=1),
            replace(second, route_order=0),
        ),
    )

    assert (
        original.source_snapshot.snapshot_fingerprint
        != reordered.source_snapshot.snapshot_fingerprint
    )
    original.dispose()
    reordered.dispose()


def test_unpublished_catalog_composes_and_loads_borrowed_extension_generation(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _unpublished_catalog_composes_and_loads_borrowed_extension_generation(tmp_path)
    )


async def _unpublished_catalog_composes_and_loads_borrowed_extension_generation(
    tmp_path: Path,
) -> None:
    generation = freeze_extension_resource_source_generation(
        product_id="coding",
        runtime_id="extension-runtime-1",
        extension_generation=1,
        extension_set_fingerprint=_digest("extension-set"),
        route_contributions=(
            _route(
                prompts=(_prompt(tmp_path / "review.md"),),
                diagnostics=(
                    DiagnosticDraft(
                        code="extension_resource_notice",
                        message="extension resource notice",
                    ),
                ),
            ),
        ),
    )
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="session:test",
        runtime_id="resource-runtime-1",
        product_policy_revision="resource-policy-v1",
        root_handles=(),
        issued_at=1,
        expires_at=10,
        now=2,
        extension_source_generation=generation,
    )
    identity = ResourceIdentity(
        resource_kind="prompt",
        schema_id="loushang.resource.prompt",
        schema_version=1,
        public_id="review",
    )

    assert generation.source_snapshot.snapshot_fingerprint in (
        shadow.catalog_snapshot.source_generation_fingerprints
    )
    assert any(
        diagnostic.code == "extension_resource_notice"
        for diagnostic in shadow.catalog_snapshot.diagnostics
    )
    load_handle = shadow.load_handle(identity)
    loaded = await shadow.load(load_handle)
    assert loaded.body == b"extension prompt"

    await shadow.dispose()
    assert generation.is_disposed is False
    generation.dispose()
    assert generation.is_disposed is True
    with pytest.raises(ExtensionResourceSourceError) as stale:
        generation.load(load_handle)
    assert stale.value.code == "resource_body_read_failed"
    assert stale.value.reason == "source_disposed"


def test_graph_owned_catalog_loads_extension_body_without_stealing_its_custody(
    tmp_path: Path,
) -> None:
    asyncio.run(_graph_owned_catalog_loads_extension_body(tmp_path))


async def _graph_owned_catalog_loads_extension_body(tmp_path: Path) -> None:
    extension_generation = freeze_extension_resource_source_generation(
        product_id="coding",
        runtime_id="extension-runtime-graph",
        extension_generation=1,
        extension_set_fingerprint=_digest("extension-set-graph"),
        route_contributions=(
            _route(prompts=(_prompt(tmp_path / "review.md", text="graph body"),)),
        ),
    )
    profile = _profile()
    candidate = stage_resource_composition_candidate(profile)
    await prepare_first_party_resource_owner_generation(
        staged_candidate=candidate,
        product_id="coding",
        scope_id="session:test",
        runtime_id="resource-owner:extension",
        product_policy_revision="resource-policy-v1",
        root_handles=(),
        issued_at=1,
        expires_at=10,
        now=2,
        extension_source_generation=extension_generation,
    )
    binding = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id="session:test",
        staged_candidate=candidate,
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=(RESOURCES_CAPABILITY_DEFINITION_V2.capability_id,),
            definitions=(RESOURCES_CAPABILITY_DEFINITION_V2,),
            providers=(binding.provider,),
        )
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="session:test",
        profile_fingerprint=_digest("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, plan, (binding,))
    consumer = ResourceCatalogCapabilityConsumer(
        runtime.capture(RESOURCES_CATALOG_LOAD_REQUIREMENT)
    )
    identity = ResourceIdentity(
        resource_kind="prompt",
        schema_id="loushang.resource.prompt",
        schema_version=1,
        public_id="review",
    )

    loaded = await consumer.load(consumer.load_handle(identity))
    assert loaded.body == b"graph body"
    assert candidate.ownership_state == "graph_owned"
    assert extension_generation.is_disposed is False

    assert await binder.dispose(runtime) == ()
    assert candidate.ownership_state == "disposed"
    # Idempotent compatibility cleanup after Graph retirement must not demand an
    # impossible second asynchronous owner-generation disposal.
    candidate.dispose()
    assert extension_generation.is_disposed is False
    extension_generation.dispose()


def test_extension_runtime_prepares_defensive_exact_route_inputs(
    tmp_path: Path,
) -> None:
    asyncio.run(_extension_runtime_prepares_defensive_exact_route_inputs(tmp_path))


async def _extension_runtime_prepares_defensive_exact_route_inputs(
    tmp_path: Path,
) -> None:
    mutated_input = _skill(tmp_path / "mutated" / "SKILL.md", content="mutation")

    async def discover(event, _context):  # type: ignore[no-untyped-def]
        event.skills.append(mutated_input)
        return ExtensionResourceContribution(
            prompt_descriptors=[
                _prompt(tmp_path / "review.md", text="defensive route body")
            ]
        )

    extension = LoadedExtension(
        name="example.review",
        source_path=tmp_path / "extension.py",
        source="extension",
        source_kind="project_local",
        source_scope="project",
        source_root=tmp_path,
        source_root_order=9,
        hooks={"resources_discover": [discover]},
    )
    base = ResourceBundle(cwd=tmp_path)
    runtime = ExtensionResourceRuntime([extension], diagnostics=[])
    discovery = await runtime.prepare_catalog_inputs_async(base, context=object())

    assert base.skills == []
    assert discovery.projection.skills == []
    assert [item.text for item in discovery.projection.prompt_descriptors] == [
        "defensive route body"
    ]
    assert len(discovery.route_contributions) == 1
    routed = discovery.route_contributions[0]
    assert routed.extension_id == "example.review"
    assert routed.source_root_order == 9
    assert routed.prompt_descriptors[0].source_root_order == 9

    frozen = freeze_extension_resource_source_generation(
        product_id="coding",
        runtime_id="extension-runtime-defensive",
        extension_generation=3,
        extension_set_fingerprint=_digest("extension-set-defensive"),
        route_contributions=discovery.route_contributions,
    )
    assert len(frozen.source_snapshot.candidate_summaries) == 1
    frozen.dispose()


def test_extension_runtime_keeps_initial_catalog_preparation_synchronous(
    tmp_path: Path,
) -> None:
    mutated_input = _skill(tmp_path / "mutated" / "SKILL.md", content="mutation")

    def discover(event, _context):  # type: ignore[no-untyped-def]
        event.skills.append(mutated_input)
        return ExtensionResourceContribution(
            prompt_descriptors=[
                _prompt(tmp_path / "review.md", text="synchronous route body")
            ]
        )

    extension = LoadedExtension(
        name="example.review",
        source_path=tmp_path / "extension.py",
        source_root_order=4,
        hooks={"resources_discover": [discover]},
    )
    base = ResourceBundle(cwd=tmp_path)
    discovery = ExtensionResourceRuntime(
        [extension],
        diagnostics=[],
    ).prepare_catalog_inputs(base, context=object())

    assert base.skills == []
    assert discovery.projection.skills == []
    assert discovery.route_contributions[0].source_root_order == 4
    assert discovery.route_contributions[0].prompt_descriptors[0].text == (
        "synchronous route body"
    )
