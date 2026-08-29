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
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources._catalog_records import ResourceIdentity
from loushang.harness.resources._skill_catalog_consumer import (
    SkillCatalogConsumer,
    SkillCatalogConsumerError,
    SkillCatalogLoadHandle,
)
from loushang.harness.runtime import RuntimeProfileResolver


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _mounted_skill_consumer(
    tmp_path: Path,
) -> tuple[
    SkillCatalogConsumer,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphRuntime,
    bytes,
]:
    workspace = tmp_path / "workspace"
    resource_root = workspace / ".loushang"
    skill_root = resource_root / "skills" / "review"
    skill_root.mkdir(parents=True)
    skill_body = (
        b"---\nname: review\ndescription: Review changes\n---\nReview carefully.\n"
    )
    (skill_root / "SKILL.md").write_bytes(skill_body)
    root_handle = mint_native_resource_root_handle(
        handle_id="workspace-resources",
        root=resource_root,
        source_class="project_local",
        root_kind="standard",
        source_root_order=0,
    )
    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )
    candidate = stage_resource_composition_candidate(profile)
    await prepare_first_party_resource_owner_generation(
        staged_candidate=candidate,
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-owner:skill-consumer",
        product_policy_revision="coding-resource-catalog-v2",
        root_handles=(root_handle,),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=workspace,
    )
    binding = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id="session:coding",
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
        runtime_id="coding-session",
        profile_fingerprint=_sha("profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, plan, (binding,))
    resource_catalog = ResourceCatalogCapabilityConsumer(
        runtime.capture(RESOURCES_CATALOG_LOAD_REQUIREMENT)
    )
    return SkillCatalogConsumer(resource_catalog), binder, runtime, skill_body


def test_typed_skill_consumer_lists_metadata_and_loads_exact_body_lazily(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        consumer, binder, runtime, skill_body = await _mounted_skill_consumer(tmp_path)

        summaries = consumer.list_effective_skills()
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.name == "review"
        assert summary.description == "Review changes"
        assert summary.identity.resource_kind == "skill"
        assert summary.expected_content_digest == hashlib.sha256(skill_body).hexdigest()
        assert summary.expected_content_length == len(skill_body)
        assert summary.to_metadata_descriptor().content is None

        handle = consumer.load_handle(summary)
        loaded = await consumer.load(handle)

        assert loaded.summary is summary
        assert loaded.body == skill_body
        assert loaded.content == skill_body.decode("utf-8")
        assert loaded.receipt.content_digest == summary.expected_content_digest
        assert (
            loaded.receipt.snapshot_fingerprint
            == consumer.catalog_snapshot_fingerprint
        )

        assert await binder.dispose(runtime) == ()
        with pytest.raises(RuntimeError):
            await consumer.load(handle)

    asyncio.run(scenario())


def test_typed_skill_consumer_rejects_foreign_and_non_skill_handles(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        consumer, binder, runtime, _skill_body = await _mounted_skill_consumer(
            tmp_path
        )
        handle = consumer.load_handle("review")
        foreign_resource_handle = replace(
            handle.resource_handle,
            catalog_generation=handle.catalog_generation + 1,
        )
        foreign = replace(
            handle,
            catalog_generation=handle.catalog_generation + 1,
            resource_handle=foreign_resource_handle,
        )

        with pytest.raises(SkillCatalogConsumerError, match="another Catalog"):
            await consumer.load(foreign)

        prompt_identity = ResourceIdentity(
            resource_kind="prompt",
            schema_id=handle.identity.schema_id,
            schema_version=handle.identity.schema_version,
            public_id=handle.identity.public_id,
        )
        prompt_resource_handle = replace(
            handle.resource_handle,
            identity=prompt_identity,
        )
        with pytest.raises(ValueError, match="must name a Skill"):
            SkillCatalogLoadHandle(
                catalog_generation=handle.catalog_generation,
                catalog_snapshot_fingerprint=handle.catalog_snapshot_fingerprint,
                candidate_fingerprint=handle.candidate_fingerprint,
                identity=prompt_identity,
                resource_handle=prompt_resource_handle,
            )

        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())
