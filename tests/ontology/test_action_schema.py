from __future__ import annotations

import json

import pytest

from loushang.ontology.package import build_ontology_package_artifact
from loushang.ontology.schema import (
    ActionDefinition,
    ActionParameterDefinition,
    ChangeImpact,
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaCompilationError,
    SetPropertyEffectDefinition,
    StateAuthority,
    ValueType,
    compare_schemas,
)


def _draft(
    *,
    version: str = "1.0.0",
    action_name: str = "set_review_note",
    action_id: str = "project.set_review_note",
    property_id: str = "project.review_note",
    parameter_type: ValueType | object = ValueType.STRING,
    policy_requirement_ref: str = "policy.project.edit-review-note",
    include_action: bool = True,
) -> OntologyPackageDraft:
    return OntologyPackageDraft(
        package_id="test.action-schema",
        namespace="urn:test:action-schema",
        version=version,
        object_types=[
            ObjectTypeDefinition(
                "Project",
                semantic_id="project",
                state_authority=StateAuthority.SOURCE_BACKED,
                properties=[
                    PropertyDefinition(
                        "review_note",
                        ValueType.STRING,
                        semantic_id="project.review_note",
                        state_authority=StateAuthority.ONTOLOGY_OWNED,
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
        actions=(
            [
                ActionDefinition(
                    action_name,
                    semantic_id=action_id,
                    target_object_type_id="project",
                    parameters=[
                        ActionParameterDefinition("value", parameter_type)
                    ],
                    effect=SetPropertyEffectDefinition(
                        property_id=property_id,
                        value_parameter="value",
                    ),
                    policy_requirement_ref=policy_requirement_ref,
                    description="Set the internal review note.",
                )
            ]
            if include_action
            else []
        ),
    )


def test_action_definition_compiles_round_trips_and_is_package_content() -> None:
    compiler = OntologyCompiler()
    compiled = compiler.compile(_draft())
    loaded = compiler.load_json(compiled.to_json())

    action = loaded.action_by_id("project.set_review_note")
    assert compiled.format == "loushang.ontology.schema/v4"
    assert action is not None
    assert action.name == "set_review_note"
    assert action.target_object_type_id == "project"
    assert action.parameters[0].value_type is ValueType.STRING
    assert action.effect.property_id == "project.review_note"
    assert action.effect.value_parameter == "value"
    assert loaded.action("set_review_note") == action

    without_action = compiler.compile(_draft(include_action=False))
    assert (
        build_ontology_package_artifact(compiled).artifact_digest
        != build_ontology_package_artifact(without_action).artifact_digest
    )


def test_schema_v3_documents_are_not_loaded_as_v4() -> None:
    compiler = OntologyCompiler()
    payload = json.loads(compiler.compile(_draft()).to_json())
    payload["format"] = "loushang.ontology.schema/v3"

    with pytest.raises(SchemaCompilationError, match="schema/v4"):
        compiler.load_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("action", "expected_code"),
    [
        (
            ActionDefinition(
                "missing_target",
                semantic_id="action.missing-target",
                target_object_type_id="missing",
                parameters=[ActionParameterDefinition("value", ValueType.STRING)],
                effect=SetPropertyEffectDefinition("project.review_note", "value"),
                policy_requirement_ref="policy.edit",
            ),
            "unknown_action_target_type",
        ),
        (
            ActionDefinition(
                "missing_property",
                semantic_id="action.missing-property",
                target_object_type_id="project",
                parameters=[ActionParameterDefinition("value", ValueType.STRING)],
                effect=SetPropertyEffectDefinition("project.missing", "value"),
                policy_requirement_ref="policy.edit",
            ),
            "unknown_action_property",
        ),
        (
            ActionDefinition(
                "wrong_type",
                semantic_id="action.wrong-type",
                target_object_type_id="project",
                parameters=[ActionParameterDefinition("value", ValueType.INTEGER)],
                effect=SetPropertyEffectDefinition("project.review_note", "value"),
                policy_requirement_ref="policy.edit",
            ),
            "action_parameter_type_mismatch",
        ),
        (
            ActionDefinition(
                "unused_parameter",
                semantic_id="action.unused-parameter",
                target_object_type_id="project",
                parameters=[
                    ActionParameterDefinition("value", ValueType.STRING),
                    ActionParameterDefinition("reason", ValueType.STRING),
                ],
                effect=SetPropertyEffectDefinition("project.review_note", "value"),
                policy_requirement_ref="policy.edit",
            ),
            "unsupported_action_parameter_shape",
        ),
    ],
)
def test_action_compilation_rejects_invalid_contracts(
    action: ActionDefinition,
    expected_code: str,
) -> None:
    draft = _draft(include_action=False)
    draft = OntologyPackageDraft(
        package_id=draft.package_id,
        namespace=draft.namespace,
        version=draft.version,
        object_types=draft.object_types,
        actions=[action],
    )

    diagnostics = OntologyCompiler().validate(draft)

    assert expected_code in {item.code for item in diagnostics}


def test_action_semantic_ids_share_the_package_local_identity_space() -> None:
    draft = _draft(action_id="project.review_note")

    diagnostics = OntologyCompiler().validate(draft)

    assert [item.code for item in diagnostics] == ["duplicate_semantic_id"]


def test_action_schema_diff_tracks_identity_and_contract_changes() -> None:
    compiler = OntologyCompiler()
    without_action = compiler.compile(_draft(include_action=False))
    original = compiler.compile(_draft())
    changed = compiler.compile(
        _draft(
            version="2.0.0",
            action_name="revise_review_note",
            policy_requirement_ref="policy.project.approve-review-note",
        )
    )

    assert [item.code for item in compare_schemas(without_action, original).changes] == [
        "action_added"
    ]
    assert [item.code for item in compare_schemas(original, without_action).changes] == [
        "action_removed"
    ]
    changes = compare_schemas(original, changed).changes
    assert [(item.code, item.impact) for item in changes] == [
        ("action_contract_changed", ChangeImpact.BREAKING),
        ("action_name_changed", ChangeImpact.BREAKING),
    ]
