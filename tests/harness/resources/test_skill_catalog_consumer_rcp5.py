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
    ResourceSkillCatalogCapabilityConsumer,
)
from loushang.harness.capabilities.resources_contracts import (
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
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import (
    LoadedResource,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadReceipt,
    build_activation_policy_snapshot,
    catalog_snapshot_fingerprint,
)
from loushang.harness.resources._skill_catalog_consumer import (
    EffectiveSkillCatalogProjection,
    SkillCatalogConsumer,
    SkillCatalogConsumerError,
    SkillCatalogLoadHandle,
    build_effective_skill_catalog_projection,
)
from loushang.harness.runtime import RuntimeProfileResolver


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _replace_catalog_snapshot(
    snapshot: ResourceCatalogSnapshot,
    *,
    catalog_generation: int | None = None,
    engine_binding_fingerprint: str | None = None,
    complete: bool | None = None,
) -> ResourceCatalogSnapshot:
    generation = catalog_generation or snapshot.catalog_generation
    engine_fingerprint = (
        engine_binding_fingerprint or snapshot.engine_binding_fingerprint
    )
    resolved_complete = snapshot.complete if complete is None else complete
    snapshot_fingerprint = catalog_snapshot_fingerprint(
        catalog_contract_version=snapshot.catalog_contract_version,
        catalog_generation=generation,
        engine_binding_fingerprint=engine_fingerprint,
        source_generation_fingerprints=snapshot.source_generation_fingerprints,
        merge_policy_revision=snapshot.merge_policy_revision,
        activation_policy_fingerprint=snapshot.activation_policy_fingerprint,
        candidate_summaries=snapshot.candidate_summaries,
        effective_entries=snapshot.effective_entries,
        merge_decisions=snapshot.merge_decisions,
        diagnostics=snapshot.diagnostics,
        complete=resolved_complete,
    )
    return replace(
        snapshot,
        catalog_generation=generation,
        engine_binding_fingerprint=engine_fingerprint,
        complete=resolved_complete,
        snapshot_fingerprint=snapshot_fingerprint,
    )


async def _mounted_skill_consumer(
    tmp_path: Path,
    *,
    disabled_review: bool = False,
    second_skill_with_same_name: bool = False,
) -> tuple[
    SkillCatalogConsumer,
    ResourceSkillCatalogCapabilityConsumer,
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
    if second_skill_with_same_name:
        second_root = resource_root / "skills" / "audit"
        second_root.mkdir(parents=True)
        (second_root / "SKILL.md").write_text(
            "---\nname: review\ndescription: Audit changes\n---\nAudit carefully.\n",
            encoding="utf-8",
        )
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
        activation_policy=(
            build_activation_policy_snapshot(
                policy_revision="disabled-review",
                disabled_identities=(
                    ResourceIdentity(
                        resource_kind="skill",
                        schema_id="loushang.resource.skill",
                        schema_version=1,
                        public_id="review/SKILL.md",
                    ),
                ),
            )
            if disabled_review
            else None
        ),
    )
    binding = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id="session:coding",
        staged_candidate=candidate,
        enable_skill_catalog_v3=True,
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=(RESOURCES_CAPABILITY_DEFINITION_V3.capability_id,),
            definitions=(RESOURCES_CAPABILITY_DEFINITION_V3,),
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
    resource_catalog = ResourceSkillCatalogCapabilityConsumer(
        runtime.capture(RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT)
    )
    return (
        SkillCatalogConsumer(resource_catalog),
        resource_catalog,
        binder,
        runtime,
        skill_body,
    )


def test_typed_skill_consumer_lists_metadata_and_loads_exact_body_lazily(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        consumer, _catalog, binder, runtime, skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )

        summaries = consumer.list_effective_skills()
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.name == "review"
        assert summary.description == "Review changes"
        assert summary.identity.resource_kind == "skill"
        assert summary.expected_content_digest == hashlib.sha256(skill_body).hexdigest()
        assert summary.expected_content_length == len(skill_body)
        assert not hasattr(summary, "content")
        assert not hasattr(summary, "body")
        assert not hasattr(summary, "metadata")

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
        with pytest.raises(RuntimeError, match="Capability Mount graph is disposed"):
            await consumer.load(handle)

    asyncio.run(scenario())


def test_skill_projection_requires_opt_in_v3_contract(tmp_path: Path) -> None:
    async def scenario() -> None:
        _consumer, catalog, binder, runtime, _skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )

        with pytest.raises(RuntimeError, match="contract is incompatible"):
            runtime.capture(RESOURCES_CATALOG_LOAD_REQUIREMENT)
        facet = catalog.facets.require("resource.catalog")
        assert not hasattr(facet, "projection")
        assert not hasattr(facet, "skill_status_projection")
        assert catalog.skill_projection.skills
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_skill_projection_opt_in_requires_prepared_owner_generation() -> None:
    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )

    with pytest.raises(
        ValueError,
        match="requires a prepared owner generation",
    ):
        resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:coding",
            enable_skill_catalog_v3=True,
        )


