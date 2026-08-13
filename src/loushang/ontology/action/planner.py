"""Pure first-slice Action planning for ontology-owned property state."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import cast
from uuid import UUID, uuid5

from loushang.foundation.json import dump_json_value, require_json_value
from loushang.ontology.action.model import (
    ActionPlan,
    ActionRequest,
    OntologyFactEffect,
    ProjectionGuard,
)
from loushang.ontology.deployment import (
    DeploymentProfile,
    lock_schema_artifact,
)
from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    FactSelection,
    PropertyAssertion,
)
from loushang.ontology.projection import (
    FactOrigin,
    ProjectionSnapshot,
)
from loushang.ontology.schema import (
    CompiledObjectTypeDefinition,
    CompiledOntologySchema,
    CompiledPropertyDefinition,
    SchemaIdentity,
    StateAuthority,
    ValueType,
)

_ACTION_FACT_NAMESPACE = UUID("69cce6ca-4ed9-5d77-8553-4f568fce2ccb")
_ACTION_METHODOLOGY_REF = "loushang.ontology.action/set-property-v1"


class ActionPlanningError(ValueError):
    """Stable semantic failure emitted before authorization or execution."""

    def __init__(self, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        self.code = code
        super().__init__(message)


def plan_action(
    request: ActionRequest,
    *,
    schema: CompiledOntologySchema,
    projection: ProjectionSnapshot,
    fact_selection: FactSelection,
    deployment_profile: DeploymentProfile,
) -> ActionPlan:
    """Compile one guarded ontology-owned SetProperty request without I/O."""

    _require_inputs(request, schema, projection, fact_selection, deployment_profile)
    action = schema.action_by_id(request.action_id)
    if action is None:
        _fail("unknown_action", f"Action '{request.action_id}' is not published")

    target = projection.get(request.target_object_id)
    if target is None:
        _fail("unknown_action_target", "Action target is absent from the Projection")
    target_type = schema.object_type(target.object_type)
    if (
        target_type is None
        or target_type.semantic_id != action.target_object_type_id
    ):
        _fail(
            "action_target_type_mismatch",
            "Action target does not have the published object type",
        )

    expected_arguments = {item.name for item in action.parameters}
    arguments = request.arguments
    if set(arguments) != expected_arguments:
        _fail(
            "action_argument_set_mismatch",
            "Action arguments do not match the published parameter set",
        )
    parameter = action.parameter(action.effect.value_parameter)
    assert parameter is not None  # compiler invariant
    value = _validate_action_value(arguments[parameter.name], parameter.value_type)

    property_definition = _resolved_property_by_id(
        schema,
        target_type,
        action.effect.property_id,
    )
    assert property_definition is not None  # compiler invariant
    authority = property_definition.state_authority
    assert authority is not None
    if authority is StateAuthority.SOURCE_BACKED:
        _fail(
            "source_backed_action_unsupported",
            "source-backed Action planning is not implemented in Phase 2",
        )
    if authority is StateAuthority.DERIVED:
        _fail(
            "derived_property_not_writable",
            "derived properties must be recomputed and cannot be edited",
        )

    current_property = target.property(property_definition.name)
    if current_property is not None and _same_json(current_property.raw_value, value):
        _fail("action_has_no_effect", "SetProperty would not change the selected value")

    predecessor = None
    if current_property is not None and isinstance(current_property.origin, FactOrigin):
        predecessor = next(
            (
                item.fact
                for item in fact_selection.facts
                if item.fact.fact_id == current_property.origin.fact_id
            ),
            None,
        )
        if predecessor is None:
            _fail(
                "action_predecessor_fact_missing",
                "Projection FactOrigin is absent from the supplied FactSelection",
            )
    if predecessor is not None and request.recorded_at < predecessor.recorded_at:
        _fail(
            "action_recorded_at_precedes_predecessor",
            "Action recorded_at cannot precede the selected predecessor Fact",
        )

    source_ref = (
        predecessor.source_ref
        if predecessor is not None
        else f"ontology-owned:{property_definition.semantic_id}"
    )
    source_record_ref = (
        predecessor.source_record_ref
        if predecessor is not None
        else f"{request.target_object_id}:{property_definition.semantic_id}"
    )
    request_digest = request.request_digest
    fact = FactRecord(
        fact_id=uuid5(_ACTION_FACT_NAMESPACE, f"{request_digest}:effect:0"),
        subject_id=request.target_object_id,
        schema_identity=request.schema_identity,
        assertion=PropertyAssertion(action.effect.property_id, value),
        assertion_kind=AssertionKind.ASSERTED,
        source_ref=source_ref,
        source_record_ref=source_record_ref,
        evidence_refs=(f"action-request:{request_digest}",),
        methodology_ref=_ACTION_METHODOLOGY_REF,
        author_ref=request.actor_context_ref,
        valid_from=request.valid_from,
        recorded_at=request.recorded_at,
        supersedes=None if predecessor is None else predecessor.fact_id,
    )
    batch = FactBatch(
        batch_id=(
            f"action:{request.deployment_id}:{request.action_id}:{request.request_id}"
        ),
        facts=(fact,),
    )
    return ActionPlan(
        schema_identity=request.schema_identity,
        action_id=request.action_id,
        request_id=request.request_id,
        request_digest=request_digest,
        target_object_id=request.target_object_id,
        policy_requirement_ref=action.policy_requirement_ref,
        effect=OntologyFactEffect(
            fact_batch=batch,
            expected_fact_watermark=fact_selection.fact_watermark,
        ),
    )


def _require_inputs(
    request: ActionRequest,
    schema: CompiledOntologySchema,
    projection: ProjectionSnapshot,
    fact_selection: FactSelection,
    deployment_profile: DeploymentProfile,
) -> None:
    if not isinstance(request, ActionRequest):
        raise TypeError("request must be an ActionRequest")
    if not isinstance(schema, CompiledOntologySchema):
        raise TypeError("schema must be a CompiledOntologySchema")
    if not isinstance(projection, ProjectionSnapshot):
        raise TypeError("projection must be a ProjectionSnapshot")
    if not isinstance(fact_selection, FactSelection):
        raise TypeError("fact_selection must be a FactSelection")
    if not isinstance(deployment_profile, DeploymentProfile):
        raise TypeError("deployment_profile must be a DeploymentProfile")

    schema_identity = SchemaIdentity.from_schema(schema)
    if request.schema_identity != schema_identity:
        _fail("action_schema_identity_mismatch", "ActionRequest targets another Schema")
    if projection.schema != schema:
        _fail("action_projection_schema_mismatch", "Projection contains another Schema")
    if request.projection_guard != ProjectionGuard.from_state(projection.state):
        _fail(
            "projection_guard_mismatch",
            "ActionRequest was not chosen against this exact Projection",
        )
    if request.deployment_id != deployment_profile.deployment_id:
        _fail("action_deployment_mismatch", "ActionRequest targets another deployment")
    if request.deployment_profile_digest != deployment_profile.profile_digest:
        _fail(
            "action_deployment_profile_mismatch",
            "ActionRequest targets another Deployment Profile content",
        )
    if deployment_profile.schema_lock != lock_schema_artifact(schema):
        _fail(
            "action_deployment_schema_mismatch",
            "Deployment Profile does not lock the supplied Schema",
        )

    cut = projection.state.materialization_cut
    selection_fact_ids = tuple(item.fact.fact_id for item in fact_selection.facts)
    if (
        fact_selection.fact_watermark != cut.fact_watermark
        or fact_selection.valid_at != cut.valid_at
        or fact_selection.recorded_at != cut.recorded_at
        or selection_fact_ids != projection.fact_ids
    ):
        _fail(
            "fact_selection_cut_mismatch",
            "FactSelection does not reproduce the Projection materialization cut",
        )
    if request.recorded_at < cut.recorded_at:
        _fail(
            "action_recorded_at_precedes_projection",
            "Action recorded_at cannot precede the guarded Projection cut",
        )


def _resolved_property_by_id(
    schema: CompiledOntologySchema,
    object_type: CompiledObjectTypeDefinition,
    property_id: str,
) -> CompiledPropertyDefinition | None:
    direct = object_type.property_by_id(property_id)
    if direct is not None:
        return direct
    for parent_name in object_type.parent_types:
        parent = schema.object_type(parent_name)
        if parent is None:
            continue
        inherited = _resolved_property_by_id(schema, parent, property_id)
        if inherited is not None:
            return inherited
    return None


def _validate_action_value(value: object, value_type: ValueType):
    valid = True
    if value_type is ValueType.STRING:
        valid = isinstance(value, str)
    elif value_type is ValueType.INTEGER:
        valid = type(value) is int
    elif value_type is ValueType.NUMBER:
        valid = type(value) in (int, float) and math.isfinite(
            float(cast(int | float, value))
        )
    elif value_type is ValueType.BOOLEAN:
        valid = type(value) is bool
    elif value_type is ValueType.DATETIME:
        valid = isinstance(value, str)
        if valid:
            try:
                datetime.fromisoformat(cast(str, value))
            except ValueError:
                valid = False
    if not valid:
        _fail(
            "action_argument_type_mismatch",
            f"Action value is not a valid {value_type.value}",
        )
    checked = require_json_value(value, name="action argument")
    return json.loads(dump_json_value(checked, name="action argument", sort_keys=True))


def _same_json(left: object, right: object) -> bool:
    return dump_json_value(left, sort_keys=True) == dump_json_value(right, sort_keys=True)


def _fail(code: str, message: str):
    raise ActionPlanningError(code, message)


__all__ = ["ActionPlanningError", "plan_action"]
