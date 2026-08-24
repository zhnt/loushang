from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from loushang.harness.resources._catalog_engine import (
    CatalogCompositionError,
    compose_resource_catalog,
    default_resource_merge_policy,
)
from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    EmbeddedOemOrigin,
    ExtensionOutputOrigin,
    ExtensionOwnerProducer,
    NativeHostOrigin,
    ResourceActivationPolicySnapshot,
    ResourceBodyRead,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceCatalogHandle,
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceLoadHandle,
    ResourceLoadReceipt,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    VerifiedPluginResourceOrigin,
    build_activation_policy_snapshot,
    build_candidate_summary,
    build_source_snapshot,
    fingerprint_catalog_value,
)


def _digest(value: str) -> str:
    return fingerprint_catalog_value("test", value)


def _source_ref(source_id: str = "native") -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id=source_id,
        product_id="coding",
        generation="generation-1",
        source_policy_fingerprint=_digest(f"policy:{source_id}"),
        producer=ResourceComponentProducer(
            component_contribution_id="resource.source.native",
            component_candidate_fingerprint=_digest(f"candidate:{source_id}"),
            component_admission_fingerprint=_digest(f"admission:{source_id}"),
            binding_fingerprint=_digest(f"binding:{source_id}"),
            plugin_instance_revision_ref="first-party",
            package_content_digest=_digest("first-party-package"),
        ),
    )


def _extension_source_ref() -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id="extension-output",
        product_id="coding",
        generation="extension-generation-1",
        source_policy_fingerprint=_digest("extension-policy"),
        producer=ExtensionOwnerProducer(
            runtime_id="extension-runtime-1",
            extension_generation="extension-generation-1",
            extension_set_fingerprint=_digest("extension-set"),
            extension_owner_fingerprint=_digest("extension-owner"),
        ),
    )


def _candidate(
    public_id: str,
    *,
    resource_kind: str = "skill",
    source_class: str = "project_local",
    root_order: int = 0,
    locator_suffix: str = "SKILL.md",
    source_ref: ResourceSourceGenerationRef | None = None,
    enabled: bool = True,
    model_invocable: bool = True,
) -> ResourceCandidateSummary:
    source_generation_ref = source_ref or _source_ref()
    body = f"body:{resource_kind}:{public_id}:{source_class}:{root_order}"
    encoded = body.encode()
    if source_class == "external_package":
        content_origin = VerifiedPluginResourceOrigin(
            resource_contribution_id=f"resource:{public_id}",
            resource_admission_fingerprint=_digest(f"resource:{public_id}:admission"),
            plugin_instance_revision_ref="plugin-instance-1",
            package_content_digest=_digest(f"package:{public_id}"),
        )
    elif source_class == "built_in":
        content_origin = EmbeddedOemOrigin(
            embedded_collection_id="loushang.builtin",
            embedded_revision="revision-1",
            collection_content_digest=_digest("loushang.builtin"),
        )
    else:
        content_origin = NativeHostOrigin(
            host_root_handle_id=f"root:{source_class}:{root_order}",
            root_policy_fingerprint=_digest(f"root:{source_class}:{root_order}"),
            workspace_or_user_scope=(
                "user"
                if source_class == "user_global"
                else "temporary"
                if source_class == "temporary"
                else "workspace"
            ),
        )
    return build_candidate_summary(
        identity=ResourceIdentity(
            resource_kind=resource_kind,
            schema_id=f"loushang.resource.{resource_kind}",
            schema_version=1,
            public_id=public_id,
        ),
        canonical_name=public_id,
        description=f"{public_id} description",
        media_type="text/markdown" if resource_kind != "theme" else "application/json",
        invocation_policy=ResourceInvocationPolicy(
            enabled=enabled,
            model_invocable=model_invocable,
            reason="test",
        ),
        source_generation_ref=source_generation_ref,
        source_class=source_class,  # type: ignore[arg-type]
        scope_id=(
            "package"
            if source_class == "external_package"
            else "builtin"
            if source_class == "built_in"
            else "user"
            if source_class == "user_global"
            else "temporary"
            if source_class == "temporary"
            else "project"
        ),
        source_root_order=root_order,
        content_origin=content_origin,
        opaque_locator=f"{public_id}/{locator_suffix}",
        discovery_fingerprint=_digest("discovery"),
        expected_content_digest=hashlib.sha256(encoded).hexdigest(),
        expected_content_length=len(encoded),
    )


