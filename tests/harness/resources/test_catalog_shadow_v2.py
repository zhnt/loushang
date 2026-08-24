from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.resources._catalog_engine import (
    compose_resource_catalog,
    default_resource_merge_policy,
)
from loushang.harness.resources._catalog_records import (
    EmbeddedOemOrigin,
    ExtensionOutputOrigin,
    ExtensionOwnerProducer,
    NativeHostOrigin,
    ResourceComponentProducer,
    ResourceSourceGenerationRef,
    VerifiedPluginResourceOrigin,
    build_activation_policy_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._catalog_shadow import (
    LegacyCandidateProvenance,
    LegacyShadowAdaptationError,
    adapt_legacy_resource_snapshot,
    compare_legacy_resource_snapshot,
    project_shadow_compatibility_bundle,
)
from loushang.harness.resources._loader_resolution import (
    _resolve_candidates,
    _resolve_extension_candidates,
    _resolve_strict_named_candidates,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSnapshot,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
    ThemeDescriptor,
)


def _digest(value: str) -> str:
    return fingerprint_catalog_value("shadow-test", value)


def _source_ref() -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id="legacy-shadow",
        product_id="coding",
        generation="legacy-1",
        source_policy_fingerprint=_digest("source-policy"),
        producer=ResourceComponentProducer(
            component_contribution_id="resource.source.legacy-shadow",
            component_candidate_fingerprint=_digest("component-candidate"),
            component_admission_fingerprint=_digest("component-admission"),
            binding_fingerprint=_digest("binding"),
            plugin_instance_revision_ref="first-party",
            package_content_digest=_digest("package"),
        ),
    )


def test_legacy_snapshot_adapter_is_explicitly_provenance_supplied_and_pure(
    tmp_path: Path,
) -> None:
    skill = SkillDescriptor(
        name="review",
        description="Review changes",
        content="---\nname: review\n---\nReview changes.",
        source_path=tmp_path / "skills" / "review" / "SKILL.md",
        source_root=tmp_path / "skills",
    )
    theme = ThemeDescriptor(
        name="clean",
        content='{"background": "black"}',
        source_path=tmp_path / "themes" / "clean.json",
        source_root=tmp_path / "themes",
    )
    extension = ExtensionDescriptor(
        name="guard",
        source_path=tmp_path / "extensions" / "guard.py",
        source_root=tmp_path / "extensions",
    )
    legacy = ResourceSnapshot(
        cwd=tmp_path,
        active_skill_descriptors=(skill,),
        candidate_skill_descriptors=(skill,),
        active_theme_descriptors=(theme,),
        candidate_theme_descriptors=(theme,),
        active_extension_descriptors=(extension,),
        candidate_extension_descriptors=(extension,),
    )
    source_ref = _source_ref()

    def provenance(descriptor: object) -> LegacyCandidateProvenance:
        source_path = descriptor.source_path  # type: ignore[attr-defined]
        source_root = descriptor.source_root  # type: ignore[attr-defined]
        return LegacyCandidateProvenance(
            source_generation_ref=source_ref,
            content_origin=NativeHostOrigin(
                host_root_handle_id="legacy-root-handle",
                root_policy_fingerprint=_digest("root-policy"),
                workspace_or_user_scope="workspace",
            ),
            opaque_locator=source_path.relative_to(source_root).as_posix(),
        )

    adapted = adapt_legacy_resource_snapshot(
        legacy,
        discovery_request_fingerprint=_digest("request"),
        provenance_resolver=provenance,
    )
    catalog = compose_resource_catalog(
        adapted.source_snapshots,
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=build_activation_policy_snapshot(
            policy_revision="activation-v1"
        ),
    )
    report = compare_legacy_resource_snapshot(
        adaptation=adapted,
        catalog_snapshot=catalog,
    )
    legacy_bundle = legacy.to_bundle()
    shadow_bundle = project_shadow_compatibility_bundle(
        adaptation=adapted,
        catalog_snapshot=catalog,
        cwd=legacy.cwd,
    )

    assert report.matches is True
    assert report.differences == ()
    assert shadow_bundle.prompt_descriptors == legacy_bundle.prompt_descriptors
    assert shadow_bundle.prompt_fragments == legacy_bundle.prompt_fragments
    assert shadow_bundle.skills == legacy_bundle.skills
    assert shadow_bundle.extensions == legacy_bundle.extensions
    assert shadow_bundle.themes == legacy_bundle.themes
    assert shadow_bundle.diagnostics == legacy_bundle.diagnostics
    assert [entry.identity.resource_kind for entry in catalog.effective_entries] == [
        "extension",
        "skill",
        "theme",
    ]
    assert legacy.active_skill_descriptors == (skill,)