@pytest.mark.parametrize(
    "snapshot_change",
    ("generation", "fingerprint"),
)
def test_skill_projection_builder_rejects_another_catalog_snapshot(
    tmp_path: Path,
    snapshot_change: str,
) -> None:
    async def scenario() -> None:
        workspace = tmp_path / snapshot_change / "workspace"
        resource_root = workspace / ".loushang"
        skill_root = resource_root / "skills" / "review"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "---\nname: review\ndescription: Review changes\n---\nReview carefully.\n",
            encoding="utf-8",
        )
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
            runtime_id="resource-owner:projection-mismatch",
            product_policy_revision="coding-resource-catalog-v2",
            root_handles=(root_handle,),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=workspace,
        )
        bootstrap_handles = candidate._root_owned_handles()
        snapshot = bootstrap_handles.resource_catalog_snapshot
        projection = bootstrap_handles.resource_catalog_projection
        assert isinstance(snapshot, ResourceCatalogSnapshot)
        assert isinstance(projection, ResourceCatalogProjection)
        if snapshot_change == "generation":
            foreign_snapshot = _replace_catalog_snapshot(
                snapshot,
                catalog_generation=snapshot.catalog_generation + 1,
            )
        else:
            foreign_snapshot = _replace_catalog_snapshot(
                snapshot,
                engine_binding_fingerprint=_sha("foreign-engine-binding"),
            )

        with pytest.raises(
            SkillCatalogConsumerError,
            match="belongs to another Catalog generation",
        ):
            build_effective_skill_catalog_projection(
                snapshot=foreign_snapshot,
                projection=projection,
            )
        await candidate.dispose_root_owned()

    asyncio.run(scenario())