def _source_snapshot(
    *candidates: ResourceCandidateSummary,
) -> ResourceSourceSnapshot:
    return build_source_snapshot(
        source_generation_ref=candidates[0].source_generation_ref,
        discovery_request_fingerprint=_digest("request"),
        candidate_summaries=candidates,
    )


def _activation(
    *,
    disabled: tuple[ResourceIdentity, ...] = (),
    model_disabled: tuple[ResourceIdentity, ...] = (),
) -> ResourceActivationPolicySnapshot:
    return build_activation_policy_snapshot(
        policy_revision="activation-v1",
        disabled_identities=disabled,
        model_invocation_disabled_identities=model_disabled,
    )


def _compose(
    *snapshots: ResourceSourceSnapshot,
    activation: ResourceActivationPolicySnapshot | None = None,
):
    return compose_resource_catalog(
        snapshots,
        catalog_generation=1,
        engine_binding_fingerprint=_digest("engine"),
        merge_policy=default_resource_merge_policy(),
        activation_policy=activation or _activation(),
    )


def test_catalog_records_are_immutable_and_source_snapshot_is_canonical() -> None:
    beta = _candidate("beta")
    alpha = _candidate("alpha")

    snapshot = _source_snapshot(beta, alpha)

    assert [item.identity.public_id for item in snapshot.candidate_summaries] == [
        "alpha",
        "beta",
    ]
    with pytest.raises(FrozenInstanceError):
        snapshot.complete = False  # type: ignore[misc]


def test_source_snapshot_rejects_foreign_generation_and_exact_duplicates() -> None:
    candidate = _candidate("review")
    foreign = _candidate("other", source_ref=_source_ref("foreign"))

    with pytest.raises(ValueError, match="same source generation"):
        build_source_snapshot(
            source_generation_ref=candidate.source_generation_ref,
            discovery_request_fingerprint=_digest("request"),
            candidate_summaries=(candidate, foreign),
        )
    with pytest.raises(ValueError, match="duplicate candidate"):
        build_source_snapshot(
            source_generation_ref=candidate.source_generation_ref,
            discovery_request_fingerprint=_digest("request"),
            candidate_summaries=(candidate, candidate),
        )


def test_strict_named_policy_preserves_precedence_and_input_order_independence() -> (
    None
):
    source_ref = _source_ref()
    candidates = tuple(
        _candidate("review", source_class=source_class, source_ref=source_ref)
        for source_class in (
            "built_in",
            "external_package",
            "user_global",
            "project_local",
            "temporary",
        )
    )

    forward = _compose(_source_snapshot(*candidates))
    reverse = _compose(_source_snapshot(*reversed(candidates)))

    assert forward.snapshot_fingerprint == reverse.snapshot_fingerprint
    assert len(forward.effective_entries) == 1
    winner = forward.candidate_by_fingerprint(
        forward.effective_entries[0].primary_candidate_fingerprint
    )
    assert winner.source_class == "temporary"
    assert forward.merge_decisions[0].reason == "source_precedence"


def test_strict_named_policy_rejects_same_precedence_conflict() -> None:
    source_ref = _source_ref()
    first = _candidate(
        "review",
        source_class="project_local",
        root_order=1,
        source_ref=source_ref,
    )
    second = _candidate(
        "review",
        source_class="project_local",
        root_order=2,
        source_ref=source_ref,
    )

    catalog = _compose(_source_snapshot(first, second))

    assert catalog.effective_entries == ()
    assert catalog.merge_decisions[0].winner_candidate_fingerprint is None
    assert catalog.merge_decisions[0].reason == "same_precedence_conflict"


def test_permissive_and_additive_policies_are_kind_specific() -> None:
    source_ref = _source_ref()
    later_theme = _candidate(
        "clean",
        resource_kind="theme",
        root_order=2,
        locator_suffix="clean.json",
        source_ref=source_ref,
    )
    earlier_theme = _candidate(
        "clean",
        resource_kind="theme",
        root_order=1,
        locator_suffix="clean.json",
        source_ref=source_ref,
    )
    project_extension = _candidate(
        "guard",
        resource_kind="extension",
        source_class="project_local",
        locator_suffix="guard.py",
        source_ref=source_ref,
    )
    built_in_extension = _candidate(
        "guard",
        resource_kind="extension",
        source_class="built_in",
        locator_suffix="guard.py",
        source_ref=source_ref,
    )

    catalog = _compose(
        _source_snapshot(
            later_theme,
            earlier_theme,
            built_in_extension,
            project_extension,
        )
    )
    entries = {
        entry.identity.resource_kind: entry for entry in catalog.effective_entries
    }

    theme = catalog.candidate_by_fingerprint(
        entries["theme"].primary_candidate_fingerprint
    )
    assert theme.source_root_order == 1
    assert entries["extension"].candidate_fingerprints == (
        project_extension.candidate_fingerprint,
        built_in_extension.candidate_fingerprint,
    )
    decisions = {
        decision.identity.resource_kind: decision
        for decision in catalog.merge_decisions
    }
    assert decisions["theme"].reason == "precedence_and_tiebreak"
    assert decisions["extension"].reason == "all_enabled_candidates_active"