def test_shadow_report_does_not_hide_unapproved_differences(tmp_path: Path) -> None:
    skill = SkillDescriptor(
        name="review",
        content="Review changes.",
        source_path=tmp_path / "review" / "SKILL.md",
        source_root=tmp_path,
    )
    legacy = ResourceSnapshot(
        cwd=tmp_path,
        active_skill_descriptors=(skill,),
        candidate_skill_descriptors=(skill,),
    )
    source_ref = _source_ref()
    adapted = adapt_legacy_resource_snapshot(
        legacy,
        discovery_request_fingerprint=_digest("request"),
        provenance_resolver=lambda _descriptor: LegacyCandidateProvenance(
            source_generation_ref=source_ref,
            content_origin=NativeHostOrigin(
                host_root_handle_id="legacy-root-handle",
                root_policy_fingerprint=_digest("root-policy"),
                workspace_or_user_scope="workspace",
            ),
            opaque_locator="review/SKILL.md",
        ),
    )
    empty_catalog = compose_resource_catalog(
        (),
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=build_activation_policy_snapshot(
            policy_revision="activation-v1"
        ),
    )

    report = compare_legacy_resource_snapshot(
        adaptation=adapted,
        catalog_snapshot=empty_catalog,
    )

    assert report.matches is False
    assert len(report.differences) == 1
    assert report.differences[0].identity.public_id == "review"
    assert report.known_exceptions == ()

    with pytest.raises(
        LegacyShadowAdaptationError,
        match="requires duplicate legacy Skill/Prompt evidence",
    ):
        compare_legacy_resource_snapshot(
            adaptation=adapted,
            catalog_snapshot=empty_catalog,
            known_extension_collision_identities=(
                adapted.legacy_effective_entries[0].identity,
            ),
        )


def test_shadow_catalog_matches_current_kind_specific_resolvers() -> None:
    source_ref = _source_ref()
    scope_by_kind: dict[ResourceSourceKind, ResourceSourceScope] = {
        "temporary": "temporary",
        "project_local": "project",
        "user_global": "user",
        "external_package": "package",
        "built_in": "builtin",
    }
    skills = tuple(
        SkillDescriptor(
            name="review",
            content=f"Review from {source_kind}.",
            source_path=Path(source_kind) / "review" / "SKILL.md",
            source_root=Path(source_kind),
            source_kind=source_kind,
            source_scope=scope_by_kind[source_kind],
        )
        for source_kind in (
            "built_in",
            "external_package",
            "user_global",
            "project_local",
            "temporary",
        )
    )
    prompts = tuple(
        PromptFragmentDescriptor(
            name="review-prompt",
            text=f"Prompt from {source_kind}.",
            source_path=Path(source_kind) / "review.md",
            source_root=Path(source_kind),
            source_kind=source_kind,
            source_scope=scope_by_kind[source_kind],
        )
        for source_kind in ("built_in", "project_local")
    )
    themes = (
        ThemeDescriptor(
            name="clean",
            content='{"root": 2}',
            source_path=Path("project") / "later" / "clean.json",
            source_root=Path("project"),
            source_root_order=2,
        ),
        ThemeDescriptor(
            name="clean",
            content='{"root": 1}',
            source_path=Path("project") / "earlier" / "clean.json",
            source_root=Path("project"),
            source_root_order=1,
        ),
    )
    extensions = (
        ExtensionDescriptor(
            name="guard",
            source_path=Path("built_in") / "guard.py",
            source_root=Path("built_in"),
            source_kind="built_in",
            source_scope="builtin",
        ),
        ExtensionDescriptor(
            name="guard",
            source_path=Path("project") / "guard.py",
            source_root=Path("project"),
        ),
    )
    active_skills, _, skill_decisions = _resolve_strict_named_candidates(
        skills,
        resource_type="skill",
    )
    active_prompts, _, prompt_decisions = _resolve_strict_named_candidates(
        prompts,
        resource_type="prompt",
    )
    active_themes, _, theme_decisions = _resolve_candidates(
        themes,
        resource_type="theme",
    )
    active_extensions, _, extension_decisions = _resolve_extension_candidates(
        extensions,
        resource_type="extension",
    )
    legacy = ResourceSnapshot(
        cwd=Path("workspace"),
        active_prompt_descriptors=tuple(active_prompts),
        candidate_prompt_descriptors=prompts,
        active_skill_descriptors=tuple(active_skills),
        candidate_skill_descriptors=skills,
        active_extension_descriptors=tuple(active_extensions),
        candidate_extension_descriptors=extensions,
        active_theme_descriptors=tuple(active_themes),
        candidate_theme_descriptors=themes,
        merge_decisions=tuple(
            (
                *skill_decisions,
                *prompt_decisions,
                *theme_decisions,
                *extension_decisions,
            )
        ),
    )

    def provenance(descriptor: object) -> LegacyCandidateProvenance:
        source_kind = descriptor.source_kind  # type: ignore[attr-defined]
        if source_kind == "external_package":
            origin = VerifiedPluginResourceOrigin(
                resource_contribution_id=f"legacy:{descriptor.id}",  # type: ignore[attr-defined]
                resource_admission_fingerprint=_digest("package-admission"),
                plugin_instance_revision_ref="plugin-instance-1",
                package_content_digest=_digest("package-content"),
            )
        elif source_kind == "built_in":
            origin = EmbeddedOemOrigin(
                embedded_collection_id="loushang.builtin",
                embedded_revision="revision-1",
                collection_content_digest=_digest("builtin-content"),
            )
        else:
            origin = NativeHostOrigin(
                host_root_handle_id=f"root:{source_kind}",
                root_policy_fingerprint=_digest(f"root:{source_kind}"),
                workspace_or_user_scope=(
                    "user"
                    if source_kind == "user_global"
                    else "temporary"
                    if source_kind == "temporary"
                    else "workspace"
                ),
            )
        return LegacyCandidateProvenance(
            source_generation_ref=source_ref,
            content_origin=origin,
            opaque_locator=(
                f"{source_kind}/{descriptor.source_root_order}/"  # type: ignore[attr-defined]
                f"{descriptor.canonical_name}"  # type: ignore[attr-defined]
            ),
        )

    adapted = adapt_legacy_resource_snapshot(
        legacy,
        discovery_request_fingerprint=_digest("resolver-parity-request"),
        provenance_resolver=provenance,
    )
    catalog = compose_resource_catalog(
        adapted.source_snapshots,
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=build_activation_policy_snapshot(
            policy_revision="activation-v1"
        ),
    )

    report = compare_legacy_resource_snapshot(
        adaptation=adapted,
        catalog_snapshot=catalog,
    )

    assert report.matches is True
    assert report.differences == ()
    assert {
        decision.identity.resource_kind: decision.reason
        for decision in catalog.merge_decisions
    } == {
        "extension": "all_enabled_candidates_active",
        "prompt": "source_precedence",
        "skill": "source_precedence",
        "theme": "precedence_and_tiebreak",
    }


