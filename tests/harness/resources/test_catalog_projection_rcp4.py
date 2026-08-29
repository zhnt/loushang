from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from loushang.harness.resources._catalog_engine import (
    compose_resource_catalog,
    default_resource_merge_policy,
)
from loushang.harness.resources._catalog_projection import (
    ResourceCatalogProjectionError,
    build_resource_projection_binding,
    project_resource_catalog,
)
from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    EmbeddedOemOrigin,
    NativeHostOrigin,
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceSourceGenerationRef,
    build_activation_policy_snapshot,
    build_candidate_summary,
    build_source_snapshot,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_ref(source_id: str, source_class: str) -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id=source_id,
        product_id="coding",
        generation="1",
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


def _prompt_candidate(
    descriptor: PromptFragmentDescriptor,
    *,
    source_ref: ResourceSourceGenerationRef,
):  # type: ignore[no-untyped-def]
    body = descriptor.text.encode("utf-8")
    identity = ResourceIdentity(
        resource_kind=(
            "context"
            if descriptor.prompt_kind in {"agents_md", "claude_md"}
            else "prompt"
        ),
        schema_id=(
            "loushang.resource.context"
            if descriptor.prompt_kind in {"agents_md", "claude_md"}
            else "loushang.resource.prompt"
        ),
        schema_version=1,
        public_id=descriptor.id or descriptor.name,
    )
    return build_candidate_summary(
        identity=identity,
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=descriptor.description,
        media_type="text/markdown",
        invocation_policy=ResourceInvocationPolicy(
            enabled=descriptor.enabled,
            model_invocable=True,
            reason="projection-test",
        ),
        source_generation_ref=source_ref,
        source_class=descriptor.source_kind,
        scope_id=descriptor.source_scope,
        source_root_order=descriptor.source_root_order,
        content_origin=(
            EmbeddedOemOrigin(
                embedded_collection_id=f"collection:{source_ref.source_id}",
                embedded_revision="test-v1",
                collection_content_digest=_digest(
                    f"collection:{source_ref.source_id}"
                ),
            )
            if descriptor.source_kind == "built_in"
            else NativeHostOrigin(
                host_root_handle_id=f"root:{source_ref.source_id}",
                root_policy_fingerprint=_digest(f"root:{source_ref.source_id}"),
                workspace_or_user_scope=(
                    "user"
                    if descriptor.source_kind == "user_global"
                    else "workspace"
                ),
            )
        ),
        opaque_locator=f"{source_ref.source_id}/{descriptor.source_path.name}",
        discovery_fingerprint=_digest(
            f"discovery:{source_ref.source_id}:{descriptor.name}"
        ),
        expected_content_digest=hashlib.sha256(body).hexdigest(),
        expected_content_length=len(body),
    )


def _catalog(*pairs):  # type: ignore[no-untyped-def]
    snapshots = []
    for source_ref, candidate in pairs:
        snapshots.append(
            build_source_snapshot(
                source_generation_ref=source_ref,
                discovery_request_fingerprint=_digest(
                    f"request:{source_ref.source_id}"
                ),
                candidate_summaries=(candidate,),
            )
        )
    return compose_resource_catalog(
        snapshots,
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=build_activation_policy_snapshot(
            policy_revision="projection-test"
        ),
    )


def _extension_candidate(
    descriptor: ExtensionDescriptor,
    *,
    source_ref: ResourceSourceGenerationRef,
):  # type: ignore[no-untyped-def]
    return build_candidate_summary(
        identity=ResourceIdentity(
            resource_kind="extension",
            schema_id="loushang.resource.extension",
            schema_version=1,
            public_id=descriptor.id or descriptor.name,
        ),
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=None,
        media_type=NO_BODY_MEDIA_TYPE,
        invocation_policy=ResourceInvocationPolicy(
            enabled=descriptor.enabled,
            model_invocable=False,
            reason="projection-test",
        ),
        source_generation_ref=source_ref,
        source_class=descriptor.source_kind,
        scope_id=descriptor.source_scope,
        source_root_order=descriptor.source_root_order,
        content_origin=NativeHostOrigin(
            host_root_handle_id=f"root:{source_ref.source_id}",
            root_policy_fingerprint=_digest(f"root:{source_ref.source_id}"),
            workspace_or_user_scope="workspace",
        ),
        opaque_locator=f"{source_ref.source_id}/{descriptor.name}",
        discovery_fingerprint=_digest(
            f"discovery:{source_ref.source_id}:{descriptor.name}"
        ),
        expected_content_digest=None,
        expected_content_length=None,
    )