def test_activation_overlay_does_not_mutate_candidate_evidence() -> None:
    skill = _candidate("review")
    theme = _candidate("clean", resource_kind="theme", locator_suffix="clean.json")

    catalog = _compose(
        _source_snapshot(skill, theme),
        activation=_activation(
            disabled=(theme.identity,),
            model_disabled=(skill.identity,),
        ),
    )

    assert catalog.candidate_summaries == tuple(
        sorted((skill, theme), key=lambda item: item.canonical_sort_key())
    )
    assert [entry.identity.public_id for entry in catalog.effective_entries] == [
        "review"
    ]
    assert catalog.effective_entries[0].model_invocable is False


def test_catalog_rejects_one_candidate_entering_through_two_source_snapshots() -> None:
    candidate = _candidate("review")
    snapshot = _source_snapshot(candidate)

    with pytest.raises(CatalogCompositionError, match="more than one source snapshot"):
        _compose(snapshot, snapshot)


def test_load_records_bind_exact_catalog_source_locator_and_body_identity() -> None:
    candidate = _candidate("review")
    catalog = _compose(_source_snapshot(candidate))
    entry = catalog.effective_entries[0]
    catalog_handle = ResourceCatalogHandle(
        catalog_generation=catalog.catalog_generation,
        snapshot_fingerprint=catalog.snapshot_fingerprint,
        identity=entry.identity,
        candidate_fingerprint=entry.primary_candidate_fingerprint,
    )
    load_handle = ResourceLoadHandle.from_catalog(
        catalog_handle=catalog_handle,
        candidate=candidate,
    )
    body = b"body:skill:review:project_local:0"
    body_read = ResourceBodyRead(
        source_generation_ref=candidate.source_generation_ref,
        opaque_locator=candidate.opaque_locator,
        body=body,
        observed_content_digest=hashlib.sha256(body).hexdigest(),
        observed_content_length=len(body),
    )
    receipt = ResourceLoadReceipt.from_validated_read(
        load_handle=load_handle,
        body_read=body_read,
    )

    assert receipt.content_digest == candidate.expected_content_digest
    assert receipt.content_length == candidate.expected_content_length

    mismatched = replace(body_read, observed_content_length=len(body) + 1)
    with pytest.raises(ValueError, match="expected content identity"):
        ResourceLoadReceipt.from_validated_read(
            load_handle=load_handle,
            body_read=mismatched,
        )


def test_no_body_candidates_use_an_explicit_media_variant() -> None:
    source_ref = _source_ref()

    candidate = build_candidate_summary(
        identity=ResourceIdentity(
            "extension", "loushang.resource.extension", 1, "guard"
        ),
        canonical_name="guard",
        description=None,
        media_type=NO_BODY_MEDIA_TYPE,
        invocation_policy=ResourceInvocationPolicy(
            enabled=True,
            model_invocable=False,
            reason="executable_owner_only",
        ),
        source_generation_ref=source_ref,
        source_class="project_local",
        scope_id="project",
        source_root_order=0,
        content_origin=NativeHostOrigin(
            host_root_handle_id="root:extension",
            root_policy_fingerprint=_digest("root:extension"),
            workspace_or_user_scope="workspace",
        ),
        opaque_locator="guard.py",
        discovery_fingerprint=_digest("discovery"),
        expected_content_digest=None,
        expected_content_length=None,
    )

    assert candidate.has_body is False

    with pytest.raises(ValueError, match="no-body media type"):
        replace(candidate, media_type="text/plain")