def test_shadow_report_requires_explicit_opt_in_for_frozen_extension_exception(
    tmp_path: Path,
) -> None:
    base_skill = SkillDescriptor(
        name="review",
        content="Review base changes.",
        source_path=tmp_path / "base" / "review" / "SKILL.md",
        source_root=tmp_path,
    )
    extension_skill = SkillDescriptor(
        name="review",
        content="Review Extension changes.",
        source_path=tmp_path / "extension" / "review" / "SKILL.md",
        source_root=tmp_path,
    )
    legacy = ResourceSnapshot(
        cwd=tmp_path,
        active_skill_descriptors=(base_skill, extension_skill),
        candidate_skill_descriptors=(base_skill, extension_skill),
    )
    native_source_ref = _source_ref()
    extension_source_ref = ResourceSourceGenerationRef(
        source_id="legacy-extension-shadow",
        product_id="coding",
        generation="extension-generation-1",
        source_policy_fingerprint=_digest("extension-source-policy"),
        producer=ExtensionOwnerProducer(
            runtime_id="extension-runtime-1",
            extension_generation="extension-generation-1",
            extension_set_fingerprint=_digest("extension-set"),
            extension_owner_fingerprint=_digest("extension-owner"),
        ),
    )

    def provenance(descriptor: object) -> LegacyCandidateProvenance:
        if descriptor is extension_skill:
            return LegacyCandidateProvenance(
                source_generation_ref=extension_source_ref,
                content_origin=ExtensionOutputOrigin(
                    extension_generation_ref="extension-generation-1",
                    extension_id="resource-parity-extension",
                    route_id="resources-discover-1",
                    route_set_fingerprint=_digest("route-set"),
                    hook_snapshot_fingerprint=_digest("hook-snapshot"),
                ),
                opaque_locator="extension/review/SKILL.md",
            )
        return LegacyCandidateProvenance(
            source_generation_ref=native_source_ref,
            content_origin=NativeHostOrigin(
                host_root_handle_id="legacy-root-handle",
                root_policy_fingerprint=_digest("root-policy"),
                workspace_or_user_scope="workspace",
            ),
            opaque_locator="base/review/SKILL.md",
        )

    adapted = adapt_legacy_resource_snapshot(
        legacy,
        discovery_request_fingerprint=_digest("request"),
        provenance_resolver=provenance,
    )
    catalog = compose_resource_catalog(
        adapted.source_snapshots,
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=build_activation_policy_snapshot(
            policy_revision="activation-v1"
        ),
    )

    report = compare_legacy_resource_snapshot(
        adaptation=adapted,
        catalog_snapshot=catalog,
        known_extension_collision_identities=(
            adapted.legacy_effective_entries[0].identity,
        ),
    )

    assert report.matches is True
    assert report.differences == ()
    assert len(report.known_exceptions) == 1
    assert (
        report.known_exceptions[0].reason == "legacy_extension_post_discovery_collision"
    )
