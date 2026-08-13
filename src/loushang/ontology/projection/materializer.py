"""Pure bitemporal Fact-to-snapshot materialization."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from loushang.foundation.json import JSONValue, dump_json_value
from loushang.ontology.facts.model import (
    LinkAssertion,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.facts.ports import FactSelection, StoredFact
from loushang.ontology.projection.model import (
    FactOrigin,
    MaterializationCut,
    ProjectedLink,
    ProjectedObject,
    ProjectedProperty,
    ProjectionSnapshot,
    ProjectionState,
    SchemaDefaultOrigin,
    SourceOrigin,
)
from loushang.ontology.projection.revalidation_model import (
    FactSchemaRevalidationReceipt,
)
from loushang.ontology.schema import (
    CompiledObjectTypeDefinition,
    CompiledOntologySchema,
    CompiledPropertyDefinition,
    LinkCardinality,
    SchemaIdentity,
    StateAuthority,
    ValueType,
)
from loushang.ontology.source import (
    MappedSourceInput,
    SourceBinding,
    SourceCoverage,
    SourceInputCut,
)


@dataclass(frozen=True, slots=True)
class ProjectionDiagnostic:
    """Stable reason why selected facts cannot form a serving snapshot."""

    code: str
    path: str
    message: str


class ProjectionMaterializationError(ValueError):
    """Raised with every deterministic materialization diagnostic."""

    def __init__(self, diagnostics: tuple[ProjectionDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError(
                "ProjectionMaterializationError requires at least one diagnostic"
            )
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


@dataclass(frozen=True, slots=True)
class _MappedPropertyCandidate:
    path: str
    object_id: UUID
    object_type: str
    property_name: str
    definition: CompiledPropertyDefinition
    value: JSONValue
    valid_from: float
    source_ref: str
    origin: SourceOrigin


def materialize_projection(
    selection: FactSelection,
    schema: CompiledOntologySchema,
    *,
    source_bindings: Iterable[SourceBinding] = (),
    source_inputs: Iterable[MappedSourceInput] = (),
    fact_revalidation: FactSchemaRevalidationReceipt | None = None,
    projection_version: int = 1,
    built_at: float | None = None,
) -> ProjectionSnapshot:
    """Build an immutable graph from detached source and Fact selections."""

    if not isinstance(selection, FactSelection):
        raise TypeError("materialize_projection requires a FactSelection")
    if type(projection_version) is not int or projection_version < 1:
        raise ValueError("projection_version must be a positive integer")
    selected = selection.facts
    valid_at = selection.valid_at
    recorded_at = selection.recorded_at
    built_at = recorded_at if built_at is None else _finite("built_at", built_at)
    diagnostics: list[ProjectionDiagnostic] = []
    schema_identity = SchemaIdentity.from_schema(schema)
    accepted_fact_schema = schema_identity
    fact_revalidation_digest: str | None = None
    if fact_revalidation is not None:
        if not isinstance(fact_revalidation, FactSchemaRevalidationReceipt):
            raise TypeError(
                "fact_revalidation must be a FactSchemaRevalidationReceipt or None"
            )
        try:
            fact_revalidation.validate_for(selection, schema)
        except ValueError as exc:
            raise ProjectionMaterializationError(
                (
                    ProjectionDiagnostic(
                        "fact_revalidation_invalid",
                        "$.fact_revalidation",
                        str(exc),
                    ),
                )
            ) from exc
        accepted_fact_schema = fact_revalidation.source_schema
        fact_revalidation_digest = fact_revalidation.receipt_digest
    binding_values = tuple(source_bindings)
    input_values = tuple(source_inputs)
    if any(not isinstance(item, SourceBinding) for item in binding_values):
        raise TypeError("source_bindings must contain SourceBinding values")
    if any(not isinstance(item, MappedSourceInput) for item in input_values):
        raise TypeError("source_inputs must contain MappedSourceInput values")
    (
        source_types,
        source_object_origins,
        source_property_candidates,
        source_links,
        source_cuts,
    ) = _resolve_source_inputs(
        binding_values,
        input_values,
        schema,
        schema_identity=schema_identity,
        valid_at=valid_at,
        diagnostics=diagnostics,
    )
    object_type_facts: dict[UUID, dict[str, list[StoredFact]]] = {}
    property_facts: dict[tuple[UUID, str], list[StoredFact]] = {}
    link_facts: dict[tuple[UUID, str, UUID], list[StoredFact]] = {}

    for item in selected:
        if item.fact.schema_identity != accepted_fact_schema:
            diagnostics.append(
                ProjectionDiagnostic(
                    "fact_schema_identity_mismatch",
                    f"facts.{item.fact.fact_id}.schema_identity",
                    f"Fact {item.fact.fact_id} targets {item.fact.schema_identity}, "
                    f"not accepted Fact schema {accepted_fact_schema}",
                )
            )
            continue
        assertion = item.fact.assertion
        if isinstance(assertion, ObjectAssertion):
            object_type_facts.setdefault(item.fact.subject_id, {}).setdefault(
                assertion.object_type_id,
                [],
            ).append(item)
        elif isinstance(assertion, PropertyAssertion):
            property_facts.setdefault(
                (item.fact.subject_id, assertion.property_id),
                [],
            ).append(item)
        elif isinstance(assertion, LinkAssertion):
            link_facts.setdefault(
                (item.fact.subject_id, assertion.link_type_id, assertion.target_id),
                [],
            ).append(item)

    resolved_types, resolved_object_origins = _resolve_object_types(
        object_type_facts,
        schema,
        diagnostics,
        initial_types=source_types,
        initial_origins=source_object_origins,
    )
    source_properties = _resolve_source_properties(
        source_property_candidates,
        resolved_types,
        diagnostics,
    )
    resolved_properties = _resolve_property_facts(
        property_facts,
        resolved_types,
        schema,
        diagnostics,
        initial=source_properties,
    )
    _apply_defaults_and_required_properties(
        resolved_types,
        resolved_properties,
        schema,
        valid_at=valid_at,
        diagnostics=diagnostics,
    )
    _validate_unique_properties(
        resolved_types,
        resolved_properties,
        schema,
        diagnostics,
    )
    resolved_links = _resolve_link_facts(
        link_facts,
        resolved_types,
        schema,
        diagnostics,
        initial=source_links,
    )
    _validate_link_integrity(
        resolved_types,
        resolved_links,
        schema,
        diagnostics,
    )
    if diagnostics:
        raise ProjectionMaterializationError(_sorted_diagnostics(diagnostics))

    objects = [
        ProjectedObject(
            object_id=object_id,
            object_type=object_type,
            origin=resolved_object_origins[object_id],
            properties=resolved_properties.get(object_id, {}).values(),
        )
        for object_id, object_type in resolved_types.items()
    ]
    cut = MaterializationCut(
        schema_identity=schema_identity,
        source_inputs=source_cuts,
        fact_watermark=selection.fact_watermark,
        valid_at=valid_at,
        recorded_at=recorded_at,
        fact_revalidation_digest=fact_revalidation_digest,
    )
    state = ProjectionState(
        schema_identity=schema_identity,
        projection_version=projection_version,
        materialization_cut=cut,
        built_at=built_at,
    )
    return ProjectionSnapshot(
        schema=schema,
        state=state,
        objects=objects,
        links=resolved_links,
        fact_ids=(item.fact.fact_id for item in selected),
    )


def _resolve_source_inputs(
    bindings: tuple[SourceBinding, ...],
    inputs: tuple[MappedSourceInput, ...],
    schema: CompiledOntologySchema,
    *,
    schema_identity: SchemaIdentity,
    valid_at: float,
    diagnostics: list[ProjectionDiagnostic],
) -> tuple[
    dict[UUID, str],
    dict[UUID, SourceOrigin],
    tuple[_MappedPropertyCandidate, ...],
    list[ProjectedLink],
    tuple[SourceInputCut, ...],
]:
    binding_by_id: dict[str, SourceBinding] = {}
    object_target_owner: dict[str, str] = {}
    property_target_owner: dict[str, str] = {}
    link_target_owner: dict[str, str] = {}
    for binding in sorted(bindings, key=lambda item: item.binding_id):
        path = f"source_bindings.{binding.binding_id}"
        if binding.binding_id in binding_by_id:
            diagnostics.append(
                ProjectionDiagnostic(
                    "duplicate_source_binding",
                    path,
                    f"source binding '{binding.binding_id}' is declared more than once",
                )
            )
            continue
        binding_by_id[binding.binding_id] = binding
        if binding.schema_identity != schema_identity:
            diagnostics.append(
                ProjectionDiagnostic(
                    "source_binding_schema_identity_mismatch",
                    f"{path}.schema_identity",
                    f"source binding '{binding.binding_id}' targets "
                    f"{binding.schema_identity}, not selected schema "
                    f"{schema_identity}",
                )
            )
            continue
        for semantic_id in binding.object_existence_ids:
            _register_source_authority_target(
                semantic_id,
                binding.binding_id,
                target_kind="object existence",
                owners=object_target_owner,
                diagnostics=diagnostics,
            )
            object_declaration = schema.object_type_by_id(semantic_id)
            if object_declaration is None:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unknown_source_authority_target",
                        f"{path}.object_existence_ids.{semantic_id}",
                        f"object semantic ID '{semantic_id}' is not declared",
                    )
                )
            elif object_declaration.state_authority is not StateAuthority.SOURCE_BACKED:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "source_authority_mismatch",
                        f"{path}.object_existence_ids.{semantic_id}",
                        f"object existence '{semantic_id}' is "
                        f"{object_declaration.state_authority.value}, "
                        "not source-backed",
                    )
                )
        for semantic_id in binding.property_ids:
            _register_source_authority_target(
                semantic_id,
                binding.binding_id,
                target_kind="property",
                owners=property_target_owner,
                diagnostics=diagnostics,
            )
            declaration = _property_by_semantic_id(schema, semantic_id)
            if declaration is None:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unknown_source_authority_target",
                        f"{path}.property_ids.{semantic_id}",
                        f"property semantic ID '{semantic_id}' is not declared",
                    )
                )
            elif declaration.state_authority is not StateAuthority.SOURCE_BACKED:
                authority = declaration.state_authority
                diagnostics.append(
                    ProjectionDiagnostic(
                        "source_authority_mismatch",
                        f"{path}.property_ids.{semantic_id}",
                        f"property '{semantic_id}' is "
                        f"{_authority_label(authority)}, not source-backed",
                    )
                )
        for semantic_id in binding.link_type_ids:
            _register_source_authority_target(
                semantic_id,
                binding.binding_id,
                target_kind="link family",
                owners=link_target_owner,
                diagnostics=diagnostics,
            )
            link_declaration = schema.link_type_by_id(semantic_id)
            if link_declaration is None:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unknown_source_authority_target",
                        f"{path}.link_type_ids.{semantic_id}",
                        f"link semantic ID '{semantic_id}' is not declared",
                    )
                )
            elif link_declaration.state_authority is not StateAuthority.SOURCE_BACKED:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "source_authority_mismatch",
                        f"{path}.link_type_ids.{semantic_id}",
                        f"link family '{semantic_id}' is "
                        f"{link_declaration.state_authority.value}, not source-backed",
                    )
                )

    input_by_binding: dict[str, MappedSourceInput] = {}
    for source_input in sorted(
        inputs,
        key=lambda item: (
            item.binding_id,
            item.mapping_version,
            item.source_revision,
        ),
    ):
        path = f"source_inputs.{source_input.binding_id}"
        if source_input.binding_id in input_by_binding:
            diagnostics.append(
                ProjectionDiagnostic(
                    "source_input_conflict",
                    path,
                    f"multiple source inputs were selected for binding "
                    f"'{source_input.binding_id}'",
                )
            )
            continue
        input_by_binding[source_input.binding_id] = source_input
        matched_binding = binding_by_id.get(source_input.binding_id)
        if matched_binding is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "unknown_source_binding",
                    path,
                    f"source input references unknown binding "
                    f"'{source_input.binding_id}'",
                )
            )
        elif matched_binding.mapping_version != source_input.mapping_version:
            diagnostics.append(
                ProjectionDiagnostic(
                    "source_mapping_version_mismatch",
                    path,
                    f"source input mapping version '{source_input.mapping_version}' "
                    f"does not match binding version "
                    f"'{matched_binding.mapping_version}'",
                )
            )
        elif matched_binding.coverage is not source_input.coverage:
            diagnostics.append(
                ProjectionDiagnostic(
                    "source_coverage_mismatch",
                    f"{path}.coverage",
                    f"source input coverage '{source_input.coverage.value}' "
                    f"does not match binding coverage "
                    f"'{matched_binding.coverage.value}'",
                )
            )
        elif source_input.coverage is not SourceCoverage.COMPLETE:
            diagnostics.append(
                ProjectionDiagnostic(
                    "source_coverage_unsupported",
                    f"{path}.coverage",
                    f"whole-snapshot materialization requires complete coverage; "
                    f"binding '{source_input.binding_id}' supplied "
                    f"{source_input.coverage.value}",
                )
            )

    for binding_id in sorted(binding_by_id.keys() - input_by_binding.keys()):
        diagnostics.append(
            ProjectionDiagnostic(
                "source_input_missing",
                f"source_inputs.{binding_id}",
                f"no mapped snapshot was selected for binding '{binding_id}'",
            )
        )

    resolved_types: dict[UUID, str] = {}
    resolved_object_origins: dict[UUID, SourceOrigin] = {}
    property_candidates: list[_MappedPropertyCandidate] = []
    resolved_links: list[ProjectedLink] = []
    resolved_link_keys: set[tuple[UUID, str, UUID]] = set()
    cuts: list[SourceInputCut] = []
    for binding_id, source_input in sorted(input_by_binding.items()):
        matched_binding = binding_by_id.get(binding_id)
        if (
            matched_binding is None
            or matched_binding.mapping_version != source_input.mapping_version
            or matched_binding.schema_identity != schema_identity
            or matched_binding.coverage is not source_input.coverage
            or source_input.coverage is not SourceCoverage.COMPLETE
        ):
            continue
        cuts.append(source_input.cut)
        for mapped_object in source_input.payload.objects:
            object_path = (
                f"source_inputs.{binding_id}.objects.{mapped_object.object_id}"
            )
            object_definition = schema.object_type_by_id(mapped_object.object_type_id)
            if object_definition is None:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unknown_mapped_object_type",
                        f"{object_path}.object_type_id",
                        f"object semantic ID '{mapped_object.object_type_id}' is not declared",
                    )
                )
                continue
            owns_existence = (
                mapped_object.object_type_id in matched_binding.object_existence_ids
            )
            owns_mapped_property = any(
                prop.property_id in matched_binding.property_ids
                for prop in mapped_object.properties
            )
            if not owns_existence and not owns_mapped_property:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unbound_mapped_object_existence",
                        f"{object_path}.object_type_id",
                        f"binding '{binding_id}' does not own object existence "
                        f"'{mapped_object.object_type_id}'",
                    )
                )
                continue
            if object_definition.abstract:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "abstract_object_type",
                        f"{object_path}.object_type_id",
                        f"abstract object type '{object_definition.name}' cannot be materialized",
                    )
                )
                continue
            if owns_existence:
                existing_type = resolved_types.get(mapped_object.object_id)
                if existing_type is not None:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "source_object_conflict",
                            f"{object_path}.object_type_id",
                            f"multiple source records produce object "
                            f"{mapped_object.object_id}",
                        )
                    )
                else:
                    resolved_types[mapped_object.object_id] = object_definition.name
                    resolved_object_origins[mapped_object.object_id] = SourceOrigin(
                        binding_id=binding_id,
                        mapping_version=source_input.mapping_version,
                        source_revision=source_input.source_revision,
                        source_record_ref=mapped_object.source_record_ref,
                        field_ref=mapped_object.identity_field_ref,
                    )
            declarations = {
                definition.semantic_id: (name, definition)
                for name, (_, definition) in _resolved_properties(
                    schema,
                    object_definition.name,
                ).items()
            }
            for mapped_property in mapped_object.properties:
                property_path = (
                    f"{object_path}.properties.{mapped_property.property_id}"
                )
                mapped_declaration = declarations.get(mapped_property.property_id)
                if mapped_declaration is None:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "unknown_mapped_property",
                            property_path,
                            f"property semantic ID '{mapped_property.property_id}' "
                            f"is not declared for '{object_definition.name}'",
                        )
                    )
                    continue
                property_name, mapped_property_definition = mapped_declaration
                if mapped_property.property_id not in matched_binding.property_ids:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "unbound_mapped_property",
                            property_path,
                            f"binding '{binding_id}' does not own property "
                            f"'{mapped_property.property_id}'",
                        )
                    )
                    continue
                try:
                    _validate_property_value(
                        mapped_property_definition,
                        mapped_property.raw_value,
                    )
                except ValueError as exc:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "mapped_property_value_invalid",
                            property_path,
                            str(exc),
                        )
                    )
                    continue
                if mapped_property.valid_from > valid_at:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "source_value_not_yet_valid",
                            property_path,
                            f"mapped property '{mapped_property.property_id}' is valid "
                            f"from {mapped_property.valid_from}, after selected "
                            f"valid_at {valid_at}",
                        )
                    )
                    continue
                property_candidates.append(
                    _MappedPropertyCandidate(
                        path=property_path,
                        object_id=mapped_object.object_id,
                        object_type=object_definition.name,
                        property_name=property_name,
                        definition=mapped_property_definition,
                        value=mapped_property.raw_value,
                        valid_from=mapped_property.valid_from,
                        source_ref=f"source.binding:{binding_id}",
                        origin=SourceOrigin(
                            binding_id=binding_id,
                            mapping_version=source_input.mapping_version,
                            source_revision=source_input.source_revision,
                            source_record_ref=mapped_object.source_record_ref,
                            field_ref=mapped_property.field_ref,
                        ),
                    )
                )
        for mapped_link in source_input.payload.links:
            link_path = (
                f"source_inputs.{binding_id}.links.{mapped_link.source_id}."
                f"{mapped_link.link_type_id}.{mapped_link.target_id}"
            )
            link_definition = schema.link_type_by_id(mapped_link.link_type_id)
            if link_definition is None:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unknown_mapped_link_type",
                        link_path,
                        f"link semantic ID '{mapped_link.link_type_id}' is not declared",
                    )
                )
                continue
            if mapped_link.link_type_id not in matched_binding.link_type_ids:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "unbound_mapped_link",
                        link_path,
                        f"binding '{binding_id}' does not own link family "
                        f"'{mapped_link.link_type_id}'",
                    )
                )
                continue
            if mapped_link.valid_from > valid_at:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "source_value_not_yet_valid",
                        link_path,
                        f"mapped link '{mapped_link.link_type_id}' is valid from "
                        f"{mapped_link.valid_from}, after selected valid_at {valid_at}",
                    )
                )
                continue
            link_key = (
                mapped_link.source_id,
                link_definition.name,
                mapped_link.target_id,
            )
            if link_key in resolved_link_keys:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "source_link_conflict",
                        link_path,
                        f"multiple source records produce link "
                        f"{mapped_link.source_id}.{link_definition.name}."
                        f"{mapped_link.target_id}",
                    )
                )
                continue
            resolved_link_keys.add(link_key)
            resolved_links.append(
                ProjectedLink(
                    source_id=mapped_link.source_id,
                    link_type=link_definition.name,
                    target_id=mapped_link.target_id,
                    properties=mapped_link.properties,
                    valid_from=mapped_link.valid_from,
                    source_ref=f"source.binding:{binding_id}",
                    origin=SourceOrigin(
                        binding_id=binding_id,
                        mapping_version=source_input.mapping_version,
                        source_revision=source_input.source_revision,
                        source_record_ref=mapped_link.source_record_ref,
                        field_ref=mapped_link.field_ref,
                    ),
                )
            )
    return (
        resolved_types,
        resolved_object_origins,
        tuple(property_candidates),
        resolved_links,
        tuple(cuts),
    )


def _resolve_source_properties(
    candidates: tuple[_MappedPropertyCandidate, ...],
    resolved_types: dict[UUID, str],
    diagnostics: list[ProjectionDiagnostic],
) -> dict[UUID, dict[str, ProjectedProperty]]:
    resolved: dict[UUID, dict[str, ProjectedProperty]] = {}
    for candidate in sorted(candidates, key=lambda item: item.path):
        actual_type = resolved_types.get(candidate.object_id)
        if actual_type is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "mapped_property_subject_missing",
                    candidate.path,
                    f"mapped property '{candidate.property_name}' has no projected "
                    f"object subject {candidate.object_id}",
                )
            )
            continue
        if actual_type != candidate.object_type:
            diagnostics.append(
                ProjectionDiagnostic(
                    "mapped_property_subject_type_invalid",
                    candidate.path,
                    f"mapped property '{candidate.property_name}' expects object type "
                    f"'{candidate.object_type}', got '{actual_type}'",
                )
            )
            continue
        object_values = resolved.setdefault(candidate.object_id, {})
        if candidate.property_name in object_values:
            diagnostics.append(
                ProjectionDiagnostic(
                    "source_property_conflict",
                    candidate.path,
                    f"multiple source records produce property "
                    f"{candidate.object_id}.{candidate.property_name}",
                )
            )
            continue
        object_values[candidate.property_name] = ProjectedProperty(
            name=candidate.property_name,
            value_type=candidate.definition.value_type,
            value=candidate.value,
            valid_from=candidate.valid_from,
            source_ref=candidate.source_ref,
            origin=candidate.origin,
        )
    return resolved


def _register_source_authority_target(
    semantic_id: str,
    binding_id: str,
    *,
    target_kind: str,
    owners: dict[str, str],
    diagnostics: list[ProjectionDiagnostic],
) -> None:
    previous = owners.get(semantic_id)
    if previous is None:
        owners[semantic_id] = binding_id
    elif previous != binding_id:
        diagnostics.append(
            ProjectionDiagnostic(
                "source_authority_binding_conflict",
                f"source_bindings.{binding_id}",
                f"{target_kind} '{semantic_id}' is bound by both "
                f"'{previous}' and '{binding_id}'",
            )
        )


def _property_by_semantic_id(
    schema: CompiledOntologySchema,
    semantic_id: str,
) -> CompiledPropertyDefinition | None:
    for object_type in schema.object_types:
        for definition in object_type.properties:
            if definition.semantic_id == semantic_id:
                return definition
    return None


def _authority_label(authority: StateAuthority | None) -> str:
    return "undeclared" if authority is None else authority.value


def _resolve_object_types(
    candidates: dict[UUID, dict[str, list[StoredFact]]],
    schema: CompiledOntologySchema,
    diagnostics: list[ProjectionDiagnostic],
    *,
    initial_types: dict[UUID, str] | None = None,
    initial_origins: dict[UUID, SourceOrigin] | None = None,
) -> tuple[dict[UUID, str], dict[UUID, FactOrigin | SourceOrigin]]:
    resolved = {} if initial_types is None else dict(initial_types)
    origins: dict[UUID, FactOrigin | SourceOrigin] = (
        {} if initial_origins is None else dict(initial_origins)
    )
    for subject_id, candidate_types in sorted(
        candidates.items(),
        key=lambda item: str(item[0]),
    ):
        path = f"objects.{subject_id}.type"
        if len(candidate_types) != 1:
            diagnostics.append(
                ProjectionDiagnostic(
                    "object_type_fact_conflict",
                    path,
                    f"conflicting object type facts for {subject_id}: "
                    f"{', '.join(sorted(candidate_types))}",
                )
            )
            continue
        candidate_type_id = next(iter(candidate_types))
        definition = schema.object_type_by_id(candidate_type_id)
        if definition is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "unknown_object_type",
                    path,
                    f"object semantic ID '{candidate_type_id}' is not declared by "
                    "the schema",
                )
            )
            continue
        if definition.abstract:
            diagnostics.append(
                ProjectionDiagnostic(
                    "abstract_object_type",
                    path,
                    f"abstract object type '{definition.name}' cannot be materialized",
                )
            )
            continue
        if definition.state_authority is not StateAuthority.ONTOLOGY_OWNED:
            diagnostics.append(
                ProjectionDiagnostic(
                    "object_fact_authority_mismatch",
                    path,
                    f"object existence '{candidate_type_id}' is "
                    f"{definition.state_authority.value}, not ontology-owned",
                )
            )
            continue
        existing = resolved.get(subject_id)
        if existing is not None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "object_authority_conflict",
                    path,
                    f"object {subject_id} is supplied by both source input and Facts",
                )
            )
            continue
        resolved[subject_id] = definition.name
        selected = min(
            candidate_types[candidate_type_id],
            key=lambda item: item.sequence,
        )
        origins[subject_id] = FactOrigin(selected.fact.fact_id)
    return resolved, origins


def _resolve_property_facts(
    candidates: dict[tuple[UUID, str], list[StoredFact]],
    resolved_types: dict[UUID, str],
    schema: CompiledOntologySchema,
    diagnostics: list[ProjectionDiagnostic],
    *,
    initial: dict[UUID, dict[str, ProjectedProperty]] | None = None,
) -> dict[UUID, dict[str, ProjectedProperty]]:
    resolved = (
        {}
        if initial is None
        else {object_id: dict(values) for object_id, values in initial.items()}
    )
    for (subject_id, property_id), values in sorted(
        candidates.items(),
        key=lambda item: (str(item[0][0]), item[0][1]),
    ):
        path = f"objects.{subject_id}.properties.{property_id}"
        subject_type = resolved_types.get(subject_id)
        if subject_type is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "property_subject_missing",
                    path,
                    f"property fact '{property_id}' has no projected object subject "
                    f"{subject_id}",
                )
            )
            continue
        declarations = {
            definition.semantic_id: (name, definition)
            for name, (_, definition) in _resolved_properties(
                schema,
                subject_type,
            ).items()
        }
        declaration = declarations.get(property_id)
        if declaration is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "unknown_property",
                    path,
                    f"property semantic ID '{property_id}' is not declared for object type "
                    f"'{subject_type}'",
                )
            )
            continue
        property_name, definition = declaration
        if definition.state_authority is not StateAuthority.ONTOLOGY_OWNED:
            diagnostics.append(
                ProjectionDiagnostic(
                    "property_fact_authority_mismatch",
                    path,
                    f"property '{subject_type}.{property_name}' is "
                    f"{_authority_label(definition.state_authority)}, "
                    "not ontology-owned",
                )
            )
            continue
        by_json = {
            dump_json_value(
                cast(PropertyAssertion, item.fact.assertion).value,
                name="fact property value",
                sort_keys=True,
            ): cast(PropertyAssertion, item.fact.assertion).value
            for item in values
        }
        if len(by_json) != 1:
            diagnostics.append(
                ProjectionDiagnostic(
                    "property_fact_conflict",
                    path,
                    f"conflicting property facts for {subject_id}.{property_id}",
                )
            )
            continue
        value = next(iter(by_json.values()))
        try:
            _validate_property_value(definition, value)
        except ValueError as exc:
            diagnostics.append(
                ProjectionDiagnostic(
                    "property_fact_value_invalid",
                    path,
                    str(exc),
                )
            )
            continue
        selected = min(values, key=lambda item: item.sequence)
        resolved.setdefault(subject_id, {})[property_name] = ProjectedProperty(
            name=property_name,
            value_type=definition.value_type,
            value=value,
            valid_from=selected.fact.valid_from,
            fact_id=selected.fact.fact_id,
            author_ref=selected.fact.author_ref,
            source_ref=selected.fact.source_ref,
            origin=FactOrigin(selected.fact.fact_id),
        )
    return resolved


def _apply_defaults_and_required_properties(
    resolved_types: dict[UUID, str],
    resolved: dict[UUID, dict[str, ProjectedProperty]],
    schema: CompiledOntologySchema,
    *,
    valid_at: float,
    diagnostics: list[ProjectionDiagnostic],
) -> None:
    for object_id, object_type in sorted(
        resolved_types.items(),
        key=lambda item: str(item[0]),
    ):
        values = resolved.setdefault(object_id, {})
        for name, (_, definition) in _resolved_properties(schema, object_type).items():
            if name in values:
                continue
            if definition.state_authority is StateAuthority.DERIVED:
                if definition.default is not None or definition.required:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "derived_state_unsupported",
                            f"objects.{object_id}.properties.{name}",
                            f"derived property '{object_type}.{name}' requires a "
                            "published computation origin",
                        )
                    )
                continue
            if definition.state_authority is StateAuthority.SOURCE_BACKED:
                if definition.required:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "required_property_missing",
                            f"objects.{object_id}.properties.{name}",
                            f"required property '{object_type}.{name}' is missing",
                        )
                    )
                continue
            default = definition.default
            if default is not None:
                try:
                    _validate_property_value(definition, default)
                except ValueError as exc:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "property_default_invalid",
                            f"objects.{object_id}.properties.{name}",
                            str(exc),
                        )
                    )
                    continue
                values[name] = ProjectedProperty(
                    name=name,
                    value_type=definition.value_type,
                    value=default,
                    valid_from=valid_at,
                    source_ref="ontology.schema.default",
                    origin=SchemaDefaultOrigin(SchemaIdentity.from_schema(schema)),
                )
            elif definition.required:
                diagnostics.append(
                    ProjectionDiagnostic(
                        "required_property_missing",
                        f"objects.{object_id}.properties.{name}",
                        f"required property '{object_type}.{name}' is missing",
                    )
                )


def _validate_unique_properties(
    resolved_types: dict[UUID, str],
    resolved: dict[UUID, dict[str, ProjectedProperty]],
    schema: CompiledOntologySchema,
    diagnostics: list[ProjectionDiagnostic],
) -> None:
    seen: dict[tuple[str, str, str], UUID] = {}
    for object_id, object_type in sorted(
        resolved_types.items(),
        key=lambda item: str(item[0]),
    ):
        declarations = _resolved_properties(schema, object_type)
        for name, prop in resolved.get(object_id, {}).items():
            owner, definition = declarations[name]
            if not definition.unique:
                continue
            key = (
                owner,
                name,
                dump_json_value(prop.raw_value, sort_keys=True),
            )
            previous = seen.get(key)
            if previous is None:
                seen[key] = object_id
                continue
            diagnostics.append(
                ProjectionDiagnostic(
                    "unique_property_conflict",
                    f"objects.{object_id}.properties.{name}",
                    f"unique property '{owner}.{name}' is shared by "
                    f"{previous} and {object_id}",
                )
            )


def _resolve_link_facts(
    candidates: dict[tuple[UUID, str, UUID], list[StoredFact]],
    resolved_types: dict[UUID, str],
    schema: CompiledOntologySchema,
    diagnostics: list[ProjectionDiagnostic],
    *,
    initial: list[ProjectedLink] | None = None,
) -> list[ProjectedLink]:
    resolved = [] if initial is None else list(initial)
    for (source_id, link_type_id, target_id), values in sorted(
        candidates.items(),
        key=lambda item: (str(item[0][0]), item[0][1], str(item[0][2])),
    ):
        path = f"objects.{source_id}.links.{link_type_id}.{target_id}"
        source_type = resolved_types.get(source_id)
        target_type = resolved_types.get(target_id)
        if source_type is None or target_type is None:
            missing_role = "source" if source_type is None else "target"
            diagnostics.append(
                ProjectionDiagnostic(
                    "link_endpoint_missing",
                    path,
                    f"link fact '{link_type_id}' has no projected {missing_role} object",
                )
            )
            continue
        definition = schema.link_type_by_id(link_type_id)
        if definition is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "unknown_link_type",
                    path,
                    f"link semantic ID '{link_type_id}' is not declared by the schema",
                )
            )
            continue
        if definition.state_authority is not StateAuthority.ONTOLOGY_OWNED:
            diagnostics.append(
                ProjectionDiagnostic(
                    "link_fact_authority_mismatch",
                    path,
                    f"link family '{link_type_id}' is "
                    f"{definition.state_authority.value}, not ontology-owned",
                )
            )
            continue
        if (
            source_type != definition.source_type
            or target_type != definition.target_type
        ):
            diagnostics.append(
                ProjectionDiagnostic(
                    "link_endpoint_type_invalid",
                    path,
                    f"link '{definition.name}' requires {definition.source_type} -> "
                    f"{definition.target_type}, got {source_type} -> {target_type}",
                )
            )
            continue
        by_json = {
            dump_json_value(
                cast(LinkAssertion, item.fact.assertion).properties,
                name="fact link properties",
                sort_keys=True,
            ): cast(LinkAssertion, item.fact.assertion).properties
            for item in values
        }
        if len(by_json) != 1:
            diagnostics.append(
                ProjectionDiagnostic(
                    "link_fact_conflict",
                    path,
                    f"conflicting link facts for "
                    f"{source_id}.{link_type_id}.{target_id}",
                )
            )
            continue
        selected = min(values, key=lambda item: item.sequence)
        resolved.append(
            ProjectedLink(
                source_id=source_id,
                link_type=definition.name,
                target_id=target_id,
                properties=next(iter(by_json.values())),
                valid_from=selected.fact.valid_from,
                fact_id=selected.fact.fact_id,
                source_ref=selected.fact.source_ref,
                origin=FactOrigin(selected.fact.fact_id),
            )
        )
    return resolved


def _validate_link_integrity(
    resolved_types: dict[UUID, str],
    links: list[ProjectedLink],
    schema: CompiledOntologySchema,
    diagnostics: list[ProjectionDiagnostic],
) -> None:
    valid_links: list[ProjectedLink] = []
    for link in links:
        path = f"objects.{link.source_id}.links.{link.link_type}.{link.target_id}"
        source_type = resolved_types.get(link.source_id)
        target_type = resolved_types.get(link.target_id)
        if source_type is None or target_type is None:
            missing_role = "source" if source_type is None else "target"
            diagnostics.append(
                ProjectionDiagnostic(
                    "link_endpoint_missing",
                    path,
                    f"link '{link.link_type}' has no projected {missing_role} object",
                )
            )
            continue
        definition = schema.link_type(link.link_type)
        if definition is None:
            diagnostics.append(
                ProjectionDiagnostic(
                    "unknown_link_type",
                    path,
                    f"link type '{link.link_type}' is not declared by the schema",
                )
            )
            continue
        if (
            source_type != definition.source_type
            or target_type != definition.target_type
        ):
            diagnostics.append(
                ProjectionDiagnostic(
                    "link_endpoint_type_invalid",
                    path,
                    f"link '{link.link_type}' requires {definition.source_type} -> "
                    f"{definition.target_type}, got {source_type} -> {target_type}",
                )
            )
            continue
        valid_links.append(link)

    for definition in schema.link_types:
        matching = [link for link in valid_links if link.link_type == definition.name]
        outgoing: dict[UUID, int] = {}
        incoming: dict[UUID, int] = {}
        for link in matching:
            outgoing[link.source_id] = outgoing.get(link.source_id, 0) + 1
            incoming[link.target_id] = incoming.get(link.target_id, 0) + 1
        if definition.cardinality in {
            LinkCardinality.ONE_TO_ONE,
            LinkCardinality.MANY_TO_ONE,
        }:
            for source_id, count in outgoing.items():
                if count > 1:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "link_cardinality_violation",
                            f"objects.{source_id}.links.{definition.name}",
                            f"link '{definition.name}' permits at most one outgoing target",
                        )
                    )
        if definition.cardinality in {
            LinkCardinality.ONE_TO_ONE,
            LinkCardinality.ONE_TO_MANY,
        }:
            for target_id, count in incoming.items():
                if count > 1:
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "link_cardinality_violation",
                            f"objects.{target_id}.incoming.{definition.name}",
                            f"link '{definition.name}' permits at most one incoming source",
                        )
                    )
        if definition.required:
            for source_id, object_type in resolved_types.items():
                if object_type == definition.source_type and not outgoing.get(
                    source_id
                ):
                    diagnostics.append(
                        ProjectionDiagnostic(
                            "required_link_missing",
                            f"objects.{source_id}.links.{definition.name}",
                            f"required link '{definition.name}' is missing for {source_id}",
                        )
                    )


def _resolved_properties(
    schema: CompiledOntologySchema,
    object_type_name: str,
) -> dict[str, tuple[str, CompiledPropertyDefinition]]:
    resolved: dict[str, tuple[str, CompiledPropertyDefinition]] = {}
    visited: set[str] = set()

    def visit(object_type: CompiledObjectTypeDefinition) -> None:
        if object_type.name in visited:
            return
        visited.add(object_type.name)
        for parent_name in object_type.parent_types:
            parent = schema.object_type(parent_name)
            if parent is not None:
                visit(parent)
        for definition in object_type.properties:
            resolved[definition.name] = (object_type.name, definition)

    object_type = schema.object_type(object_type_name)
    if object_type is not None:
        visit(object_type)
    return resolved


def _validate_property_value(
    definition: CompiledPropertyDefinition,
    value: JSONValue,
) -> None:
    value_type = definition.value_type
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
    elif value_type is ValueType.JSON:
        valid = True
    if not valid:
        raise ValueError(
            f"property '{definition.name}' requires a {value_type.value} value"
        )


def _finite(name: str, value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(
        float(cast(int | float, value))
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(cast(int | float, value))


def _sorted_diagnostics(
    diagnostics: list[ProjectionDiagnostic],
) -> tuple[ProjectionDiagnostic, ...]:
    return tuple(
        sorted(diagnostics, key=lambda item: (item.path, item.code, item.message))
    )


__all__ = [
    "ProjectionDiagnostic",
    "ProjectionMaterializationError",
    "materialize_projection",
]
