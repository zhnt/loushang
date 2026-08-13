from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from loushang.ontology.action import (
    ActionPlanningError,
    ActionRequest,
    ProjectionGuard,
    plan_action,
)
from loushang.ontology.deployment import DeploymentProfile, lock_schema_artifact
from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.projection import materialize_projection
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
from loushang.ontology.storage import MemoryFactStore

PROJECT_ID = UUID("20000000-0000-0000-0000-000000000001")
OBJECT_FACT_ID = UUID("21000000-0000-0000-0000-000000000001")
NOTE_FACT_ID = UUID("21000000-0000-0000-0000-000000000002")


def _action(
    name: str,
    action_id: str,
    property_id: str,
    value_type: ValueType,
) -> ActionDefinition:
    return ActionDefinition(
        name,
        semantic_id=action_id,
        target_object_type_id="project",
        parameters=[ActionParameterDefinition("value", value_type)],
        effect=SetPropertyEffectDefinition(property_id, "value"),
        policy_requirement_ref=f"policy.{name}",
    )


def _schema():
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.action-planning",
            namespace="urn:test:action-planning",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Project",
                    semantic_id="project",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[
                        PropertyDefinition(
                            "review_note",
                            ValueType.STRING,
                            semantic_id="project.review_note",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        ),
                        PropertyDefinition(
                            "budget",
                            ValueType.NUMBER,
                            semantic_id="project.budget",
                            state_authority=StateAuthority.SOURCE_BACKED,
                        ),
                        PropertyDefinition(
                            "risk_score",
                            ValueType.NUMBER,
                            semantic_id="project.risk_score",
                            state_authority=StateAuthority.DERIVED,
                        ),
                    ],
                )
            ],
            actions=[
                _action(
                    "set_review_note",
                    "project.set_review_note",
                    "project.review_note",
                    ValueType.STRING,
                ),
                _action(
                    "set_budget",
                    "project.set_budget",
                    "project.budget",
                    ValueType.NUMBER,
                ),
                _action(
                    "set_risk_score",
                    "project.set_risk_score",
                    "project.risk_score",
                    ValueType.NUMBER,
                ),
            ],
        )
    )


def _profile(schema) -> DeploymentProfile:
    return DeploymentProfile(
        deployment_id="test-deployment",
        schema_lock=lock_schema_artifact(schema),
        adapter_locks=[],
        source_instances=[],
        identity_crosswalk_lock=None,
        fact_store_ref="memory:facts",
        projection_store_ref="memory:projection",
    )


def _fixture():
    schema = _schema()
    identity = SchemaIdentity.from_schema(schema)
    facts = MemoryFactStore()
    facts.commit_fact_batch(
        FactBatch(
            "initial-project",
            [
                FactRecord(
                    fact_id=OBJECT_FACT_ID,
                    subject_id=PROJECT_ID,
                    schema_identity=identity,
                    assertion=ObjectAssertion("project"),
                    assertion_kind=AssertionKind.ASSERTED,
                    source_ref="ontology-owned:project",
                    source_record_ref=str(PROJECT_ID),
                    valid_from=0,
                    recorded_at=10,
                ),
                FactRecord(
                    fact_id=NOTE_FACT_ID,
                    subject_id=PROJECT_ID,
                    schema_identity=identity,
                    assertion=PropertyAssertion("project.review_note", "old"),
                    assertion_kind=AssertionKind.ASSERTED,
                    source_ref="ontology-owned:project.review_note",
                    source_record_ref=f"{PROJECT_ID}:project.review_note",
                    valid_from=0,
                    recorded_at=10,
                ),
            ],
        )
    )
    selection = facts.select_facts(valid_at=50, recorded_at=50)
    snapshot = materialize_projection(selection, schema, built_at=50)
    return schema, _profile(schema), selection, snapshot


def _request(
    schema,
    profile,
    snapshot,
    *,
    action_id: str = "project.set_review_note",
    target_id: UUID = PROJECT_ID,
    value: object = "new",
    request_id: str = "request-1",
) -> ActionRequest:
    return ActionRequest(
        deployment_id=profile.deployment_id,
        deployment_profile_digest=profile.profile_digest,
        schema_identity=SchemaIdentity.from_schema(schema),
        action_id=action_id,
        request_id=request_id,
        target_object_id=target_id,
        arguments={"value": value},
        projection_guard=ProjectionGuard.from_state(snapshot.state),
        actor_context_ref="user:123",
        valid_from=50,
        recorded_at=60,
    )


