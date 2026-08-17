from __future__ import annotations

from uuid import UUID

from loushang.ontology.action import ActionRequest, ProjectionGuard, plan_action
from loushang.ontology.deployment import (
    DeploymentProfile,
    SourceInstanceSelection,
    lock_schema_artifact,
    lock_source_adapter_artifact,
    validate_deployment_profile,
)
from loushang.ontology.projection import (
    ProjectionFreshnessStatus,
    evaluate_projection_freshness,
    materialize_projection,
)
from loushang.ontology.query import QueryBuilder
from loushang.ontology.schema import (
    ActionDefinition,
    ActionParameterDefinition,
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaIdentity,
    SetPropertyEffectDefinition,
    StateAuthority,
    ValueType,
)
from loushang.ontology.source import (
    ApplicationSchemaIdentity,
    MappedSourceInput,
    MappedSourceObject,
    MappedSourceProperty,
    MappedSourceSnapshot,
    SourceAdapterManifest,
    SourceBinding,
    SourceCoverage,
)
from loushang.ontology.storage import MemoryFactStore, MemoryProjectionStore

PROJECT_ID = UUID("30000000-0000-0000-0000-000000000001")


def test_source_project_can_receive_an_ontology_owned_action_property() -> None:
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.action-flow",
            namespace="urn:test:action-flow",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Project",
                    semantic_id="project",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    properties=[
                        PropertyDefinition(
                            "name",
                            ValueType.STRING,
                            semantic_id="project.name",
                            state_authority=StateAuthority.SOURCE_BACKED,
                            required=True,
                        ),
                        PropertyDefinition(
                            "review_note",
                            ValueType.STRING,
                            semantic_id="project.review_note",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                            default="not-reviewed",
                        ),
                    ],
                )
            ],
            actions=[
                ActionDefinition(
                    "set_review_note",
                    semantic_id="project.set_review_note",
                    target_object_type_id="project",
                    parameters=[ActionParameterDefinition("value", ValueType.STRING)],
                    effect=SetPropertyEffectDefinition(
                        "project.review_note",
                        "value",
                    ),
                    policy_requirement_ref="policy.project.review",
                )
            ],
        )
    )
    identity = SchemaIdentity.from_schema(schema)
    binding = SourceBinding(
        binding_id="erp.projects",
        mapping_version="1",
        schema_identity=identity,
        object_existence_ids=("project",),
        property_ids=("project.name",),
    )
    manifest = SourceAdapterManifest(
        adapter_id="erp-adapter",
        adapter_version="1.0.0",
        application_schema=ApplicationSchemaIdentity("erp", "2026.1"),
        target_schema=identity,
        bindings=(binding,),
    )
    profile = DeploymentProfile(
        deployment_id="bureau-projects",
        schema_lock=lock_schema_artifact(schema),
        adapter_locks=(lock_source_adapter_artifact(manifest),),
        source_instances=(
            SourceInstanceSelection(
                "erp:province",
                "erp-adapter",
                ("erp.projects",),
            ),
        ),
        identity_crosswalk_lock=None,
        fact_store_ref="memory:facts",
        projection_store_ref="memory:projection",
    )
    enabled_bindings = validate_deployment_profile(
        profile,
        schema=schema,
        adapter_manifests=(manifest,),
        identity_crosswalk=None,
    )
    source_input = MappedSourceInput(
        binding_id="erp.projects",
        mapping_version="1",
        source_revision="tx:10",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=PROJECT_ID,
                    object_type_id="project",
                    source_record_ref="project:P-1",
                    identity_field_ref="project_id",
                    properties=(
                        MappedSourceProperty(
                            property_id="project.name",
                            value="River Restoration",
                            field_ref="project_name",
                            valid_from=0,
                        ),
                    ),
                ),
            )
        ),
    )
    facts = MemoryFactStore()
    initial_selection = facts.select_facts(valid_at=50, recorded_at=50)
    initial = materialize_projection(
        initial_selection,
        schema,
        source_bindings=enabled_bindings,
        source_inputs=(source_input,),
        projection_version=1,
        built_at=50,
    )
    projections = MemoryProjectionStore()
    projections.replace(initial)
    assert projections.get(PROJECT_ID).get("review_note") == "not-reviewed"  # type: ignore[union-attr]

    request = ActionRequest(
        deployment_id=profile.deployment_id,
        deployment_profile_digest=profile.profile_digest,
        schema_identity=identity,
        action_id="project.set_review_note",
        request_id="review-request-1",
        target_object_id=PROJECT_ID,
        arguments={"value": "approved for execution"},
        projection_guard=ProjectionGuard.from_state(initial.state),
        actor_context_ref="user:project-director",
        valid_from=50,
        recorded_at=60,
    )
    plan = plan_action(
        request,
        schema=schema,
        projection=initial,
        fact_selection=initial_selection,
        deployment_profile=profile,
    )
    commit = facts.commit_fact_batch_guarded(
        plan.effect.fact_batch,
        expected_watermark=plan.effect.expected_fact_watermark,
    )
    assert commit.replayed is False
    assert projections.get(PROJECT_ID).get("review_note") == "not-reviewed"  # type: ignore[union-attr]
    freshness = evaluate_projection_freshness(
        projections.projection_state,
        observed_fact_watermark=facts.fact_watermark,
        observed_source_heads=(source_input.revision,),
        observed_at=60,
    )
    assert freshness.status is ProjectionFreshnessStatus.STALE

    refreshed_selection = facts.select_facts(valid_at=50, recorded_at=60)
    refreshed = materialize_projection(
        refreshed_selection,
        schema,
        source_bindings=enabled_bindings,
        source_inputs=(source_input,),
        projection_version=2,
        built_at=61,
    )
    projections.replace(refreshed)

    project = QueryBuilder(projections).start_from(PROJECT_ID).execute_first()
    assert project is not None
    assert project.get("name") == "River Restoration"
    assert project.get("review_note") == "approved for execution"