def test_candidate_rejects_tampering_foreign_origin_and_locator_escape() -> None:
    candidate = _candidate("review")

    with pytest.raises(ValueError, match="candidate fingerprint"):
        replace(candidate, description="tampered")
    with pytest.raises(ValueError, match="host path escape"):
        replace(candidate, opaque_locator="../outside/SKILL.md")

    package_candidate = _candidate("package-review", source_class="external_package")
    with pytest.raises(ValueError, match="origin does not match"):
        replace(
            package_candidate,
            content_origin=NativeHostOrigin(
                host_root_handle_id="wrong-root",
                root_policy_fingerprint=_digest("wrong-root"),
                workspace_or_user_scope="workspace",
            ),
        )


def test_extension_origin_must_match_the_exact_extension_owner_generation() -> None:
    candidate = _candidate("review")
    extension_origin = ExtensionOutputOrigin(
        extension_generation_ref="extension-generation-1",
        extension_id="review-extension",
        route_id="resources-discover-1",
        route_set_fingerprint=_digest("route-set"),
        hook_snapshot_fingerprint=_digest("hook-snapshot"),
    )

    with pytest.raises(ValueError, match="Extension owner producer"):
        replace(candidate, content_origin=extension_origin)

    extension_source = _extension_source_ref()
    with pytest.raises(ValueError, match="exact Extension generation"):
        build_candidate_summary(
            identity=candidate.identity,
            canonical_name=candidate.canonical_name,
            description=candidate.description,
            media_type=candidate.media_type,
            invocation_policy=candidate.invocation_policy,
            source_generation_ref=extension_source,
            source_class="project_local",
            scope_id="project",
            source_root_order=0,
            content_origin=replace(
                extension_origin,
                extension_generation_ref="extension-generation-2",
            ),
            opaque_locator=candidate.opaque_locator,
            discovery_fingerprint=candidate.discovery_fingerprint,
            expected_content_digest=candidate.expected_content_digest,
            expected_content_length=candidate.expected_content_length,
        )


def test_candidate_and_source_diagnostics_cannot_cross_identity_or_generation() -> None:
    candidate = _candidate("review")
    foreign_identity = ResourceIdentity(
        "skill",
        "loushang.resource.skill",
        1,
        "foreign",
    )

    with pytest.raises(ValueError, match="candidate identity"):
        build_candidate_summary(
            identity=candidate.identity,
            canonical_name=candidate.canonical_name,
            description=candidate.description,
            media_type=candidate.media_type,
            invocation_policy=candidate.invocation_policy,
            source_generation_ref=candidate.source_generation_ref,
            source_class=candidate.source_class,
            scope_id=candidate.scope_id,
            source_root_order=candidate.source_root_order,
            content_origin=candidate.content_origin,
            opaque_locator=candidate.opaque_locator,
            discovery_fingerprint=candidate.discovery_fingerprint,
            expected_content_digest=candidate.expected_content_digest,
            expected_content_length=candidate.expected_content_length,
            diagnostics=(
                ResourceCatalogDiagnostic(
                    code="resource_source_snapshot_invalid",
                    reason="foreign_identity",
                    identity=foreign_identity,
                    source_id=candidate.source_generation_ref.source_id,
                ),
            ),
        )

    with pytest.raises(ValueError, match="source generation"):
        build_source_snapshot(
            source_generation_ref=candidate.source_generation_ref,
            discovery_request_fingerprint=_digest("request"),
            candidate_summaries=(candidate,),
            diagnostics=(
                ResourceCatalogDiagnostic(
                    code="resource_source_snapshot_invalid",
                    reason="foreign_source",
                    source_id="foreign-source",
                ),
            ),
        )


def test_body_records_require_immutable_bytes() -> None:
    candidate = _candidate("review")

    with pytest.raises(TypeError, match="immutable bytes"):
        ResourceBodyRead(
            source_generation_ref=candidate.source_generation_ref,
            opaque_locator=candidate.opaque_locator,
            body="not-bytes",  # type: ignore[arg-type]
            observed_content_digest=candidate.expected_content_digest or "",
            observed_content_length=9,
        )


def test_catalog_snapshot_rejects_omitted_decisions() -> None:
    candidate = _candidate("review")
    catalog = _compose(_source_snapshot(candidate))

    with pytest.raises(ValueError, match="account for every candidate"):
        replace(catalog, merge_decisions=())


def test_incomplete_source_evidence_propagates_without_reusing_old_state() -> None:
    candidate = _candidate("review")
    source = build_source_snapshot(
        source_generation_ref=candidate.source_generation_ref,
        discovery_request_fingerprint=_digest("request"),
        candidate_summaries=(candidate,),
        complete=False,
    )

    catalog = _compose(source)

    assert catalog.complete is False