def test_typed_skill_consumer_rejects_foreign_and_non_skill_handles(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        consumer, _catalog, binder, runtime, _skill_body = await _mounted_skill_consumer(
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

        forged_resource_handle = replace(
            handle.resource_handle,
            media_type="application/octet-stream",
        )
        forged = replace(handle, resource_handle=forged_resource_handle)
        with pytest.raises(
            SkillCatalogConsumerError,
            match="does not match the selected Skill",
        ):
            await consumer.load(forged)

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


def test_typed_skill_consumer_rejects_foreign_summary_values(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        consumer, _catalog, binder, runtime, _skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )
        summary = consumer.list_effective_skills()[0]

        for foreign in (
            replace(summary, catalog_generation=summary.catalog_generation + 1),
            replace(summary, catalog_snapshot_fingerprint=_sha("foreign-snapshot")),
            replace(summary, candidate_fingerprint=_sha("foreign-candidate")),
            replace(summary, name="forged-name"),
        ):
            with pytest.raises(SkillCatalogConsumerError):
                consumer.load_handle(foreign)

        # Summaries are generation-scoped values, not ambient object-identity tokens.
        equal_value = replace(summary)
        assert consumer.load_handle(equal_value).identity == summary.identity
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_typed_skill_metadata_operations_do_not_mint_or_load_body(
    tmp_path: Path,
) -> None:
    class RecordingCatalog:
        def __init__(self, delegate: ResourceSkillCatalogCapabilityConsumer) -> None:
            self.delegate = delegate
            self.handle_calls = 0
            self.load_calls = 0

        @property
        def snapshot(self):  # type: ignore[no-untyped-def]
            return self.delegate.snapshot

        @property
        def skill_projection(self):  # type: ignore[no-untyped-def]
            return self.delegate.skill_projection

        def load_handle(self, identity):  # type: ignore[no-untyped-def]
            self.handle_calls += 1
            return self.delegate.load_handle(identity)

        async def load(self, handle):  # type: ignore[no-untyped-def]
            self.load_calls += 1
            return await self.delegate.load(handle)

    async def scenario() -> None:
        _consumer, catalog, binder, runtime, skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )
        recording = RecordingCatalog(catalog)
        consumer = SkillCatalogConsumer(recording)

        summary = consumer.list_effective_skills()[0]
        assert consumer.get_effective_skill("review") == summary
        assert recording.handle_calls == 0
        assert recording.load_calls == 0
        assert "Review carefully" not in repr(summary)
        assert skill_body.decode("utf-8") not in repr(summary)

        handle = consumer.load_handle(summary)
        assert recording.handle_calls == 1
        assert recording.load_calls == 0
        loaded = await consumer.load(handle)
        # Load re-mints once to prove the nested handle is exactly owner-issued.
        assert recording.handle_calls == 2
        assert recording.load_calls == 1
        assert loaded.body == skill_body
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_typed_skill_consumer_rejects_projection_not_bound_to_snapshot(
    tmp_path: Path,
) -> None:
    class ForgedProjectionCatalog:
        def __init__(
            self,
            delegate: ResourceSkillCatalogCapabilityConsumer,
            projection: EffectiveSkillCatalogProjection,
        ) -> None:
            self.delegate = delegate
            self.projection = projection

        @property
        def snapshot(self):  # type: ignore[no-untyped-def]
            return self.delegate.snapshot

        @property
        def skill_projection(self) -> EffectiveSkillCatalogProjection:
            return self.projection

        def load_handle(self, identity):  # type: ignore[no-untyped-def]
            return self.delegate.load_handle(identity)

        async def load(self, handle):  # type: ignore[no-untyped-def]
            return await self.delegate.load(handle)

    async def scenario() -> None:
        _consumer, catalog, binder, runtime, _skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )
        projection = catalog.skill_projection
        summary = projection.skills[0]
        foreign_projection = replace(
            projection,
            skills=(
                replace(
                    summary,
                    candidate_fingerprint=_sha("foreign-candidate"),
                ),
            ),
        )
        with pytest.raises(
            SkillCatalogConsumerError,
            match="foreign Catalog candidate",
        ):
            SkillCatalogConsumer(
                ForgedProjectionCatalog(catalog, foreign_projection)
            )

        forged_facts = replace(
            projection,
            skills=(replace(summary, canonical_name="forged-review"),),
        )
        with pytest.raises(
            SkillCatalogConsumerError,
            match="facts do not match the captured Catalog",
        ):
            SkillCatalogConsumer(ForgedProjectionCatalog(catalog, forged_facts))
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_typed_skill_consumer_rejects_self_consistent_incomplete_catalog(
    tmp_path: Path,
) -> None:
    class IncompleteCatalog:
        def __init__(
            self,
            delegate: ResourceSkillCatalogCapabilityConsumer,
        ) -> None:
            self.delegate = delegate
            self.snapshot = _replace_catalog_snapshot(
                delegate.snapshot,
                complete=False,
            )
            self.skill_projection = replace(
                delegate.skill_projection,
                catalog_snapshot_fingerprint=self.snapshot.snapshot_fingerprint,
                skills=tuple(
                    replace(
                        summary,
                        catalog_snapshot_fingerprint=(
                            self.snapshot.snapshot_fingerprint
                        ),
                    )
                    for summary in delegate.skill_projection.skills
                ),
            )

        def load_handle(self, identity):  # type: ignore[no-untyped-def]
            return self.delegate.load_handle(identity)

        async def load(self, handle):  # type: ignore[no-untyped-def]
            return await self.delegate.load(handle)

    async def scenario() -> None:
        _consumer, catalog, binder, runtime, _skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )

        with pytest.raises(SkillCatalogConsumerError, match="Catalog is incomplete"):
            SkillCatalogConsumer(IncompleteCatalog(catalog))

        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_typed_skill_consumer_rejects_forged_owner_locator(
    tmp_path: Path,
) -> None:
    class ForgedHandleCatalog:
        def __init__(self, delegate: ResourceSkillCatalogCapabilityConsumer) -> None:
            self.delegate = delegate

        @property
        def snapshot(self):  # type: ignore[no-untyped-def]
            return self.delegate.snapshot

        @property
        def skill_projection(self):  # type: ignore[no-untyped-def]
            return self.delegate.skill_projection

        def load_handle(self, identity):  # type: ignore[no-untyped-def]
            return replace(
                self.delegate.load_handle(identity),
                opaque_locator="forged/SKILL.md",
            )

        async def load(self, handle):  # type: ignore[no-untyped-def]
            return await self.delegate.load(handle)

    async def scenario() -> None:
        _consumer, catalog, binder, runtime, _skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )
        forged = SkillCatalogConsumer(ForgedHandleCatalog(catalog))

        with pytest.raises(
            SkillCatalogConsumerError,
            match="does not match the selected Skill",
        ):
            forged.load_handle("review")
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_typed_skill_consumer_rejects_self_consistent_foreign_receipt(
    tmp_path: Path,
) -> None:
    class ForgedReceiptCatalog:
        def __init__(self, delegate: ResourceSkillCatalogCapabilityConsumer) -> None:
            self.delegate = delegate

        @property
        def snapshot(self):  # type: ignore[no-untyped-def]
            return self.delegate.snapshot

        @property
        def skill_projection(self):  # type: ignore[no-untyped-def]
            return self.delegate.skill_projection

        def load_handle(self, identity):  # type: ignore[no-untyped-def]
            return self.delegate.load_handle(identity)

        async def load(self, handle):  # type: ignore[no-untyped-def]
            body = b"self-consistent but foreign body"
            return LoadedResource(
                receipt=ResourceLoadReceipt(
                    catalog_generation=handle.catalog_generation,
                    snapshot_fingerprint=handle.snapshot_fingerprint,
                    candidate_fingerprint=handle.candidate_fingerprint,
                    source_generation_ref=handle.source_generation_ref,
                    schema_id=handle.schema_id,
                    schema_version=handle.schema_version,
                    media_type=handle.media_type,
                    content_digest=hashlib.sha256(body).hexdigest(),
                    content_length=len(body),
                ),
                body=body,
            )

    async def scenario() -> None:
        _consumer, catalog, binder, runtime, _skill_body = (
            await _mounted_skill_consumer(tmp_path)
        )
        consumer = SkillCatalogConsumer(ForgedReceiptCatalog(catalog))
        handle = consumer.load_handle("review")

        with pytest.raises(
            SkillCatalogConsumerError,
            match="receipt does not match the owner-minted Skill handle",
        ):
            await consumer.load(handle)
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_effective_skill_boundary_excludes_disabled_and_rejects_alias_ambiguity(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disabled, _catalog, binder, runtime, _body = (
            await _mounted_skill_consumer(tmp_path / "disabled", disabled_review=True)
        )
        assert disabled.list_effective_skills() == ()
        assert await binder.dispose(runtime) == ()

        ambiguous, _catalog, binder, runtime, _body = (
            await _mounted_skill_consumer(
                tmp_path / "ambiguous",
                second_skill_with_same_name=True,
            )
        )
        assert len(ambiguous.list_effective_skills()) == 2
        with pytest.raises(SkillCatalogConsumerError, match="lookup is ambiguous"):
            ambiguous.get_effective_skill("review")
        exact = ambiguous.get_effective_skill("review/SKILL.md")
        assert exact is not None
        assert exact.id == "review/SKILL.md"
        assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())