def test_planner_emits_a_deterministic_superseding_fact_batch() -> None:
    schema, profile, selection, snapshot = _fixture()
    request = _request(schema, profile, snapshot)

    first = plan_action(
        request,
        schema=schema,
        projection=snapshot,
        fact_selection=selection,
        deployment_profile=profile,
    )
    second = plan_action(
        ActionRequest.from_json(request.to_json()),
        schema=schema,
        projection=snapshot,
        fact_selection=selection,
        deployment_profile=profile,
    )

    assert second == first
    assert first.to_json() == second.to_json()
    assert first.plan_digest == second.plan_digest
    assert first.request_digest == request.request_digest
    assert first.effect.expected_fact_watermark == selection.fact_watermark
    fact = first.effect.fact_batch.facts[0]
    assert fact.fact_id != NOTE_FACT_ID
    assert fact.subject_id == PROJECT_ID
    assert fact.assertion == PropertyAssertion("project.review_note", "new")
    assert fact.assertion_kind is AssertionKind.ASSERTED
    assert fact.supersedes == NOTE_FACT_ID
    assert fact.source_ref == "ontology-owned:project.review_note"
    assert fact.source_record_ref == f"{PROJECT_ID}:project.review_note"
    assert fact.author_ref == "user:123"
    assert fact.valid_from == 50
    assert fact.recorded_at == 60
    assert first.from_json(first.to_json()) == first


def test_request_detaches_arguments_and_guards_the_exact_projection() -> None:
    schema, profile, selection, snapshot = _fixture()
    arguments = {"value": "new"}
    request = ActionRequest(
        deployment_id=profile.deployment_id,
        deployment_profile_digest=profile.profile_digest,
        schema_identity=SchemaIdentity.from_schema(schema),
        action_id="project.set_review_note",
        request_id="request-detached",
        target_object_id=PROJECT_ID,
        arguments=arguments,
        projection_guard=ProjectionGuard.from_state(snapshot.state),
        actor_context_ref="user:123",
        valid_from=50,
        recorded_at=60,
    )
    arguments["value"] = "changed"

    assert request.arguments == {"value": "new"}
    assert ActionRequest.from_json(request.to_json()) == request

    stale = ActionRequest(
        deployment_id=request.deployment_id,
        deployment_profile_digest=request.deployment_profile_digest,
        schema_identity=request.schema_identity,
        action_id=request.action_id,
        request_id=request.request_id,
        target_object_id=request.target_object_id,
        arguments=request.arguments,
        projection_guard=replace(
            request.projection_guard,
            projection_version=request.projection_guard.projection_version + 1,
        ),
        actor_context_ref=request.actor_context_ref,
        valid_from=request.valid_from,
        recorded_at=request.recorded_at,
    )
    with pytest.raises(ActionPlanningError) as captured:
        plan_action(
            stale,
            schema=schema,
            projection=snapshot,
            fact_selection=selection,
            deployment_profile=profile,
        )
    assert captured.value.code == "projection_guard_mismatch"


@pytest.mark.parametrize(
    ("action_id", "value", "expected_code"),
    [
        ("project.set_budget", 100.0, "source_backed_action_unsupported"),
        ("project.set_risk_score", 1.0, "derived_property_not_writable"),
        ("project.set_review_note", 123, "action_argument_type_mismatch"),
        ("project.set_review_note", "old", "action_has_no_effect"),
    ],
)
def test_planner_rejects_unimplemented_authorities_and_invalid_values(
    action_id: str,
    value: object,
    expected_code: str,
) -> None:
    schema, profile, selection, snapshot = _fixture()

    with pytest.raises(ActionPlanningError) as captured:
        plan_action(
            _request(schema, profile, snapshot, action_id=action_id, value=value),
            schema=schema,
            projection=snapshot,
            fact_selection=selection,
            deployment_profile=profile,
        )

    assert captured.value.code == expected_code


def test_planner_rejects_a_fact_selection_outside_the_projection_cut() -> None:
    schema, profile, selection, snapshot = _fixture()
    mismatched_selection = replace(selection, fact_watermark=selection.fact_watermark + 1)

    with pytest.raises(ActionPlanningError) as captured:
        plan_action(
            _request(schema, profile, snapshot),
            schema=schema,
            projection=snapshot,
            fact_selection=mismatched_selection,
            deployment_profile=profile,
        )

    assert captured.value.code == "fact_selection_cut_mismatch"