def _skill_candidate(
    descriptor: SkillDescriptor,
    *,
    source_ref: ResourceSourceGenerationRef,
):  # type: ignore[no-untyped-def]
    body = (descriptor.content or "").encode("utf-8")
    return build_candidate_summary(
        identity=ResourceIdentity(
            resource_kind="skill",
            schema_id="loushang.resource.skill",
            schema_version=1,
            public_id=descriptor.id or descriptor.name,
        ),
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=descriptor.description,
        media_type="text/markdown",
        invocation_policy=ResourceInvocationPolicy(
            enabled=descriptor.enabled,
            model_invocable=not descriptor.disable_model_invocation,
            reason="projection-test",
        ),
        source_generation_ref=source_ref,
        source_class=descriptor.source_kind,
        scope_id=descriptor.source_scope,
        source_root_order=descriptor.source_root_order,
        content_origin=NativeHostOrigin(
            host_root_handle_id=f"root:{source_ref.source_id}",
            root_policy_fingerprint=_digest(f"root:{source_ref.source_id}"),
            workspace_or_user_scope="workspace",
        ),
        opaque_locator=f"{source_ref.source_id}/{descriptor.name}",
        discovery_fingerprint=_digest(
            f"discovery:{source_ref.source_id}:{descriptor.name}"
        ),
        expected_content_digest=hashlib.sha256(body).hexdigest(),
        expected_content_length=len(body),
    )


def test_projection_never_retains_or_reprojects_eager_skill_body(
    tmp_path: Path,
) -> None:
    descriptor = SkillDescriptor(
        name="review",
        source_path=tmp_path / "skills" / "review" / "SKILL.md",
        source_root=tmp_path,
        content="Exact source-owned body.",
        description="Review changes.",
        metadata={
            "frontmatter": {"name": "review"},
            "body": "Exact source-owned body.",
        },
    )
    source_ref = _source_ref("project-skill", "project_local")
    candidate = _skill_candidate(descriptor, source_ref=source_ref)
    catalog = _catalog((source_ref, candidate))

    projection = project_resource_catalog(
        catalog_snapshot=catalog,
        cwd=tmp_path,
        descriptor_bindings=(
            build_resource_projection_binding(
                candidate=candidate,
                descriptor=descriptor,
                body=b"Exact source-owned body.",
            ),
        ),
    )

    projected = projection.selected_bindings[0].descriptor
    assert isinstance(projected, SkillDescriptor)
    assert projected.content is None
    assert projected.metadata == {"frontmatter": {"name": "review"}}
    bundle = projection.to_compatibility_bundle()
    assert [skill.name for skill in bundle.skills] == ["review"]
    assert bundle.skills[0].content is None
    assert "body" not in bundle.skills[0].metadata


def test_projection_is_catalog_selected_bound_and_defensively_copied(
    tmp_path: Path,
) -> None:
    built_in = PromptFragmentDescriptor(
        name="review",
        id="review",
        text="built-in",
        source_path=tmp_path / "builtin" / "review.md",
        source_root=tmp_path / "builtin",
        source_kind="built_in",
        source_scope="builtin",
        metadata={"nested": ["stable", tmp_path / "metadata-path"]},
    )
    project = PromptFragmentDescriptor(
        name="review",
        id="review",
        text="project",
        source_path=tmp_path / "project" / "review.md",
        source_root=tmp_path / "project",
        source_kind="project_local",
        source_scope="project",
        metadata={"nested": ["stable"]},
    )
    built_in_ref = _source_ref("builtin", "built_in")
    project_ref = _source_ref("project", "project_local")
    built_in_candidate = _prompt_candidate(built_in, source_ref=built_in_ref)
    project_candidate = _prompt_candidate(project, source_ref=project_ref)
    catalog = _catalog(
        (built_in_ref, built_in_candidate),
        (project_ref, project_candidate),
    )

    projection = project_resource_catalog(
        catalog_snapshot=catalog,
        cwd=tmp_path,
        descriptor_bindings=(
            build_resource_projection_binding(
                candidate=built_in_candidate,
                descriptor=built_in,
                body=built_in.text.encode("utf-8"),
            ),
            build_resource_projection_binding(
                candidate=project_candidate,
                descriptor=project,
                body=project.text.encode("utf-8"),
            ),
        ),
    )

    assert projection.catalog_snapshot_fingerprint == catalog.snapshot_fingerprint
    assert [
        item.candidate_fingerprint for item in projection.selected_bindings
    ] == [project_candidate.candidate_fingerprint]
    first = projection.to_compatibility_bundle()
    assert [item.text for item in first.prompt_descriptors] == ["project"]
    first.prompt_descriptors.clear()
    assert [
        item.text
        for item in projection.to_compatibility_bundle().prompt_descriptors
    ] == ["project"]
    selected_descriptor = projection.selected_bindings[0].descriptor
    with pytest.raises(TypeError):
        selected_descriptor.metadata["mutated"] = True  # type: ignore[index,union-attr]


