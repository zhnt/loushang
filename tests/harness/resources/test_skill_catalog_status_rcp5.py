from __future__ import annotations

import asyncio
import hashlib
from dataclasses import fields
from pathlib import Path

import pytest

from loushang.harness.capabilities import (
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resources._catalog_engine import (
    compose_resource_catalog,
    default_resource_merge_policy,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources._catalog_projection import (
    ResourceProjectionDescriptorBinding,
    build_resource_projection_binding,
)
from loushang.harness.resources._catalog_records import (
    NativeHostOrigin,
    ResourceCandidateSummary,
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceSourceGenerationRef,
    build_activation_policy_snapshot,
    build_candidate_summary,
    build_source_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._skill_catalog_status import (
    SkillCatalogStatusProjection,
    SkillCatalogStatusProjectionError,
    SkillCatalogStatusSummary,
    build_skill_catalog_status_projection,
)
from loushang.harness.resources.types import (
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
)
from loushang.harness.runtime import RuntimeProfileResolver


def _digest(value: str) -> str:
    return fingerprint_catalog_value("test.skill-status", value)


def _source_ref(source_id: str) -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id=source_id,
        product_id="coding",
        generation="generation-1",
        source_policy_fingerprint=_digest(f"policy:{source_id}"),
        producer=ResourceComponentProducer(
            component_contribution_id=f"resource.source.{source_id}",
            component_candidate_fingerprint=_digest(f"candidate:{source_id}"),
            component_admission_fingerprint=_digest(f"admission:{source_id}"),
            binding_fingerprint=_digest(f"binding:{source_id}"),
            plugin_instance_revision_ref="first-party",
            package_content_digest=_digest(f"package:{source_id}"),
        ),
    )


def _candidate_and_binding(
    *,
    source_id: str,
    source_kind: ResourceSourceKind,
    enabled: bool = True,
    source_root_order: int = 0,
) -> tuple[ResourceCandidateSummary, ResourceProjectionDescriptorBinding]:
    source_scope: ResourceSourceScope = {
        "project_local": "project",
        "temporary": "temporary",
        "user_global": "user",
    }[source_kind]  # type: ignore[assignment]
    workspace_scope = {
        "project_local": "workspace",
        "temporary": "temporary",
        "user_global": "user",
    }[source_kind]
    source_ref = _source_ref(source_id)
    body = f"body:{source_id}:review".encode()
    identity = ResourceIdentity(
        resource_kind="skill",
        schema_id="loushang.resource.skill",
        schema_version=1,
        public_id="review",
    )
    candidate = build_candidate_summary(
        identity=identity,
        canonical_name="review",
        description="Review changes",
        media_type="text/markdown",
        invocation_policy=ResourceInvocationPolicy(
            enabled=enabled,
            model_invocable=True,
            reason="test",
        ),
        source_generation_ref=source_ref,
        source_class=source_kind,
        scope_id=source_scope,
        source_root_order=source_root_order,
        content_origin=NativeHostOrigin(
            host_root_handle_id=f"root:{source_id}",
            root_policy_fingerprint=_digest(f"root:{source_id}"),
            workspace_or_user_scope=workspace_scope,  # type: ignore[arg-type]
        ),
        opaque_locator=f"{source_id}/skills/review/SKILL.md",
        discovery_fingerprint=_digest(f"discovery:{source_id}"),
        expected_content_digest=hashlib.sha256(body).hexdigest(),
        expected_content_length=len(body),
    )
    descriptor = SkillDescriptor(
        name="review",
        source_path=Path(f"/{source_id}/skills/review/SKILL.md"),
        content=body.decode(),
        description="Review changes",
        enabled=enabled,
        canonical_name="review",
        source_kind=source_kind,
        source_scope=source_scope,
        source=f"test:{source_id}",
        source_root=Path(f"/{source_id}"),
        source_root_order=source_root_order,
    )
    return candidate, build_resource_projection_binding(
        candidate=candidate,
        descriptor=descriptor,
        body=body,
    )


def _project(
    *candidates_and_bindings: tuple[
        ResourceCandidateSummary,
        ResourceProjectionDescriptorBinding,
    ],
    disabled: bool = False,
) -> SkillCatalogStatusProjection:
    candidates = tuple(item[0] for item in candidates_and_bindings)
    bindings = tuple(item[1] for item in candidates_and_bindings)
    snapshots = tuple(
        build_source_snapshot(
            source_generation_ref=candidate.source_generation_ref,
            discovery_request_fingerprint=_digest(
                f"request:{candidate.source_generation_ref.source_id}"
            ),
            candidate_summaries=(candidate,),
        )
        for candidate in candidates
    )
    activation_policy = build_activation_policy_snapshot(
        policy_revision="test-skill-status",
        disabled_identities=(candidates[0].identity,) if disabled else (),
    )
    catalog = compose_resource_catalog(
        snapshots,
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=activation_policy,
    )
    return build_skill_catalog_status_projection(
        snapshot=catalog,
        descriptor_bindings=bindings,
    )


def test_status_projection_preserves_effective_and_shadowed_catalog_order() -> None:
    temporary = _candidate_and_binding(
        source_id="temporary",
        source_kind="temporary",
    )
    project = _candidate_and_binding(
        source_id="project",
        source_kind="project_local",
    )

    projection = _project(project, temporary)

    assert [summary.source_kind for summary in projection.skills] == [
        "temporary",
        "project_local",
    ]
    assert [summary.status for summary in projection.skills] == [
        "effective",
        "shadowed",
    ]
    assert [summary.primary for summary in projection.skills] == [True, False]
    assert [summary.status_reason for summary in projection.skills] == [
        "source_precedence",
        "source_precedence",
    ]


def test_status_projection_distinguishes_activation_and_declaration_inactive() -> None:
    enabled = _candidate_and_binding(
        source_id="activation-disabled",
        source_kind="project_local",
    )
    activation_disabled = _project(enabled, disabled=True).skills[0]
    assert activation_disabled.status == "inactive_activation"
    assert activation_disabled.status_reason == "activation_disabled"
    assert activation_disabled.declared_enabled is True
    assert activation_disabled.effective is False

    declaration_disabled = _project(
        _candidate_and_binding(
            source_id="declaration-disabled",
            source_kind="project_local",
            enabled=False,
        )
    ).skills[0]
    assert declaration_disabled.status == "inactive_declaration"
    assert declaration_disabled.status_reason == "no_enabled_candidates"
    assert declaration_disabled.declared_enabled is False
    assert declaration_disabled.effective is False


def test_status_projection_reports_every_same_precedence_conflict_candidate() -> None:
    first = _candidate_and_binding(
        source_id="project-a",
        source_kind="project_local",
        source_root_order=0,
    )
    second = _candidate_and_binding(
        source_id="project-b",
        source_kind="project_local",
        source_root_order=1,
    )

    projection = _project(first, second)

    assert len(projection.skills) == 2
    assert {summary.status for summary in projection.skills} == {
        "rejected_conflict"
    }
    assert {summary.status_reason for summary in projection.skills} == {
        "same_precedence_conflict"
    }
    assert not any(summary.effective or summary.primary for summary in projection.skills)


def test_declaration_inactive_candidate_is_not_relabelled_by_peer_conflict() -> None:
    first = _candidate_and_binding(
        source_id="project-a",
        source_kind="project_local",
    )
    second = _candidate_and_binding(
        source_id="project-b",
        source_kind="project_local",
        source_root_order=1,
    )
    disabled = _candidate_and_binding(
        source_id="project-disabled",
        source_kind="project_local",
        enabled=False,
        source_root_order=2,
    )

    projection = _project(first, second, disabled)

    assert [summary.status for summary in projection.skills].count(
        "rejected_conflict"
    ) == 2
    disabled_status = next(
        summary
        for summary in projection.skills
        if summary.source == "test:project-disabled"
    )
    assert disabled_status.status == "inactive_declaration"


def test_status_projection_is_body_free_and_requires_complete_candidate_coverage() -> None:
    item = _candidate_and_binding(
        source_id="project",
        source_kind="project_local",
    )
    projection = _project(item)
    summary = projection.skills[0]

    field_names = {field.name for field in fields(SkillCatalogStatusSummary)}
    assert field_names.isdisjoint({"body", "content", "metadata", "opaque_locator"})
    assert "body:project:review" not in repr(summary)
    assert summary.expected_content_digest == item[0].expected_content_digest

    catalog = compose_resource_catalog(
        (
            build_source_snapshot(
                source_generation_ref=item[0].source_generation_ref,
                discovery_request_fingerprint=_digest("request:missing"),
                candidate_summaries=(item[0],),
            ),
        ),
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine:missing"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=build_activation_policy_snapshot(
            policy_revision="test-missing-binding"
        ),
    )
    with pytest.raises(
        SkillCatalogStatusProjectionError,
        match="does not cover every Catalog candidate",
    ):
        build_skill_catalog_status_projection(
            snapshot=catalog,
            descriptor_bindings=(),
        )
    with pytest.raises(
        SkillCatalogStatusProjectionError,
        match="duplicate descriptor binding",
    ):
        build_skill_catalog_status_projection(
            snapshot=catalog,
            descriptor_bindings=(item[1], item[1]),
        )
    foreign = _candidate_and_binding(
        source_id="foreign",
        source_kind="temporary",
    )
    with pytest.raises(
        SkillCatalogStatusProjectionError,
        match="foreign descriptor binding",
    ):
        build_skill_catalog_status_projection(
            snapshot=catalog,
            descriptor_bindings=(foreign[1],),
        )


def test_prepared_owner_generation_retains_status_until_disposal(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
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
            runtime_id="resource-owner:skill-status",
            product_policy_revision="coding-resource-catalog-v2",
            root_handles=(root_handle,),
            issued_at=10,
            expires_at=100,
            now=20,
        )

        assert candidate.resource_catalog_projection is None
        projection = candidate.resource_skill_status_projection
        assert isinstance(projection, SkillCatalogStatusProjection)
        assert [summary.status for summary in projection.skills] == ["effective"]
        assert not hasattr(projection.skills[0], "body")

        await candidate.dispose_root_owned()
        with pytest.raises(RuntimeError, match="generation is not retained"):
            _ = candidate.resource_skill_status_projection

    asyncio.run(scenario())