def test_projection_rejects_missing_effective_descriptor_binding(
    tmp_path: Path,
) -> None:
    descriptor = PromptFragmentDescriptor(
        name="review",
        text="project",
        source_path=tmp_path / "review.md",
        source_root=tmp_path,
    )
    source_ref = _source_ref("project", "project_local")
    candidate = _prompt_candidate(descriptor, source_ref=source_ref)
    catalog = _catalog((source_ref, candidate))

    with pytest.raises(ResourceCatalogProjectionError) as caught:
        project_resource_catalog(
            catalog_snapshot=catalog,
            cwd=tmp_path,
            descriptor_bindings=(),
        )

    assert caught.value.code == "resource_catalog_projection_invalid"
    assert caught.value.reason == "missing_effective_descriptor_binding"


def test_projection_preserves_catalog_order_for_additive_extensions(
    tmp_path: Path,
) -> None:
    descriptors = (
        ExtensionDescriptor(
            name="shared",
            source_path=tmp_path / "outer" / "extension.py",
            source_root=tmp_path / "outer",
            source_root_order=1,
        ),
        ExtensionDescriptor(
            name="shared",
            source_path=tmp_path / "inner" / "extension.py",
            source_root=tmp_path / "inner",
            source_root_order=0,
        ),
    )
    refs = (
        _source_ref("extension-outer", "project_local"),
        _source_ref("extension-inner", "project_local"),
    )
    candidates = tuple(
        _extension_candidate(descriptor, source_ref=source_ref)
        for descriptor, source_ref in zip(descriptors, refs, strict=True)
    )
    catalog = _catalog(*zip(refs, candidates, strict=True))
    effective = next(
        entry
        for entry in catalog.effective_entries
        if entry.identity.resource_kind == "extension"
    )

    projection = project_resource_catalog(
        catalog_snapshot=catalog,
        cwd=tmp_path,
        descriptor_bindings=tuple(
            build_resource_projection_binding(
                candidate=candidate,
                descriptor=descriptor,
                body=None,
            )
            for candidate, descriptor in zip(candidates, descriptors, strict=True)
        ),
    )

    assert tuple(
        binding.candidate_fingerprint for binding in projection.selected_bindings
    ) == effective.candidate_fingerprints


def test_projection_orders_context_from_user_then_outer_to_inner_project(
    tmp_path: Path,
) -> None:
    descriptors = (
        PromptFragmentDescriptor(
            name="AGENTS.md",
            id="project.inner",
            text="inner",
            prompt_kind="agents_md",
            source_path=tmp_path / "project" / "inner" / "AGENTS.md",
            source_root=tmp_path / "project" / "inner",
            source_root_order=1,
        ),
        PromptFragmentDescriptor(
            name="AGENTS.md",
            id="user.agents",
            text="user",
            prompt_kind="agents_md",
            source_path=tmp_path / "user" / "AGENTS.md",
            source_root=tmp_path / "user",
            source_kind="user_global",
            source_scope="user",
        ),
        PromptFragmentDescriptor(
            name="AGENTS.md",
            id="project.outer",
            text="outer",
            prompt_kind="agents_md",
            source_path=tmp_path / "project" / "AGENTS.md",
            source_root=tmp_path / "project",
        ),
    )
    refs = tuple(
        _source_ref(f"context-{index}", descriptor.source_kind)
        for index, descriptor in enumerate(descriptors)
    )
    candidates = tuple(
        _prompt_candidate(descriptor, source_ref=source_ref)
        for descriptor, source_ref in zip(descriptors, refs, strict=True)
    )
    catalog = _catalog(*zip(refs, candidates, strict=True))

    projection = project_resource_catalog(
        catalog_snapshot=catalog,
        cwd=tmp_path,
        descriptor_bindings=tuple(
            build_resource_projection_binding(
                candidate=candidate,
                descriptor=descriptor,
                body=descriptor.text.encode("utf-8"),
            )
            for candidate, descriptor in zip(candidates, descriptors, strict=True)
        ),
    )

    assert projection.to_compatibility_bundle().prompt_fragments == [
        "user",
        "outer",
        "inner",
    ]
    assert projection.to_compatibility_bundle().agents_md == "inner"
